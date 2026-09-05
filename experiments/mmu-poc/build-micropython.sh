#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/../.." && pwd)
build_dir=${1:-"$repo_dir/../refs/esp32-linux-build/build"}
source_dir="$script_dir/out/micropython-src"
expected_commit=4ce2dd2cdab6e57f3982fc899f15a2103d71b0be
if [[ ! -d "$source_dir/.git" ]]; then
    echo "Fetch official MicroPython v1.26.0 into $source_dir first (see README)." >&2
    exit 1
fi
if [[ $(git -C "$source_dir" rev-parse HEAD) != "$expected_commit" ||
      -n $(git -C "$source_dir" status --porcelain) ]]; then
    echo "MicroPython source must be the clean pinned v1.26.0 commit." >&2
    exit 1
fi
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
prefix="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic-"
make -C "$script_dir/micropython" -j4 CROSS_COMPILE="$prefix"
"${prefix}strip" -o "$script_dir/out/micropython.elf" "$script_dir/out/micropython-build/micropython.elf"
"${prefix}size" "$script_dir/out/micropython.elf"
