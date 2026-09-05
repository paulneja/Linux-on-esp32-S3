#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
if ! test -d "$programs_out/micropython"; then
    cp -a "$experiment_dir/out/micropython-src" "$programs_out/micropython"
fi
if ! patch -d "$programs_out/micropython" -p1 -R --dry-run --force < "$programs_dir/micropython.patch" >/dev/null 2>&1; then
    patch -d "$programs_out/micropython" -p1 --forward --batch < "$programs_dir/micropython.patch"
fi
unset CFLAGS CXXFLAGS LDFLAGS LIBS
variant=${OPT_VARIANT:-baseline}
case "$variant" in
    baseline) opt_flags=; build_name=build-micropython; output=micropython-linux ;;
    oz|lto|local)
        opt_flags=-Oz
        if [[ "$variant" != oz ]]; then opt_flags+=' -flto'; fi
        if [[ "$variant" == local ]]; then opt_flags+=' -fno-semantic-interposition'; fi
        build_name=build-micropython-$variant; output=micropython-$variant ;;
    *) exit 2 ;;
esac
make -C "$programs_out/micropython/ports/unix" -j4 \
    BUILD="$build_name" \
    VARIANT_DIR="$programs_dir/micropython" \
    CROSS_COMPILE="$prefix-" \
    USER_C_MODULES="$programs_dir/modules" \
    CFLAGS_EXTRA="-mfdpic -mauto-litpools -fPIC $opt_flags" \
    LDFLAGS_EXTRA="$opt_flags -Wl,-z,stack-size=65536 -L$experiment_dir/out -l:libfork.so.0" \
    FROZEN_MANIFEST=
install -m 755 "$programs_out/micropython/ports/unix/$build_name/micropython" "$programs_out/$output"
"$prefix-strip" -R .xt.prop -R .xt.lit "$programs_out/$output"
"$prefix-size" "$programs_out/$output"
