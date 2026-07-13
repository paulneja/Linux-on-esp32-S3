/*
 * Fase C: give the emulated guest internet access.
 *
 *   guest eth0 (virtio-net, 10.0.0.2)
 *        │  frames
 *        ▼
 *   [virtio device]  ── tx ──►  vnet lwIP netif (10.0.0.1) ──► NAPT ──► WiFi STA ──► home router ──► internet
 *        ▲  rx  ◄───────────────  vnet netif output
 *
 * The ESP runs in AP+STA: it keeps the 'esp32-linux' AP (for telnet) and joins
 * your home WiFi as a station for the uplink. Guest traffic is NAT'd out the
 * station interface.
 */
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"

#include "lwip/netif.h"
#include "lwip/etharp.h"
#include "lwip/tcpip.h"
#include "lwip/ip4_addr.h"
#include "lwip/lwip_napt.h"
#include "lwip/sockets.h"

#include "virtio.h"

static const char *TAG = "nat";

/* Host side of the guest link. Guest uses 10.0.0.2, gw 10.0.0.1. */
#define VNET_IP   0x0A000001   /* 10.0.0.1 (host byte order) */
#define VNET_MASK 0xFFFFFF00   /* 255.255.255.0 */

static struct netif vnet;
static bool napt_on;
static volatile uint32_t upstream_dns_addr = ESP_IP4TOADDR(1, 1, 1, 1);

struct dns_query {
    uint16_t port, len;
    uint8_t nsip[4];    /* nameserver IP the guest sent the query TO (net order) */
    uint8_t gip[4];     /* guest IP the query came FROM (net order) */
    uint8_t data[512];
};
static QueueHandle_t dns_queue;

/* Consume guest DNS before lwIP/NAPT can rewrite its source port. */
static bool dns_queue_guest_query(const uint8_t *frame, size_t len)
{
    if (len < 42 || frame[12] != 0x08 || frame[13] != 0x00 ||
        frame[23] != IPPROTO_UDP)
        return false;
    size_t udp = 14 + ((frame[14] & 0x0f) * 4);
    if (udp + 8 > len || frame[udp + 2] != 0 || frame[udp + 3] != 53)
        return false;
    size_t payload_len = len - (udp + 8);
    if (payload_len > 512) return true;
    struct dns_query q = { .len = payload_len };
    memcpy(&q.port, frame + udp, 2);        /* network byte order */
    memcpy(q.gip,  frame + 14 + 12, 4);     /* IP source = guest */
    memcpy(q.nsip, frame + 14 + 16, 4);     /* IP dest = the nameserver used */
    memcpy(q.data, frame + udp + 8, payload_len);
    ESP_LOGI(TAG, "DNS intercept: ns=%u.%u.%u.%u gport=%u len=%u",
             q.nsip[0], q.nsip[1], q.nsip[2], q.nsip[3],
             ntohs(q.port), (unsigned)payload_len);
    xQueueSend(dns_queue, &q, 0);
    return true;
}

