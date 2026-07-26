# Changelog

Releases carry one flashable `.bin` for a 16 MB / 8 MB-PSRAM ESP32-S3. Full
notes and the binaries are on the
[releases page](https://github.com/paulneja/Linux-on-esp32-S3/releases).

## Unreleased

Build reproducibility only — **the `0.4` binary is unchanged**. A build made
from a clean clone of this repo did not reproduce the released image; these are
the four defects that stood in the way, all found on hardware.

- The Docker image was missing `cpio`, which buildroot checks for *after*
  crosstool-NG has compiled the entire toolchain — hours in, at the most
  expensive point.
- `03-buildroot-tracked-changes.patch` carried a compiled binary `git apply`
  cannot reconstruct, so it was rejected in full on every fresh clone — and the
  failure was read as "already applied" and ignored. Builds reported success
  while producing images with no `/etc/fstab`, `inetd.conf` or `S05home`.
- The firmware patch had drifted behind the tree the images were built from: it
  was missing the RSA handover (without which **the kernel hangs at boot with no
  output**), the entire BLE link, and a vendored ESP-IDF change. Regenerated
  from that tree and verified byte for byte.
- The defconfig had drifted too: `setup-home.sh` was not being run, so root
  landed in `/root` on the read-only cramfs. And buildroot's own default
  `wpa_supplicant.conf` was reaching the image, making a clean build join any
  open WiFi network by itself.

A full from-scratch build in Docker now runs to completion and the result boots
on hardware.

### SoftAP removed for real

0.3 disabled the SoftAP; the code stayed behind, unreachable. It is now gone
from both sides, and the binaries change accordingly.

- Kernel: `01-kernel-esp32ng-ap-support.patch` is deleted. The esp32-ng driver
  is pristine upstream plus the BLE pipe — no `.start_ap`/`.stop_ap`, no
  `cmd_ap_start`/`cmd_ap_stop`, no `CMD_AP_*`/`EVENT_AP_*` codes, no
  `ap_iface`/`esp_ap_password` module parameters, `ESP_MAX_INTERFACE` back to 1.
  This is a no-op for the STA: the removed refactor threaded `priv->if_type`
  through 19 call sites, and on a STA-only build that value is always
  `ESP_STA_IF` — exactly the constant upstream hardcodes.
- Firmware: `cmd.c` is byte-identical to upstream again. WiFi start-up returns
  to upstream's model (event loop and `esp_wifi_start()` inside
  `process_init_interface()`, behind the `!sta_init_flag` guard) rather than
  starting once at boot, which was only ever done so the AP beacon would carry
  its RSN element.
- The vendored ESP-IDF needs no patch now, so `06-idf-hostap-sta-join.patch`
  is gone; `hostap_sta_join` is `static` again.
- One entry of that `wpa_funcs` block had to go back: `wpa_sta_set_ap_rsnxe`
  sits among the AP callbacks but belongs to the supplicant —
  `wpa_sm_set_ap_rsnxe` lives in `rsn_supp/wpa.c` and records the RSNXE the
  *access point* advertised. `initialise_wifi()` memsets `wpa_cb` and re-fills
  it, so anything `esp_supplicant_init()` had set is lost unless restored by
  hand. With it NULL the blob logs `wifi:null wpa_sta_ap_set_rsnxe` on every
  association: WPA2-PSK still associates and routes, but the message lands on
  the serial console mid-command, and WPA3/SAE-H2E does need the callback.
  Caught on hardware after the removal, not by review.
