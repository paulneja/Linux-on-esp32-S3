#!/usr/bin/env bash
# Copyright (c) 2026 Paulneja. GPLv3, see LICENSE. https://github.com/paulneja/Linux-on-esp32-S3
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
out=${1:-$repo/build-output/host-hush}
version=1.36.1
sha=b8cc24c9574d809e7279c3be349795c5d5ceb6fdf19ca709f80cde50e47de314
tarball=$out/busybox-$version.tar.bz2

mkdir -p "$out"
if [ -x "$out/sh" ]; then
    echo "$out/sh"
    exit 0
fi
if [ ! -f "$tarball" ] || ! echo "$sha  $tarball" | sha256sum -c --status; then
    curl -fsSL --retry 3 -o "$tarball" "https://busybox.net/downloads/busybox-$version.tar.bz2"
fi
echo "$sha  $tarball" | sha256sum -c --status
rm -rf "$out/src"
mkdir "$out/src"
tar -xjf "$tarball" -C "$out/src" --strip-components=1
cd "$out/src"
make -s allnoconfig >/dev/null
grep -E '^CONFIG_(SHELL_HUSH|HUSH_[A-Z0-9_]*|FEATURE_SH_[A-Z0-9_]*|FEATURE_EDITING[A-Z0-9_]*|LONG_OPTS)=' \
    "$repo/new-files/board/espressif/esp32s3/busybox.config" |
while IFS= read -r line; do
    sed -i "s/^# ${line%%=*} is not set\$/$line/" .config
done
sed -i 's/^CONFIG_SH_IS_ASH=y/# CONFIG_SH_IS_ASH is not set/; s/^# CONFIG_SH_IS_HUSH is not set/CONFIG_SH_IS_HUSH=y/' .config
{ yes '' || true; } | make -s oldconfig >/dev/null
grep -q '^CONFIG_SH_IS_HUSH=y' .config
make -s -j"${JOBS:-4}" busybox >/dev/null
cp busybox "$out/busybox"
ln -sf busybox "$out/sh"
"$out/sh" -c 'true'
echo "$out/sh"
