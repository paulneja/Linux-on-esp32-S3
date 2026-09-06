#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('profiles', here / 'image-profiles.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
for name, selected in [('rootfs-all', set(p.PACKAGES)),
                       ('rootfs-python-automatizacion', {'dash', 'make', 'micropython'}),
                       ('rootfs-bash-red', {'bash', 'dash', 'make', 'socat'}),
                       ('rootfs-custom', {'bash', 'dash', 'micropython'})]:
    image = p.PROGRAMS / (name + '.cramfs')
    manifest = json.loads(image.with_suffix('.json').read_text())
    assert set(manifest['programs']) == selected
    assert image.stat().st_size == manifest['image_bytes'] <= p.LIMIT
    with tempfile.TemporaryDirectory(prefix='profile-check-') as tmp:
        tree = Path(tmp) / 'tree'
        subprocess.run([str(p.HOST / 'bin/cramfsck'), '-x', str(tree), str(image)], check=True)
        for program, package in p.PACKAGES.items():
            assert (tree / package['binary']).exists() == (program in selected)
        assert (tree / 'bin/sh').readlink() == Path('busybox')
        assert (tree / 'bin/nc').readlink() == Path('busybox')
        for path in ('usr/bin/user-shell', 'usr/bin/programbench', 'usr/bin/jobq', 'usr/bin/process-test',
                     'usr/sbin/ble-wifi-setup', 'usr/lib/libfork.so.0'):
            assert (tree / path).exists(), path
    r = subprocess.run(['python3', str(here / 'image-profiles.py'), 'build', '--output', str(image)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and 'Output exists' in r.stderr
    print('PASS:', name, 'selected files, core services, partition size, overwrite refusal')
bad = subprocess.run(['python3', str(here / 'image-profiles.py'), 'plan', '--programs', 'neovim'],
                     capture_output=True)
assert bad.returncode == 2
print('PASS: unconfigured programs rejected; nothing compiled/flashed')
