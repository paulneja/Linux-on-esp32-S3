#!/usr/bin/env bash
# Copyright (c) 2026 Paulneja. GPLv3, see LICENSE. https://github.com/paulneja/Linux-on-esp32-S3
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
CACHE=${CACHE:-clean}
case "$CACHE" in
	dev|clean) ;;
	*) echo "error: CACHE must be dev or clean (got: $CACHE)" >&2; exit 1 ;;
esac
dirty=$(git status --porcelain)
if [ -n "$dirty" ]; then
	echo 'The snapshot is taken from HEAD, so the tree must be clean.' >&2
	echo 'Commit tracked changes; move or ignore untracked files, including' >&2
	echo 'any build log written into the repository root:' >&2
	printf '%s\n' "$dirty" >&2
	exit 1
fi
test "$(id -u)" != 0 || { echo 'Run as a regular user with Docker access.' >&2; exit 1; }

# docker ate a whole disk once (#12)
LOG_CAP_BYTES=${LOG_CAP_BYTES:-50000000}

free_kb=$(df -Pk "$repo" | awk 'NR==2 {print $4}')
if [[ "$free_kb" =~ ^[0-9]+$ ]]; then
    free_gb=$((free_kb / 1024 / 1024))
else
    free_gb=""
fi
if [ -z "$free_gb" ] || [ "$free_gb" -lt 25 ] 2>/dev/null; then
	echo "error: ${free_gb:-an unknown amount of} GB free; one build takes about 21 GB." >&2
	echo 'Free some space (build-output/ is the usual place) before building.' >&2
	exit 1
fi

mkdir -p build-output
work=$(mktemp -d "$repo/build-output/reproduce.XXXXXX")
mkdir -p "$work/Linux-on-esp32-S3" "$work/logs"
git archive HEAD | tar -x --exclude=images -C "$work/Linux-on-esp32-S3"
git rev-parse HEAD > "$work/source-commit.txt"
git ls-tree -r HEAD > "$work/source-tree.txt"
image=linux-esp32s3-reproduce:$(sha256sum < build/Dockerfile | cut -c1-12)
docker build --network host --build-arg BUILDER_UID="$(id -u)" --build-arg BUILDER_GID="$(id -g)" \
    -f build/Dockerfile -t "$image" . 2>&1 | tee >(head -c "$LOG_CAP_BYTES" > "$work/logs/container-image.log")
docker inspect --format '{{.Id}}' "$image" > "$work/container-image-id.txt"
printf 'Build directory: %s\n' "$work"
cache_mounts=()
if [ "$CACHE" = dev ]; then
	cache_root=${ESP32_CACHE_DIR:-$repo/.cache}
	for d in toolchain crosstool-src buildroot-dl ccache espressif; do
		mkdir -p "$cache_root/$d"
	done
	cache_root=$(cd "$cache_root" && pwd -P)
	cache_mounts=(
		--mount "type=bind,source=$cache_root/toolchain,target=/cache/toolchain"
		--mount "type=bind,source=$cache_root/crosstool-src,target=/home/builder/src"
		--mount "type=bind,source=$cache_root/buildroot-dl,target=/cache/buildroot-dl"
		--mount "type=bind,source=$cache_root/ccache,target=/cache/ccache"
		--mount "type=bind,source=$cache_root/espressif,target=/home/builder/.espressif"
	)
	printf 'Cache: %s\n' "$cache_root"
else
	printf 'Cache: none, clean build\n'
fi
printf '%s\n' "$CACHE" > "$work/cache-mode.txt"
docker run --network host --name "esp32-reproduce-$(basename "$work")" --rm \
    --mount "type=bind,source=$work,target=/work" \
    ${cache_mounts[@]+"${cache_mounts[@]}"} \
    --env JOBS="${JOBS:-8}" \
    "$image" 2>&1 | tee >(head -c "$LOG_CAP_BYTES" > "$work/logs/build.log")
printf 'Complete local build: %s/artifacts\nNo board access or push was performed.\n' "$work"
