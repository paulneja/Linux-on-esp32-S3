#!/usr/bin/env bash
set -euo pipefail
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$task_dir/../../../.." && pwd)
out_dir="$task_dir/../../out"
build_dir="$repo_dir/../refs/esp32-linux-build/build"
prefix="$build_dir/crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic"
export XTENSA_GNU_CONFIG="$build_dir/xtensa-dynconfig/esp32s3.so"
export CC="$prefix-gcc" AR="$prefix-ar" RANLIB="$prefix-ranlib" STRIP="$prefix-strip"
variant=${OPT_VARIANT:-baseline}
case "$variant" in
    baseline) opt_flags='-Os' ;;
    oz) opt_flags='-Oz' ;;
    lto) opt_flags='-Oz -flto' ;;
    *) echo 'OPT_VARIANT must be baseline, oz or lto' >&2; exit 2 ;;
esac
export CFLAGS="$opt_flags -g -mfdpic -mauto-litpools -fPIC -ffunction-sections -fdata-sections"
export CPPFLAGS="-D_GNU_SOURCE -I$task_dir"
export LDFLAGS="-Wl,--gc-sections,-z,stack-size=65536 -L$out_dir"
export LIBS='-l:libfork.so.0'
export CC_FOR_BUILD=cc
apply_source_patch() {
    if ! patch --force --dry-run -R -p1 < "$1" >/dev/null 2>&1; then
        patch --batch --forward --dry-run -p1 < "$1"
        patch --batch --forward -p1 < "$1"
    fi
}
case "${1:-all}" in
dash|all)
    cd "$out_dir/real-bins/dash-0.5.12"
    apply_source_patch "$task_dir/dash.patch"
    make distclean >/dev/null 2>&1 || test ! -f Makefile
    ./configure --host=xtensa-esp32s3-linux-uclibcfdpic --prefix=/usr \
        --disable-static --without-libedit
    make -j1
    "$STRIP" --strip-unneeded -R .xt.prop -R .xt.lit -o "$out_dir/real-bins/dash-$variant" src/dash
    if [[ "$variant" == baseline ]]; then cp "$out_dir/real-bins/dash-$variant" "$out_dir/real-bins/dash"; fi
    ;;
esac
case "${1:-all}" in
make|all)
    cd "$out_dir/real-bins/make-4.4.1"
    apply_source_patch "$task_dir/make.patch"
    make distclean >/dev/null 2>&1 || test ! -f Makefile
    # make only ever spawns a recipe and execs it, so it never needs the
    # copying fork backend. Its non-posix_spawn path in job.c is vfork() plus
    # dup2() plus exec, which is exactly what vfork allows, and vfork on
    # NOMMU costs no copy at all. It used to be configured onto fork() to
    # exercise the backend, at a full private-memory copy per live recipe.
    #
    # posix_spawn stays off on purpose: this uClibc's __spawni() returns
    # ENOSYS on NOMMU whenever file actions are given, and make always gives
    # them. AC_FUNC_FORK cannot run its probes when cross-compiling, so the
    # answers are supplied: vfork works, and it is not to be aliased to fork.
    ac_cv_func_vfork=yes ac_cv_func_vfork_works=yes ac_cv_func_fork_works=yes \
        ./configure --host=xtensa-esp32s3-linux-uclibcfdpic --prefix=/usr \
        --without-guile --disable-nls --disable-load --disable-posix-spawn
    make -j4
    "$STRIP" --strip-unneeded -R .xt.prop -R .xt.lit -o "$out_dir/real-bins/make-$variant" make
    if [[ "$variant" == baseline ]]; then cp "$out_dir/real-bins/make-$variant" "$out_dir/real-bins/make"; fi
    ;;
esac
