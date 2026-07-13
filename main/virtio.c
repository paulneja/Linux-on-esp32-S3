/*
 * Minimal PLIC + legacy virtio-mmio + virtio-net for mini-rv32ima on ESP32-S3.
 * See virtio.h for the threading model.
 *
 * Guest is little-endian RV32 and the ESP32-S3 is little-endian too, so guest
 * RAM structures are read/written directly with no byte swapping.
 */
#include <string.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/message_buffer.h"

#include "virtio.h"
#include "psram.h"

#define GUEST_RAM_BASE 0x80000000u

#ifndef VIRTIO_DEBUG
#define VIRTIO_DEBUG 0
#endif
#if VIRTIO_DEBUG
#define VDBG(...) printf(__VA_ARGS__)
#else
#define VDBG(...) do {} while (0)
#endif

/* ---- guest RAM access helpers ---- */
static inline uint8_t *gram(uint32_t gpa) {
    return (uint8_t *)psram_get_base() + (gpa - GUEST_RAM_BASE);
}
static inline uint16_t rd16(uint32_t gpa){ uint16_t v; memcpy(&v, gram(gpa), 2); return v; }
static inline uint32_t rd32(uint32_t gpa){ uint32_t v; memcpy(&v, gram(gpa), 4); return v; }
static inline void wr16(uint32_t gpa, uint16_t v){ memcpy(gram(gpa), &v, 2); }
static inline void wr32(uint32_t gpa, uint32_t v){ memcpy(gram(gpa), &v, 4); }

/* =====================================================================
 *  PLIC (single M-mode context, sources 1..31)
 * ===================================================================== */
static uint32_t plic_priority[32];
static uint32_t plic_enable;        /* bitmap, context 0 */
static uint32_t plic_threshold;
static uint32_t plic_claimed;       /* bitmap of in-service sources */
static uint32_t plic_line;          /* bitmap of asserted device lines */

static void plic_set_line(int src, int high) {
    if (high) plic_line |= (1u << src);
    else      plic_line &= ~(1u << src);
}

void virtio_uart_irq(bool asserted)
{
    plic_set_line(UART_IRQ, asserted);
}

/* highest-priority source that is asserted, enabled, unclaimed, > threshold */
static int plic_best(void) {
    int best = 0; uint32_t bestprio = 0;
    uint32_t cand = plic_line & plic_enable & ~plic_claimed;
    for (int s = 1; s < 32; s++) {
        if (!(cand & (1u << s))) continue;
        if (plic_priority[s] > plic_threshold && plic_priority[s] > bestprio) {
            bestprio = plic_priority[s]; best = s;
        }
    }
    return best;
}

static bool plic_store(uint32_t off, uint32_t val) {
    if (off < 0x1000) { plic_priority[(off >> 2) & 31] = val; return true; }
    if (off == 0x2000) { plic_enable = val; return true; }       /* ctx0 enable */
    if (off == 0x200000) { plic_threshold = val; return true; }  /* ctx0 threshold */
    if (off == 0x200004) { plic_claimed &= ~(1u << (val & 31)); return true; } /* complete */
    return true; /* swallow other PLIC writes */
}

static bool plic_load(uint32_t off, uint32_t *out) {
    if (off < 0x1000) { *out = plic_priority[(off >> 2) & 31]; return true; }
    if (off == 0x1000) { *out = plic_line; return true; }        /* pending */
    if (off == 0x2000) { *out = plic_enable; return true; }
    if (off == 0x200000) { *out = plic_threshold; return true; }
    if (off == 0x200004) {                                       /* claim */
        int s = plic_best();
        if (s) plic_claimed |= (1u << s);
        *out = s;
        return true;
    }
    *out = 0; return true;
}

/* =====================================================================
 *  virtio-net (legacy virtio-mmio, version 1)
 * ===================================================================== */
#define VIRTQ_DESC_F_NEXT   1
#define VIRTQ_DESC_F_WRITE  2
#define VNET_HDR_LEN        10          /* legacy, no mrg_rxbuf */
#define VNET_F_MAC          (1u << 5)
#define NUM_QUEUES          2           /* 0=RX, 1=TX */
#define PKT_MAX             1600

uint8_t virtio_net_mac[6] = { 0x02, 0x00, 0x00, 0xca, 0xfe, 0x01 };

