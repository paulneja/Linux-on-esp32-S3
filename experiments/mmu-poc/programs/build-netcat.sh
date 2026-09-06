#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
original="$build_dir/build-buildroot-esp32s3_devkit_c1_16m/build/busybox-1.36.1"
source_dir="$programs_out/busybox-netcat"
variant=${OPT_VARIANT:-baseline}
extra=()
output=busybox-with-netcat
case "$variant" in
    baseline) ;;
    oz|lto)
        source_dir="$programs_out/busybox-$variant"
        flags=-Oz
        if [[ "$variant" == lto ]]; then flags+=' -flto'; fi
        extra=("CONFIG_EXTRA_CFLAGS=$flags" "CONFIG_EXTRA_LDFLAGS=$flags -Wl,-z,stack-size=16384")
        output=busybox-$variant.bin ;;
    *) exit 2 ;;
esac
if [[ ! -d "$source_dir" ]]; then
    cp -a --reflink=auto "$original" "$source_dir"
fi
apply_program_patch "$source_dir" busybox-nc.patch
apply_program_patch "$source_dir" busybox-login.patch
apply_program_patch "$source_dir" busybox-users.patch
apply_program_patch "$source_dir" busybox-stat.patch
apply_program_patch "$source_dir" busybox-cron.patch
apply_program_patch "$source_dir" busybox-cron-pidfile.patch
apply_program_patch "$source_dir" busybox-cron-special.patch
cron_patch="$repo_dir/new-files/board/espressif/esp32s3/package-patches/busybox/0002-cron-private-environment.patch"
if ! patch -d "$source_dir" -p1 -R --force --dry-run < "$cron_patch" >/dev/null 2>&1; then
    patch -d "$source_dir" -p1 --forward --batch < "$cron_patch"
fi
unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS LIBS
make -C "$source_dir" ARCH=xtensa CROSS_COMPILE="$host_dir/bin/xtensa-esp32s3-linux-uclibcfdpic-" \
    HOSTCC='cc -std=gnu17' oldconfig < /dev/null
make -C "$source_dir" -j"${JOBS:-4}" ARCH=xtensa \
    CROSS_COMPILE="$host_dir/bin/xtensa-esp32s3-linux-uclibcfdpic-" HOSTCC='cc -std=gnu17' "${extra[@]}"
install -m 755 "$source_dir/busybox_unstripped" "$programs_out/$output.debug"
"$prefix-strip" --strip-unneeded -R .xt.prop -R .xt.lit \
    -o "$programs_out/$output" "$source_dir/busybox_unstripped"
"$prefix-size" "$programs_out/$output"
