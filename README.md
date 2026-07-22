# Linux on an ESP32-S3 — natively, with WiFi

A real Linux 6.11 kernel, compiled for **Xtensa** and running **natively on the
ESP32-S3's own cores** — no emulator in between. WiFi keeps working while it
runs: the Espressif firmware lives on the same die and Linux talks to it, so
the board joins your network, reaches the internet, and you get a shell over
telnet or the serial console.

The chip's **hardware RSA accelerator** is exposed to Linux through the Crypto
API, so it is usable by any program, not just one demo.

> **Status: working, validated on real hardware.** Flashed to a fully erased
> ESP32-S3: it boots to a login prompt, the RSA accelerator passes its
> self-tests, the rootfs mounts from flash, telnet comes up and the board
> reaches the internet. It is a hobby project, not a product — see
> [What works](#what-works-and-what-does-not) for the honest list.

> **Note on history.** This repo used to host an *emulated* approach (a RISC-V
> RV32IMA interpreter running Linux on top of the ESP32-S3). That worked, but
> was inherently slow and limited. This is the same project, continued: the
> native Xtensa build replaces it and improves on it in every way. The old
> approach remains in the git history and in the `0.1` release.

## Hardware

- **ESP32-S3 with 16 MB flash and 8 MB Octal PSRAM** (an N16R8 module, e.g.
  DevKitC-1). The PSRAM is the system RAM — the 8 MB Octal part is required.
- A USB cable. The console is the built-in USB-Serial-JTAG (`/dev/ttyACM0`).

## Quick start (nothing to build)

Prebuilt images are in `images/`. You only need `esptool`:

```bash
pip install esptool          # or activate ESP-IDF: . $IDF_PATH/export.sh
./flash.sh                   # write the one full-flash image — that is all
```

`flash.sh` finds esptool and the serial port on its own (`-p /dev/ttyXXX` to
override). It writes `images/linux-esp32s3-native-full.bin`, a single
**full-flash 16 MB image** for offset `0x0` that contains everything —
bootloader, partition table, WiFi firmware, `/etc`, kernel and rootfs — with
the unused space (the `/home` partition) padded to `0xff`. Flashing it erases
and rewrites the whole chip in one shot, so this one file is a complete,
self-contained install: no separate `--erase` step, nothing else to flash.
(`--erase` still works and is harmless if you want a belt-and-suspenders wipe.)

Then open the console and log in:

```bash
screen /dev/ttyACM0 115200   # or: picocom -b 115200 /dev/ttyACM0
```

Login is **`root`** / **`changeme123`** — change it with `passwd`.

A fresh flash has no WiFi configured, so `Starting network: ... FAIL` in the
boot log is expected. Join your network with:

```sh
wifi                                      # interactive: scans, lists networks,
                                          # pick a number; open ones connect
                                          # straight away, secured ones ask for
                                          # the password
wifi connect "YOUR SSID" "YOUR PASSWORD"  # or do it non-interactively
```

From then on the board gets an IP over DHCP and you can `telnet` to it from
your LAN. Right after boot RAM is tight while services start, so an occasional
command can be killed by the OOM killer — wait a few seconds and retry.

## What works, and what does not

**Works**

- Serial console and **telnet** (on by default).
- **STA WiFi** with real internet access — run `wifi` for an interactive
  scan-and-pick, or `wifi connect "SSID" "PASS"` non-interactively.
- **nano** as the editor (the busybox `vi` applet is disabled; `vi` is a
  symlink to `nano`).
- **Hardware RSA accelerator** — `rsa-esp32s3` in the Crypto API, with a
  boot-time self-test at 512 and 2048 bits. The kernel stacks
  `pkcs1pad(rsa-esp32s3,sha256)` on top, so X.509 verification uses it.
- **SSH** (dropbear) — present but **off by default**: `ssh-server on|off|status`.
  It is slow here, and the RSA accelerator does not help it (modern SSH uses
  Curve25519, not RSA).
- **Lua**, and a BusyBox **httpd** serving a small status page (`/www`), started
  on demand with `httpd -h /www -p 80` so it costs nothing when unused.
- **curl** over plain HTTP.

**Partly works**

- **curl over HTTPS** — real certificate verification against a curated CA
  bundle, checked against sites like github and google, but **experimental**:
  the bundle is trimmed to 34 major roots because the full 140-cert set
  exhausts mbedTLS's memory on this board, TLS is 1.2 only, and RAM is tight.
  Fine for light fetches, not a robust tool.

**Removed**

- **SoftAP** (the board acting as an access point) — **disabled on purpose.**
  The closed WiFi blob beaconed as **WEP** instead of WPA2 (clients reject it),
  and bringing the AP up wedged the firmware so the STA could no longer scan or
  associate. So the `espap0` interface is no longer created at all — the kernel
  driver hard-forces it off — and the `ap` command is gone. This board is **STA
  only**: it joins an existing network, it does not host one.

## Build from source

Everything needed to reproduce the images is here: the kernel patches (including
the RSA driver), the buildroot configuration and overlay, and the firmware
patches. They apply automatically on top of fresh upstream clones.

Once a build finishes, `./make-images.sh /path/to/esp32-linux-build` collects
the results into `images/` and merges them into the single flashable image —
byte for byte the one published in the releases.

See **[DEVELOPMENT.md](DEVELOPMENT.md)** for the build, the patch system, the
packaging step and the reproducibility caveats. See **[ARCHITECTURE.md](ARCHITECTURE.md)** for how two
operating systems share one chip, the boot flow and the flash layout.

## Constraints worth knowing

For Linux's purposes the ESP32-S3 has **no MMU**, so this is a NOMMU build
(`BINFMT_ELF_FDPIC`): there is **no `fork()`**, which rules out anything that
depends on it (bash, python, nginx, hostapd...). BusyBox `hush` (the default
shell here) and everything shipped work within that limit. The rootfs is a read-only **cramfs executed
in place (XIP)** straight from flash, which is why it fits at all; `/etc` and
`/home` are separate writable jffs2 partitions mounted over it.

## Credits and license

Built on the Xtensa Linux, buildroot and esp-hosted work of
[**jcmvbkbc**](https://github.com/jcmvbkbc) (Max Filippov), and on Espressif's
esp-hosted firmware. See [NOTICE](NOTICE) for the full list of third-party
components and their licenses.

This project is licensed under the **GPLv3** (see [LICENSE](LICENSE)). Kernel
code contributed here (`drivers/crypto/esp32s3_rsa.c`) is GPL-2.0-or-later, as
kernel code must be.