struct vq {
    uint32_t num;
    uint32_t pfn;
    uint32_t align;
    uint16_t last_avail;
    bool ready;
};

static struct {
    uint32_t status;
    uint32_t isr;                 /* interrupt status (bit0 = used buffer) */
    uint32_t irq_generation;      /* preserve events racing ISR read/ack */
    uint32_t irq_read_generation;
    uint32_t guest_page_size;
    uint32_t host_features_sel;
    uint32_t cur_queue;
    struct vq q[NUM_QUEUES];
    uint8_t  config[8];           /* mac[6] + status[2] */
} vnet;

static MessageBufferHandle_t rx_mb;   /* host -> guest frames */
static MessageBufferHandle_t tx_mb;   /* guest -> host frames */
static unsigned rx_kick_budget;
static unsigned rx_kick_delay;

/* addresses of the three rings for the current queue layout */
static void vq_addrs(struct vq *q, uint32_t *desc, uint32_t *avail, uint32_t *used) {
    uint32_t base = q->pfn * vnet.guest_page_size;
    uint32_t al = q->align ? q->align : 4096;
    *desc  = base;
    *avail = base + 16 * q->num;
    uint32_t used_off = (16 * q->num + 6 + 2 * q->num + al - 1) & ~(al - 1);
    *used  = base + used_off;
}

static void vnet_raise(void) {
    vnet.irq_generation++;
    vnet.isr |= 1;
    plic_set_line(VIRTIO_NET_IRQ, 1);
}

/* Guest -> host: drain the TX queue (queue 1) into tx_mb. */
static void process_tx(void) {
    struct vq *q = &vnet.q[1];
    if (!q->ready) return;
    uint32_t desc, avail, used;
    vq_addrs(q, &desc, &avail, &used);
    uint16_t avail_idx = rd16(avail + 2);
    static uint8_t lin[PKT_MAX + 64];

    while (q->last_avail != avail_idx) {
        uint16_t head = rd16(avail + 4 + 2 * (q->last_avail % q->num));
        uint32_t len = 0, d = head;
        for (int guard = 0; guard < 64; guard++) {
            uint32_t da = desc + 16 * d;
            uint32_t addr = rd32(da);            /* low 32 of le64 addr */
            uint32_t dlen = rd32(da + 8);
            uint16_t flags = rd16(da + 12);
            uint16_t next = rd16(da + 14);
            if (len + dlen > sizeof(lin)) dlen = sizeof(lin) - len;
            memcpy(lin + len, gram(addr), dlen);
            len += dlen;
            if (!(flags & VIRTQ_DESC_F_NEXT)) break;
            d = next;
        }
        if (len > VNET_HDR_LEN)
            xMessageBufferSend(tx_mb, lin + VNET_HDR_LEN, len - VNET_HDR_LEN, 0);

        uint16_t uidx = rd16(used + 2);
        wr32(used + 4 + 8 * (uidx % q->num), head);
        wr32(used + 4 + 8 * (uidx % q->num) + 4, len);
        wr16(used + 2, uidx + 1);
        q->last_avail++;
        vnet_raise();
        /* The emulated CPU can acknowledge the shared TX/RX ISR before its
         * deferred NAPI poll runs.  Repeat a few spaced level kicks so an RX
         * descriptor never remains unnoticed until the next transmission. */
        rx_kick_budget = 12;
        rx_kick_delay = 256;
    }
}

