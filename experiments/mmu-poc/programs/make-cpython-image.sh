#!/usr/bin/env bash
# Standalone sizing/boot experiment. Never replace the normal artifact.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
image_dir=$(mktemp -d "$programs_out/cpython-image.XXXXXX")
install -d "$image_dir/tree"
for directory in bin lib sbin etc dev proc sys tmp run root home var; do
    cp -a "$programs_out/tree/$directory" "$image_dir/tree/"
done
install -m 644 "$programs_dir/cpython-inittab" "$image_dir/tree/etc/inittab"
install -d "$image_dir/tree/usr/bin" "$image_dir/tree/usr/lib/python3.12" "$image_dir/tree/usr/share/licenses/python"
install -m 755 "$programs_out/python3.12" "$image_dir/tree/usr/bin/python3.12"
ln -s python3.12 "$image_dir/tree/usr/bin/python3"
install -m 755 "$experiment_dir/out/libfork.so.0" "$image_dir/tree/usr/lib/"
cp -a "$programs_out/Python-3.12.5/Lib/encodings" "$image_dir/tree/usr/lib/python3.12/"
install -m 644 "$programs_out/Python-3.12.5/LICENSE" "$image_dir/tree/usr/share/licenses/python/"
"$host_dir/bin/mkcramfs" -X -q "$image_dir/tree" "$programs_out/rootfs-cpython.cramfs"
test "$(wc -c < "$programs_out/rootfs-cpython.cramfs")" -le $((0x780000))
"$host_dir/bin/cramfsck" "$programs_out/rootfs-cpython.cramfs"
sha256sum "$programs_out/rootfs-cpython.cramfs"
echo "$image_dir"
