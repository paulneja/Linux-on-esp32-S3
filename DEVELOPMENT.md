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

## With Docker (recommended)

Debian 12 is used deliberately: its GCC and CMake are old enough not to trip
the "host tools too new" failures a rolling-release distro hits. From the root
of this repo:

```bash
docker build -f new-files/toplevel/Dockerfile -t linux-on-esp32s3 .
docker run --rm -v $(pwd)/build-output:/work/esp32-linux-build/build \
    linux-on-esp32s3
```

The image clones jcmvbkbc's `esp32-linux-build`, patches it with
`patches/00-...`, and drops `apply-local-changes.sh` plus the 16MB board
profile next to it. The run then fetches crosstool-NG, buildroot, esp-hosted
and the kernel, and builds everything into the mounted `build-output/`. It
takes hours; the toolchain alone is most of it.

**Verified**, end to end: a clean clone of this repo, built in this container,
runs to completion, and the images it produces boot on the hardware. That is the
whole path — nothing from a local working tree in the middle of it, which is
exactly what four earlier failures had been hiding in (incidents 4-7 below).

The images shipped with the releases were built natively rather than in Docker,
so they are not bit-identical to a container build; they are the same sources.

## Without Docker

The host needs a working build environment (autoconf, automake, bison, flex,
cmake, rsync, texinfo, ...) and a GCC that is not too new. If the host's GCC
defaults to C23 (15/16.x), GMP's configure breaks; the wrapper works around it
by putting a directory of gcc-14 symlinks first in `PATH` — set `GCC14_SHIM` to
it, or create `~/esp/gcc14shim`. On an older host, skip that.

```bash
git clone https://github.com/paulneja/Linux-on-esp32-S3
git clone https://github.com/jcmvbkbc/esp32-linux-build
cd esp32-linux-build
patch -p1 < ../Linux-on-esp32-S3/patches/00-esp32-linux-build.patch
cp ../Linux-on-esp32-S3/new-files/toplevel/apply-local-changes.sh \
   ../Linux-on-esp32-S3/new-files/toplevel/devkit-c1-16m.conf .
./rebuild-esp32s3-linux-wifi.sh -c devkit-c1-16m.conf
```

Images land in `build/build-buildroot-esp32s3_devkit_c1_16m/images/` and in the
firmware's build directory. `flash.sh --parts` in this repo documents which
image goes at which offset.

## Packaging the images

The build driver compiles everything but stops there — it does not gather the
results or package them. `make-images.sh` closes that gap:

```bash
./make-images.sh /path/to/esp32-linux-build
```

It collects the six binaries into `images/`, checks each one fits its
partition, refuses to package an `etc.jffs2` that has a `psk=` line in it, and
merges everything into `images/linux-esp32s3-native-full.bin` for offset `0x0`.

Two things it does deliberately, both learned the hard way:

- **It regenerates `partition-table.bin` from the CSV**, never copying the one
  the firmware build emits — that one comes from an older CSV that puts rootfs
  at the wrong offset, and since the kernel derives the rootfs XIP address from
  the partition table, booting it panics with "Cannot open root device".
- **It refuses images carrying WiFi credentials.** buildroot's `target/` is
  incremental, and a stale `target/etc/wpa_supplicant.conf` left over from a
  manual test once got baked into `etc.jffs2` and shipped. WiFi belongs at
  runtime (`wifi connect`), never in the image.

Running it against the tree that produced the published release reproduces
`linux-esp32s3-native-full.bin` byte for byte (same sha256).

## Reproducibility caveats

Worth knowing before trusting a rebuild to match:

- **The upstream trees are tracked by branch, not by pinned commit.** The build
  driver clones `jcmvbkbc/buildroot -b xtensa-2024.08-fdpic`,
  `esp-hosted -b ipc-5.1.1` and the kernel tag the same way. If upstream moves,
  a rebuild can produce different output, or a patch here can stop applying.
  That is upstream's design, not something this repo overrides.
- **A full from-scratch build has now been run end to end, and the result boots
  on hardware.** It took four fixes to get there (incidents 4-7 below): the
  container was missing `cpio`, one patch was being discarded in silence, and
  both the firmware patch and the defconfig had drifted behind the tree the
  published images were built from. Nothing built before those is comparable.
- **GitHub's source ZIP drops the executable bit.** Git stores it correctly
  (`100755`), so a `git clone` is fine; if you downloaded the ZIP, run
  `bash flash.sh` or `chmod +x *.sh` first.

## How the pieces fit

The build driver (`rebuild-esp32s3-linux-wifi.sh`) is **upstream's**, not ours:
it clones crosstool-NG, buildroot, esp-hosted and the kernel, and builds them.
Left alone it would build jcmvbkbc's project, not this one.

`patches/00-esp32-linux-build.patch` is what changes that. Besides the
host-tool workarounds, it adds two lines — one after the buildroot clone, one
after the esp-hosted clone:

