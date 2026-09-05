#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$programs_out/Python-3.12.5"
ac_cv_file__dev_ptmx=yes ac_cv_file__dev_ptc=no ac_cv_working_tzset=yes \
ac_cv_func_fork=yes ac_cv_little_endian_double=yes \
py_cv_module__ssl=n/a py_cv_module__hashlib=n/a py_cv_module__tkinter=n/a \
py_cv_module__ctypes=n/a py_cv_module__decimal=n/a py_cv_module__sqlite3=n/a \
py_cv_module__bz2=n/a py_cv_module__lzma=n/a py_cv_module_nis=n/a \
    ./configure --host=xtensa-esp32s3-linux-uclibcfdpic \
    --build="$(./config.guess)" --prefix=/usr \
    --with-build-python="$host_dir/bin/python3.12" --without-ensurepip \
    --disable-test-modules --without-pymalloc --disable-ipv6
make -j6 python
"$prefix-strip" -o "$programs_out/python3.12" python
"$prefix-size" "$programs_out/python3.12"
