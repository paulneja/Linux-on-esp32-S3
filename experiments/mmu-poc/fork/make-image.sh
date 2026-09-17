#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$task_dir/../../.." && pwd)
out_dir="$task_dir/../out"
PROFILE="${PROFILE:-esp32s3_devkit_c1_16m}"
case "$PROFILE" in
    esp32s3_devkit_c1_16m)
        KERNEL_LIMIT=0x400000
        ROOTFS_LIMIT=0x780000
        ;;
    xiao_esp32s3_8m)
        KERNEL_LIMIT=0x3c0000
        ROOTFS_LIMIT=0x300000
        ;;
    *)
        echo "error: unknown PROFILE=$PROFILE" >&2
        exit 1
        ;;
esac
host_dir="$repo_dir/../refs/esp32-linux-build/build/build-buildroot-$PROFILE/host"
bash "$task_dir/build-test.sh"
image_dir=$(mktemp -d "$out_dir/fork-image.XXXXXX")
"$host_dir/bin/cramfsck" -x "$image_dir/tree" "$out_dir/rootfs-probe.cramfs"
install -m 755 "$out_dir/fork-test" "$image_dir/tree/usr/bin/fork-test"
install -m 755 "$out_dir/fork-test-dynamic" "$image_dir/tree/usr/bin/fork-test-dynamic"
install -m 755 "$out_dir/libfork.so.0" "$image_dir/tree/usr/lib/libfork.so.0"
install -m 755 "$task_dir/fork-run.sh" "$image_dir/tree/usr/bin/fork-run"
"$host_dir/bin/mkcramfs" -X -q "$image_dir/tree" "$out_dir/rootfs-fork.cramfs"
"$host_dir/bin/cramfsck" "$out_dir/rootfs-fork.cramfs"
cp "$out_dir/linux-fork/arch/xtensa/boot/xipImage" "$out_dir/xipImage-fork"
test "$(wc -c < "$out_dir/xipImage-fork")" -le $((KERNEL_LIMIT))
test "$(wc -c < "$out_dir/rootfs-fork.cramfs")" -le $((ROOTFS_LIMIT))
sha256sum "$out_dir/xipImage-fork" "$out_dir/rootfs-fork.cramfs" "$out_dir/fork-test"
echo "No flash performed; images/ unchanged."
