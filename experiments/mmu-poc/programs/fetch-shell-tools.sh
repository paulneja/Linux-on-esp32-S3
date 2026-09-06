#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
mkdir -p "$programs_out/downloads"
cd "$programs_out/downloads"
for item in \
    'bash-5.2.37.tar.gz|https://ftp.gnu.org/gnu/bash/bash-5.2.37.tar.gz' \
    'socat-1.8.1.3.tar.bz2|https://sources.buildroot.net/socat/socat-1.8.1.3.tar.bz2'; do
    file=${item%%|*}
    url=${item#*|}
    if [[ ! -f "$file" ]]; then
        curl --fail --location --connect-timeout 15 --max-time 120 --retry 1 "$url" -o "$file"
    fi
done
sha256sum -c "$programs_dir/shell-tools.sha256"
