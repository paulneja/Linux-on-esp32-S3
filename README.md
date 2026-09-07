# Linux on an ESP32-S3 — native Linux, fork and a usable shell

Linux 6.11 running **natively on the ESP32-S3's Xtensa cores**, with WiFi,
Bash, MicroPython and writable storage. Linux is not emulated: Espressif's
firmware runs alongside it on the same chip and handles WiFi and flash access.
All of this runs on one N16R8 board, without extra RAM, an SD card or a second
computer attached to keep it running.

## What's new in the current version

The `mmu-poc` branch expands the earlier 0.6 system with **native `fork()`
support and a larger userspace**. It is the current experimental development
version, not a new numbered stable release.

- **Native fork-enabled programs.** Software memory banks let parent and child
  keep independent private state, with backup memory reclaimed when it is no
  longer shared. This unlocks tested process workflows that the previous
  NOMMU system could not run.
- **Bash for the user, a lightweight shell for services.** Bash 5.2.37 is the
  login shell; BusyBox remains `/bin/sh`. Dash 0.5.12 is also available.
- **More real programs under their normal names.** GNU Make 4.4.1, MicroPython
  1.26.0 with fork/IPC support, socat 1.8.1.3 and `nc`/`netcat`.
  Make executes build recipes; it is not a C compiler.
- **An editable web page and private user homes.** Web content lives in
  `/home/www`; root gets a welcome README in `/home/root`. Users have their
  own homes, Unix permissions and `su`/`passwd`.
- **Scheduled jobs and detachable sessions.** Persistent per-user
  `cron`/`crontab`, `@reboot` jobs, `session`/dtach consoles and
  `nohup ... &` for background work.
- **Tools for working within 8 MiB of RAM.** `jobq` limits job concurrency
  and checks available memory; `programbench` measures program costs.
  Image profiles select programs, and checked ELF stripping saves flash.
- **A complete clean-build pipeline.** Toolchain, kernel, firmware and
  userspace are built from downloaded sources. Images have checksums and
  partition checks; the board test suite ties results to one exact image.
  Boot initialization avoids unnecessary writes and has a bounded wait for
  slow home setup.

**Fork is not a full MMU.** This remains NOMMU Linux, with no hardware process
memory protection. The switchable MMU-remap experiment is a separate runtime,
not a loader for arbitrary desktop binaries. See [limits](#limits) below.

## Hardware

- **ESP32-S3 with 16 MB flash and 8 MB Octal PSRAM**: an N16R8 module such as
  the corresponding DevKitC-1.
- Power and a serial/COM connection for flashing and the console. Use your
  board's actual adapter port; no additional peripherals are required.

## Get the current version

**The combined BIN committed in `images/` is still 0.6.** It does not contain
the new fork backend or programs. Build `mmu-poc` to get the current system.

### 1. Build from a clean checkout

On a Linux host with Git and Docker access, as a regular user:

```sh
git clone --branch mmu-poc https://github.com/paulneja/Linux-on-esp32-S3.git
cd Linux-on-esp32-S3
JOBS=8 bash build/reproduce.sh
```

Allow time for downloads and compilation, and substantial free disk space.
The build uses its own directory and does not reuse the development machine's
toolchain or overwrite the older committed images.

The output is `build-output/reproduce.XXXXXX/artifacts/`, containing the
16 MiB `linux-esp32s3-native-full.bin`, its component images,
`SHA256SUMS` and `build-manifest.json`. Replace `XXXXXX` with the directory
printed by your run. See the [complete build instructions](build/README.md).

### 2. Flash the image you just built

Install esptool on the host, close any console holding the COM port, and use
the actual adapter path in place of `/dev/ttyUSB0`.

**A full-image write replaces configuration and user files, including
`/etc` and `/home`, even without a separate erase command. Back up anything
you need first.**

```sh
esptool --chip esp32s3 --port /dev/ttyUSB0 --baud 460800 \
    write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m \
    0x0 build-output/reproduce.XXXXXX/artifacts/linux-esp32s3-native-full.bin
```

Do not use `./flash.sh` for this step unless you deliberately want its
`images/` inputs: it does not automatically pick up the new build.

### 3. Log in and connect

Open your serial terminal at **115200 baud**, using the same COM adapter.
For example:

```sh
screen /dev/ttyUSB0 115200
```

Log in as **`root` / `changeme123`**, then run `passwd` to change the
password. A factory image has no WiFi configured:

```sh
wifi
```

The interactive menu scans and lets you choose a network. Alternatively,
use `wifi connect "YOUR SSID" "YOUR PASSWORD"`.

`Starting network (background): OK` only means startup was launched, not
that WiFi connected. Check `/var/log/network.log` for the result. NTP sets
the clock after networking comes up; until then, HTTPS certificate checks
can fail because the board has no battery-backed clock.

Telnet is enabled by default and sends credentials in clear text. Use a
trusted LAN and read [SECURITY.md](SECURITY.md) before connecting.

## Things to try

- Run a script with `micropython /home/root/script.py`. This is MicroPython,
  not CPython; general `pip` compatibility is not provided.
- Edit `/home/www/index.html`, run `web-server on`, then open the board's IP
  in a browser. `web-server off` disables it; the setting survives reboot.
- Use `crontab -e` to schedule jobs for your user.
- Run `session work` to create or reattach a lightweight shell. Detach with
  **Ctrl-]** and list sessions with `session list`.
