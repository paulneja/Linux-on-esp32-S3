#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$task_dir/../programs/env.sh"
kernel_dir="$experiment_dir/out/linux-fork"
if patch -d "$kernel_dir" --force --dry-run -R -p1 < "$task_dir/quiet-trace.patch" >/dev/null 2>&1; then
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
# swap-banks is OFF by default: it corrupts memory on the board. A clean build
# of 1af3a5b took an "Illegal instruction in kernel" in one boot and an Oops in
# __rb_erase_color under exit_mmap in another, and bash turned itself restricted
# and exited -- all three are one process's pages appearing inside another,
# which is what this patch moves around. The host model in test-reclaim.py
# passes, so whatever is wrong is not in the page bookkeeping it covers.
# Set FORK_SWAP_BANKS=1 to build it back in while working on that.
#
# It goes last: it rewrites the page handling the three patches above build up,
# so it has to see them already applied. switch-latency.patch edits the swap
# version of nommu_bank_switch(), so it rides along.
if [ "${FORK_SWAP_BANKS:-0}" = 1 ]; then
    if ! patch -d "$kernel_dir" --force --dry-run -R -p1 < "$task_dir/swap-banks.patch" >/dev/null 2>&1; then
        patch -d "$kernel_dir" --forward --batch --dry-run -p1 < "$task_dir/swap-banks.patch"
        patch -d "$kernel_dir" --forward --batch -p1 < "$task_dir/swap-banks.patch"
    fi
    if ! patch -d "$kernel_dir" --force --dry-run -R -p1 < "$task_dir/switch-latency.patch" >/dev/null 2>&1; then
        patch -d "$kernel_dir" --forward --batch --dry-run -p1 < "$task_dir/switch-latency.patch"
        patch -d "$kernel_dir" --forward --batch -p1 < "$task_dir/switch-latency.patch"
    fi
elif patch -d "$kernel_dir" --force --dry-run -R -p1 < "$task_dir/switch-latency.patch" >/dev/null 2>&1; then
    # A warm tree built with them still has them applied; take them back off.
    patch -d "$kernel_dir" --force --batch -R -p1 < "$task_dir/switch-latency.patch"
    patch -d "$kernel_dir" --force --batch -R -p1 < "$task_dir/swap-banks.patch"
fi
python3 "$task_dir/check-kernel-config.py" \
    "$repo_dir/new-files/board/espressif/esp32s3/devkit_c1_16m_linux.config" \
    "$kernel_dir/.config"
make -C "$kernel_dir" -j"${JOBS:-8}" ARCH=xtensa CROSS_COMPILE="$prefix-" xipImage \
    2>&1 | tee "$experiment_dir/out/kernel-quiet-details.log"
test "$(wc -c < "$kernel_dir/arch/xtensa/boot/xipImage")" -le $((0x400000))
cp "$kernel_dir/arch/xtensa/boot/xipImage" "$experiment_dir/out/real-bins/xipImage-fork-quiet"
sha256sum "$experiment_dir/out/real-bins/xipImage-fork-quiet"
