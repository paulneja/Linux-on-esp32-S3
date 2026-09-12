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
# swap-banks goes last: it rewrites the page handling that the three patches
# above build up, so it has to see them already applied.
if ! patch -d "$kernel_dir" --force --dry-run -R -p1 < "$task_dir/swap-banks.patch" >/dev/null 2>&1; then
    patch -d "$kernel_dir" --forward --batch --dry-run -p1 < "$task_dir/swap-banks.patch"
    patch -d "$kernel_dir" --forward --batch -p1 < "$task_dir/swap-banks.patch"
fi
python3 "$task_dir/check-kernel-config.py" \
    "$repo_dir/new-files/board/espressif/esp32s3/devkit_c1_16m_linux.config" \
    "$kernel_dir/.config"
make -C "$kernel_dir" -j"${JOBS:-8}" ARCH=xtensa CROSS_COMPILE="$prefix-" xipImage \
    2>&1 | tee "$experiment_dir/out/kernel-quiet-details.log"
test "$(wc -c < "$kernel_dir/arch/xtensa/boot/xipImage")" -le $((0x400000))
cp "$kernel_dir/arch/xtensa/boot/xipImage" "$experiment_dir/out/real-bins/xipImage-fork-quiet"
sha256sum "$experiment_dir/out/real-bins/xipImage-fork-quiet"