```sh
[ -x ../apply-local-changes.sh ] && ../apply-local-changes.sh buildroot
[ -x ../apply-local-changes.sh ] && ../apply-local-changes.sh esp-hosted
```

Those two lines are the hinge of the whole thing. Without them the build
silently produces the upstream project — it does not fail, it just builds
something else. `apply-local-changes.sh` then applies
`patches/03-buildroot-tracked-changes.patch`, copies `new-files/board` and
`new-files/configs` into buildroot, applies the firmware patch and commits it
locally (the firmware's own CMakeLists runs `git reset --hard` on every `cmake`
invocation, so a local commit is the only thing that survives).

It finds this repo's `patches/` and `new-files/` by looking for `$LOCAL_CHANGES`,
then `./local-changes` (what the Dockerfile sets up), then any directory beside
or above it that has both — so the checkout's directory name does not matter.

The kernel patches are **not** applied by that script: they are wired into
buildroot itself via `BR2_LINUX_KERNEL_PATCH` in
`configs/esp32s3_devkit_c1_16m_defconfig`, pointing at
`board/espressif/esp32s3/patches/linux/`. Buildroot re-applies them after every
kernel extraction, including ones triggered mid-session — see below for why
that matters.

**Verified against fresh independent clones** (not against an already-patched
tree): the buildroot patch applies to a fresh `jcmvbkbc/buildroot
-b xtensa-2024.08-fdpic`, the firmware patch to a fresh `jcmvbkbc/esp-hosted
-b ipc-5.1.1`, and both kernel patches to a fresh `jcmvbkbc/linux-xtensa
-b xtensa-6.11-esp32-tag`.

### The kernel driver: a special case, already solved more robustly

The directory `drivers/net/wireless/espressif/esp32-ng/` is not tracked by git
in the kernel repo (`git status` shows it as `??`), so a `git reset --hard`
does not touch it — but a full re-extraction of the kernel
(`make linux-dirclean && make linux-rebuild`, or any clean rebuild of the
profile) does overwrite it with the pristine version, without any warning.
**This actually happened once**: an `xipImage` in `images/` had been built with
the esp32-ng driver reverted to its pristine upstream version — the local
changes were silently missing, so the shipped kernel did not match the patch
this repo carries.

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
4. **Container, incident 4**: buildroot needs `cpio`, and the Dockerfile never
   installed it. It is checked in `support/dependencies/`, i.e. *after*
   crosstool-NG has compiled the entire toolchain, so the build died hours in,
   at its most expensive point. `file` and `bzip2` were missing for the same
   reason. Fix: install them.
5. **Patches, incident 5** (the dangerous one):
   `03-buildroot-tracked-changes.patch` carried a compiled binary recorded as
   `Binary files ... differ` with an abbreviated index. `git apply` cannot
   reconstruct that, and it is atomic, so the patch was rejected **in full** on
   every fresh clone — and `apply-local-changes.sh` read "does not apply" as
   "already applied" and carried on. The build reported success while producing
   an image with no `/etc/fstab`, no `inetd.conf` and no `S05home`. Fix: drop
   from the patch everything `new-files/` already ships, and make the two cases
   distinguishable — a reverse check for "already applied", a hard error for
   anything else.
6. **Firmware, incident 6**: a from-scratch build reached the MMC host and
   stopped dead — no panic, no output. The kernel's RSA driver opens with an
   unbounded `while (readl(rsa + RSA_QUERY_CLEAN) != 1)`, waiting on a clock it
   deliberately never enables: the firmware hands the block over with
   `periph_module_enable(PERIPH_RSA_MODULE)`. That line,
   `CONFIG_MBEDTLS_HARDWARE_MPI=n`, the entire BLE link (patch 05 existed;
   nothing ever applied it) and a one-symbol ESP-IDF change were all in the
   working tree and in no patch here. Fix: regenerate the firmware patch
   straight from that tree, and verify the reconstruction byte for byte.
   **The wait loop still has no timeout.**
7. **Config, incident 7**: two things the released image had only by accident of
   a hand-edited, incremental `target/`. `setup-home.sh` was missing from
   `BR2_ROOTFS_POST_BUILD_SCRIPT`, so root landed in `/root`, on the read-only
   cramfs, instead of the writable jffs2. And buildroot's wpa_supplicant package
   installs its own `/etc/wpa_supplicant.conf`: a network block with no ssid and
   `key_mgmt=NONE`, which matches **any** open network — a clean build joined a
   carrier hotspot by itself. `make-images.sh` waved it through because its check
   looked only for `psk=`, and an open-network block has no credentials in it at
   all. Fix: `no-open-wifi.sh` at post-build, and a second check in
   `make-images.sh`.

## What's here

