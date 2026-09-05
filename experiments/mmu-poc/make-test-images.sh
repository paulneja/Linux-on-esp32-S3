#!/usr/bin/env bash
# Build experimental images separately. This script NEVER flashes or publishes.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/../.." && pwd)
build_dir=${1:-"$repo_dir/../refs/esp32-linux-build/build"}
host_dir="$build_dir/build-buildroot-esp32s3_devkit_c1_16m/host"
bash "$script_dir/build.sh" "$build_dir"
bash "$script_dir/build-micropython.sh" "$build_dir"
bash "$script_dir/test-host.sh"
image_work=$(mktemp -d "$script_dir/out/image.XXXXXX")
"$host_dir/bin/cramfsck" -x "$image_work/tree" "$repo_dir/images/rootfs.cramfs"
install -m 755 "$script_dir/out/mmu-probe" "$script_dir/out/mmu-probe-dynamic" "$script_dir/out/mmu-run" \
    "$image_work/tree/usr/bin/"
install -d "$image_work/tree/usr/share/mmu"
for name in counter-a counter-b fib timeout pages tools micropython; do
    install -m 644 "$script_dir/out/$name.elf" "$image_work/tree/usr/share/mmu/"
done
install -m 755 "$script_dir/micropython-mmu.sh" "$image_work/tree/usr/bin/micropython-mmu"
install -m 755 "$script_dir/mmu-tools.sh" "$image_work/tree/usr/bin/mmu-tools"
install -m 644 "$script_dir/micropython/selftest.py" "$image_work/tree/usr/share/mmu/selftest.py"
install -d "$image_work/tree/usr/share/licenses/micropython"
install -m 644 "$script_dir/out/micropython-src/LICENSE" \
    "$image_work/tree/usr/share/licenses/micropython/LICENSE"
install -m 644 "$script_dir/profile.sh" "$image_work/tree/etc/profile.d/mmu-poc.sh"
"$host_dir/bin/mkcramfs" -X -q "$image_work/tree" "$script_dir/out/rootfs-probe.cramfs"
"$host_dir/sbin/mkfs.jffs2" -l -e 65536 -U -f --pad=458752 \
    -d "$image_work/tree/etc" -o "$script_dir/out/etc-no-history.jffs2"
rootfs_bytes=$(wc -c < "$script_dir/out/rootfs-probe.cramfs")
if ((rootfs_bytes > 0x780000)); then
    echo "Experimental rootfs exceeds its partition; DO NOT FLASH." >&2
    exit 1
fi
"$host_dir/bin/cramfsck" "$script_dir/out/rootfs-probe.cramfs"
sha256sum "$script_dir/out/rootfs-probe.cramfs" "$script_dir/out/etc-no-history.jffs2"
echo "Prepared $image_work; original images/ unchanged. No flash performed."