static void dns_send_raw_to_guest(const uint8_t *reply, size_t reply_len,
                                  const struct dns_query *q)
{
    if (!q->port || reply_len > 512) return;
    uint8_t frame[14 + 20 + 8 + 512] = {0};
    static const uint8_t host_mac[6] = { 0x02, 0x00, 0x00, 0xca, 0xfe, 0x02 };
    memcpy(frame, virtio_net_mac, 6);
    memcpy(frame + 6, host_mac, 6);
    frame[12] = 0x08; frame[13] = 0x00;

    uint8_t *ip = frame + 14;
    uint16_t ip_len = 20 + 8 + reply_len;
    ip[0] = 0x45;
    ip[2] = ip_len >> 8; ip[3] = ip_len;
    ip[8] = 64; ip[9] = IPPROTO_UDP;
    /* Source = the exact nameserver IP the guest queried; dest = the guest.
     * The guest's resolver socket is connect()'d to that nameserver, so a reply
     * from any other source (e.g. the 10.0.0.1 gateway) is dropped as NoPorts. */
    memcpy(ip + 12, q->nsip, 4);   /* source IP */
    memcpy(ip + 16, q->gip, 4);    /* dest IP (guest) */
    uint32_t sum = 0;
    for (int i = 0; i < 20; i += 2)
        sum += ((uint16_t)ip[i] << 8) | ip[i + 1];
    while (sum >> 16) sum = (sum & 0xffff) + (sum >> 16);
    uint16_t csum = (uint16_t)~sum;
    ip[10] = csum >> 8; ip[11] = csum;

    uint8_t *udp = ip + 20;
    udp[0] = 0; udp[1] = 53;
    memcpy(udp + 2, &q->port, 2);
    uint16_t udp_len = 8 + reply_len;
    udp[4] = udp_len >> 8; udp[5] = udp_len;
    memcpy(udp + 8, reply, reply_len);

    /* Supply a full UDP checksum.  Zero is legal in IPv4, but the virtio-net
     * receive path is more predictable when the packet is self-validated. */
    sum = IPPROTO_UDP + udp_len;
    sum += ((uint16_t)q->nsip[0] << 8) | q->nsip[1];
    sum += ((uint16_t)q->nsip[2] << 8) | q->nsip[3];
    sum += ((uint16_t)q->gip[0]  << 8) | q->gip[1];
    sum += ((uint16_t)q->gip[2]  << 8) | q->gip[3];
    for (size_t i = 0; i < udp_len; i += 2) {
        uint16_t word = (uint16_t)udp[i] << 8;
        if (i + 1 < udp_len) word |= udp[i + 1];
        sum += word;
    }
    while (sum >> 16) sum = (sum & 0xffff) + (sum >> 16);
    csum = (uint16_t)~sum;
    if (!csum) csum = 0xffff;
    udp[6] = csum >> 8; udp[7] = csum;
    virtio_net_rx_push(frame, 14 + ip_len);
}

/* Transparent DNS proxy for the tiny guest.  UDP/53 does not traverse the
 * ESP-IDF NAPT path reliably, so relay complete packets through an ordinary
 * host socket to the DNS server learned by the WiFi STA. */
static void dns_proxy_task(void *arg)
{
    (void)arg;
    int upfd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    struct timeval timeout = { .tv_sec = 3, .tv_usec = 0 };
    if (upfd < 0 || setsockopt(upfd, SOL_SOCKET, SO_RCVTIMEO,
                              &timeout, sizeof(timeout)) != 0) {
        ESP_LOGE(TAG, "guest DNS upstream socket failed");
        if (upfd >= 0) close(upfd);
        vTaskDelete(NULL);
        return;
    }
    ESP_LOGI(TAG, "guest DNS proxy ready");

    uint8_t pkt[512];
    while (1) {
        struct dns_query q;
        if (xQueueReceive(dns_queue, &q, portMAX_DELAY) != pdTRUE || q.len < 12)
            continue;

        struct sockaddr_in upstream = {
            .sin_family = AF_INET,
            .sin_port = htons(53),
            .sin_addr.s_addr = upstream_dns_addr,
        };
        int sret = sendto(upfd, q.data, q.len, 0, (struct sockaddr *)&upstream,
                          sizeof(upstream));
        if (sret < 0) {
            ESP_LOGW(TAG, "DNS sendto upstream failed: errno=%d", errno);
            continue;
        }
        ESP_LOGI(TAG, "DNS fwd -> %08x:53 (%d bytes), waiting reply",
                 (unsigned)upstream_dns_addr, sret);

        int out = recvfrom(upfd, pkt, sizeof(pkt), 0, NULL, NULL);
        if (out >= 12) {
            ESP_LOGI(TAG, "DNS reply %d bytes -> guest port %u",
                     out, ntohs(q.port));
            dns_send_raw_to_guest(pkt, out, &q);
        } else {
            ESP_LOGW(TAG, "DNS upstream timeout/error: %d errno=%d", out, errno);
        }
    }
}

