# `8ea9011` from a clean clone: firmware fix and bank swap, end to end

The first image the whole pipeline built with both of the day's changes in
it: the firmware invalidating the flash cache after every write Linux makes
(incident 15), and the page-set exchange as the fork backend (incident 16).
Clone of the preview repository into an empty directory, `run.sh --yes
--all`. The host running it went into memory pressure during the build and
the harness killed `run.sh`; the build container is a separate process and
finished on its own (all five stage markers present, `toolchain` 03:49 to
`package` 04:16 UTC), and the three steps `run.sh` had left -- checksums,
flash, suite -- were then run by hand with the same commands it uses.

Image SHA-256 `ed93926ac16e01b12414b7929a052298b7cb46745276286af619c626740c7774`,
source commit `8ea9011`. `sha256sum -c SHA256SUMS`: all eight artifacts
match. Flashed with `flash.sh --images`, the full 16 MB, hash verified.

Read back rather than assumed: the firmware ELF carries
`Cache_Invalidate_Addr` at `0x400016b0` (the ROM call the fix uses; the
previous build's did not) with `space_for_vectors` still at `0x40380000`;
the kernel tree's `mm/nommu.o` carries `nommu_bank_orphans` and
`nommu_bank_broken`; and the board reports `ForkSwitchLast` in
`/proc/meminfo`, which only the swap's `switch-latency.patch` adds.

## The board suite

**36 tests, 0 failed** ([`2026-09-14-final-results.json`](2026-09-14-final-results.json)).
`tainted` 0. MemAvailable 3744 kB at the start, 3624 kB at the end,
largest free contiguous block 2048 kB, 256 KiB to jffs2 in 3 s.

`programbench`, peak system-wide fork shadow during each run, against the
same suite on the copy model a few hours earlier:

| program | copy model | **swap** |
|---|---:|---:|
| bash | 1056 kB | **528 kB** |
| dash | 560 kB | **280 kB** |
| micropython | 616 kB | **308 kB** |
| socat | 304 kB | **152 kB** |
| make, jobq, nc, busybox | 0 | 0 |

Exactly half for every program that forks: N-1 sets against N, which is
what the exchange was written to do. `make` and `jobq` are at zero either
way because they no longer fork at all.

## Beyond the suite

`build/extra-board-tests.py`, ten things a person does with the board that
the suite does not ([`2026-09-14-extra-tests.json`](2026-09-14-extra-tests.json)):
**10 of 10**.

- The exchange is live (`ForkSwitchMax` 21.9 ms) and its inconsistency
  latch stays silent after 40 subshell pipelines, with `ForkShadow` back at 0.
- 384 KiB of random data written to jffs2, copied, the original deleted,
  the copy read back: identical SHA-256. This is the read-after-write that
  incident 15 corrupted.
- A dtach session started, written to through its socket while detached,
  stopped. Cron fires a job. `passwd` changes the password; a fresh login
  with it works; restored.
- A reboot keeps a file in `/home` and does not re-seed it. `bootlog
  verbose` gives 138 console lines across a reboot and `bootlog quiet` 29.

Two of these failed on the first pass and both were the test, not the
board: the password check typed the new password before getty had put the
prompt back, which jams getty for sixty seconds, and the final health grep
matched `panic_print=0x20` in the kernel command line. Both fixed in the
script; the run above is the corrected one.

## The soak

`build/soak-boot.py --rounds 10 --identity` on this image, each round
rewriting `/etc` and `/home` from the artifacts so every boot is a factory
boot: **10 PASS, 0 FAIL, 0 INCONCLUSIVE**. Every round logged in, read
`dmesg` and `tainted` (`0`) back, and reported the exchange at work
(`ForkSwitchMax` 13.8 to 14.2 ms). The partitions read back at the start
hash to `1c9be8ee…` (kernel) and `233e0b1a…` (firmware), which are this
build's `xipImage` and `network_adapter.bin` padded with `0xff` to the
partition size -- the transcripts are of these bytes and no others.
[`2026-09-14-final-soak.json`](2026-09-14-final-soak.json).

With the 25 of the cache-fix record and the 20 of the swap record, that is
55 consecutive clean factory boots today on firmware that invalidates the
cache, against 10 faults in 17 this afternoon on firmware that did not.

## Not covered

WiFi association, telnet and the web page over the network: no credentials
are stored on this board or in any backup, and none were invented. The BLE
provisioning dialog.
