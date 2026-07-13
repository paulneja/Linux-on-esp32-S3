/*
 * Minimal PLIC + legacy virtio-mmio + virtio-net for mini-rv32ima.
 *
 * Split across two cores:
 *  - All virtqueue / guest-RAM / IRQ logic runs on Core 1 (the emulator),
 *    driven from virtio_poll() once per emulator batch.
 *  - The NAT/lwIP layer (Core 0) only hands packets across via two thread-safe
 *    message buffers, using virtio_net_rx_push() / virtio_net_tx_pull().
 */
#ifndef VIRTIO_H
#define VIRTIO_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* MMIO regions (must match the device tree passed to the guest). */
#define PLIC_BASE        0x0C000000u
#define PLIC_SIZE        0x00400000u
#define VIRTIO_NET_BASE  0x10001000u
#define VIRTIO_BLK_BASE  0x10002000u
#define VIRTIO_MMIO_SIZE 0x00001000u
#define VIRTIO_NET_IRQ   1            /* PLIC source number for virtio-net */
#define VIRTIO_BLK_IRQ   2            /* PLIC source number for virtio-blk */
#define UART_IRQ         3            /* PLIC source number for ns16550a */

/* Backing store for virtio-blk: the emulator provides read/write of 512-byte
 * sectors (returns 0 on success). Implemented over a flash partition. */
int  vblk_backend_read(uint64_t sector, void *buf, uint32_t count);
int  vblk_backend_write(uint64_t sector, const void *buf, uint32_t count);
uint64_t vblk_backend_sectors(void);

void virtio_init(void);

/* MMIO dispatch from the emulator's control load/store hooks.
 * Return true if the address belonged to us (PLIC or a virtio device). */
bool virtio_mmio_store(uint32_t addr, uint32_t val);
bool virtio_mmio_load(uint32_t addr, uint32_t *out);

/* Called once per emulator batch (Core 1): services queues and returns
 * nonzero if the supervisor external interrupt line (SEIP) should be asserted. */
int  virtio_poll(void);
void virtio_uart_irq(bool asserted);

/* Host <-> guest packet handoff (called from the NAT/lwIP layer on Core 0). */
void   virtio_net_rx_push(const void *frame, size_t len);   /* host -> guest */
size_t virtio_net_tx_pull(void *buf, size_t maxlen);        /* guest -> host */

/* MAC address the guest will use (host picks it; NAT layer may read it). */
extern uint8_t virtio_net_mac[6];

#endif /* VIRTIO_H */
