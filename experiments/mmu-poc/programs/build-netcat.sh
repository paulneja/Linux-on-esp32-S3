#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
original="$build_dir/build-buildroot-esp32s3_devkit_c1_16m/build/busybox-1.36.1"
source_dir="$programs_out/busybox-netcat"
if [[ ! -d "$source_dir" ]]; then
    cp -a --reflink=auto "$original" "$source_dir"
fi
apply_program_patch "$source_dir" busybox-nc.patch
# Use Buildroot's wrapper, which already supplies the board's ABI and sysroot.
unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS LIBS
make -C "$source_dir" ARCH=xtensa CROSS_COMPILE="$host_dir/bin/xtensa-esp32s3-linux-uclibcfdpic-" \
    HOSTCC='cc -std=gnu17' oldconfig < /dev/null
make -C "$source_dir" -j"${JOBS:-4}" ARCH=xtensa \
    CROSS_COMPILE="$host_dir/bin/xtensa-esp32s3-linux-uclibcfdpic-" HOSTCC='cc -std=gnu17'
install -m 755 "$source_dir/busybox_unstripped" "$programs_out/busybox-netcat.debug"
"$prefix-strip" --strip-unneeded -R .xt.prop -R .xt.lit \
    -o "$programs_out/busybox-with-netcat" "$source_dir/busybox_unstripped"
"$prefix-size" "$programs_out/busybox-with-netcat"
