#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
work=$(cd "$repo/.." && pwd)
test "$work" = /work
set -a
source "$repo/build/sources.lock"
set +a
export JOBS=${JOBS:-8}
export KBUILD_BUILD_USER=builder KBUILD_BUILD_HOST=esp32-repro
export KBUILD_BUILD_TIMESTAMP='Sat Sep 5 00:00:00 UTC 2026' KBUILD_BUILD_VERSION=1
export SOURCE_DATE_EPOCH=1788566400
export GIT_AUTHOR_DATE='2026-09-05T00:00:00+00:00' GIT_COMMITTER_DATE='2026-09-05T00:00:00+00:00'
mkdir -p "$work/refs" "$work/logs" "$work/stages" "$work/artifacts"
driver="$work/refs/esp32-linux-build"
base="$driver/build"
br="$base/build-buildroot-esp32s3_devkit_c1_16m"
exp="$repo/experiments/mmu-poc"

clone_locked() {
    local url=$1 revision=$2 target=$3
    if [[ ! -e "$target" ]]; then
        mkdir -p "$target"
        git -C "$target" init -q
        git -C "$target" remote add origin "$url"
    fi
    test "$(git -C "$target" remote get-url origin)" = "$url"
    if ! git -C "$target" rev-parse --verify HEAD >/dev/null 2>&1; then
        git -C "$target" fetch --depth 1 origin "$revision"
        git -C "$target" checkout --detach FETCH_HEAD
    fi
    test "$(git -C "$target" rev-parse HEAD)" = "$revision"
}

stage() {
    local name=$1
    shift
    if [[ -f "$work/stages/$name.done" ]]; then
        echo "RESUME: $name already completed in this build directory"
        return
    fi
    echo "START: $name $(date -u +%FT%TZ)"
    (set -euo pipefail; "$@") 2>&1 | tee "$work/logs/$name.log"
    date -u +%FT%TZ > "$work/stages/$name.done"
    echo "PASS: $name"
}

toolchain() {
    clone_locked https://github.com/jcmvbkbc/esp32-linux-build "$BUILD_DRIVER_REV" "$driver"
    mkdir -p "$base"
    clone_locked https://github.com/jcmvbkbc/xtensa-dynconfig "$DYNCONFIG_REV" "$base/xtensa-dynconfig"
    clone_locked https://github.com/jcmvbkbc/config-esp32s3 "$ESP32_CONFIG_REV" "$base/esp32s3"
    make -C "$base/xtensa-dynconfig" ORIG=1 CONF_DIR="$base" esp32s3.so
    clone_locked https://github.com/jcmvbkbc/crosstool-NG "$CTNG_REV" "$base/crosstool-NG"
    cd "$base/crosstool-NG"
    ./bootstrap
    ./configure --enable-local
    make -j"$JOBS"
    ./ct-ng xtensa-esp32s3-linux-uclibcfdpic
    python3 "$repo/build/pin-toolchain.py" .config
    CT_PREFIX="$PWD/builds" ./ct-ng build
    test -x builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic-gcc
}

rootfs_base() {
    clone_locked https://github.com/jcmvbkbc/buildroot "$BUILDROOT_REV" "$base/buildroot"
    install -m 755 "$repo/new-files/toplevel/apply-local-changes.sh" "$driver/apply-local-changes.sh"
    if [[ ! -L "$driver/local-changes" ]]; then ln -s "$repo" "$driver/local-changes"; fi
    test "$(readlink "$driver/local-changes")" = "$repo"
    cd "$driver"
    ./apply-local-changes.sh buildroot
    make -C "$base/buildroot" O="$br" esp32s3_devkit_c1_16m_defconfig
    "$base/buildroot/utils/config" --file "$br/.config" --set-str TOOLCHAIN_EXTERNAL_PATH "$base/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic"
    "$base/buildroot/utils/config" --file "$br/.config" --set-str TOOLCHAIN_EXTERNAL_CUSTOM_PREFIX '$(ARCH)-esp32s3-linux-uclibcfdpic'
    "$base/buildroot/utils/config" --file "$br/.config" --set-str PRIMARY_SITE 'https://sources.buildroot.net'
    "$base/buildroot/utils/config" --file "$br/.config" --set-str WGET 'wget -nd -t 3 --timeout=20'
    test "$(git ls-remote https://github.com/jcmvbkbc/linux-xtensa.git "refs/tags/$LINUX_KERNEL_TAG^{}" | cut -f1)" = "$LINUX_KERNEL_REV"
    make -C "$base/buildroot" O="$br" BR2_JLEVEL="$JOBS"
    test -s "$br/images/rootfs.cramfs"
}

firmware() {
    clone_locked https://github.com/jcmvbkbc/esp-hosted "$ESP_HOSTED_REV" "$base/esp-hosted"
    cd "$driver"
    ./apply-local-changes.sh esp-hosted
    cd "$base/esp-hosted/esp_hosted_ng/esp/esp_driver"
    git submodule update --init --depth 1
    test "$(git -C esp-idf rev-parse HEAD)" = "$ESP_IDF_REV"
    cmake .
    cd esp-idf
    set +u
    source export.sh
    set -u
    cd ../network_adapter
    idf.py set-target esp32s3
    cp sdkconfig.defaults.esp32s3.16m8r sdkconfig
    idf.py build
    cd "$repo"
    bash make-images.sh "$driver"
    cp -a images "$work/base-images"
}

userspace() {
    mkdir -p "$exp/out/programs" "$exp/out/real-bins"
    clone_locked https://github.com/micropython/micropython "$MICROPYTHON_REV" "$exp/out/micropython-src"
    git -C "$exp/out/micropython-src" submodule update --init --depth 1 lib/berkeley-db-1.xx lib/libffi lib/mbedtls
    bash "$exp/make-test-images.sh" "$base"
    bash "$exp/fork/build-kernel-reclaim.sh"
    bash "$exp/fork/make-image.sh"
    bash "$exp/fork/real/fetch.sh"
    bash "$exp/fork/real/build.sh" all
    OPT_VARIANT=lto bash "$exp/fork/real/build.sh" make
    bash "$exp/programs/build-atfork-test.sh"
    bash "$exp/programs/build-micropython.sh"
    bash "$exp/programs/fetch-shell-tools.sh"
    bash "$exp/programs/build-bash.sh"
    bash "$exp/programs/build-socat.sh"
    bash "$exp/programs/build-netcat.sh"
    curl -fL --retry 2 "https://codeload.github.com/crigler/dtach/tar.gz/$DTACH_REV" -o "$exp/out/programs/dtach-b027c27.tar.gz"
    bash "$exp/programs/build-dtach.sh"
    bash "$exp/programs/build-process-tools.sh"
    bash "$exp/programs/make-image.sh"
    bash "$exp/programs/compact-image.sh"
    python3 "$exp/programs/image-profiles.py" build --profile all --output "$work/artifacts/rootfs.cramfs"
    python3 "$exp/programs/test-cron-image.py" "$work/artifacts/rootfs.cramfs"
    python3 "$exp/programs/test-process-tools.py"
    python3 "$exp/programs/test-strip-sections.py"
    python3 "$exp/fork/test-reclaim.py"
}

package() {
    python3 "$repo/build/package-final.py" "$work"
}

export XTENSA_GNU_CONFIG="$base/xtensa-dynconfig/esp32s3.so"
stage toolchain toolchain
stage base-rootfs rootfs_base
stage firmware firmware
stage userspace userspace
stage package package
sha256sum "$work/artifacts/linux-esp32s3-native-full.bin"