/* Host -> guest: deliver frames from rx_mb into the RX queue (queue 0). */
static void process_rx(void) {
    struct vq *q = &vnet.q[0];
    if (!q->ready) return;
    uint32_t desc, avail, used;
    vq_addrs(q, &desc, &avail, &used);
    static uint8_t pkt[PKT_MAX];

    while (1) {
        uint16_t avail_idx = rd16(avail + 2);
        if (q->last_avail == avail_idx) break;             /* no guest buffer */
        size_t plen = xMessageBufferReceive(rx_mb, pkt, sizeof(pkt), 0);
        if (plen == 0) break;                               /* no packet */

        uint16_t head = rd16(avail + 4 + 2 * (q->last_avail % q->num));
        /* scatter [10-byte zero hdr][packet] across the writable descriptors */
        uint32_t total = VNET_HDR_LEN + plen, written = 0, d = head;
        for (int guard = 0; guard < 64 && written < total; guard++) {
            uint32_t da = desc + 16 * d;
            uint32_t addr = rd32(da);
            uint32_t dlen = rd32(da + 8);
            uint16_t flags = rd16(da + 12);
            uint16_t next = rd16(da + 14);
            uint32_t n = total - written;
            if (n > dlen) n = dlen;
            for (uint32_t i = 0; i < n; i++) {
                uint32_t pos = written + i;
                uint8_t b = (pos < VNET_HDR_LEN) ? 0 : pkt[pos - VNET_HDR_LEN];
                *gram(addr + i) = b;
            }
            written += n;
            if (!(flags & VIRTQ_DESC_F_NEXT)) break;
            d = next;
        }
        uint16_t uidx = rd16(used + 2);
        wr32(used + 4 + 8 * (uidx % q->num), head);
        wr32(used + 4 + 8 * (uidx % q->num) + 4, total);
        wr16(used + 2, uidx + 1);
        q->last_avail++;
        vnet_raise();
    }
}

/* ---- virtio-mmio register file ---- */
static bool vnet_store(uint32_t off, uint32_t val) {
    switch (off) {
    case 0x014: vnet.host_features_sel = val; return true;
    case 0x024: return true;                       /* GuestFeaturesSel */
    case 0x020: return true;                       /* GuestFeatures (accept) */
    case 0x028: vnet.guest_page_size = val; return true;
    case 0x030: vnet.cur_queue = val; return true;
    case 0x038: if (vnet.cur_queue < NUM_QUEUES) vnet.q[vnet.cur_queue].num = val; return true;
    case 0x03c: if (vnet.cur_queue < NUM_QUEUES) vnet.q[vnet.cur_queue].align = val; return true;
    case 0x040:
        if (vnet.cur_queue < NUM_QUEUES) {
            vnet.q[vnet.cur_queue].pfn = val;
            vnet.q[vnet.cur_queue].ready = (val != 0);
        }
        return true;
    case 0x050: return true;                        /* QueueNotify: handled in poll */
    case 0x064:
        /* TX and RX share bit 0.  Do not let an ACK for an older event erase
         * an RX completion raised after InterruptStatus was read. */
        if (vnet.irq_read_generation == vnet.irq_generation)
            vnet.isr &= ~val;
        if (!vnet.isr) plic_set_line(VIRTIO_NET_IRQ, 0);
        return true;
    case 0x070:
        vnet.status = val;
        if (val == 0) {                             /* reset */
            memset(vnet.q, 0, sizeof(vnet.q));
            vnet.isr = 0; plic_set_line(VIRTIO_NET_IRQ, 0);
        }
        return true;
    default: return true;
    }
}

static bool vnet_load(uint32_t off, uint32_t *out) {
    if (off >= 0x100 && off < 0x100 + sizeof(vnet.config)) {
        uint32_t v = 0;
        for (int i = 0; i < 4; i++) {
            uint32_t idx = (off - 0x100) + i;
            if (idx < sizeof(vnet.config)) v |= (uint32_t)vnet.config[idx] << (8 * i);
        }
        *out = v; return true;
    }
    switch (off) {
    case 0x000: *out = 0x74726976; return true;    /* 'virt' */
    case 0x004: *out = 1; return true;             /* legacy version */
    case 0x008: *out = 1; return true;             /* device id: net */
    case 0x00c: *out = 0x554d4551; return true;    /* 'QEMU' */
    case 0x010: *out = (vnet.host_features_sel == 0) ? VNET_F_MAC : 0; return true;
    case 0x034: *out = 256; return true;           /* QueueNumMax */
    case 0x040: *out = (vnet.cur_queue < NUM_QUEUES) ? vnet.q[vnet.cur_queue].pfn : 0; return true;
    case 0x060:
        vnet.irq_read_generation = vnet.irq_generation;
        *out = vnet.isr;
        return true;
    case 0x070: *out = vnet.status; return true;
    default: *out = 0; return true;
    }
}

/* =====================================================================
 *  virtio-blk (legacy virtio-mmio, version 1) — one request queue
 * ===================================================================== */
#define VIRTIO_BLK_T_IN   0   /* read: device -> guest */
#define VIRTIO_BLK_T_OUT  1   /* write: guest -> device */
#define BLK_SECTOR        512

