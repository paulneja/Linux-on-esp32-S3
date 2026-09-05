#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cc -Wall -Wextra -Werror -O2 "$programs_dir/atfork-test.c" "$experiment_dir/fork/fork-compat.c" \
    -pthread -o "$programs_out/atfork-compat-host"
"$programs_out/atfork-compat-host"
cc -Wall -Wextra -Werror -O2 "$programs_dir/atfork-failure-test.c" "$experiment_dir/fork/fork-compat.c" \
    -pthread -Wl,--wrap=syscall -o "$programs_out/atfork-failure-host"
"$programs_out/atfork-failure-host"
"$CC" $CFLAGS -Wall -Wextra -Werror -Wl,-z,stack-size=32768 \
    "$programs_dir/atfork-test.c" -L"$experiment_dir/out" -l:libfork.so.0 -o "$programs_out/atfork-test"
"$prefix-strip" -R .xt.prop -R .xt.lit "$programs_out/atfork-test"
