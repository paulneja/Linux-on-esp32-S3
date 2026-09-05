#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
source_dir="$programs_out/socat-1.8.1.3"
(cd "$programs_out/downloads" && sha256sum -c "$programs_dir/shell-tools.sha256")
if [[ ! -d "$source_dir" ]]; then
    tar -xjf "$programs_out/downloads/socat-1.8.1.3.tar.bz2" -C "$programs_out"
fi
apply_program_patch "$source_dir" socat-fork.patch
export CFLAGS="$CFLAGS -Oz -flto"
cd "$source_dir"
if [[ -f Makefile ]]; then make clean; fi
ac_cv_have_c99_snprintf=yes ac_cv_have_z_modifier=yes \
sc_cv_sys_crdly_shift=9 sc_cv_sys_tabdly_shift=11 sc_cv_sys_csize_shift=4 \
ac_cv_func_fork=yes ./configure --host=xtensa-linux --build="$(./config.guess)" \
    --prefix=/usr --disable-readline --disable-openssl --disable-sycls --disable-filan --enable-msglevel=2 \
    --disable-sctp --disable-dccp --disable-vsock --disable-namespaces --disable-posixmq
make -j"${JOBS:-4}" socat
install -m 755 socat "$programs_out/socat.debug"
"$prefix-strip" --strip-unneeded -R .xt.prop -R .xt.lit -o "$programs_out/socat" socat
"$prefix-size" "$programs_out/socat"
"$prefix-readelf" -d "$programs_out/socat" | sed -n '/NEEDED/p'
