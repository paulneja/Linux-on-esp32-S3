#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

work = Path(sys.argv[1]).resolve(strict=True)
if work != Path('/work'):
    raise SystemExit('Run inside the isolated build container')
repo = work / 'Linux-on-esp32-S3'
build = work / 'refs/esp32-linux-build/build'
host = build / 'build-buildroot-esp32s3_devkit_c1_16m/host'
out = work / 'artifacts'
experiment = repo / 'experiments/mmu-poc/out'
firmware = build / 'esp-hosted/esp_hosted_ng/esp/esp_driver/network_adapter/build'
board = repo / 'new-files/board/espressif/esp32s3'

def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

parts = {}
for line in (repo / 'new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r').read_text().splitlines():
    if not line or line.startswith('#'): continue
    fields = [field.strip() for field in line.split(',')]
    parts[fields[0]] = {'offset': int(fields[3], 0), 'size': int(fields[4], 0)}

elf = (firmware / 'network_adapter.elf').read_bytes()
shoff, = struct.unpack_from('<I', elf, 0x20)
shsize, shnum = struct.unpack_from('<HH', elf, 0x2e)
sections = [struct.unpack_from('<10I', elf, shoff + n * shsize) for n in range(shnum)]
vectors = None
for _, kind, _, _, offset, size, link, _, _, entsize in sections:
    if kind != 2: continue
    names = elf[sections[link][4]:sections[link][4] + sections[link][5]]
    for pos in range(offset, offset + size, entsize):
        name, address = struct.unpack_from('<II', elf, pos)
        if names[name:].split(b'\0', 1)[0] == b'space_for_vectors': vectors = address
config = (experiment / 'linux-fork/.config').read_text()
match = re.search(r'^CONFIG_VECTORS_ADDR=(0x[0-9a-fA-F]+)$', config, re.M)
assert match and vectors == int(match[1], 16), 'Firmware/kernel vector mismatch'
assert 'CONFIG_XTENSA_NOMMU_FORK=y' in config
assert '# CONFIG_XTENSA_VARIANT_MMU is not set' in config
assert not re.search(r'^CONFIG_MMU=[ym]$', config, re.M)
autoconf = (experiment / 'linux-fork/include/generated/autoconf.h').read_text()
assert not re.search(r'^#define CONFIG_MMU\s', autoconf, re.M)

with tempfile.TemporaryDirectory(prefix='final-rootfs-', dir=work) as directory:
    tree = Path(directory) / 'tree'
    run(host / 'bin/cramfsck', '-x', tree, out / 'rootfs.cramfs')
    passwd = tree / 'etc/passwd'
    entries = passwd.read_text().splitlines()
    roots = [n for n, entry in enumerate(entries) if entry.startswith('root:')]
    assert len(roots) == 1
    fields = entries[roots[0]].split(':')
    fields[-2:] = ['/home/root', '/usr/bin/user-shell']
    entries[roots[0]] = ':'.join(fields)
    passwd.write_text('\n'.join(entries) + '\n')
    assert any(entry.startswith('www-data:') for entry in entries)
    shells = tree / 'etc/shells'
    allowed = shells.read_text().splitlines()
    if '/usr/bin/user-shell' not in allowed:
        shells.write_text('\n'.join(allowed + ['/usr/bin/user-shell']) + '\n')
    assert not (tree / 'etc/wpa_supplicant.conf').exists()
    assert not (tree / 'usr/bin/sqlite3').exists()
    assert not (tree / 'usr/bin/sudo').exists()
    assert not (tree / 'usr/bin/doas').exists()
    assert (tree / 'bin/sh').readlink() == Path('busybox')
    (tree / 'bin/busybox').chmod(0o4755)
    (tree / 'etc/shadow').chmod(0o600)
    for name in ('cron', 'cron/crontabs'):
        (tree / 'etc' / name).mkdir(exist_ok=True)
    (tree / 'etc/cron').chmod(0o711)
    (tree / 'etc/cron/crontabs').chmod(0o700)
    assert not list((tree / 'etc/cron/crontabs').iterdir())
    run(host / 'sbin/mkfs.jffs2', '-l', '-e', '65536', '-U', '-f',
        '--pad=' + str(parts['etc']['size']), '-d', tree / 'etc', '-o', out / 'etc.jffs2')
    factory_home = Path(directory) / 'home'
    factory_home.mkdir(mode=0o755)
    run(host / 'sbin/mkfs.jffs2', '-l', '-e', '65536', '-U', '-f',
        '--pad=' + str(parts['home']['size']), '-d', factory_home, '-o', out / 'home.jffs2')
    run(host / 'bin/mkcramfs', '-X', '-q', tree, out / 'rootfs.cramfs')
    run(host / 'bin/cramfsck', out / 'rootfs.cramfs')

