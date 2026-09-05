#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
apply_program_patch "$programs_out/nvim-sources/LIBUV" libuv-fork.patch
apply_program_patch "$programs_out/uclibc-ng-1.0.48" uclibc-ifaddrs.patch
apply_program_patch "$programs_out/uclibc-ng-1.0.48" uclibc-forkpty.patch
cmake -S "$programs_dir/nvim-deps" -B "$programs_out/nvim-deps-build" -G Ninja \
    -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=xtensa \
    -DCMAKE_C_COMPILER="$CC" -DCMAKE_C_FLAGS="$CFLAGS" \
    -DCMAKE_EXE_LINKER_FLAGS="$LDFLAGS" -DCMAKE_BUILD_TYPE=MinSizeRel \
    -DCMAKE_INSTALL_PREFIX="$programs_out/nvim-deps"
cmake --build "$programs_out/nvim-deps-build" -j6
cmake --install "$programs_out/nvim-deps-build"
