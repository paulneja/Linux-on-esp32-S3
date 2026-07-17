# Building from source

See [README.md](README.md) if you only want to flash the prebuilt images —
this file is about rebuilding them.

The project is not a normal source tree: it is a set of **patches and files
applied on top of three upstream trees** (a kernel, buildroot, and the WiFi
firmware), all cloned fresh by the build script. Nothing here is a fork; this
repo holds only the delta. That is why the layout looks the way it does:

- `patches/` — diffs against pristine upstream clones.
- `new-files/` — whole files copied into those trees (board config, defconfig,
  rootfs overlay, firmware profile files).
- `kernel-driver-esp32-ng/` — a readable reference copy of the WiFi driver.

`apply-local-changes.sh` puts all of it in place automatically, and the build
script calls it right after each clone, so a clean build reproduces the shipped
images. The sections below explain how that is wired and how to redo it by hand
if the script is ever lost.

## Reproducible build: what it really means

`refs/esp32-linux-build/Dockerfile` builds a reproducible Debian 12 image, and
**as of today it also reproduces this project's changes**, not just the
jcmvbkbc upstream. Before today that was NOT true: the `.dockerignore` excluded
`build/` (where all the changes lived) and nothing re-applied the patches after
a clean clone, so a fresh `docker run` would have built the original project,
with no AP, no NAT, no espctl.

The fix: `refs/esp32-linux-build/rebuild-esp32s3-linux-wifi.sh` now calls
`apply-local-changes.sh buildroot` right after the buildroot clone, and
`apply-local-changes.sh esp-hosted` right after the esp-hosted clone — in both
cases before the first build of that part. That script looks for the patches in
`../../native-s3` (local checkout) or in `./local-changes` (which the
Dockerfile copies there from `native-s3/patches` and `native-s3/new-files`).

**Verified today, end to end, against fresh independent clones** (not against
the already-patched working tree):
- `git apply` of the buildroot patch onto a fresh `git clone` of
  `jcmvbkbc/buildroot -b xtensa-2024.08-fdpic` → applies cleanly.
- `git apply` of the firmware patch onto a fresh `git clone` of
  `jcmvbkbc/esp-hosted -b ipc-5.1.1` → applies cleanly, local commit is
  created correctly.
- `patch -p1` of the kernel patch onto a fresh `git clone` of
  `jcmvbkbc/linux-xtensa -b xtensa-6.11-esp32-tag` → applies cleanly.
- The three steps above also run **inside the freshly built Docker container**
  (`docker run --rm --entrypoint bash ...`), not just on the host.

What is **not** verified: the full build (`make`, hours) running end to end
inside the container. That was never attempted for time reasons — the image was
built and tested, and the clone+patch flow was proven to work for real inside
it, but not the full kernel/rootfs compilation in there.

```bash
cd /home/paulneja/Arduino/esp-32/LINUX   # project root, not refs/esp32-linux-build
docker build -f refs/esp32-linux-build/Dockerfile -t linux-on-esp32s3-native .
docker run --rm -v $(pwd)/build-output:/work/build linux-on-esp32s3-native
```

### The kernel driver: a special case, already solved more robustly

The directory `drivers/net/wireless/espressif/esp32-ng/` is not tracked by git
in the kernel repo (`git status` shows it as `??`), so a `git reset --hard`
does not touch it — but a full re-extraction of the kernel
(`make linux-dirclean && make linux-rebuild`, or any clean rebuild of the
profile) does overwrite it with the pristine version, without any warning.
**This actually happened today**: the `xipImage` that was in `images/` had been
built with the driver reverted (no `espap0`, no `start_ap`/`stop_ap`) — the
firmware did have the SSID/password flashed, but the kernel never created the
AP interface, so the SoftAP would never have come up on the board.

Fix (does not rely on "don't touch that folder"):
`configs/esp32s3_devkit_c1_16m_defconfig` now has
`BR2_LINUX_KERNEL_PATCH="board/espressif/esp32s3/patches/linux"`, buildroot's
native option for kernel patches — it re-applies itself after **every** kernel
extraction, no matter what triggers it. Verified with
`make linux-dirclean && make linux-patch`: the patch applied itself, with no
manual intervention. `patches/01-kernel-esp32ng-ap-support.patch` is no longer
empty (it used to be a "this could not be generated as a diff" placeholder) —
it is now a real 493-line diff against the pristine kernel, verified to apply
cleanly with `patch -p1 --dry-run`.

## This session's incidents (why all this armor exists)

1. **Firmware, incident 1**: `keep_bootloader=y` was forgotten, `rm -rf
   build/esp-hosted` deleted 4 hand-edited files. They were rewritten from
   memory.
2. **Firmware, incident 2**: `esp_hosted_ng/esp/esp_driver/CMakeLists.txt` runs
   `git reset --hard` **unconditionally, on every `cmake .`** — it happens even
   with `keep_bootloader=y`. Fix: commit the changes directly in that repo
   (`git -c user.email=local@backup -c user.name=local-backup commit`, branch
   `ipc-5.1.1`, never pushed) so the reset lands on that commit, not on
   upstream. Now `apply-local-changes.sh esp-hosted` does this automatically.
3. **Kernel driver, incident 3** (found today, subtler): the directory is not
   tracked, so it survives `git reset --hard`, but does **not** survive a full
   re-extraction (`linux-dirclean` or fresh clone). It happened silently in some
   rebuild of the 16m profile without being noticed — the kernel compiled fine
   anyway (it compiles fine without AP too). It was discovered while auditing
   the Docker build's reproducibility, not through a visible failure. Fix:
   `BR2_LINUX_KERNEL_PATCH`, see above.

