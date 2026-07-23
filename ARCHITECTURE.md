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
│   ├── Owns the WiFi radio (closed blob) directly.
│   │   Talks to Core 1 over shared memory (shmem IPC).
│   └── NimBLE peripheral — advertises as "Esp32-Linux" (Nordic UART
│       Service). A byte pipe only: it never drives the WiFi radio itself.
│
└── Core 1 — Linux 6.11 (real, native Xtensa binary)
    ├── esp32-ng driver (drivers/net/wireless/espressif/esp32-ng/)
    │   ├── espsta0 — STA netdev, joins the home WiFi (wpa_supplicant).
    │   │             STA only: the AP side is hard-disabled (see below).
    │   └── /dev/esp-ble — the other end of the BLE pipe (single reader)
    ├── BusyBox userland (telnetd, dropbear/ssh, inetd) + nano editor
    ├── wifi — interactive scan/connect helper for the STA uplink
    ├── ble-wifi-setup — runs the provisioning dialog over /dev/esp-ble,
    │                    through the same `wifi` command (see BLE.md)
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
2. Kernel brings up `espsta0` (STA) → fires `CMD_INIT_INTERFACE` to
   Core 0's firmware → `esp_wifi_set_mode(WIFI_MODE_STA)` +
   `esp_wifi_start()`. The driver never creates an AP interface (see below),
   so the firmware stays in plain STA mode.
3. userspace: `S45inetd` (telnet; ssh only if enabled with `ssh-server on`)
   → `wpa_supplicant` on `espsta0` (via `/etc/network/interfaces`, joining the
   WiFi set with the interactive `wifi` command or `wifi connect "SSID" "PASS"`).
   With no network chosen yet there is no `/etc/wpa_supplicant.conf`, so
   `wpa_supplicant` exits and the step reports `FAIL` — that is the expected
   state of a freshly flashed board, not a fault.
4. `S46blewifi` starts `ble-wifi-setup` if the firmware exposed `/dev/esp-ble`,
   so the board can be joined to a network from a phone with no PC and no
   cable. Core 0 has been advertising since long before this point, which is
   why connecting in the first ~30 s is unreliable (see BLE.md).

## Why there is no SoftAP (STA only)

Earlier versions created a second netdev (`espap0`) and let Core 0's firmware
run a SoftAP with a fixed SSID/password. It was removed because it never
worked and actively hurt: the closed WiFi blob beacons as **WEP** instead of
WPA2, so clients reject it, and — worse — bringing the AP up wedged the
firmware's wifi task so `CMD_SCAN_REQUEST` never returned, meaning the STA
could no longer scan or associate.

So the esp32-ng driver is now hard-forced to **never create `espap0`**
(`esp_add_network_ifaces()` returns right after adding the STA interface), and
the `ap` command was deleted. With no AP netdev, the firmware never receives an
AP init and never beacons — the board is **STA only**: it joins an existing
network, it does not host one. The `.start_ap`/`.stop_ap` cfg80211 plumbing and
the firmware's `start_softap_fixed()` still exist, dormant, in case a future
build wants a working AP — which would need `hostapd`, and `hostapd` doesn't
build here: its `os_unix.c` calls `fork()`, which this target's NOMMU C library
(`uClibc-ng-fdpic`) does not declare at all. BusyBox's daemons (`inetd`,
`dropbear`, `crond`) work only because BusyBox falls back to `vfork()` on NOMMU;
`hostapd` upstream has no such fallback.

## Storage layout (devkit-c1-16m profile, 16MB flash / 8MB PSRAM)

| Partition | Offset | Size | Contents |
|---|---|---|---|
| `nvs` | `0xa000` | 20K | ESP-IDF NVS (unused by Linux) |
| `phy_init` | `0xf000` | 4K | WiFi PHY calibration data |
| `factory` | `0x10000` | 768K | `network_adapter.bin` (Core 0 firmware) |
| `etc` | `0xd0000` | 448K | jffs2, writable, wear-leveled — `/etc` |
| `linux` | `0x140000` | 4M | `xipImage`, XIP kernel |
| `rootfs` | `0x540000` | 7.5M | `rootfs.cramfs`, read-only root |
| `home` | `0xcc0000` | 3.25M | jffs2, writable — `/home` |

The authoritative source of this layout is
`new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r`, and this
table is a copy of it — if the two disagree, the CSV is right. It matters more
than it looks: the kernel derives the rootfs XIP address from the partition
offset (`0x42000000 + 0x540000`), so flashing `rootfs.cramfs` at the wrong
offset panics the kernel with "Cannot open root device". A booting board prints
both, which is the quickest way to check this table against reality:

```
0x000000540000-0x000000cc0000 : "rootfs"
cramfs: checking physical address 0x42540000 for linear cramfs image
```

The layout has been recut several times — `rootfs` grown for curl and its CA
bundle, then again for nano and ncurses; `factory` grown for the BLE stack;
`linux` and `home` shrunk to pay for it. Moving `rootfs` means the kernel's XIP
address moves with it, and moving `linux` means `CONFIG_KERNEL_LOAD_ADDRESS`
(`0x42000000 +` the `linux` offset) has to move too, or the board boot-loops in
the bootloader before Linux prints anything.

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
- No session timeout, no brute-force throttling yet.
- Telnet is plaintext on the wire; SSH is not. Telnet is on by default for
  convenience on a trusted local network, not because it is recommended
  beyond one; SSH ships disabled and is enabled with `ssh-server on`.

## Known gaps

Recovery mode, OTA, GitHub Actions CI and hardware-in-the-loop testing are all
either deferred by design or simply not built yet. There is no SoftAP — the
board is STA only (see above). curl's HTTPS support works but is experimental.