static struct {
    uint32_t status;
    uint32_t isr;
    uint32_t guest_page_size;
    uint32_t host_features_sel;
    uint32_t cur_queue;
    struct vq q[1];
    uint8_t  config[8];      /* capacity (le64, in 512B sectors) */
} vblk;

static void vblk_raise(void) {
    vblk.isr |= 1;
    plic_set_line(VIRTIO_BLK_IRQ, 1);
}

/* Service the block request queue (queue 0). */
static void process_blk(void) {
    struct vq *q = &vblk.q[0];
    if (!q->ready) return;
    uint32_t desc, avail, used;
    vq_addrs(q, &desc, &avail, &used);
    uint16_t avail_idx = rd16(avail + 2);
    static uint8_t secbuf[BLK_SECTOR];

    while (q->last_avail != avail_idx) {
        uint16_t head = rd16(avail + 4 + 2 * (q->last_avail % q->num));

        /* First descriptor: 16-byte request header. */
        uint32_t d = head;
        uint32_t hda = desc + 16 * d;
        uint32_t hdr = rd32(hda);
        uint32_t type = rd32(hdr);
        uint64_t sector = (uint64_t)rd32(hdr + 8) | ((uint64_t)rd32(hdr + 12) << 32);
        uint16_t flags = rd16(hda + 12);
        d = rd16(hda + 14);

        static int bc = 0;
        if (bc++ < 40)
            VDBG("[BLK #%d] num=%lu la=%u ai=%u head=%u desc=%lx used=%lx uidx=%u type=%lu sec=%lu\n",
                 bc, (unsigned long)q->num, q->last_avail, avail_idx, head,
                 (unsigned long)desc, (unsigned long)used, rd16(used + 2),
                 (unsigned long)type, (unsigned long)sector);

        uint8_t status = 0;              /* 0 = VIRTIO_BLK_S_OK */
        uint32_t status_addr = 0;

        while (flags & VIRTQ_DESC_F_NEXT) {
            uint32_t da = desc + 16 * d;
            uint32_t addr = rd32(da);
            uint32_t dlen = rd32(da + 8);
            uint16_t dflags = rd16(da + 12);
            uint16_t dnext = rd16(da + 14);

            if (!(dflags & VIRTQ_DESC_F_NEXT)) {
                status_addr = addr;      /* last descriptor = 1-byte status */
                break;
            }

            /* data descriptor: transfer dlen bytes, sector by sector */
            uint32_t nsec = dlen / BLK_SECTOR;
            for (uint32_t s = 0; s < nsec; s++) {
                if (type == VIRTIO_BLK_T_IN) {
                    if (vblk_backend_read(sector, secbuf, 1) != 0) status = 1;
                    memcpy(gram(addr + s * BLK_SECTOR), secbuf, BLK_SECTOR);
                } else if (type == VIRTIO_BLK_T_OUT) {
                    memcpy(secbuf, gram(addr + s * BLK_SECTOR), BLK_SECTOR);
                    if (vblk_backend_write(sector, secbuf, 1) != 0) status = 1;
                }
                sector++;
            }
            flags = dflags;
            d = dnext;
        }

        if (status_addr)
            *gram(status_addr) = status;

        uint16_t uidx = rd16(used + 2);
        wr32(used + 4 + 8 * (uidx % q->num), head);
        wr32(used + 4 + 8 * (uidx % q->num) + 4, 1);
        wr16(used + 2, uidx + 1);
        q->last_avail++;
        vblk_raise();
    }
}

static bool vblk_store(uint32_t off, uint32_t val) {
    switch (off) {
    case 0x014: vblk.host_features_sel = val; return true;
    case 0x020: case 0x024: return true;
    case 0x028: vblk.guest_page_size = val; return true;
    case 0x030: vblk.cur_queue = val; return true;
    case 0x038: if (vblk.cur_queue == 0) vblk.q[0].num = val; return true;
    case 0x03c: if (vblk.cur_queue == 0) vblk.q[0].align = val; return true;
    case 0x040:
        if (vblk.cur_queue == 0) { vblk.q[0].pfn = val; vblk.q[0].ready = (val != 0); }
        return true;
    case 0x050: return true;      /* QueueNotify: serviced in poll */
    case 0x064: vblk.isr &= ~val; if (!vblk.isr) plic_set_line(VIRTIO_BLK_IRQ, 0); return true;
    case 0x070:
        vblk.status = val;
        if (val == 0) { memset(vblk.q, 0, sizeof(vblk.q)); vblk.isr = 0; plic_set_line(VIRTIO_BLK_IRQ, 0); }
        return true;
    default: return true;
    }
}

