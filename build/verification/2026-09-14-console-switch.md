# `27027d4` on the board: 36/36, and the console switch verified by rebooting

A second clean build the way a user runs it -- `git pull` into the clone from
the previous record, then `./run.sh --all`. Image SHA-256
`06b8cbe779807e37cac8ab923f079ee5e28d39ba3b02544b12fd0f5fcc3da968`, source
commit `27027d4`. Results in
[`2026-09-14-results.json`](2026-09-14-results.json).

**36 tests, 0 failed**, `tainted` 0. MemAvailable 3724 kB at the start of the
suite and 3612 kB at the end.

The board was read back, not assumed: `sha256sum` over the kernel and rootfs
partitions returns `48713c61…` and `b5927369…`, the `xipImage` and
`rootfs.cramfs` lines of this build's `SHA256SUMS`.

The kernel is **byte-identical to the previous build's**: `bootlog` adds two
shell scripts to the overlay and touches nothing the kernel is made of. Two
builds a day apart, on different trees, producing the same `xipImage` is not
what this record set out to show, but it is worth writing down.

## The console switch, on hardware

`test-board.py` has three checks for `bootlog`: the default is quiet, verbose
moves `/proc/sys/kernel/printk` to 8, quiet moves it back. None of them says
the **boot** changes, which is the entire point of the command and can only be
seen by rebooting and watching the line. Three real boots, reset over EN each
time, counting the console bytes and looking for lines the kernel emits below
KERN_ERR (`Kernel command line:`, `devtmpfs: initialized`, `Run /sbin/init as
init process`):

| setting | console bytes | replay line | sub-KERN_ERR lines |
|---|---:|---|---|
| verbose | 8636 | yes | 3 of 3 |
| quiet | 1148 | no | 0 of 3 |

Seven and a half times the output, and the board was left as it was found, on
quiet. This is not in the suite: it costs two reboots and would leave a
36/36 run restarting in the middle of itself. It is recorded here instead.

## A test nothing ran

`test-bash-pid-cache.py` compiles the patched `bgp_resize()` out of bash's
`jobs.c` into a host fixture and checks the growth and wrap behaviour.
Nothing invoked it -- only `SHELL-TOOLS.md` mentioned it existed -- so
`bash-pid-cache.patch` had never been verified from the build's side. Run by
hand against this build's bash source it passes, and `build-bash.sh` now runs
it after applying the patches.

## Not covered here

The fault rate on this image: `build/soak-boot.py --rounds 20` with the
runner that reads `dmesg` and the taint flags back is a separate record.
WiFi was not associated and the BLE dialog was not exercised.
