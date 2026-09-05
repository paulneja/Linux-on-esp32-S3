#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$task_dir/../../../.." && pwd)
out_dir="$task_dir/../../out"
build_dir="$repo_dir/../refs/esp32-linux-build/build"
prefix="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic"
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
export CC="$prefix-gcc" AR="$prefix-ar" RANLIB="$prefix-ranlib" STRIP="$prefix-strip"
export CFLAGS='-Os -g -mfdpic -mauto-litpools -fPIC -ffunction-sections -fdata-sections'
export CPPFLAGS="-D_GNU_SOURCE -I$task_dir"
export LDFLAGS="-Wl,--gc-sections,-z,stack-size=65536 -L$out_dir"
export LIBS='-l:libfork.so.0'
export CC_FOR_BUILD=cc
apply_source_patch() {
    if ! patch --batch --dry-run -R -p1 < "$1" >/dev/null 2>&1; then
        patch --batch --forward --dry-run -p1 < "$1"
        patch --batch --forward -p1 < "$1"
    fi
}
case "${1:-all}" in
dash|all)
    cd "$out_dir/real-bins/dash-0.5.12"
    apply_source_patch "$task_dir/dash.patch"
    ./configure --host=xtensa-esp32s3-linux-uclibcfdpic --prefix=/usr \
        --disable-static --without-libedit
    make -j1
    "$STRIP" -o "$out_dir/real-bins/dash" src/dash
    ;;
esac
case "${1:-all}" in
make|all)
    cd "$out_dir/real-bins/make-4.4.1"
    apply_source_patch "$task_dir/make.patch"
    ac_cv_func_posix_spawn=no ac_cv_func_vfork=no ac_cv_func_fork=yes \
    ac_cv_func_fork_works=yes ac_cv_func_vfork_works=no \
        ./configure --host=xtensa-esp32s3-linux-uclibcfdpic --prefix=/usr \
        --without-guile --disable-nls --disable-load
    make -j4
    "$STRIP" -o "$out_dir/real-bins/make" make
    ;;
esac
