#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$task_dir/../../.." && pwd)
build_dir="$repo_dir/../refs/esp32-linux-build/build"
source_dir="$build_dir/build-buildroot-esp32s3_devkit_c1_16m/build/linux-xtensa-6.11-esp32-tag"
kernel_dir="$task_dir/../out/linux-fork"
prefix="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic-"
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
if [[ ! -e "$kernel_dir" ]]; then
    cp -a --reflink=auto "$source_dir" "$kernel_dir"
fi
cd -- "$kernel_dir"
if patch --force --dry-run -R -p1 < "$task_dir/kernel.patch" >/dev/null 2>&1; then
    echo "Kernel patch already present."
else
    patch --batch --forward --dry-run -p1 < "$task_dir/kernel.patch"
    patch --batch --forward -p1 < "$task_dir/kernel.patch"
fi
scripts/config --enable XTENSA_NOMMU_FORK --set-str LOCALVERSION '-forkbank'
make ARCH=xtensa CROSS_COMPILE="$prefix" olddefconfig
make -j8 ARCH=xtensa CROSS_COMPILE="$prefix" xipImage 2>&1 | tee "$task_dir/../out/fork-kernel-build.log"
echo "Built only. Original source tree, images and board unchanged."
