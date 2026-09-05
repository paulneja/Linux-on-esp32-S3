#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
"$CC" $CFLAGS -Wall -Wextra -Werror -I"$programs_out/nvim-deps/include" \
    "$programs_dir/uv-test.c" "$programs_dir/nvim-abort-trace.c" \
    "$programs_out/nvim-deps/lib/libuv.a" -L"$experiment_dir/out" -l:libfork.so.0 \
    -pthread -ldl -lrt -Wl,--wrap=abort,--gc-sections,-z,stack-size=65536 -o "$programs_out/uv-test"
"$prefix-strip" -R .xt.prop -R .xt.lit "$programs_out/uv-test"
"$prefix-size" "$programs_out/uv-test"
