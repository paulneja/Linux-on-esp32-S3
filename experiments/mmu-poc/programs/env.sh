#!/usr/bin/env bash
programs_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
experiment_dir=$(cd "$programs_dir/.." && pwd)
repo_dir=$(cd "$experiment_dir/../.." && pwd)
build_dir=$(cd "$repo_dir/../refs/esp32-linux-build/build" && pwd)
programs_out="$experiment_dir/out/programs"
prefix="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic"
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
export CC="$prefix-gcc" CXX="$prefix-g++" AR="$prefix-ar" RANLIB="$prefix-ranlib"
export CFLAGS='-Os -mfdpic -mauto-litpools -fPIC -ffunction-sections -fdata-sections'
export CXXFLAGS="$CFLAGS"
export LDFLAGS="-Wl,--gc-sections,-z,stack-size=65536 -L$experiment_dir/out"
export LIBS='-l:libfork.so.0'
host_dir="$build_dir/build-buildroot-esp32s3_devkit_c1_16m/host"

apply_program_patch() {
    local source_dir=$1 patch_name=$2
    if ! patch -d "$source_dir" -p1 -R --dry-run --batch < "$programs_dir/$patch_name" >/dev/null 2>&1; then
        patch -d "$source_dir" -p1 --forward --dry-run --batch < "$programs_dir/$patch_name"
        patch -d "$source_dir" -p1 --forward --batch < "$programs_dir/$patch_name"
    fi
}
