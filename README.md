# Linux on an ESP32-S3 — natively, with WiFi

A real Linux 6.11 kernel, compiled for **Xtensa** and running **natively on the
ESP32-S3's own cores** — no emulator in between. WiFi keeps working while it
runs: the Espressif firmware lives on the same die and Linux talks to it, so
the board joins your network, reaches the internet, and you get a shell over
telnet or the serial console.

The chip's **hardware RSA accelerator** is exposed to Linux through the Crypto
API, so it is usable by any program, not just one demo.

> **Current branch: experimental native fork and expanded userspace.** Bash,
> Dash, GNU Make, MicroPython, socat/nc, detached sessions, private user homes
> and cron have passed tests on the ESP32-S3. The fork implementation uses
> software memory banks; it is not a full MMU or hardware memory protection.
>
> The committed `images/` still contain the earlier 0.6 release. For the
> complete current branch, use [the clean build pipeline](build/README.md).
> Its first end-to-end build and exact-image hardware verification are in
> progress; the earlier clean-build evidence applies to 0.6, not automatically
> to this new image. This is a research project, not a production system.

> **Note on history.** This repo used to host an *emulated* approach (a RISC-V
> RV32IMA interpreter running Linux on top of the ESP32-S3). That worked, but
> was inherently slow and limited. This is the same project, continued: the
> native Xtensa build replaces it and improves on it in every way. The old
> approach remains in the git history and in the `0.1` release.

## Hardware

- **ESP32-S3 with 16 MB flash and 8 MB Octal PSRAM** (an N16R8 module, e.g.
  DevKitC-1). The PSRAM is the system RAM — the 8 MB Octal part is required.
- A cable for the board's serial/COM connection. The device name depends on
  the adapter and OS; use the port actually detected on your machine.

## Quick start (nothing to build)

The earlier 0.6 prebuilt images are in `images/`. They do not include the new
fork/userspace work. You only need `esptool` to flash that release:

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

A fresh flash has no WiFi configured. `Starting network (background): OK` in
the boot log only means the step was launched — it runs behind the login prompt
and what it actually did lands in `/var/log/network.log`. Join your network
with:

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

- **Bash 5.2.37 for user logins**, with BusyBox `/bin/sh` retained for services.
- **Native fork-enabled programs:** Dash 0.5.12, GNU Make 4.4.1, MicroPython
  1.26.0 and socat 1.8.1.3. `make` runs build recipes; it is not a C compiler.
  MicroPython is not CPython and does not provide general pip compatibility.
- **nc/netcat**, cron/crontab, `jobq`, `programbench`, and process diagnostics.
- **Private user homes and Unix permissions**, `su`/`passwd`, editable web
  files in `/home/www`, and `session`/dtach for detachable consoles. No sudo
  or doas. `nohup ... &` supports noninteractive jobs across a COM disconnect,
  provided the console does not reset the board and power remains on.
- Serial console and **telnet** (on by default).
- **STA WiFi** with real internet access — run `wifi` for an interactive
  scan-and-pick, or `wifi connect "SSID" "PASS"` non-interactively.
- **WiFi setup over Bluetooth** — the board advertises as `Esp32-Linux`; connect
  from a phone with any BLE serial terminal and pick a network, no PC and no
  cable needed. Wait ~30 s after power-on before connecting. See **[BLE.md](BLE.md)**.
- **nano** as the editor (the busybox `vi` applet is disabled; `vi` is a
  symlink to `nano`).
- **Hardware RSA accelerator** — `rsa-esp32s3` in the Crypto API, with a
  boot-time self-test at 512 and 2048 bits. The kernel stacks
  `pkcs1pad(rsa-esp32s3,sha256)` on top, so X.509 verification uses it.
- **SSH** (dropbear) — present but **off by default**: `ssh-server on|off|status`.
  It is slow here, and the RSA accelerator does not help it (modern SSH uses
  Curve25519, not RSA).
- **Lua**, and a BusyBox **httpd** serving an editable status page (`/home/www`) —
  **off by default**: `web-server on|off|status`, the same idea as
  `ssh-server`. Turn it on and browse to the board's IP; the setting survives a
  reboot, and while nobody is looking at the page nothing is running.
- **curl** over plain HTTP.
- **The clock sets itself.** There is no RTC on this board, so it powers on
  believing it is 1 Jan 1970 — and until that is fixed *every* HTTPS request
  fails, because every certificate is "not valid before" a date still in the
  future. It now asks NTP as soon as the interface gets an address. That is
  *after* the login prompt, not before — the prompt comes up at ~11 s and the
  clock lands around 20–35 s in, once WiFi has associated — so if you log
  straight in, `date` can still say 1970 for a moment. What it did is in
  `/var/log/network.log`. On a network with no internet it stays in 1970;
  `date -s "2026-07-31 10:00:00"` still works by hand.

**Partly works**

- **curl over HTTPS** — real certificate verification against a curated CA
  bundle, checked against github, google and example.com, but **experimental**:
  the bundle is trimmed to 34 major roots because the full 140-cert set
  exhausts mbedTLS's memory on this board, TLS is 1.2 only, and RAM is tight.
  Fine for light fetches, not a robust tool.

**Removed**

- **SoftAP** (the board acting as an access point) — **removed on purpose.**
  The closed WiFi blob beaconed as **WEP** instead of WPA2 (clients reject it),
  and bringing the AP up wedged the firmware so the STA could no longer scan or
  associate. It was disabled first and has now been taken out of both the
  kernel driver and the firmware entirely, along with the `ap` command. This
  board is **STA only**: it joins an existing network, it does not host one.

## Build from source

Everything needed to reproduce the images is here: the kernel patches (including
the RSA driver), the buildroot configuration and overlay, and the firmware
patches. They apply automatically on top of fresh upstream clones.

For the current fork-enabled branch, run `JOBS=8 bash build/reproduce.sh`.
The [complete build pipeline](build/README.md) produces a combined BIN and
checksums in a new `build-output/reproduce.XXXXXX/artifacts/` directory,
without replacing the committed stable images.

`make-images.sh` remains the legacy base-system packager; by itself it does
not add the fork backend or expanded userspace. Repackaging existing outputs
can preserve their bytes, but does not demonstrate a fresh source build.

## Documentation

| | |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | How two operating systems share one chip, the boot flow, the flash layout |
| **[DEVELOPMENT.md](DEVELOPMENT.md)** | Building from source, the patch system, packaging, reproducibility caveats |
| **[BLE.md](BLE.md)** | The Bluetooth provisioning link |
| **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** | Symptoms seen on hardware, and what caused them |
| **[SECURITY.md](SECURITY.md)** | What a flashed board exposes — read this before putting one on a network |
| **[CHANGELOG.md](CHANGELOG.md)** | What changed in each release |

## Constraints worth knowing

This remains a NOMMU Linux build (`BINFMT_ELF_FDPIC`). The experimental kernel
implements native `fork()` using private software memory banks and restores
their contents at context switches. It uses eager copies, not copy-on-write;
the current backend is UP-only, rejects multithreaded fork and limits private
memory per fork to 512 KiB. A successful fork needs additional RAM, and the
MMU remap demonstration is a separate runtime, not a universal Linux loader.

Only programs compiled for this Xtensa/FDPIC ABI can run natively. Arbitrary
x86, ARM or desktop Linux binaries will not work. CPython and Neovim are not
included; SQLite, sudo and doas were also deliberately excluded. Unix users
and permissions do not make hostile code safe without memory protection.
See [implementation and measured limits](experiments/mmu-poc/programs/USERSPACE-UPGRADE.md).

The rootfs is a read-only **cramfs executed
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
