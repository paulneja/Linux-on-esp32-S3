#!/usr/bin/env python3
"""Inspect the packed image and exercise inetd migration in isolated fixtures."""
import os
from pathlib import Path
import stat
import struct
import sys
import subprocess
import tarfile
import tempfile

here = Path(__file__).resolve().parent
repo = here.parents[2]
board = repo / 'new-files/board/espressif/esp32s3'
host = repo.parent / 'refs/esp32-linux-build/build/build-buildroot-esp32s3_devkit_c1_16m/host'
image = Path(sys.argv[1]) if len(sys.argv) > 1 else here.parent / 'out/programs/rootfs-home-users-ready.cramfs'
# cramfsck deliberately does not restore SUID when extracting as non-root.
# Inspect the packed inode, not the safely downgraded host copy.
data = image.read_bytes()
assert struct.unpack_from('<I', data)[0] == 0x28CD3D45
inode = struct.unpack_from('<III', data, 64)
for part in ('bin', 'busybox'):
    offset = (inode[2] >> 6) * 4
    end = offset + (inode[1] & 0xFFFFFF)
    while offset < end:
        child = struct.unpack_from('<III', data, offset)
        length = (child[2] & 63) * 4
        name = data[offset+12:offset+12+length].rstrip(b'\0').decode()
        if name == part:
            inode = child
            break
        offset += 12 + length
    else:
        raise AssertionError('Missing packed inode: ' + part)
assert inode[0] >> 16 == 0
assert inode[0] & 0o7777 == 0o4755
with tempfile.TemporaryDirectory(prefix='home-users-check-') as tmp:
    tmp = Path(tmp)
    tree = tmp / 'tree'
    subprocess.run([host / 'bin/cramfsck', '-x', tree, image], check=True)
    assert not (tree / 'www').exists()
    assert (tree / 'bin/sh').readlink() == Path('busybox')
    assert (tree / 'usr/bin/dtach').is_file()
    assert (tree / 'bin/stat').readlink() == Path('busybox')
    assert not (tree / 'usr/bin/sudo').exists()
    assert not (tree / 'usr/bin/doas').exists()
    assert (tree / 'usr/share/esp32-home/README.txt').read_text().splitlines()[0] == 'Hi, Welcome to Linux on esp32-S3 !!!'
    with tarfile.open(tree / 'usr/share/esp32-home/www.tar.gz') as seed:
        for name in ('www/index.html', 'www/cgi-bin/status'):
            assert seed.extractfile(name).read() == (board / 'home-defaults' / name).read_bytes()
        assert all(not m.issym() and not m.islnk() and '..' not in Path(m.name).parts for m in seed)
    print('PASS: /www removed; identical web seed; welcome README; SUID BusyBox; dtach; /bin/sh unchanged')

    etc = tmp / 'etc'
    etc.mkdir()
    fakebin = tmp / 'bin'
    fakebin.mkdir()
    for name, script in {
        'id': '#!/bin/sh\nif [ "$1" = -u ]; then if [ "$#" = 1 ]; then echo 0; else echo 33; fi; fi\n',
        'killall': '#!/bin/sh\nexit 0\n',
    }.items():
        path = fakebin / name
        path.write_text(script)
        path.chmod(0o755)
    web = tmp / 'web-server'
    web.write_text((board / 'rootfs_overlay/usr/sbin/web-server').read_text().replace('/etc/', str(etc) + '/'))
    env = {**os.environ, 'PATH': str(fakebin) + ':' + os.environ['PATH']}
    conf = etc / 'inetd.conf'
    for prefix in ('#', ''):
        original = prefix + '80\tstream\ttcp\tnowait\troot\t/usr/sbin/httpd\thttpd -i -h /www\n'
        conf.write_text(original)
        conf.chmod(0o640)
        subprocess.run(['sh', web, 'migrate'], env=env, check=True)
        expected = original.replace('\troot\t', '\twww-data\t').replace(' -h /www', ' -h /home/www')
        assert conf.read_text() == expected
        assert stat.S_IMODE(conf.stat().st_mode) == 0o640
        subprocess.run(['sh', web, 'migrate'], env=env, check=True)
        assert conf.read_text() == expected
    conf.write_text('80 stream tcp nowait root /usr/bin/custom custom\n')
    original = conf.read_bytes()
    result = subprocess.run(['sh', web, 'migrate'], env=env, capture_output=True)
    assert result.returncode != 0 and conf.read_bytes() == original
    print('PASS: enabled/disabled state preserved, www-data migration, modes, repeat run, custom-service refusal')
