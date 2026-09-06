#!/usr/bin/env python3
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

repo = Path(__file__).resolve().parents[3]
source = repo / 'new-files/board/espressif/esp32s3/rootfs_overlay/usr/sbin/home-init'
with tempfile.TemporaryDirectory(prefix='esp32-init-test-') as directory:
    root = Path(directory)
    for name in ('home', 'etc', 'share', 'bin'):
        (root / name).mkdir()
    (root / 'etc/shells').write_text('/bin/sh\n')
    (root / 'share/README.txt').write_text('Welcome\n')
    seed = root / 'share/www.tar.gz'
    with tarfile.open(seed, 'w:gz') as archive:
        for name in ('www/index.html', 'www/cgi-bin/status'):
            payload = b'test seed\n'
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    good_seed = seed.read_bytes()
    real_tar = shutil.which('tar')
    for name, body in {
        'id': 'echo 0',
        'awk': 'exit 0',
        'chown': 'exit 0',
        'web-server': 'exit 0',
        'tar': f'case "$1" in *z*) exit 99;; esac\nexec "{real_tar}" "$@"',
    }.items():
        target = root / 'bin' / name
        target.write_text('#!/bin/sh\n' + body + '\n')
        target.chmod(0o755)
    text = source.read_text()
    for old, new in (
        ('/usr/share/esp32-home', str(root / 'share')),
        ('/usr/sbin/web-server', str(root / 'bin/web-server')),
        ('/etc/shells', str(root / 'etc/shells')),
        ('/home', str(root / 'home')),
    ):
        text = text.replace(old, new)
    script = root / 'init.sh'
    script.write_text(text)
    env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH']}
    seed.write_bytes(b'invalid gzip')
    result = subprocess.run(['sh', script], env=env, capture_output=True)
    assert result.returncode != 0
    assert not (root / 'home/www').exists()
    assert not list((root / 'home').glob('.www-seed.*'))
    seed.write_bytes(good_seed)
    subprocess.run(['sh', script], env=env, check=True)
    index = root / 'home/www/index.html'
    assert index.read_bytes() == b'test seed\n'
    assert (root / 'home/www/cgi-bin/status').stat().st_mode & 0o777 == 0o755
    assert (root / 'home/root/README.txt').stat().st_mode & 0o777 == 0o600
    index.write_text('user changes\n')
    subprocess.run(['sh', script], env=env, check=True)
    assert index.read_text() == 'user changes\n'
    assert not list((root / 'home').glob('.www-seed.*'))
    assert (root / 'etc/shells').read_text().count('/usr/bin/user-shell') == 1
print('PASS: plain tar, fresh seed, failed gzip cleanup, retry, modes, existing web preserved')
