#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$task_dir/../programs/env.sh"
kernel_dir="$experiment_dir/out/linux-fork"
applied() { patch -d "$kernel_dir" --force --dry-run -R -p1 < "$task_dir/$1" >/dev/null 2>&1; }
# Dependencies come off first. swap-banks and switch-latency rewrite the
# code the base patches touch, so on a warm tree that still carries them the
# base patches' own checks below would fail on changed context before this
# script ever reached the line that removes them. Strip them in reverse
# order; the block near the end puts them back when FORK_SWAP_BANKS=1.
if applied switch-latency.patch; then
    patch -d "$kernel_dir" --force --batch -R -p1 < "$task_dir/switch-latency.patch"
fi
if applied swap-banks.patch; then
    patch -d "$kernel_dir" --force --batch -R -p1 < "$task_dir/swap-banks.patch"
fi
if applied quiet-trace.patch; then
    patch -d "$kernel_dir" --force --batch -R -p1 < "$task_dir/quiet-trace.patch"
fi
if ! patch -d "$kernel_dir" --force --dry-run -R -p1 < "$task_dir/reclaim.patch" >/dev/null 2>&1; then
    bash "$task_dir/build-kernel.sh"
    bash "$task_dir/real/build-kernel-slice.sh"
    patch -d "$kernel_dir" --forward --batch --dry-run -p1 < "$task_dir/reclaim.patch"
    patch -d "$kernel_dir" --forward --batch -p1 < "$task_dir/reclaim.patch"
fi
patch -d "$kernel_dir" --forward --batch --dry-run -p1 < "$task_dir/quiet-trace.patch"
patch -d "$kernel_dir" --forward --batch -p1 < "$task_dir/quiet-trace.patch"
# swap-banks is ON by default. It was off for a week because it corrupted
# memory on the board -- an "Illegal instruction in kernel", an Oops in
# __rb_erase_color, a bash that turned itself restricted -- and it turned out
# it never had: the firmware was not invalidating the flash cache after any
# write Linux made (DEVELOPMENT.md incident 15), so every model read stale
# pages, and this one, keeping each process's memory in one place rather than
# two, had nothing to survive that with. With the firmware fixed, twenty
# factory boots with the swap on: 20 clean, the inconsistency latch never
# fired. Set FORK_SWAP_BANKS=0 to build the copy model instead.
#
# It goes last: it rewrites the page handling the three patches above build up,
# so it has to see them already applied. switch-latency.patch edits the swap
# version of nommu_bank_switch(), so it rides along.
if [ "${FORK_SWAP_BANKS:-1}" = 1 ]; then
    patch -d "$kernel_dir" --forward --batch --dry-run -p1 < "$task_dir/swap-banks.patch"
    patch -d "$kernel_dir" --forward --batch -p1 < "$task_dir/swap-banks.patch"
    patch -d "$kernel_dir" --forward --batch --dry-run -p1 < "$task_dir/switch-latency.patch"
    patch -d "$kernel_dir" --forward --batch -p1 < "$task_dir/switch-latency.patch"
fi
python3 "$task_dir/check-kernel-config.py" \
    "$repo_dir/new-files/board/espressif/esp32s3/devkit_c1_16m_linux.config" \
    "$kernel_dir/.config"
make -C "$kernel_dir" -j"${JOBS:-8}" ARCH=xtensa CROSS_COMPILE="$prefix-" xipImage \
    2>&1 | tee "$experiment_dir/out/kernel-quiet-details.log"
test "$(wc -c < "$kernel_dir/arch/xtensa/boot/xipImage")" -le $((0x400000))
cp "$kernel_dir/arch/xtensa/boot/xipImage" "$experiment_dir/out/real-bins/xipImage-fork-quiet"
sha256sum "$experiment_dir/out/real-bins/xipImage-fork-quiet"
