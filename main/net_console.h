/* WiFi AP + Telnet bridge to the emulated guest console. */
#ifndef NET_CONSOLE_H
#define NET_CONSOLE_H

#include <stdbool.h>

void net_console_init(void);   /* create the in/out stream buffers */
void console_putc(char c);     /* guest -> host: to UART0 (local) and telnet client */
int  console_getc(void);       /* host -> guest: returns byte or -1 if none */
int  console_kbhit(void);      /* nonzero if a byte is waiting for the guest */

void wifi_ap_start(void);      /* bring up AP+STA WiFi */
void telnet_start(void);       /* start the TCP:23 server task (Core 0) */
void nat_start(void);          /* guest virtio-net <-> NAPT -> STA uplink */

#endif /* NET_CONSOLE_H */