static bool vblk_load(uint32_t off, uint32_t *out) {
    if (off >= 0x100 && off < 0x108) {   /* config: capacity (le64 sectors) */
        uint32_t v = 0;
        for (int i = 0; i < 4; i++) {
            uint32_t idx = (off - 0x100) + i;
            if (idx < 8) v |= (uint32_t)vblk.config[idx] << (8 * i);
        }
        *out = v; return true;
    }
    switch (off) {
    case 0x000: *out = 0x74726976; return true;   /* 'virt' */
    case 0x004: *out = 1; return true;            /* legacy version */
    case 0x008: *out = 2; return true;            /* device id: block */
    case 0x00c: *out = 0x554d4551; return true;   /* 'QEMU' */
    case 0x010: *out = 0; return true;            /* no feature bits needed */
    case 0x034: *out = 256; return true;          /* QueueNumMax */
    case 0x040: *out = (vblk.cur_queue == 0) ? vblk.q[0].pfn : 0; return true;
    case 0x060: *out = vblk.isr; return true;
    case 0x070: *out = vblk.status; return true;
    default: *out = 0; return true;
    }
}

/* =====================================================================
 *  Public API
 * ===================================================================== */
void virtio_init(void) {
    memcpy(vnet.config, virtio_net_mac, 6);
    vnet.config[6] = 0; vnet.config[7] = 0;      /* link status */
    vnet.guest_page_size = 4096;
    rx_mb = xMessageBufferCreate(16 * 1600);
    tx_mb = xMessageBufferCreate(16 * 1600);

    /* virtio-blk capacity from the backing store (in 512-byte sectors). */
    vblk.guest_page_size = 4096;
    uint64_t cap = vblk_backend_sectors();
    for (int i = 0; i < 8; i++) vblk.config[i] = (cap >> (8 * i)) & 0xff;
}

bool virtio_mmio_store(uint32_t addr, uint32_t val) {
    if (addr >= PLIC_BASE && addr < PLIC_BASE + PLIC_SIZE)
        return plic_store(addr - PLIC_BASE, val);
    if (addr >= VIRTIO_NET_BASE && addr < VIRTIO_NET_BASE + VIRTIO_MMIO_SIZE)
        return vnet_store(addr - VIRTIO_NET_BASE, val);
    if (addr >= VIRTIO_BLK_BASE && addr < VIRTIO_BLK_BASE + VIRTIO_MMIO_SIZE)
        return vblk_store(addr - VIRTIO_BLK_BASE, val);
    return false;
}

bool virtio_mmio_load(uint32_t addr, uint32_t *out) {
    if (addr >= PLIC_BASE && addr < PLIC_BASE + PLIC_SIZE)
        return plic_load(addr - PLIC_BASE, out);
    if (addr >= VIRTIO_NET_BASE && addr < VIRTIO_NET_BASE + VIRTIO_MMIO_SIZE)
        return vnet_load(addr - VIRTIO_NET_BASE, out);
    if (addr >= VIRTIO_BLK_BASE && addr < VIRTIO_BLK_BASE + VIRTIO_MMIO_SIZE)
        return vblk_load(addr - VIRTIO_BLK_BASE, out);
    return false;
}

int virtio_poll(void) {
    process_tx();
    process_rx();
    process_blk();
    if (rx_kick_budget && --rx_kick_delay == 0) {
        vnet_raise();
        rx_kick_budget--;
        rx_kick_delay = 256;
    }
    /* keep the PLIC lines in sync with each device's interrupt status */
    plic_set_line(VIRTIO_NET_IRQ, vnet.isr != 0);
    plic_set_line(VIRTIO_BLK_IRQ, vblk.isr != 0);
    return plic_best() != 0;
}

void virtio_net_rx_push(const void *frame, size_t len) {
    if (rx_mb && len && len <= PKT_MAX)
        xMessageBufferSend(rx_mb, frame, len, 0);
}

size_t virtio_net_tx_pull(void *buf, size_t maxlen) {
    if (!tx_mb) return 0;
    return xMessageBufferReceive(tx_mb, buf, maxlen, 0);
}
