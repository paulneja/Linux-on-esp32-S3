#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cmake -S "$programs_out/nvim-sources/LUV" -B "$programs_out/luv-build" -G Ninja \
    -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=xtensa \
    -DCMAKE_C_COMPILER="$CC" -DCMAKE_C_FLAGS="$CFLAGS" \
    -DCMAKE_EXE_LINKER_FLAGS="$LDFLAGS" -DCMAKE_BUILD_TYPE=MinSizeRel \
    -DCMAKE_INSTALL_PREFIX="$programs_out/nvim-deps" \
    -DCMAKE_PREFIX_PATH="$programs_out/nvim-deps" \
    -DWITH_LUA_ENGINE=Lua -DLUA_BUILD_TYPE=System \
    -DLUA_INCLUDE_DIR="$programs_out/nvim-deps/include" \
    -DLUA_LIBRARY="$programs_out/nvim-deps/lib/liblua.a" \
    -DWITH_SHARED_LIBUV=ON -DBUILD_STATIC_LIBS=ON -DBUILD_MODULE=OFF \
    -DLUA_COMPAT53_DIR="$programs_out/nvim-sources/LUA_COMPAT53"
cmake --build "$programs_out/luv-build" -j6
cmake --install "$programs_out/luv-build"
