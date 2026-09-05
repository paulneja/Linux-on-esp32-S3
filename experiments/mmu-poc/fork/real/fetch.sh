#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
out_dir="$task_dir/../../out/real-bins"
mkdir -p "$out_dir"
cd "$out_dir"
if [[ ! -f dash-0.5.12.tar.gz ]]; then
    curl -fL --connect-timeout 15 --max-time 90 \
        https://deb.debian.org/debian/pool/main/d/dash/dash_0.5.12.orig.tar.gz \
        -o dash-0.5.12.tar.gz
fi
if [[ ! -f make-4.4.1.tar.gz ]]; then
    curl -fL --connect-timeout 15 --max-time 90 \
        https://ftp.gnu.org/gnu/make/make-4.4.1.tar.gz -o make-4.4.1.tar.gz
fi
sha256sum -c "$task_dir/sources.sha256"
if [[ ! -e dash-0.5.12 ]]; then tar -xzf dash-0.5.12.tar.gz; fi
if [[ ! -e make-4.4.1 ]]; then tar -xzf make-4.4.1.tar.gz; fi
