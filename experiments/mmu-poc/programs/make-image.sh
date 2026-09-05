#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
output=${1:-"$programs_out/rootfs-programs.cramfs"}
image_dir=$(mktemp -d "$programs_out/image.XXXXXX")
"$host_dir/bin/cramfsck" -x "$image_dir/tree" "$experiment_dir/out/rootfs-fork.cramfs"
install -m 755 "$experiment_dir/out/real-bins/dash" "$experiment_dir/out/real-bins/make" "$image_dir/tree/usr/bin/"
install -m 755 "$experiment_dir/out/fork-test" "$experiment_dir/out/fork-test-dynamic" "$image_dir/tree/usr/bin/"
install -m 755 "$programs_out/micropython-linux" "$image_dir/tree/usr/bin/micropython"
install -m 755 "$programs_out/atfork-test" "$image_dir/tree/usr/bin/atfork-test"
install -m 755 "$experiment_dir/out/libfork.so.0" "$image_dir/tree/usr/lib/"
install -d "$image_dir/tree/usr/share/fork-real" "$image_dir/tree/usr/share/program-tests" "$image_dir/tree/usr/lib/micropython"
install -m 644 "$experiment_dir/fork/real/"{dash-test.sh,make-test.sh,peer.sh,Makefile.test} "$image_dir/tree/usr/share/fork-real/"
install -m 644 "$programs_dir/micropython-test.py" "$image_dir/tree/usr/share/program-tests/"
for program in dash make micropython; do
    install -d "$image_dir/tree/usr/share/licenses/$program"
done
install -m 644 "$experiment_dir/out/real-bins/dash-0.5.12/COPYING" "$image_dir/tree/usr/share/licenses/dash/"
install -m 644 "$experiment_dir/out/real-bins/make-4.4.1/COPYING" "$image_dir/tree/usr/share/licenses/make/"
install -m 644 "$programs_out/micropython/LICENSE" "$image_dir/tree/usr/share/licenses/micropython/"
python3 "$programs_dir/strip-rootfs.py" "$image_dir/tree" --strip "$prefix-strip"
"$host_dir/bin/mkcramfs" -X -q "$image_dir/tree" "$image_dir/rootfs.cramfs"
size=$(wc -c < "$image_dir/rootfs.cramfs")
test "$size" -le $((0x780000))
"$host_dir/bin/cramfsck" "$image_dir/rootfs.cramfs"
cp "$image_dir/rootfs.cramfs" "$output"
sha256sum "$output"
echo "Image $image_dir: $size bytes, free $((0x780000-size)); not flashed."
