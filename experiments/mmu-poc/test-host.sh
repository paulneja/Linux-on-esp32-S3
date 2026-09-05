#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$script_dir/out"
cc -std=c99 -D_POSIX_C_SOURCE=200112L -Wall -Wextra -Werror \
    "$script_dir/mmu-probe.c" -o "$script_dir/out/probe-host"
"$script_dir/out/probe-host" --self-test
cc -std=c99 -g -O1 -Wall -Wextra -Werror -fsanitize=address,undefined \
    "$script_dir/mmu-elf.c" "$script_dir/test-elf.c" -o "$script_dir/out/test-elf"
ASAN_OPTIONS=detect_leaks=0 "$script_dir/out/test-elf" "$script_dir/out/counter-a.elf" \
    "$script_dir/out/counter-b.elf" "$script_dir/out/fib.elf" "$script_dir/out/timeout.elf" \
    "$script_dir/out/pages.elf" "$script_dir/out/tools.elf" "$script_dir/out/micropython.elf"
cc -std=c99 -g -O1 -Wall -Wextra -Werror -fsanitize=address,undefined \
    "$script_dir/test-services.c" -o "$script_dir/out/test-services"
ASAN_OPTIONS=detect_leaks=0 "$script_dir/out/test-services"
