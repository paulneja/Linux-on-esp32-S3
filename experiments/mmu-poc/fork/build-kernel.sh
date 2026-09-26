#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$task_dir/../../.." && pwd)
build_dir="$repo_dir/../refs/esp32-linux-build/build"
TARGET="${TARGET:-esp32s3_16m}"
source "$repo_dir/build/load-target.sh"
source_dir="$build_dir/build-buildroot-$PROFILE/build/linux-xtensa-6.11-esp32-tag"
kernel_dir="$task_dir/../out/linux-fork"
prefix="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic-"
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
if [[ ! -e "$kernel_dir" ]]; then
    # The copy inherits buildroot's config and patches: a stale buildroot
    # tree gives a stale copy, and deleting the copy does not fix that.
    if ! python3 "$task_dir/check-kernel-config.py" \
            "$repo_dir/new-files/$KERNEL_CONFIG" \
            "$source_dir/.config" >/dev/null 2>&1; then
        echo "build-kernel.sh: buildroot's kernel tree predates the board config:" >&2
        echo "  $source_dir" >&2
        echo "This copy comes from there, so rebuild it first (build/reproduce.sh)." >&2
        exit 1
    fi
    cp -a --reflink=auto "$source_dir" "$kernel_dir"
fi
cd -- "$kernel_dir"
# CONFIG_EXTRA_FIRMWARE builds regulatory.db into the image, because cfg80211
# asks for it before the rootfs is mounted. The kernel looks for the files in
# $kernel_dir/firmware; buildroot has already installed them into the target.
mkdir -p firmware
for blob in regulatory.db regulatory.db.p7s; do
    src="$build_dir/build-buildroot-$PROFILE/target/lib/firmware/$blob"
    if [[ -f "$src" ]]; then
        cp -f "$src" "firmware/$blob"
    else
        echo "build-kernel.sh: missing $src; CONFIG_EXTRA_FIRMWARE will fail" >&2
        exit 1
    fi
done
if patch --force --dry-run -R -p1 < "$task_dir/kernel.patch" >/dev/null 2>&1; then
    echo "Kernel patch already present."
else
    patch --batch --forward --dry-run -p1 < "$task_dir/kernel.patch"
    patch --batch --forward -p1 < "$task_dir/kernel.patch"
fi
scripts/config --enable XTENSA_NOMMU_FORK --set-str LOCALVERSION '-forkbank'
make ARCH=xtensa CROSS_COMPILE="$prefix" olddefconfig
python3 "$task_dir/check-kernel-config.py" \
    "$repo_dir/new-files/$KERNEL_CONFIG" .config
make -j8 ARCH=xtensa CROSS_COMPILE="$prefix" xipImage 2>&1 | tee "$task_dir/../out/fork-kernel-build.log"
echo "Built only. Original source tree, images and board unchanged."
