#!/usr/bin/env bash
# Preserve the known fork rootfs. Package new experiments separately; no flash.
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$task_dir/../../../.." && pwd)
out_dir="$task_dir/../../out"
host_dir="$repo_dir/../refs/esp32-linux-build/build/build-buildroot-esp32s3_devkit_c1_16m/host"
image_dir=$(mktemp -d "$out_dir/real-bins/image.XXXXXX")
"$host_dir/bin/cramfsck" -x "$image_dir/tree" "$out_dir/rootfs-fork.cramfs"
install -m 755 "$out_dir/real-bins/dash" "$out_dir/real-bins/make" "$image_dir/tree/usr/bin/"
install -d "$image_dir/tree/usr/share/fork-real" "$image_dir/tree/usr/share/licenses/dash" "$image_dir/tree/usr/share/licenses/make"
install -m 644 "$task_dir/dash-test.sh" "$task_dir/make-test.sh" "$task_dir/peer.sh" "$task_dir/Makefile.test" "$image_dir/tree/usr/share/fork-real/"
install -m 644 "$out_dir/real-bins/dash-0.5.12/COPYING" "$image_dir/tree/usr/share/licenses/dash/"
install -m 644 "$out_dir/real-bins/make-4.4.1/COPYING" "$image_dir/tree/usr/share/licenses/make/"
"$host_dir/bin/mkcramfs" -X -q "$image_dir/tree" "$out_dir/rootfs-real.cramfs"
test "$(wc -c < "$out_dir/rootfs-real.cramfs")" -le $((0x780000))
"$host_dir/bin/cramfsck" "$out_dir/rootfs-real.cramfs"
sha256sum "$out_dir/rootfs-real.cramfs" "$out_dir/real-bins/dash" "$out_dir/real-bins/make"
echo "Built $image_dir; no flash or publication performed."
