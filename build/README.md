# Complete clean build

Run from a clean, committed checkout as a regular Linux user with Docker access:

```sh
JOBS=8 bash build/reproduce.sh
```

This creates a new `build-output/reproduce.XXXXXX` directory. It snapshots the
committed source without `images/`, builds an isolated Debian 12 container,
and compiles the Linux toolchain, base system, ESP-IDF firmware, fork kernel,
MMU payloads and selected userspace. No existing `refs/`, toolchain, image,
experiment binary or compilation cache is mounted into the container.

The container uses host networking for downloads, but has no serial device
or Docker socket. It cannot flash the board. Source and build outputs remain
in the new directory; it does not overwrite the repository's stable images.
Allow several hours, an internet connection and substantial disk space.

`sources.lock` pins upstream Git revisions. Program archives are checked by
the SHA256 manifests used by their build scripts. ESP-IDF pins its own
submodules. The container base is pinned by digest; Debian package updates
and host tools are not a promise of byte-identical output across future runs.

Stages and logs are written to `stages/` and `logs/`. A failed stage stops the
pipeline. Retrying inside that same isolated directory may reuse its own
completed stages; it is not a second clean build.

## Outputs

`artifacts/` contains:

- `linux-esp32s3-native-full.bin`: exactly 16 MiB, intended for offset `0x0`.
- Bootloader, partition table, firmware, kernel, rootfs and fresh `/etc` images.
- `SHA256SUMS`, `build-manifest.json`, `rootfs.json` and `sources.lock`.
- `configs/`: the actual toolchain, Buildroot, firmware, kernel and BusyBox
  configurations, with their hashes in the build manifest.

The full image contains default settings and an empty `/home`, not a backup
of the developer's board. Flashing it replaces existing configuration and
user files. Back up a used board privately before any full-image test.
Never publish raw board backups: they may contain credentials and user data.

The packager checks partition limits, the firmware/kernel vector address,
the fork kernel setting, root's shell, BusyBox SUID mode, excluded programs,
and every component's bytes inside the combined image. It leaves hardware
verification explicitly `pending` until the exact image has been flashed
and tested. A successful build alone is not proof that it boots.

## Hardware tests

After backing up the board and explicitly flashing the full BIN at `0x0`,
run with a Python interpreter that has pyserial installed:

```sh
python3 build/test-board.py /dev/serial/by-id/YOUR_COM_ADAPTER \
    build-output/reproduce.XXXXXX/artifacts --output build-output/board-check
```

The output directory must not exist. The runner verifies the local artifact
checksums and reads the installed kernel/rootfs through their MTD devices to
compare their hashes. It then tests remapping, fork, process compatibility,
the selected programs, job admission, benchmarks, users and permissions,
HTTP, cron, detached sessions, COM reconnects and persistence across reboots.
It creates temporary users and jobs and removes them on the normal cleanup
path. It requires root access, the default Bash login policy, cron enabled
and HTTP initially disabled; do not run it against an unrelated production
installation. Review cleanup if a test is interrupted or fails.

If esptool left the freshly flashed board in its bootloader with
`--after no-reset`, add `--reset-from-bootloader` to explicitly reset it via
RTS and capture the complete startup log. Do not use that option on a running
filesystem with unsaved changes. The suite also checks both hardware RSA
self-tests and the read-only cramfs mount in the kernel log.

`results.json` records the exact image hash and each test's outcome/time.
Logs and a failed result remain available if any check stops the run. These
tests use the actual board and reboot it; they do not flash it, enable WiFi,
test an external WiFi connection or establish isolation from malicious code.

## Verification status

The first end-to-end run of this integrated pipeline is in progress. Earlier
hardware results belong to the incremental experimental images documented
under `experiments/mmu-poc/`; they must not be presented as a clean-build
verification of this new combined image.
