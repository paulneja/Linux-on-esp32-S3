#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
if ! test -d "$programs_out/micropython"; then
    cp -a "$experiment_dir/out/micropython-src" "$programs_out/micropython"
fi
if ! patch -d "$programs_out/micropython" -p1 -R --dry-run --batch < "$programs_dir/micropython.patch" >/dev/null 2>&1; then
    patch -d "$programs_out/micropython" -p1 --forward --batch < "$programs_dir/micropython.patch"
fi
unset CFLAGS CXXFLAGS LDFLAGS LIBS
make -C "$programs_out/micropython/ports/unix" -j4 \
    VARIANT_DIR="$programs_dir/micropython" \
    CROSS_COMPILE="$prefix-" \
    USER_C_MODULES="$programs_dir/modules" \
    CFLAGS_EXTRA='-mfdpic -mauto-litpools -fPIC' \
    LDFLAGS_EXTRA="-Wl,-z,stack-size=65536 -L$experiment_dir/out -l:libfork.so.0" \
    FROZEN_MANIFEST=
install -m 755 "$programs_out/micropython/ports/unix/build-micropython/micropython" "$programs_out/micropython-linux"
"$prefix-strip" -R .xt.prop -R .xt.lit "$programs_out/micropython-linux"
"$prefix-size" "$programs_out/micropython-linux"
