#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/../.." && pwd)
build_dir=${1:-"$repo_dir/../refs/esp32-linux-build/build"}
toolchain="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic"
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
if [[ ! -x "$toolchain-gcc" || ! -f "$XTENSA_GNU_CONFIG" ]]; then
    echo "Missing Linux toolchain/dynconfig. Pass the esp32-linux-build/build directory." >&2
    exit 1
fi
mkdir -p -- "$script_dir/out"
for variant in static dynamic; do
    link_flags=()
    binary="$script_dir/out/mmu-probe-dynamic"
    if [[ "$variant" == static ]]; then
        link_flags=(-static)
        binary="$script_dir/out/mmu-probe"
    fi
    "$toolchain-gcc" -std=c99 -D_POSIX_C_SOURCE=200112L -Os -g -mfdpic -mauto-litpools -fPIC \
        "${link_flags[@]}" -Wall -Wextra -Werror -Wl,--gc-sections \
        -ffunction-sections -fdata-sections \
        "$script_dir/mmu-probe.c" -o "$binary.debug"
    "$toolchain-strip" -o "$binary" "$binary.debug"
    "$toolchain-size" "$binary"
done
"$toolchain-gcc" -std=c99 -Os -g -mfdpic -mauto-litpools -fPIC -static \
    -Wall -Wextra -Werror -Wl,--gc-sections,-z,stack-size=65536 -ffunction-sections -fdata-sections \
    "$script_dir/mmu-run.c" "$script_dir/mmu-elf.c" "$script_dir/mmu-services.c" \
    -o "$script_dir/out/mmu-run.debug"
"$toolchain-strip" -o "$script_dir/out/mmu-run" "$script_dir/out/mmu-run.debug"
"$toolchain-size" "$script_dir/out/mmu-run"
for name in counter-a counter-b fib timeout pages tools; do
    extra_sources=()
    if [[ "$name" == pages ]]; then extra_sources=("$script_dir/payloads/pages-high.S"); fi
    if [[ "$name" == tools ]]; then extra_sources=("$script_dir/sdk/call.S"); fi
    "$toolchain-gcc" -std=c99 -Os -mno-fdpic -mabi=call0 -fno-pic -fno-pie \
        -mauto-litpools -ffreestanding -fno-stack-protector -nostdlib -static \
        -Wall -Wextra -Werror -Wl,-m,elf32xtensa -Wl,--build-id=none -Wl,-T,"$script_dir/payload.ld" \
        -I"$script_dir/sdk" "$script_dir/payloads/$name.c" "${extra_sources[@]}" \
        -o "$script_dir/out/$name.elf"
    "$toolchain-size" "$script_dir/out/$name.elf"
done
