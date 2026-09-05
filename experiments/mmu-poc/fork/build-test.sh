#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$task_dir/../../.." && pwd)
build_dir="$repo_dir/../refs/esp32-linux-build/build"
prefix="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic"
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
cc -std=c99 -Wall -Wextra -Werror -O2 "$task_dir/fork-test.c" -o "$task_dir/../out/fork-test-host"
"$task_dir/../out/fork-test-host"
"$prefix-gcc" -std=c99 -Os -g -mfdpic -mauto-litpools -fPIC -static \
    -Wall -Wextra -Werror -ffunction-sections -fdata-sections \
    -Wl,--gc-sections,-z,stack-size=32768 \
    "$task_dir/fork-test.c" "$task_dir/fork-compat.c" \
    -o "$task_dir/../out/fork-test.debug"
"$prefix-strip" -o "$task_dir/../out/fork-test" "$task_dir/../out/fork-test.debug"
"$prefix-size" "$task_dir/../out/fork-test"
"$prefix-gcc" -std=c99 -Os -mfdpic -mauto-litpools -fPIC -shared \
    -Wall -Wextra -Werror -Wl,-soname,libfork.so.0 \
    "$task_dir/fork-compat.c" -o "$task_dir/../out/libfork.so.0"
"$prefix-strip" "$task_dir/../out/libfork.so.0"
"$prefix-gcc" -std=c99 -Os -g -mfdpic -mauto-litpools -fPIC \
    -Wall -Wextra -Werror -Wl,-z,stack-size=32768 \
    "$task_dir/fork-test.c" -L"$task_dir/../out" -l:libfork.so.0 \
    -o "$task_dir/../out/fork-test-dynamic.debug"
"$prefix-strip" -o "$task_dir/../out/fork-test-dynamic" "$task_dir/../out/fork-test-dynamic.debug"
"$prefix-readelf" -d "$task_dir/../out/fork-test-dynamic" | sed -n '/NEEDED/p'
