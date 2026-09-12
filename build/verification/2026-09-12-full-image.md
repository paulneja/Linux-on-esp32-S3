# Full image from `19ce12c`: 27/27 on the board

Clean build in the pinned container (`build/reproduce.sh`, 34 minutes),
flashed with `flash.sh --images ... --parts` so the board's `/home` survived,
then `build/test-board.py` against the exact artifact. Recorded in
`build-output/reproduce.Ub7JNd/board-check/results.json` and
`board-check-external/`.

Image SHA-256 `4bad51126e6975f3d20c6d927a6854d644bcbe5c5cffd3f4b524df902003a720`.

## Results

23 in-suite checks pass, then the four external ones -- home users, cron,
COM reconnect, persistence across reboot -- pass when run on their own. The
one in-suite failure on the first pass was `test-home-users-board`: the
board's preserved `/home` still held the lua status CGI from before, and lua
is no longer in the image, so the page returned 404. `home-init` now
replaces the stock lua CGI on an upgraded board (commit `94282b8`, applied
to the board by hand before the external tests); a fresh `/home` never sees
it. `tainted` 0, no OOM, panic, BUG or Oops.

## Against the last verified run (`734c157`, image `ea1e17e9…`)

Same suite, same board, quiesced the same way.

| | before | after |
|---|---:|---:|
| MemAvailable at the start of the suite | 1340 kB | 3668 kB |
| largest free contiguous block | — | 2048 kB |
| rootfs partition free | 49 152 B | 1 679 360 B |
| xipImage | 3 432 520 B | 3 104 104 B |

Per-program benchmarks (`programbench`; `backups` is the peak system-wide
fork shadow during the run, `min` is the lowest MemAvailable sampled):

| program | private | backups before | backups after | min before | min after |
|---|---:|---:|---:|---:|---:|
| bash | 264 kB | 892 kB | 608 kB | 248 kB | 2872 kB |
| dash | 140 kB | 560 kB | 280 kB | 708 kB | 3296 kB |
| make | 216 kB | 432 kB | 216 kB | 660 kB | 3196 kB |
| micropython | 308 kB | 512 kB | 384 kB | 328 kB | 2804 kB |
| socat | 184 kB | 296 kB | 152 kB | 944 kB | 3460 kB |
| jobq | 124 kB | 248 kB | 124 kB | 968 kB | 3468 kB |

`make`, `jobq` and `socat` are single-fork workloads and show the exact
halving swap banking predicts. `bash` keeps several processes alive at once
and improves by about a third. The floor during the bash benchmark, which is
where the old image produced `bash: fork: Cannot allocate memory`, is now
2.8 MB.

## Two things found only by running the whole image

`tmpfs` cannot be capped on this kernel. `SHMEM` depends on MMU, so what
answers to the name is the tiny-shmem stub over ramfs, whose only mount
option is `mode`; a `size=` in fstab is rejected and nothing is mounted. The
fstab now says so.

hush rejects a multi-line single-quoted word whose line begins with an awk
function definition. The CGI feeds awk through a quoted heredoc instead.

## Not covered

WiFi was scanned in the earlier kernel-and-firmware check (five networks,
twelve scans) but not associated in this run, and no traffic was passed. The
BLE dialog was not exercised.
