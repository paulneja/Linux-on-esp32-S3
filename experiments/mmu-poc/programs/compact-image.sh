#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
input=${1:-"$programs_out/rootfs-programs.cramfs"}
output=${2:-"$programs_out/rootfs-programs-stripped.cramfs"}
test "$(realpath -m "$input")" != "$(realpath -m "$output")"
image_dir=$(mktemp -d "$programs_out/stripped.XXXXXX")
"$host_dir/bin/cramfsck" -x "$image_dir/tree" "$input"
python3 "$programs_dir/strip-rootfs.py" "$image_dir/tree" --strip "$prefix-strip"
"$host_dir/bin/mkcramfs" -X -q "$image_dir/tree" "$image_dir/rootfs.cramfs"
size=$(wc -c < "$image_dir/rootfs.cramfs")
test "$size" -le $((0x780000))
"$host_dir/bin/cramfsck" "$image_dir/rootfs.cramfs"
cp "$image_dir/rootfs.cramfs" "$output"
sha256sum "$output"
echo "Image $image_dir: $size bytes, free $((0x780000-size)); not flashed."