/* lwIP wants to transmit an ethernet frame to the guest. */
static err_t vnet_linkoutput(struct netif *nif, struct pbuf *p)
{
    (void)nif;
    static uint8_t buf[1600];
    if (p->tot_len > sizeof(buf)) return ERR_MEM;
    pbuf_copy_partial(p, buf, p->tot_len, 0);
    virtio_net_rx_push(buf, p->tot_len);
    return ERR_OK;
}

static err_t vnet_netif_init(struct netif *nif)
{
    nif->name[0] = 'v'; nif->name[1] = 'n';
    nif->output = etharp_output;          /* IPv4 -> ARP -> linkoutput */
    nif->linkoutput = vnet_linkoutput;
    nif->mtu = 1500;
    nif->hwaddr_len = 6;
    /* host-side MAC (distinct from the guest's virtio MAC) */
    nif->hwaddr[0] = 0x02; nif->hwaddr[1] = 0x00; nif->hwaddr[2] = 0x00;
    nif->hwaddr[3] = 0xca; nif->hwaddr[4] = 0xfe; nif->hwaddr[5] = 0x02;
    nif->flags = NETIF_FLAG_BROADCAST | NETIF_FLAG_ETHARP | NETIF_FLAG_ETHERNET |
                 NETIF_FLAG_LINK_UP;
    return ERR_OK;
}

/* Pump guest -> host frames into the lwIP stack. Runs on Core 0. */
static void vnet_rx_task(void *arg)
{
    (void)arg;
    static uint8_t frame[1600];
    while (1) {
        size_t len = virtio_net_tx_pull(frame, sizeof(frame));
        if (len == 0) { vTaskDelay(1); continue; }
        if (dns_queue_guest_query(frame, len)) continue;
        struct pbuf *p = pbuf_alloc(PBUF_RAW, len, PBUF_POOL);
        if (!p) continue;
        pbuf_take(p, frame, len);
        if (vnet.input(p, &vnet) != ERR_OK)
            pbuf_free(p);
    }
}

/* Enable NAPT once the station has an uplink address. */
static void enable_napt_if_ready(void)
{
    if (napt_on) return;
    ip_napt_enable(lwip_htonl(VNET_IP), 1);
    napt_on = true;
    ESP_LOGI(TAG, "NAPT enabled: guest 10.0.0.0/24 -> internet via STA");
}

static void ip_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)base;
    if (id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        (void)event;
        /* This network's DHCP DNS (192.168.1.1) returns NXDOMAIN for valid
         * public names.  Use the reachable public resolver explicitly. */
        upstream_dns_addr = ESP_IP4TOADDR(1, 1, 1, 1);
        ESP_LOGI(TAG, "uplink DNS: 1.1.1.1");
        ESP_LOGI(TAG, "STA got IP (uplink ready)");
        enable_napt_if_ready();
    }
}

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)base; (void)data;
    if (id == WIFI_EVENT_STA_START || id == WIFI_EVENT_STA_DISCONNECTED)
        esp_wifi_connect();
}

void nat_start(void)
{
    /* Create the guest-side lwIP interface 10.0.0.1/24. */
    ip4_addr_t ip, mask, gw;
    ip.addr   = lwip_htonl(VNET_IP);
    mask.addr = lwip_htonl(VNET_MASK);
    gw.addr   = 0;
    netif_add(&vnet, &ip, &mask, &gw, NULL, vnet_netif_init, tcpip_input);
    netif_set_up(&vnet);
    dns_queue = xQueueCreate(8, sizeof(struct dns_query));
    ESP_ERROR_CHECK(dns_queue ? ESP_OK : ESP_ERR_NO_MEM);

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                               wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                               ip_event_handler, NULL));

    xTaskCreatePinnedToCore(vnet_rx_task, "vnet_rx", 4096, NULL, 6, NULL, 0);
    xTaskCreatePinnedToCore(dns_proxy_task, "guest_dns", 4096, NULL, 5, NULL, 0);

    esp_wifi_connect();   /* join the home WiFi (STA) */
    ESP_LOGI(TAG, "NAT layer up; connecting STA for uplink");
}
