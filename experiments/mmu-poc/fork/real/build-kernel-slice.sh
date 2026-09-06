#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$task_dir/../../../.." && pwd)
out_dir="$task_dir/../../out"
build_dir=$(cd "$repo_dir/../refs/esp32-linux-build/build" && pwd)
prefix="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic-"
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
cd "$out_dir/linux-fork"
patch --force --dry-run -R -p1 < "$task_dir/../kernel.patch"
if ! patch --force --dry-run -R -p1 < "$task_dir/scheduler.patch" >/dev/null 2>&1; then
    patch --batch --forward --dry-run -p1 < "$task_dir/scheduler.patch"
    patch --batch --forward -p1 < "$task_dir/scheduler.patch"
fi
make -j8 ARCH=xtensa CROSS_COMPILE="$prefix" xipImage 2>&1 | tee "$out_dir/real-bins/kernel-slice-build.log"
test "$(wc -c < arch/xtensa/boot/xipImage)" -le $((0x400000))
cp arch/xtensa/boot/xipImage "$out_dir/real-bins/xipImage-fork-slice"
sha256sum "$out_dir/real-bins/xipImage-fork-slice"
