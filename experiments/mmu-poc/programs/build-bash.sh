#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
source_dir="$programs_out/bash-5.2.37"
(cd "$programs_out/downloads" && sha256sum -c "$programs_dir/shell-tools.sha256")
if [[ ! -d "$source_dir" ]]; then
    tar -xzf "$programs_out/downloads/bash-5.2.37.tar.gz" -C "$programs_out"
fi
apply_program_patch "$source_dir" bash-fork.patch
apply_program_patch "$source_dir" bash-help-cross.patch
apply_program_patch "$source_dir" bash-pid-cache.patch
staging="$build_dir/build-buildroot-esp32s3_devkit_c1_16m/staging"
export CPPFLAGS="-I$staging/usr/include"
export CFLAGS="$CFLAGS -Oz -flto --sysroot=$staging"
export LDFLAGS="$LDFLAGS --sysroot=$staging -L$staging/usr/lib -Wl,-rpath-link,$staging/usr/lib"
cd "$source_dir"
if [[ -f Makefile ]]; then make clean; fi
bash_cv_getcwd_malloc=yes bash_cv_job_control_missing=present \
bash_cv_sys_named_pipes=present bash_cv_func_sigsetjmp=present \
bash_cv_printf_a_format=yes bash_cv_getenv_redef=no \
ac_cv_func_fork=yes ac_cv_func_fork_works=yes ac_cv_func_vfork=no \
ac_cv_lib_dl_dlopen=no ac_cv_func_dlopen=no ac_cv_func_dlsym=no ac_cv_func_dlclose=no \
CC_FOR_BUILD=cc CFLAGS_FOR_BUILD='-O2 -std=gnu17 -include stdint.h' ./configure --host=xtensa-linux --build="$(sh ./support/config.guess)" \
    --prefix=/usr --bindir=/bin --without-bash-malloc --with-curses \
    --disable-nls --disable-rpath --disable-profiling --enable-separate-helpfiles
# No loadable builtin DSOs: ordinary scripts and external programs are unaffected.
# Avoid exporting every internal Bash/Readline function solely for enable -f.
make -j"${JOBS:-4}" LOCAL_LDFLAGS= bash
make -C builtins helpdoc
install -m 755 bash "$programs_out/bash.debug"
"$prefix-strip" --strip-unneeded -R .xt.prop -R .xt.lit -o "$programs_out/bash" bash
"$prefix-size" "$programs_out/bash"
"$prefix-readelf" -d "$programs_out/bash" | sed -n '/NEEDED/p'
