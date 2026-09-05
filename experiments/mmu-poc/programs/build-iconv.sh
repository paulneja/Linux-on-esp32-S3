#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$programs_out/downloads"
printf '%s  LIBICONV.tar.gz\n' 8f74213b56238c85a50a5329f77e06198771e70dd9a739779f4c02f65d971313 | sha256sum -c
if ! test -d "$programs_out/libiconv-1.17"; then
    tar -xf LIBICONV.tar.gz -C "$programs_out"
fi
cd "$programs_out/libiconv-1.17"
./configure --host=xtensa-esp32s3-linux-uclibcfdpic --prefix="$programs_out/nvim-deps" \
    --disable-shared --enable-static --disable-nls
make -j6
make install
