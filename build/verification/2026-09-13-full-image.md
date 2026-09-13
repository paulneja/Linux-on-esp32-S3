# Full image from `24f0faf`: 33/33 on the board, first boot clean

The first clean build of this branch end to end, run the way a user runs it:
`git clone` of the repository into an empty directory, then `./run.sh --all`,
which builds in the pinned container, checks the artifact hashes, flashes and
runs the board suite. Nothing was carried over from a development tree.

Image SHA-256 `f9b30da305c07a8f568bf4cc07f2bd8f6b8f6871e785bcb003b43d51ddf87864`,
source commit `24f0faf`, finished 2026-09-13T20:46:38Z. Results in
[`2026-09-13-results.json`](2026-09-13-results.json).

The board was read back rather than assumed: `sha256sum` over the kernel and
rootfs partitions returns `48713c61…` and `f7890b16…`, which are the
`xipImage` and `rootfs.cramfs` lines of the build's own `SHA256SUMS`. The
transcript below is that image and no other.

## Results

**33 tests, 0 failed.** `tainted` 0, no OOM, panic, BUG or Oops. The four
checks that had to be run separately last time -- home users, cron, COM
reconnect, persistence across reboot -- ran inside the suite and passed.

The flash erased all 16 MB, so this was a factory boot: `/home` formatted and
`home-init` filling it, which is the load DEVELOPMENT.md incident 15 faults
under.

## Memory

| | `734c157` | `19ce12c` (swap on) | this image |
|---|---:|---:|---:|
| MemAvailable at the start of the suite | 1340 kB | 3668 kB | **3712 kB** |
| largest free contiguous block | — | 2048 kB | 2048 kB |
| MemAvailable at the end | — | — | 3608 kB |

The figure the CHANGELOG withdrew is reproduced without the page-set exchange:
the RAM never depended on it. 500 `fork`+`exec` cycles of `/bin/true` cost
4 kB, and `ForkShadow` is 0 before and after.

## What a program costs to launch

`programbench`; `shadow` is the peak system-wide fork shadow during the run,
`min` the lowest MemAvailable sampled.

| program | private | shadow `19ce12c` (swap) | shadow now | min now |
|---|---:|---:|---:|---:|
| bash | 276 kB | 608 kB | 1056 kB | 2488 kB |
| dash | 140 kB | 280 kB | 560 kB | 3092 kB |
| micropython | 308 kB | 384 kB | 616 kB | 2872 kB |
| socat | 184 kB | 152 kB | 304 kB | 3376 kB |
| **make** | 224 kB | 216 kB | **0 kB** | 3216 kB |
| **jobq** | 120 kB | 124 kB | **0 kB** | 3552 kB |
| nc, busybox | 76 kB | 0 kB | 0 kB | 3768 kB |

Two results in one table. The page-set exchange is off, so everything that
forks pays the copy model's 2P again -- socat's 304 kB is exactly twice its
own 152 kB, which is the arithmetic the model predicts. And `make` and `jobq`
cost **nothing at all**, because they no longer fork: make configures onto
`vfork` and jobq launches through `posix_spawn`, which lands on `vfork` in
this libc. For the programs it applies to, moving the launch out of the kernel
beat the kernel change outright -- the exchange only ever halved those two.

It does not apply to the rest. bash, dash and micropython fork for pipelines,
subshells and `os.fork`, and socat forks one process per connection that never
execs; those children need memory of their own.

## The fault rate

`build/soak-boot.py --rounds 20 --identity` on this image, each round
rewriting `/etc` and `/home` from the artifacts so every boot is a factory
boot: **20 PASS, 0 FAIL, 0 INCONCLUSIVE**. Upper bound on the fault rate,
one-sided 95% over 20 decided rounds: **14%**. Transcripts and the partition
hashes read back at the start of the run are in
[`2026-09-13-soak.json`](2026-09-13-soak.json).

This is not the same kernel the incident-15 experiments measured. Those held
the config at 0.7's and added debugging symbols to read the faults; the worst
of them took 4 faults of 4 decided rounds, and the best, with
`CONFIG_PREEMPT_NONE`, 2 of 7. This is the shipping image with the whole
current configuration. If its true rate were still 20%, twenty clean rounds
would happen 1.2% of the time, so the rate is genuinely lower -- but 0 of 20
is not 0, the bound is 14%, and nobody found the cause. Incident 15 stays
open. What can be said is that the image being released measured clean twenty
times over the load that provokes it.

## Reproducibility

Two complete builds of `24f0faf` from pinned sources, in parallel on separate
runners, compared artifact by artifact
([run 34780294252](https://github.com/paulneja/Linux-on-esp32-S3-Preview/actions/runs/34780294252)):

**Five of eight artifacts are byte-identical** -- `bootloader.bin`,
`partition-table.bin`, `network_adapter.bin`, `home.jffs2` and the kernel
`xipImage`. All 611 rootfs entries match, and 127 of the 128 `etc.jffs2`
nodes.

The single difference is `/etc/shadow`, in both filesystems and therefore in
the combined image: root's password hash is salted, so it is drawn fresh on
each build. The comparison reports the non-password fields equal and the same
hash algorithm in both. Nothing else in the image differs between two
independent builds of the same commit.

## Not covered

WiFi was not associated and no traffic was passed; the BLE dialog was not
exercised.