## What's here

- `patches/00-esp32-linux-build.patch` — changes to the wrapper script
  (`rebuild-esp32s3-linux-wifi.sh`): GCC-14 shim fix,
  `CMAKE_POLICY_VERSION_MINIMUM` fix, hostapd disabled. **Note**: the real
  wrapper in `refs/esp32-linux-build/` also has the two lines that call
  `apply-local-changes.sh` (added today), which this older patch does not
  include — if the wrapper is rebuilt from scratch, add those two lines by hand
  (see `rebuild-esp32s3-linux-wifi.sh` itself as reference) or regenerate the
  patch with `git diff` if the wrapper becomes a git repo again.
- `patches/01-kernel-esp32ng-ap-support.patch` — a real diff (493 lines)
  against a pristine `jcmvbkbc/linux-xtensa -b xtensa-6.11-esp32-tag`. Applied
  automatically via `BR2_LINUX_KERNEL_PATCH` (see above) — no manual
  intervention needed unless the defconfig is rebuilt from scratch.
- `patches/04-kernel-esp32s3-rsa-crypto.patch` — adds the hardware RSA
  accelerator driver (`drivers/crypto/esp32s3_rsa.c`, 549 lines) plus its
  `obj-y` line. Also applied automatically: both kernel patches live in
  `new-files/board/espressif/esp32s3/patches/linux/` (as `01-` and `02-`, the
  order they are applied in), which is what `BR2_LINUX_KERNEL_PATCH` points at.
  Verified to apply cleanly with `patch -p1` and to reproduce the exact driver
  that the shipped `xipImage` was built from.
- `flash.sh` — flashes a bare board from `images/` with nothing but `esptool`
  (see "Flash directly" above).
- `patches/02-firmware-network-adapter-ap-support.patch` — changes to the
  ESP32 firmware
  (`esp-hosted/esp_hosted_ng/esp/esp_driver/network_adapter/main/`). Applied
  automatically by `apply-local-changes.sh esp-hosted`.
- `patches/03-buildroot-tracked-changes.patch` — a single consolidated
  `git diff` of all tracked files modified under `build/buildroot/`
  (busybox.config, inetd.conf, wpa_supplicant.conf.example, both defconfigs).
  Replaces the old `03-buildroot-board-config.patch` and
  `04-nat-dns-security-buildroot.patch` / `05-ssh-idle-timeout.patch`, which
  overlapped each other and are no longer maintained. Applied automatically by
  `apply-local-changes.sh buildroot`.
- `kernel-driver-esp32-ng/` — a complete reference/human-readable copy of
  `drivers/net/wireless/espressif/esp32-ng/` with AP support; the patch above is
  what is actually used in the automated flow, this is a readable backup.
- `new-files/` — an exact mirror of what has to be copied: `board/` and
  `configs/` go over `build/buildroot/` (automatic via
  `apply-local-changes.sh buildroot`); `esp-hosted/network_adapter/*.16m8r`
  (partition table + sdkconfig for the 16 MB profile, new files the firmware
  patch does not cover since it is a `git diff` of only `main/`) go over
  `build/esp-hosted/esp_hosted_ng/esp/esp_driver/network_adapter/` (automatic
  via `apply-local-changes.sh esp-hosted`); `toplevel/` is reference only
  (`devkit-c1-16m.conf`, `Dockerfile`, `.dockerignore` — the real ones live in
  `refs/esp32-linux-build/` and at the project root).

## How to restore manually (if `apply-local-changes.sh` is not available)

Normally not needed — `rebuild-esp32s3-linux-wifi.sh` calls the script itself.
This is only for the emergency case where that script is also lost:

```bash
cd refs/esp32-linux-build
git apply native-s3/patches/00-esp32-linux-build.patch   # if needed

cd build/buildroot
git apply ../../../native-s3/patches/03-buildroot-tracked-changes.patch
cp -a ../../../native-s3/new-files/board/* board/
cp -a ../../../native-s3/new-files/configs/* configs/
cd ../..

cd build/esp-hosted/esp_hosted_ng
git apply ../../../native-s3/patches/02-firmware-network-adapter-ap-support.patch
git add esp/esp_driver/network_adapter/main/
git -c user.email="local@backup" -c user.name="local-backup" \
  commit -m "AP support + 16m8r profile files (local-only, never push)"
cd ../../..

cp native-s3/new-files/toplevel/devkit-c1-16m.conf .
```

The kernel driver applies itself via `BR2_LINUX_KERNEL_PATCH` once the defconfig
above is in place — no additional manual step is required.

**Status: validated on real hardware.** The combined image was flashed to a
fully erased ESP32-S3 (N16R8) and it boots to a login prompt, the RSA
accelerator passes its 512- and 2048-bit self-tests, the rootfs mounts from
flash via XIP, and telnet comes up. Working: serial console, telnet, STA WiFi
with internet, hardware RSA, Lua, an opt-in BusyBox httpd, and curl (HTTP
solid, HTTPS with real certificate verification but experimental — see above).
Not working: the SoftAP (WEP beacon, see above).

The patch/clone flow is reproducible and was verified against fresh clones, and
the Docker image builds; what was never run end to end is the *full* multi-hour
compile inside the container.
