#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
image_dir=$(mktemp -d "$programs_out/neovim-image.XXXXXX")
install -d "$image_dir/tree"
for directory in bin lib sbin etc dev proc sys tmp run root home var; do
    cp -a "$programs_out/tree/$directory" "$image_dir/tree/"
done
install -m 644 "$programs_dir/nvim-inittab" "$image_dir/tree/etc/inittab"
install -d "$image_dir/tree/home/root"
install -d "$image_dir/tree/usr/bin" "$image_dir/tree/usr/lib" "$image_dir/tree/usr/share/nvim" "$image_dir/tree/usr/share/program-tests"
install -m 755 "$programs_out/nvim" "$image_dir/tree/usr/bin/nvim"
install -m 755 "$experiment_dir/out/real-bins/dash" "$experiment_dir/out/real-bins/make" "$image_dir/tree/usr/bin/"
install -m 755 "$programs_out/micropython-linux" "$image_dir/tree/usr/bin/micropython"
install -m 755 "$programs_out/atfork-test" "$image_dir/tree/usr/bin/atfork-test"
install -m 755 "$experiment_dir/out/libfork.so.0" "$image_dir/tree/usr/lib/"
install -m 644 "$programs_dir/micropython-test.py" "$image_dir/tree/usr/share/program-tests/"
install -m 644 "$programs_dir/neovim-test.lua" "$image_dir/tree/usr/share/program-tests/"
for file in "$programs_out/tree/usr/bin/"*; do
    if test -L "$file" && [[ $(readlink "$file") == *busybox ]]; then
        cp -a "$file" "$image_dir/tree/usr/bin/"
    fi
done
cp -a "$programs_out/tree/usr/share/terminfo" "$image_dir/tree/usr/share/"
for file in "$image_dir/tree/bin/busybox" "$image_dir/tree/lib/"*.so*; do
    if test -f "$file" && ! test -L "$file"; then
        "$prefix-strip" -R .xt.prop -R .xt.lit "$file"
    fi
done
"$host_dir/bin/mkcramfs" -X -q "$image_dir/tree" "$programs_out/rootfs-neovim.cramfs"
size=$(wc -c < "$programs_out/rootfs-neovim.cramfs")
echo "Image $image_dir: $size bytes, free $((0x780000-size))"
test "$size" -le $((0x780000))
"$host_dir/bin/cramfsck" "$programs_out/rootfs-neovim.cramfs"
sha256sum "$programs_out/rootfs-neovim.cramfs"
