#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
mode=${1:-keep-sh}
case "$mode" in
    keep-sh) output="$programs_out/rootfs-shell-tools.cramfs" ;;
    --bash-as-sh)
        echo 'WARNING: global Bash-as-sh failed the board DHCP memory test; reproduction only.' >&2
        output="$programs_out/rootfs-bash-sh.cramfs" ;;
    *) echo 'Usage: make-shell-tools-image.sh [--bash-as-sh]' >&2; exit 2 ;;
esac
image_dir=$(mktemp -d "$programs_out/shell-tools.XXXXXX")
"$host_dir/bin/cramfsck" -x "$image_dir/tree" "$programs_out/rootfs-programs-stripped.cramfs"
install -m 755 "$programs_out/bash" "$image_dir/tree/bin/bash"
install -m 755 "$programs_out/socat" "$image_dir/tree/usr/bin/socat"
install -m 755 "$programs_out/busybox-with-netcat" "$image_dir/tree/bin/busybox"
ln -s busybox "$image_dir/tree/bin/nc"
ln -s busybox "$image_dir/tree/bin/netcat"
if [[ "$mode" == --bash-as-sh ]]; then
    test "$(readlink "$image_dir/tree/bin/sh")" = busybox
    ln -sfn bash "$image_dir/tree/bin/sh"
fi
install -m 644 "$programs_dir/bash-test.sh" "$image_dir/tree/usr/share/program-tests/"
install -m 644 "$programs_dir/network-tools-test.sh" "$image_dir/tree/usr/share/program-tests/"
install -d "$image_dir/tree/usr/share/bash/helpfiles"
install -m 644 "$programs_out/bash-5.2.37/builtins/helpfiles/"* "$image_dir/tree/usr/share/bash/helpfiles/"
for program in bash socat; do
    install -d "$image_dir/tree/usr/share/licenses/$program"
done
install -m 644 "$programs_out/bash-5.2.37/COPYING" "$image_dir/tree/usr/share/licenses/bash/"
install -m 644 "$programs_out/socat-1.8.1.3/COPYING" "$image_dir/tree/usr/share/licenses/socat/"
python3 "$programs_dir/strip-rootfs.py" "$image_dir/tree" --strip "$prefix-strip"
"$host_dir/bin/mkcramfs" -X -q "$image_dir/tree" "$image_dir/rootfs.cramfs"
size=$(wc -c < "$image_dir/rootfs.cramfs")
echo "Image $image_dir: $size bytes, free $((0x780000-size)); not flashed."
test "$size" -le $((0x780000))
"$host_dir/bin/cramfsck" "$image_dir/rootfs.cramfs"
cp "$image_dir/rootfs.cramfs" "$output"
sha256sum "$output"
# Persistent /etc/passwd stays unchanged. Bash invoked as sh enters POSIX mode.
# /bin/busybox sh remains available explicitly for recovery.
