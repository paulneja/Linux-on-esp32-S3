# The bounded init scripts, checked on the board

The two changed init scripts live in `/etc`, so they were tested by rebuilding
only the `etc` jffs2 image and keeping the pipeline's `rootfs.cramfs` from
`734c157` untouched.

- Image: `2d1a2b01830c2c7f...`, `/etc` rebuilt locally, everything else from the
  clean build
- Board suite: **26/26 pass**, results in `2026-09-07-init-scripts-results.json`
- Separately, a board whose `/home` had been left needing reclaim reached login
  in 42.7 s, where the same state previously did not reach login in 280 s

## Do not repack rootfs.cramfs by hand

A first attempt rebuilt `rootfs.cramfs` locally with the same `mkcramfs -X -q`
the packager uses. All 772 entries matched the original by mode, owner, size
and content hash, and the image was the same 7815168 bytes, yet the board then
failed the `bash` benchmark with `fork: Cannot allocate memory` at a point
where the pipeline image passes.

The rootfs is a linear cramfs and `-X` exists so ELF files can be executed in
place from flash. Directory order differs between a freshly extracted tree and
the packager's, which moves where files land. Enough of that XIP layout changed
that binaries stopped running from flash and started costing RAM the board does
not have. Matching entry metadata is not enough; use the pipeline for anything
that ships.
