#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
export CCACHE_DIR="$programs_out/ccache"
apply_program_patch "$programs_out/neovim-0.11.4" neovim-cross.patch
cmake -S "$programs_out/neovim-0.11.4" -B "$programs_out/neovim-build" -G Ninja \
    -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=xtensa \
    -DCMAKE_C_COMPILER="$CC" -DCMAKE_C_FLAGS="$CFLAGS" \
    -DCMAKE_EXE_LINKER_FLAGS="$LDFLAGS -L$programs_out/nvim-deps/lib -l:libfork.so.0" \
    -DCMAKE_BUILD_TYPE=MinSizeRel -DCMAKE_INSTALL_PREFIX=/usr \
    -DDEPS_PREFIX="$programs_out/nvim-deps" \
    -DHOST_NLUA0="$programs_out/host-nlua0.so" \
    -DESP32_ABORT_TRACE="$programs_dir/nvim-abort-trace.c" \
    -DICONV_INCLUDE_DIR="$programs_out/nvim-deps/include" \
    -DICONV_LIBRARY="$programs_out/nvim-deps/lib/libiconv.a" \
    -DPREFER_LUA=ON -DCOMPILE_LUA=OFF -DENABLE_LIBINTL=OFF \
    -DLUA_INCLUDE_DIR="$programs_out/nvim-deps/include" \
    -DLUA_LIBRARY="$programs_out/nvim-deps/lib/liblua.a" \
    -DLUA_PRG=/usr/bin/lua5.1 -DLUA_GEN_PRG=/usr/bin/lua5.1
cc -Os -fPIC -shared -I/usr/include/lua5.1 -I"$programs_out/neovim-0.11.4/src" \
    -I"$programs_out/neovim-build/cmake.config" \
    "$programs_out/neovim-0.11.4/src/nlua0.c" \
    "$programs_out/neovim-0.11.4/src/mpack/"*.c \
    "$programs_out/neovim-0.11.4/src/bit.c" \
    "$programs_out/nvim-sources/LPEG/"*.c \
    -o "$programs_out/host-nlua0.so"
cmake --build "$programs_out/neovim-build" --target nvim_bin -j6
"$prefix-strip" -R .xt.prop -R .xt.lit -o "$programs_out/nvim" "$programs_out/neovim-build/bin/nvim"
"$prefix-size" "$programs_out/nvim"