- Use `nohup command > /tmp/job.log 2>&1 &` for a noninteractive job that
  should survive closing the console. It does not survive a reboot or power
  loss; make sure closing the terminal does not reset the board.

More commands, measurements and examples are in the
[userspace guide](experiments/mmu-poc/programs/USERSPACE-UPGRADE.md).

## Features carried forward from 0.6

- **STA WiFi and BLE provisioning.** Join an existing network over the
  console or through the `Esp32-Linux` BLE service. See [BLE.md](BLE.md).
  SoftAP was removed; the board does not host a WiFi access point.
- **nano and Lua.** `vi` points to nano rather than the disabled BusyBox vi
  applet.
- **Hardware RSA acceleration.** The `rsa-esp32s3` Linux Crypto API driver
  has boot-time 512-bit and 2048-bit self-tests.
- **Optional SSH and HTTP services.** Dropbear is controlled with
  `ssh-server on|off|status`; HTTP with `web-server on|off|status`.
  Both are off by default. SSH is slow on this hardware; the RSA driver does
  not accelerate its Curve25519 operations.
- **NTP and curl.** Plain HTTP works. HTTPS uses certificate verification
  with a trimmed CA bundle and TLS 1.2, but remains experimental under the
  board's RAM constraints.

## Build and test status

The build and hardware evidence are recorded separately:

- A clean build and a later **local-clone build** passed **26/26 hardware
  checks**, covering fork, programs, users, cron and session persistence.
  See the [clean-image record](build/verification/2026-09-06.md) and
  [clone-build record](build/verification/2026-09-07-clone-build.md).
- Two independent builds of **the same commit, `9226140`**, produced five
  byte-identical artifacts out of eight. Of 772 rootfs entries, only
  `/etc/shadow` differed because of the random password salt. See the
  [comparison](build/verification/2026-09-06-reproducibility.json).
- The separate clone comparison also found an embedded Git-version metadata
  difference in the firmware. **These results do not establish bit-for-bit
  reproducibility of the complete BIN.**
- The corrected source at **`7b8a4d0`** completed the full clean pipeline and
  host tests. Its new combined image still requires its own hardware run;
  earlier 26/26 results must not be attributed to it.

A build succeeding is not the same as a board test passing. Consult the
image's `build-manifest.json` and matching `results.json`. The board suite
does not test an external WiFi connection or sustained flash reclaim.

## Limits

- **8 MiB RAM is a real constraint.** Fork eagerly copies private memory;
  it is not copy-on-write. The backend is UP-only, rejects multithreaded fork
  and limits private memory per fork to 512 KiB. Several Bash sessions or
  large pipelines can run out of memory; detached sessions default to Dash.
- **Native binaries must target Xtensa/FDPIC.** Arbitrary x86, ARM or desktop
  Linux binaries do not run. CPython, Neovim, SQLite, sudo and doas are not
  included.
- **Writable flash can become extremely slow.** `/etc` and `/home` use
  JFFS2. Large writes and block reclaim caused severe slowdowns in tests,
  including with fork disabled and with the 0.6 kernel. Startup changes
  mitigate the boot impact; they do not fix write throughput. Avoid heavy
  rewrites and keep important data backed up. See the
  [flash-write investigation](build/verification/2026-09-06-jffs2-erase.md).
- **Permissions are not memory isolation.** Use trusted programs and users.
  This is a research project, not a hardened production system.
- **The rootfs is read-only XIP cramfs.** Executing directly from flash is
  essential to fitting the system in RAM. Build through the full pipeline;
  matching extracted files alone does not validate a manually repacked image.

## Older 0.6 prebuilt images

For the previous release without the new fork/userspace work:

```sh
./flash.sh -p /dev/ttyUSB0
```

The script reads `images/` and requires Python 3 and esptool. The combined
image there is still 0.6; a separate formatted `images/home.jffs2` was added
for factory resets with `--parts --erase`.

- Default full-image flashing replaces both `/etc` and `/home`.
- `--parts` preserves `/home`, but replaces `/etc`, including accounts and
  network configuration.
- `--parts --erase` wipes the chip and writes the factory home image too.

`make-images.sh` and the existing GitHub Actions workflow are the older
base-system build path, not the complete fork-enabled pipeline.

## Documentation

- [Build pipeline](build/README.md): clean builds, artifacts and board tests.
- [Architecture](ARCHITECTURE.md): shared chip, boot flow and flash layout.
- [Development](DEVELOPMENT.md): patches, upstream sources and the legacy build.
- [Userspace](experiments/mmu-poc/programs/USERSPACE-UPGRADE.md): programs,
  fork implementation and measured limits.
- [Troubleshooting](TROUBLESHOOTING.md), [security](SECURITY.md),
  [Bluetooth setup](BLE.md) and [changelog](CHANGELOG.md).

## History, credits and license

The original 0.1 approach emulated a RISC-V machine. The current project runs
native Xtensa Linux; the older approach remains in Git history.

Built on the Xtensa Linux, Buildroot and esp-hosted work of
[**jcmvbkbc**](https://github.com/jcmvbkbc) (Max Filippov), and on Espressif's
firmware. See [NOTICE](NOTICE) for third-party components and licenses.

This project is licensed under the **GPLv3** (see [LICENSE](LICENSE)). Kernel
code contributed here (`drivers/crypto/esp32s3_rsa.c`) is GPL-2.0-or-later.
