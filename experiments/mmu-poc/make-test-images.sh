#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/../.." && pwd)
build_dir=${1:-"$repo_dir/../refs/esp32-linux-build/build"}
TARGET="${TARGET:-esp32s3_16m}"

case "$TARGET" in
    esp32s3_16m)
        PROFILE="esp32s3_devkit_c1_16m"
        ;;
    xiao_esp32s3_8m)
        PROFILE="xiao_esp32s3_8m"
        ;;
    *)
        echo "error: unknown TARGET=$TARGET" >&2
        echo "supported targets: esp32s3_16m xiao_esp32s3_8m" >&2
        exit 1
        ;;
esac

host_dir="$build_dir/build-buildroot-$PROFILE/host"

bash "$script_dir/build.sh" "$build_dir"
bash "$script_dir/build-micropython.sh" "$build_dir"
bash "$script_dir/test-host.sh"
image_work=$(mktemp -d "$script_dir/out/image.XXXXXX")
trap 'rm -rf -- "$image_work"' EXIT
"$host_dir/bin/cramfsck" -x "$image_work/tree" "$repo_dir/images/rootfs.cramfs"
install -m 755 "$script_dir/out/mmu-run" "$image_work/tree/usr/bin/"
if [ "${MMU_PAYLOADS:-}" = all ]; then
    install -m 755 "$script_dir/out/mmu-probe" "$script_dir/out/mmu-probe-dynamic" \
        "$image_work/tree/usr/bin/"
fi
install -d "$image_work/tree/usr/share/mmu"
# MMU_PAYLOADS=all keeps the lab set. The default ships only what the board
# suite actually runs: mmu-run self-test uses counter-a and counter-b, and the
# fibonacci check uses fib. micropython.elf alone is 384123 bytes, a second
# copy of the interpreter already at /usr/bin/micropython.
payloads="counter-a counter-b fib"
if [ "${MMU_PAYLOADS:-}" = all ]; then
    payloads="counter-a counter-b fib timeout pages tools micropython"
fi
for name in $payloads; do
    install -m 644 "$script_dir/out/$name.elf" "$image_work/tree/usr/share/mmu/"
done
install -m 755 "$script_dir/mmu-tools.sh" "$image_work/tree/usr/bin/mmu-tools"
install -m 644 "$script_dir/micropython/selftest.py" "$image_work/tree/usr/share/mmu/selftest.py"
if [ "${MMU_PAYLOADS:-}" = all ]; then
    install -m 755 "$script_dir/micropython-mmu.sh" "$image_work/tree/usr/bin/micropython-mmu"
    install -d "$image_work/tree/usr/share/licenses/micropython"
    install -m 644 "$script_dir/out/micropython-src/LICENSE" \
        "$image_work/tree/usr/share/licenses/micropython/LICENSE"
fi
install -m 644 "$script_dir/profile.sh" "$image_work/tree/etc/profile.d/history.sh"
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
