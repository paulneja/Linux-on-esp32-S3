# Clone, build and run from scratch

Question: does a fresh clone of this branch build and boot without anything
from the working machine?

## What was done

`git clone --branch mmu-poc` into an empty directory, then `build/reproduce.sh`
with `JOBS=8` inside it. The container downloads its own sources; no toolchain,
image, experiment binary or cache from the development tree is reachable.

- Source commit: `734c157`
- Image: `ea1e17e957cfbc319338ace1983992d571469b2b13c6a0dca501117d75cbf81d`
- Board suite: **26/26 pass**, results in `2026-09-07-clone-build-results.json`

## Compared against the same-commit pair

Against a build of `9226140`, whose only source difference is documentation:

| Artifact | Result |
|---|---|
| bootloader, partition table, kernel, factory `/home` | identical |
| `network_adapter.bin` | 71 bytes differ |
| `rootfs.cramfs`, `etc.jffs2`, combined image | differ |

The firmware difference is entirely metadata: 38 bytes in the ESP-IDF
application descriptor, where the embedded `git describe` reads `2ad481e-dirty`
against `234dfe7-dirty`, and 33 bytes of the appended image hash that covers
it. Zero bytes of code differ. The rootfs difference is `/etc/shadow` and its
random password salt, as recorded separately.

`toolchain.config` differs only in `CT_PARALLEL_JOBS`, 4 against 8, which is
the `JOBS` value passed to the run. The kernel came out byte-identical anyway.

## Conclusion

A clone builds and runs. The two remaining sources of differing image hashes
are both metadata, a password salt and a git version string, not compiled code.