- The firmware is also **built** without SoftAP:
  `CONFIG_ESP_WIFI_SOFTAP_SUPPORT=n` keeps the SDK's own AP machinery
  (`esp_hostap.c`, the `ap/` authenticator sources, the WiFi lib's SoftAP init)
  out of the image. ESP-IDF supports this directly — with the option off it
  compiles an empty `net80211_softap_funcs_init()` over the weak symbol in the
  closed WiFi lib. `network_adapter.bin` drops from 721,632 to 686,992 bytes,
  and the fixed 768K `factory` partition goes from 8% to 13% free — headroom
  the BLE stack had nearly used up.
- Rootfs: `/etc/udhcpd.conf` (a DHCP server for the AP's clients) and the
  busybox `udhcpd` applet are gone. `udhcpc`, the client the STA needs, stays.
- Two build-system defects found on the way: `apply-local-changes.sh` copied
  `new-files/board/` with `rsync` and no `--delete`, so a deleted kernel patch
  would linger in the buildroot tree and keep being applied; and the reference
  copy in `kernel-driver-esp32-ng/` was stale — it shipped `esp_ble_prov.c`
  while its `Makefile` did not build it.

Verified on hardware: RSA self-tests pass, `espsta0` is the only netdev, and a
WiFi scan returns results — the operation the SoftAP used to wedge.

### Boot time: 14.6 s → 11.0 s to a login prompt

Measured from the first serial byte after reset, repeatable to 0.01 s over
several cold boots. All of it came out of userspace (8.4 s → 4.8 s); the kernel
and firmware phases are unchanged at 6.2 s.

- **`S40network` no longer blocks the boot** (~2.2 s). `ifup -a` moves to the
  background: nothing later in the boot needs the network — inetd binds
  regardless of link state and the BLE link talks over `/dev/esp-ble` — and the
  interface finishes coming up behind the login prompt. It was pure waiting:
  `/etc/network/interfaces` declares `espsta0` as `inet dhcp` with
  wpa_supplicant in a *post-up* hook, so udhcpc starts before the radio has
  even associated. Its output goes to `/var/log/network.log` instead of landing
  on top of the prompt; `/etc/init.d/S40network start-fg` runs it in the
  foreground by hand.
- **`S02sysctl` replaced** (~1.4 s). Buildroot's generic version scans five
  directories with `find`, pipes through `xargs` and `readlink`, and builds a
  two-stage `logger` pipeline — about ten process spawns to apply the single
  line this board has. On XIP cramfs with a NOMMU libc that is not free.
- **cron removed** (~0.8 s). Nothing on the board used it, there are no
  crontabs, and its own stop path was broken (`no /usr/sbin/crond found`).
  `CONFIG_CROND=n` also stops buildroot from installing `S50crond`.
- **iptables no longer starts at boot** (~0.6 s), while staying installed. It
  had nothing to restore — the SoftAP's NAT is gone — so `trim-target.sh` drops
  the `S35` prefix: `rcS` only runs `/etc/init.d/S??*`, and
  `/etc/init.d/iptables start` still works by hand.

One thing this did *not* touch: 2.48 s of the kernel's 4.2 s goes into a single
gap around `of_fixed_clk_driver_init`, where the console hands over from
earlycon to `ttyS0`. It is not initcall time (all 170 initcalls together come
to 0.87 s), and `initcall_debug` cannot be used to look at it — it hangs the
board at exactly that point, mid-character. Still unexplained.

## 0.4 — WiFi setup over Bluetooth (2026-07-22)

Join the board to WiFi **from a phone, with no PC and no cable**. It advertises
over BLE as `Esp32-Linux`; connect with any BLE serial terminal, send a
character, pick a network from the list. The ESP32-S3 has no Bluetooth Classic,
so this is the Nordic UART Service over BLE.

Wait about 30 seconds after power-on before connecting — the BLE stack comes up
long before Linux has finished booting, and that window is unreliable.

- NimBLE peripheral on core 0 as a byte pipe to Linux (`/dev/esp-ble`); the
  dialog runs through the existing `wifi` command, so the driver state cannot
  desynchronise.
- The kernel's vector address is now kept in sync with the firmware
  automatically, instead of being a hand-maintained constant that silently
  killed the boot when the firmware changed size.

## 0.3 — SoftAP removed, nano, interactive wifi (2026-07-18)

- **SoftAP removed; STA only.** The closed WiFi blob beaconed as WEP, and
  bringing the AP up wedged the firmware so the STA could no longer scan. The
  board now joins networks rather than hosting them, which also makes scanning
  reliable.
- **nano** replaces the busybox `vi` applet; `vi` is a symlink to it.
- **Interactive `wifi`.** Scan, list numbered, pick one — open networks connect
  straight away, secured ones prompt. 0.2's README promised `wifi connect`
  before the command existed; now it does.
- **One full-flash image.** Flashing it alone rewrites the whole 16 MB chip.

## 0.2 — native Xtensa Linux (2026-07-17)

**Linux runs natively on the ESP32-S3.** 0.1 ran Linux on a RISC-V emulator
hosted on the chip; this replaces it with a real Linux 6.11 kernel compiled for
Xtensa, executing on the chip's own cores. No interpreter in the middle.

Verified on a fully erased board: boots to a login prompt, the RSA accelerator
passes its self-tests, the rootfs mounts from flash, telnet comes up, and the
board reaches the internet.

## 0.1 (2026-07-13)

First release: Linux on a RISC-V emulator hosted on the ESP32-S3. Superseded by
0.2, which is better in every respect; kept for the history.
