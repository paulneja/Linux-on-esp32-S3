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
