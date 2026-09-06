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

The recorded comparison used a build of `8bf55fc`, subsequently repackaged
with a formatted factory `/home`, and a clean build of `ee9e06d`. These were
not two independent builds of the same commit. The comparison found identical
bootloader, partition table, firmware, kernel and factory `/home` bytes;
the reported extracted-tree difference was `/etc/shadow`. Buildroot hashes
`BR2_TARGET_GENERIC_ROOT_PASSWD` with a fresh random salt on each run, which
changes `rootfs.cramfs`, `etc.jffs2` and the combined image. This demonstrates
a working clean-build path, not bit-for-bit reproducibility. A same-commit
double build with controlled inputs and a full artifact comparison remains
necessary before making that stronger claim.

Stages and logs are written to `stages/` and `logs/`. A failed stage stops the
pipeline. Retrying inside that same isolated directory may reuse its own
completed stages; it is not a second clean build.

## Outputs

`artifacts/` contains:

- `linux-esp32s3-native-full.bin`: exactly 16 MiB, intended for offset `0x0`.
- Bootloader, partition table, firmware, kernel, rootfs and fresh `/etc` images.
- `home.jffs2`: an empty but formatted `/home`, avoiding the observed
  first-write stall with the fully erased experimental partition.
- `SHA256SUMS`, `build-manifest.json`, `rootfs.json` and `sources.lock`.
- `configs/`: the actual toolchain, Buildroot, firmware, kernel and BusyBox
  configurations, with their hashes in the build manifest.

The full image contains default settings and a formatted empty `/home`, not a backup
of the developer's board. Flashing it replaces existing configuration and
user files. Back up a used board privately before any full-image test.
Never publish raw board backups: they may contain credentials and user data.

The repository's `flash.sh` reads `images/`, not this new artifacts directory.
Its default combined-image write replaces `/etc` and `/home` even without
`--erase`. `--parts` preserves `/home` but still replaces `/etc`, including
accounts, password hashes and network configuration. `--parts --erase` resets
both and requires `images/home.jffs2`; the older committed 0.6 images do not
include that separate file. Missing files, invalid sizes or inconsistent
partition layouts now stop the script before any esptool invocation.

Run the host-only flasher regression tests with `python3 build/test-flash.py`.
They use temporary images and a simulated esptool, never a serial device.

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

Functional program tests run from the Bash login. For the instrumented
benchmark suite, the runner replaces that login temporarily with Dash,
then logs back into Bash. Keeping an additional interactive Bash alive
while measuring nested Bash pipelines exhausted RAM in the development run;
that combination is not a supported concurrency guarantee. Services remain
enabled during the measurements.

Session tests use a Dash primary console, restored to Bash afterwards.
Two detached Dash sessions with a Bash primary console could leave too little
RAM even for `session list`; two interactive Bash consoles could not fork
`id`. The separate `nohup` test runs from the normal Bash login, without the
two sessions. This suite does not claim those combined workloads are safe.

It creates temporary users and jobs and removes them on the normal cleanup
path. It requires root access, the default Bash login policy, cron enabled
and HTTP initially disabled; do not run it against an unrelated production
installation. Cleanup is best effort: when the console itself times out, the
temporary accounts stay on the board and the next run stops on its own
precondition check. Rewrite the two writable partitions to return the board
to the factory state before retrying, which is faster than the full image and
leaves the kernel and rootfs untouched:

```sh
esptool --chip esp32s3 --port YOUR_COM_ADAPTER \
    --before default-reset --after no-reset \
    write-flash 0xd0000 ARTIFACTS/etc.jffs2 0xcc0000 ARTIFACTS/home.jffs2
```

If esptool left the freshly flashed board in its bootloader with
`--after no-reset`, add `--reset-from-bootloader` to explicitly reset it via
RTS and capture the complete startup log. Do not use that option on a running
filesystem with unsaved changes. The suite also checks both hardware RSA
self-tests and the read-only cramfs mount in the kernel log.

`results.json` records the exact image hash and each test's outcome/time.
Logs and a failed result remain available if any check stops the run. These
results also record the hashes of the runner and its external test scripts.
Only a fully passing run updates `build-manifest.json` with the hardware
verification result and report location; image bytes are not changed.
These tests use the actual board and reboot it; they do not flash it, enable WiFi,
test an external WiFi connection or establish isolation from malicious code.

## Verification status

The clean build of `ee9e06d5a4634325376dc33d3a149d09580cf1fb` passed all 26
hardware checks on 2026-09-06, including a factory first boot in 19.08 seconds.
The exact 16 MiB image SHA256 is
`e0a066fc66eb929b13f36c3a77278aa647361c2073aadcb210df6c30054b55b7`.
See the [verification record](verification/2026-09-06.md) and its archived
machine-readable results for scope and limitations. This result applies to
that artifact, not automatically to future code changes or other profiles.
The committed `images/` remain the older 0.6 release.
