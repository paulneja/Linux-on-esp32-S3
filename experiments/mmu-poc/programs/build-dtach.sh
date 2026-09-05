#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
revision=b027c27b2439081064d07a86883c8e0b20a183c9
archive="$programs_out/dtach-b027c27.tar.gz"
echo "2ec8db52ed99700cf80258b52e77461068abf24a2798cb91f9c0b2bc6e6ee8f4  $archive" | sha256sum -c -
source_dir="$programs_out/dtach-$revision"
if [[ ! -d "$source_dir" ]]; then tar -xzf "$archive" -C "$programs_out"; fi
cd "$source_dir"
export CFLAGS="$CFLAGS -D_GNU_SOURCE"
export LIBS='-l:libfork.so.0'
./configure --build="$(cc -dumpmachine)" --host=xtensa-esp32s3-linux-uclibcfdpic \
    ac_cv_func_forkpty=no ac_cv_func_openpty=no
make clean
make -j"${JOBS:-4}" CFLAGS="$CFLAGS -I. -include $experiment_dir/fork/real/fork-decl.h"
"$prefix-strip" --strip-unneeded -R .xt.prop -R .xt.lit -o "$programs_out/dtach" dtach
"$prefix-size" "$programs_out/dtach"
