#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
for program in process-test programbench jobq; do
    # jobq spawns (vfork); it must not link the fork backend. The tools do.
    libs=$LIBS
    if [[ "$program" == jobq ]]; then libs=; fi
    cc -std=gnu17 -O2 -Wall -Wextra -Werror "$programs_dir/$program.c" -o "$programs_out/$program-host"
    if [[ "$program" == process-test ]]; then "$programs_out/$program-host"; fi
    "$CC" $CFLAGS -Oz -flto -std=gnu17 -Wall -Wextra -Werror \
        "$programs_dir/$program.c" $LDFLAGS $libs -o "$programs_out/$program"
    "$prefix-strip" --strip-unneeded -R .xt.prop -R .xt.lit "$programs_out/$program"
    "$prefix-size" "$programs_out/$program"
done

# Refuse a jobq that links libfork or imports fork.
if "$prefix-readelf" -d "$programs_out/jobq" | grep -q libfork; then
    echo "jobq links libfork; it must spawn, not fork" >&2; exit 1
fi
if "$prefix-readelf" --dyn-syms "$programs_out/jobq" | grep -qw "fork"; then
    echo "jobq still imports fork" >&2; exit 1
fi
echo "jobq: no fork import"
