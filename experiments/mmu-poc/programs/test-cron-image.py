#!/usr/bin/env python3
"""Check cron integration without extracting SUID binaries as root."""
from pathlib import Path
import subprocess
import sys
import tempfile

here = Path(__file__).resolve().parent
repo = here.parents[2]
image = Path(sys.argv[1])
config = (repo / 'new-files/board/espressif/esp32s3/busybox.config').read_text().splitlines()
for option in ('CONFIG_CROND=y', 'CONFIG_CRONTAB=y',
               'CONFIG_FEATURE_CROND_SPECIAL_TIMES=y', 'CONFIG_FEATURE_CROND_D=y',
               'CONFIG_FEATURE_PIDFILE=y', 'CONFIG_PID_FILE_PATH="/var/run"',
               'CONFIG_FEATURE_CROND_DIR="/etc/cron"'):
    assert option in config, f'Missing cron prerequisite: {option}'
host = repo.parent / 'refs/esp32-linux-build/build/build-buildroot-esp32s3_devkit_c1_16m/host'
subprocess.run([sys.executable, here / 'test-home-users.py', image], check=True)
with tempfile.TemporaryDirectory(prefix='cron-image-check-') as work:
    tree = Path(work) / 'tree'
    subprocess.run([host / 'bin/cramfsck', '-x', tree, image], check=True)
    for directory, name in (('usr/bin', 'crontab'), ('usr/sbin', 'crond')):
        assert (tree / directory / name).readlink() == Path('../../bin/busybox')
    assert not (tree / 'usr/bin/sqlite3').exists()
    assert not (tree / 'usr/bin/sqlite3').is_symlink()
    for path in ('usr/sbin/cron-server', 'usr/sbin/cron-setup', 'usr/share/esp32-cron/S50crond'):
        assert (tree / path).stat().st_mode & 0o111
    seed = (tree / 'usr/share/esp32-cron/S50crond').read_bytes()
    assert seed == (repo / 'new-files/board/espressif/esp32s3/rootfs_overlay/etc/init.d/S50crond').read_bytes()
    print('PASS: cron links, executable tools, init seed; no SQLite')
