#!/usr/bin/env python3
import os
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()
values = {
    'CT_GCC_DEVEL_BRANCH': '""',
    'CT_BINUTILS_DEVEL_BRANCH': '""',
    'CT_UCLIBC_NG_DEVEL_BRANCH': '""',
    'CT_LINUX_DEVEL_BRANCH': '""',
    'CT_GCC_DEVEL_REVISION': '"' + os.environ['GCC_REV'] + '"',
    'CT_BINUTILS_DEVEL_REVISION': '"' + os.environ['BINUTILS_REV'] + '"',
    'CT_UCLIBC_NG_DEVEL_REVISION': '"' + os.environ['UCLIBC_REV'] + '"',
    'CT_LINUX_DEVEL_REVISION': '"' + os.environ['LINUX_HEADERS_REV'] + '"',
    'CT_LINUX_DEVEL_URL': '"https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"',
    'CT_PARALLEL_JOBS': os.environ.get('JOBS', '8'),
}
for key, value in values.items():
    text, count = re.subn(r'^' + key + r'=.*$', key + '=' + value, text, flags=re.M)
    if count != 1:
        raise SystemExit('Expected one toolchain setting: ' + key)
path.write_text(text)
