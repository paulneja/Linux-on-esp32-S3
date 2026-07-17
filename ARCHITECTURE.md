# Architecture — how Linux and the WiFi firmware share one ESP32-S3

> **Status: verified on hardware.** Everything below is running on a real
> board: flashed from a fully erased chip, it boots to a login prompt, mounts
> the rootfs from flash via XIP, passes the RSA accelerator self-tests and
> reaches the internet over WiFi. See [README.md](README.md) for the list of
> what works and what does not.

## The big picture: two cores, two operating systems, one chip

Unlike the emulated (RISC-V/Sv32) edition — where a single Xtensa core runs
an emulator that interprets a foreign RISC-V CPU in software — this edition
runs **real Linux compiled directly for the ESP32-S3's own Xtensa
instruction set**. No emulation, no interpretation. The tradeoff: the
ESP32-S3's WiFi radio is driven by a closed binary blob that only runs
under ESP-IDF/FreeRTOS, so Linux can't own it directly. The solution
(`esp-hosted`, upstream jcmvbkbc project) splits the two cores:

```
ESP32-S3 (single chip, two Xtensa LX7 cores)
│
├── Core 0 — ESP-IDF / FreeRTOS ("network_adapter" app)
│   └── Owns the WiFi radio (closed blob) directly.
│       Talks to Core 1 over shared memory (shmem IPC).
│
└── Core 1 — Linux 6.11 (real, native Xtensa binary)
    ├── esp32-ng driver (drivers/net/wireless/espressif/esp32-ng/)
    │   ├── espsta0 — STA netdev, joins the home WiFi (wpa_supplicant)
    │   └── espap0  — AP netdev, broadcasts "esp32-linux" (SoftAP,
    │                 configured directly by Core 0's firmware — no
    │                 hostapd, see "Why no hostapd" below)
    ├── netfilter/NAT — MASQUERADE espap0 → espsta0 (via `ap on`)
    ├── BusyBox userland (telnetd, dropbear/ssh, udhcpd, inetd)
    ├── espctl — GPIO/I2C control from userspace
    └── / (cramfs, read-only, XIP) + /etc and /home (jffs2, writable)
```

This is the AMP (asymmetric multiprocessing) architecture the emulated
edition's own planning docs flagged as "high risk, don't start there" —
except `esp-hosted` already built and maintains it upstream, which is why
this edition exists at all.

## Boot flow

1. ROM bootloader → 2nd-stage bootloader → `xipImage` (Linux kernel,
   executes in place from flash, not copied to RAM).
2. Kernel brings up `espsta0` (STA) first → fires `CMD_INIT_INTERFACE` to
   Core 0's firmware → `esp_wifi_set_mode(WIFI_MODE_STA)` +
   `esp_wifi_start()`.
3. Kernel brings up `espap0` (AP) second → fires its own
   `CMD_INIT_INTERFACE` → firmware widens the mode to `WIFI_MODE_APSTA` and
   **auto-starts the SoftAP** with a fixed SSID/password (see below) — no
   separate trigger needed.
4. userspace: `S45inetd` (telnet; ssh only if enabled with `ssh-server on`)
   → `wpa_supplicant` on `espsta0` (via `/etc/network/interfaces`, joining the
   WiFi configured with `wifi connect`). The AP-side setup (address, DHCP
   server, NAT) no longer runs at boot: it lives in the `ap` command and is
   off by default.

## Why no hostapd (and why the AP beacons even when "off")

The obvious way to drive `espap0`'s `.start_ap` cfg80211 callback is
`hostapd`. It doesn't build here: `hostapd`'s `os_unix.c` calls `fork()`,
and this target's C library (`uClibc-ng-fdpic`, built for a NOMMU CPU) does
not declare `fork()` at all — confirmed by the compiler, not a guess.
BusyBox's own daemons (`inetd`, `dropbear`, `crond`) work fine because
BusyBox is written to use `vfork()` on NOMMU targets; `hostapd` upstream
has no such fallback.

Instead, the SoftAP (SSID `esp32-linux`, password `linux1234`, both
hardcoded — see `cmd.c:start_softap_fixed()`) is configured and started
**directly by Core 0's firmware** the moment the AP netdev initializes,
with no userspace daemon in the loop at all. The `.start_ap`/`.stop_ap`
cfg80211 plumbing is still there in the driver (for a future dynamic
reconfiguration tool), it's just unused today.

This is exactly why the `esp32-linux` SSID still shows up in a scan when
`ap status` reports off: the beacon is Core 0's, and the `ap` command only
controls the Linux side (interface address, DHCP server, NAT). The AP is
broken regardless — the blob beacons as WEP, so clients reject it — which is
why it ships disabled. See the README.

## Storage layout (devkit-c1-16m profile, 16MB flash / 8MB PSRAM)

| Partition | Offset | Size | Contents |
|---|---|---|---|
| `nvs` | `0xa000` | 20K | ESP-IDF NVS (unused by Linux) |
| `phy_init` | `0xf000` | 4K | WiFi PHY calibration data |
| `factory` | `0x10000` | 640K | `network_adapter.bin` (Core 0 firmware) |
| `etc` | `0xb0000` | 448K | jffs2, writable, wear-leveled — `/etc` |
| `linux` | `0x120000` | 4.5M | `xipImage`, XIP kernel |
| `rootfs` | `0x5a0000` | 6.5M | `rootfs.cramfs`, read-only root |
| `home` | `0xc20000` | 3968K | jffs2, writable — `/home` |

The authoritative source of this layout is
`new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r`. It
matters more than it looks: the kernel derives the rootfs XIP address from the
partition offset (`0x42000000 + 0x5a0000`), so flashing `rootfs.cramfs` at the
wrong offset panics the kernel with "Cannot open root device". `linux` was
shrunk from 6M and `rootfs` grown to 6.5M to make room for curl and its CA
bundle.

`/` is read-only cramfs by design — no wear on the root filesystem no
matter how the system is used. Anything that needs to persist (WiFi
credentials, init scripts, host keys) lives under `/etc`, and user data under
`/home` — both separate writable jffs2 partitions mounted **over** the cramfs.
Note the consequence: a file baked into the image under `/etc` or `/home` is
shadowed at runtime by the jffs2 mount, so it only shows up on a freshly
flashed board.

## Security model

- SSH (`dropbear`) and Telnet (`telnetd`) both require a real login
  (`/etc/shadow`, SHA-256). Default password `changeme123` — **must be
  changed** via `passwd` on first login, it's deliberately obvious rather
  than plausible-looking.
- AP clients (`192.168.4.0/24`) reach the internet via NAT/MASQUERADE
  through `espsta0`, but the home LAN cannot reach *into* the AP subnet
  uninvited — standard NAT one-way behavior, not full isolation.
- No session timeout, no brute-force throttling yet.
- Telnet is plaintext on the wire; SSH is not. Telnet is on by default for
  convenience on a trusted local network, not because it is recommended
  beyond one; SSH ships disabled and is enabled with `ssh-server on`.

## Known gaps

Recovery mode, OTA, GitHub Actions CI and hardware-in-the-loop testing are all
either deferred by design or simply not built yet. The SoftAP is present but
broken (see above). curl's HTTPS support works but is experimental.