- `patches/00-esp32-linux-build.patch` — changes to upstream's build driver
  `rebuild-esp32s3-linux-wifi.sh`: the two `apply-local-changes.sh` calls that
  make the build reproduce this project (see "How the pieces fit"), the
  optional gcc-14 shim and `CMAKE_POLICY_VERSION_MINIMUM` host-tool
  workarounds, and hostapd disabled. Verified to apply with `patch -p1` to a
  fresh clone of `jcmvbkbc/esp32-linux-build`, both on a host and inside the
  Docker image.
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
- `patches/02-firmware-network-adapter.patch` — every change to the ESP32
  firmware (`esp-hosted/esp_hosted_ng/esp/esp_driver/network_adapter/`): the
  SoftAP authenticator, the BLE provisioning link, and the handover of the RSA
  accelerator to Linux. Generated straight from the tree the shipped image was
  built from, so it reproduces it byte for byte. Applied automatically by
  `apply-local-changes.sh esp-hosted`.
- `patches/06-idf-hostap-sta-join.patch` — one symbol unhidden in the vendored
  ESP-IDF so the SoftAP path links. Applied to the `esp-idf` submodule by the
  same script.
- `patches/03-buildroot-tracked-changes.patch` — a single consolidated
  `git diff` of all tracked files modified under `build/buildroot/`
  (busybox.config, inetd.conf, wpa_supplicant.conf.example, both defconfigs).
  Replaces the old `03-buildroot-board-config.patch` and
  `04-nat-dns-security-buildroot.patch` / `05-ssh-idle-timeout.patch`, which
  overlapped each other and are no longer maintained. Applied automatically by
  `apply-local-changes.sh buildroot`.
- `kernel-driver-esp32-ng/` — a complete reference/human-readable copy of
  `drivers/net/wireless/espressif/esp32-ng/` (AP plumbing present but
  hard-disabled, STA only); the patch above is what is actually used in the
  automated flow, this is a readable backup.
- `new-files/` — an exact mirror of what has to be copied: `board/` and
  `configs/` go over `build/buildroot/` (automatic via
  `apply-local-changes.sh buildroot`); `esp-hosted/network_adapter/*.16m8r`
  (partition table + sdkconfig for the 16 MB profile, new files the firmware
  patch does not cover since it is a `git diff` of only `main/`) go over
  `build/esp-hosted/esp_hosted_ng/esp/esp_driver/network_adapter/` (automatic
  via `apply-local-changes.sh esp-hosted`); `toplevel/` holds the pieces that go
  next to upstream's build driver — `apply-local-changes.sh` and
  `devkit-c1-16m.conf` (upstream only ships an 8MB profile) — plus the
  `Dockerfile` and `.dockerignore`.

## Applying the changes by hand

Normally not needed — the build driver calls `apply-local-changes.sh` itself.
This is the equivalent by hand, from inside the `esp32-linux-build` clone, with
`$REPO` pointing at a checkout of this repository:

```bash
REPO=/path/to/Linux-on-esp32-S3

patch -p1 < "$REPO/patches/00-esp32-linux-build.patch"   # if not applied yet

cd build/buildroot
git apply "$REPO/patches/03-buildroot-tracked-changes.patch"
cp -a "$REPO"/new-files/board/* board/
cp -a "$REPO"/new-files/configs/* configs/
cd ../..

cd build/esp-hosted/esp_hosted_ng
git apply "$REPO/patches/02-firmware-network-adapter.patch"
cp "$REPO"/new-files/esp-hosted/network_adapter/*.16m8r \
   esp/esp_driver/network_adapter/
git add esp/esp_driver/network_adapter/
git -c user.email="local@backup" -c user.name="local-backup" \
  commit -m "network_adapter: this project's firmware (local-only, never push)"
git -C esp/esp_driver/esp-idf apply "$REPO/patches/06-idf-hostap-sta-join.patch"
cd ../../..

cp "$REPO/new-files/toplevel/devkit-c1-16m.conf" .
```

The kernel driver applies itself via `BR2_LINUX_KERNEL_PATCH` once the defconfig
above is in place — no additional manual step is required.

**Status: validated on real hardware.** The combined image was flashed to a
fully erased ESP32-S3 (N16R8) and it boots to a login prompt, the RSA
accelerator passes its 512- and 2048-bit self-tests, the rootfs mounts from
flash via XIP, and telnet comes up. Working: serial console, telnet, STA WiFi
with internet (the interactive `wifi` command scans and connects), hardware
RSA, the nano editor, Lua, an opt-in BusyBox httpd, and curl (HTTP solid,
HTTPS with real certificate verification but experimental — see above). The
board is STA only — there is no SoftAP.

The patch/clone flow is reproducible against fresh clones, and the full
multi-hour compile has been run inside the container with the result booting on
hardware. That first claim was made here once before it was true; it is not
being made again without a booting board behind it.
