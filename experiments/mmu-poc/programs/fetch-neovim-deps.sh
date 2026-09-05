#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
install -d "$programs_out/downloads"
cd "$programs_out/downloads"
while read -r key value; do
    case "$key" in
        LUA_URL|LIBUV_URL|LUV_URL|LPEG_URL|LUA_COMPAT53_URL|UNIBILIUM_URL|UTF8PROC_URL|TREESITTER_URL)
            name=${key%_URL}
            url=$value
            if [[ $url =~ ^https://github.com/([^/]+)/([^/]+)/archive/(.*)\.tar\.gz$ ]]; then
                url="https://codeload.github.com/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}/tar.gz/${BASH_REMATCH[3]}"
            fi
            url=${url/https:\/\/github.com\/neovim\/deps\/raw\//https:\/\/raw.githubusercontent.com\/neovim\/deps\/}
            expected=$(awk -v key="${name}_SHA256" '$1 == key { print $2 }' "$programs_out/neovim-0.11.4/cmake.deps/deps.txt")
            if ! printf '%s  %s\n' "$expected" "$name.tar.gz" | sha256sum -c --status; then
                curl -fL --retry 2 --connect-timeout 15 --max-time 120 "$url" -o "$name.tar.gz"
            fi
            printf '%s  %s\n' "$expected" "$name.tar.gz" | sha256sum -c
            install -d "$programs_out/nvim-sources/$name"
            tar -xf "$name.tar.gz" -C "$programs_out/nvim-sources/$name" --strip-components=1
            ;;
    esac
done < "$programs_out/neovim-0.11.4/cmake.deps/deps.txt"
