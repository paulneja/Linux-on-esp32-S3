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
patches = Path(__file__).resolve().parent.parent / 'new-files/toolchain-patches'
for pattern, line in (
        (r'^CT_UCLIBC_NG_PATCH_GLOBAL=y$', '# CT_UCLIBC_NG_PATCH_GLOBAL is not set'),
        (r'^# CT_UCLIBC_NG_PATCH_BUNDLED_LOCAL is not set$', 'CT_UCLIBC_NG_PATCH_BUNDLED_LOCAL=y'),
        (r'^CT_UCLIBC_NG_PATCH_ORDER=.*$', 'CT_UCLIBC_NG_PATCH_ORDER="bundled,local"')):
    text, count = re.subn(pattern, line, text, flags=re.M)
    if count != 1:
        raise SystemExit('Expected one toolchain setting: ' + line)
text += f'CT_PATCH_USE_LOCAL=y\nCT_LOCAL_PATCH_DIR="{patches}"\n'
path.write_text(text)
