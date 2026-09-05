#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
for program in process-test programbench jobq; do
    cc -std=gnu17 -O2 -Wall -Wextra -Werror "$programs_dir/$program.c" -o "$programs_out/$program-host"
    if [[ "$program" == process-test ]]; then "$programs_out/$program-host"; fi
    "$CC" $CFLAGS -Oz -flto -std=gnu17 -Wall -Wextra -Werror \
        "$programs_dir/$program.c" $LDFLAGS $LIBS -o "$programs_out/$program"
    "$prefix-strip" --strip-unneeded -R .xt.prop -R .xt.lit "$programs_out/$program"
    "$prefix-size" "$programs_out/$program"
done