# Reject stale firmware even if a resumed build left old staging files behind.
assert b'paperboard v3:' in (work / 'base-images/network_adapter.bin').read_bytes(), 'stale firmware: Paperboard v3 marker missing'
for name in ('bootloader.bin', 'partition-table.bin', 'network_adapter.bin'):
    shutil.copyfile(work / 'base-images' / name, out / name)
shutil.copyfile(experiment / 'real-bins/xipImage-fork-quiet', out / 'xipImage')
files = {'factory': 'network_adapter.bin', 'etc': 'etc.jffs2', 'linux': 'xipImage',
         'rootfs': 'rootfs.cramfs', 'home': 'home.jffs2'}
for partition, filename in files.items():
    assert (out / filename).stat().st_size <= parts[partition]['size'], (partition, filename)

run('esptool', '--chip', 'esp32s3', 'merge_bin', '-o', out / 'linux-esp32s3-native-full.bin',
    '--flash_mode', 'dio', '--flash_freq', '80m', '--flash_size', '16MB', '--fill-flash-size', '16MB',
    '0x0', out / 'bootloader.bin', '0x8000', out / 'partition-table.bin',
    *[arg for partition, filename in files.items() for arg in (hex(parts[partition]['offset']), out / filename)])
full = (out / 'linux-esp32s3-native-full.bin').read_bytes()
assert len(full) == 16 * 1024 * 1024
for offset, filename in ((0, 'bootloader.bin'), (0x8000, 'partition-table.bin')):
    payload = (out / filename).read_bytes()
    assert full[offset:offset + len(payload)] == payload, filename
for partition, filename in files.items():
    payload = (out / filename).read_bytes()
    start = parts[partition]['offset']
    assert full[start:start + len(payload)] == payload
home = full[parts['home']['offset']:parts['home']['offset'] + parts['home']['size']]
marker = home[:12]
assert marker[:4] == b'\x85\x19\x03\x20', 'factory /home is not a formatted jffs2'
assert len(home) % 65536 == 0
for start in range(0, len(home), 65536):
    assert home[start:start + 12] == marker, hex(start)
    assert home[start + 12:start + 65536] == b'\xff' * (65536 - 12), hex(start)
manifest = json.loads((out / 'rootfs.json').read_text())
manifest.update(image_bytes=(out / 'rootfs.cramfs').stat().st_size,
                free_bytes=parts['rootfs']['size'] - (out / 'rootfs.cramfs').stat().st_size,
                sha256=sha(out / 'rootfs.cramfs'))
(out / 'rootfs.json').write_text(json.dumps(manifest, indent=2) + '\n')
checksums = {name: sha(out / name) for name in ['bootloader.bin', 'partition-table.bin', *files.values(), 'linux-esp32s3-native-full.bin']}
(out / 'SHA256SUMS').write_text(''.join(value + '  ' + name + '\n' for name, value in checksums.items()))
inventory = {
    'source_commit': (work / 'source-commit.txt').read_text().strip(),
    'container_image_id': (work / 'container-image-id.txt').read_text().strip(),
    'vectors_addr': hex(vectors), 'partitions': parts, 'sha256': checksums,
    'build_method': 'Clean sources and Linux toolchain; no prebuilt project images or experiment binaries',
    'board_verification': 'pending',
}
configurations = {
    'toolchain.config': build / 'crosstool-NG/.config',
    'buildroot.config': build / 'build-buildroot-esp32s3_devkit_c1_16m/.config',
    'firmware.config': firmware.parent / 'sdkconfig',
    'kernel.config': experiment / 'linux-fork/.config',
    'busybox.config': experiment / 'programs/busybox-netcat/.config',
}
(out / 'configs').mkdir(exist_ok=True)
inventory['configuration_sha256'] = {}
for name, path in configurations.items():
    shutil.copyfile(path, out / 'configs' / name)
    inventory['configuration_sha256'][name] = sha(path)
(out / 'build-manifest.json').write_text(json.dumps(inventory, indent=2) + '\n')
shutil.copyfile(repo / 'build/sources.lock', out / 'sources.lock')
run('python3', repo / 'experiments/mmu-poc/programs/test-cron-image.py', out / 'rootfs.cramfs')
print(json.dumps(inventory, indent=2))
