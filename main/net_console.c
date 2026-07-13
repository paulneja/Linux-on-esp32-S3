/*
 * WiFi SoftAP + Telnet (TCP:23) bridge to the emulated guest UART console.
 *
 * Two byte stream buffers connect the RISC-V guest and the network:
 *   s_out : guest -> client (kernel/shell output)
 *   s_in  : client -> guest (keystrokes)
 * Each buffer has exactly one writer and one reader (opposite tasks), which is
 * the usage FreeRTOS stream buffers are safe for without extra locking.
 *
 * The guest console also stays mirrored on UART0 (/dev/ttyACM0) so the local
 * serial console keeps working for debugging.
 */
#include <string.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/stream_buffer.h"

#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "nvs_flash.h"

#include "lwip/sockets.h"

#include "net_console.h"
#include "port.h"   /* ReadKBByte()/IsKBHit() -> UART0 local input */
#include "wifi_creds.h"

#define WIFI_SSID   "esp32-linux"
#define WIFI_PASS   "linux1234"       /* >= 8 chars for WPA2 */
#define WIFI_CHAN   1
#define WIFI_MAXCONN 4
#define TELNET_PORT 23

static const char *TAG = "net";
static StreamBufferHandle_t s_in;    /* client -> guest */
static StreamBufferHandle_t s_out;   /* guest  -> client */

void net_console_init(void)
{
    s_in  = xStreamBufferCreate(2048, 1);
    s_out = xStreamBufferCreate(16384, 1);
}

/* ---- guest console hooks (called from the emulator task, Core 1) ---- */

void console_putc(char c)
{
    putchar(c);                       /* local UART0 mirror */
    if (s_out)
        xStreamBufferSend(s_out, &c, 1, 0);   /* drop if client is slow/full */
}

int console_getc(void)
{
    uint8_t c;
    if (s_in && xStreamBufferReceive(s_in, &c, 1, 0) == 1)
        return c;
    return ReadKBByte();              /* fall back to local UART0 */
}

int console_kbhit(void)
{
    if (s_in && xStreamBufferBytesAvailable(s_in) > 0)
        return 1;
    return IsKBHit();
}

/* ---- WiFi SoftAP ---- */

void wifi_ap_start(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    wifi_config_t apcfg = {
        .ap = {
            .ssid = WIFI_SSID,
            .ssid_len = strlen(WIFI_SSID),
            .channel = WIFI_CHAN,
            .password = WIFI_PASS,
            .max_connection = WIFI_MAXCONN,
            .authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    wifi_config_t stacfg = { 0 };
    strncpy((char *)stacfg.sta.ssid, STA_SSID, sizeof(stacfg.sta.ssid) - 1);
    strncpy((char *)stacfg.sta.password, STA_PASS, sizeof(stacfg.sta.password) - 1);

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &apcfg));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &stacfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "AP+STA up: AP '%s' (telnet 192.168.4.1), STA joining '%s'",
             WIFI_SSID, STA_SSID);
}

/* ---- Telnet server ---- */

/* Minimal telnet: put the client in char-at-a-time mode with remote echo,
 * and strip inbound IAC command sequences. */
static void telnet_send_negotiation(int fd)
{
    static const uint8_t neg[] = {
        255, 251, 1,   /* IAC WILL ECHO            */
        255, 251, 3,   /* IAC WILL SUPPRESS-GO-AHEAD*/
        255, 253, 3,   /* IAC DO   SUPPRESS-GO-AHEAD*/
    };
    send(fd, neg, sizeof(neg), 0);
}

/* Feed inbound bytes to the guest, filtering telnet IAC sequences and NULs. */
static void feed_from_client(const uint8_t *buf, int n)
{
    static int skip = 0;      /* remaining option bytes to swallow after IAC cmd */
    static bool in_iac = false;
    for (int i = 0; i < n; i++) {
        uint8_t b = buf[i];
        if (skip > 0) { skip--; continue; }
        if (in_iac) {
            in_iac = false;
            if (b >= 251 && b <= 254) skip = 1;   /* WILL/WONT/DO/DONT + option */
            /* other commands (e.g. 240 SE) carry no extra byte here */
            continue;
        }
        if (b == 255) { in_iac = true; continue; } /* IAC */
        if (b == 0) continue;                       /* telnet CR NUL -> drop NUL */
        xStreamBufferSend(s_in, &b, 1, 0);
    }
}

static void telnet_client(int fd)
{
    telnet_send_negotiation(fd);

    /* nudge the shell to reprint its prompt for the freshly-connected client */
    uint8_t nl = '\r';
    xStreamBufferSend(s_in, &nl, 1, 0);

    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);

    uint8_t rx[256];
    uint8_t tx[512];
    while (1) {
        int r = recv(fd, rx, sizeof(rx), 0);
        if (r == 0) break;                 /* client closed */
        if (r < 0 && errno != EWOULDBLOCK && errno != EAGAIN) break;
        if (r > 0) feed_from_client(rx, r);

        size_t got = xStreamBufferReceive(s_out, tx, sizeof(tx), 0);
        if (got > 0) {
            int off = 0;
            while (off < (int)got) {
                int w = send(fd, tx + off, got - off, 0);
                if (w > 0) { off += w; continue; }
                if (w < 0 && (errno == EWOULDBLOCK || errno == EAGAIN)) {
                    vTaskDelay(pdMS_TO_TICKS(2));
                    continue;
                }
                return;                    /* send error -> drop client */
            }
        } else {
            vTaskDelay(pdMS_TO_TICKS(5));   /* idle: yield */
        }
    }
}

static void telnet_task(void *arg)
{
    (void)arg;
    int srv = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_addr.s_addr = htonl(INADDR_ANY),
        .sin_port = htons(TELNET_PORT),
    };
    if (bind(srv, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        ESP_LOGE(TAG, "bind :%d failed", TELNET_PORT);
        vTaskDelete(NULL);
        return;
    }
    listen(srv, 1);
    ESP_LOGI(TAG, "telnet listening on :%d", TELNET_PORT);

    while (1) {
        struct sockaddr_in cli;
        socklen_t cl = sizeof(cli);
        int fd = accept(srv, (struct sockaddr *)&cli, &cl);
        if (fd < 0) { vTaskDelay(pdMS_TO_TICKS(100)); continue; }
        ESP_LOGI(TAG, "client connected");
        telnet_client(fd);
        close(fd);
        ESP_LOGI(TAG, "client disconnected");
    }
}

void telnet_start(void)
{
    /* pin the network task to Core 0 (WiFi core); the emulator owns Core 1 */
    xTaskCreatePinnedToCore(telnet_task, "telnet", 6144, NULL, 5, NULL, 0);
}
