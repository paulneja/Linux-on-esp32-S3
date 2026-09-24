#!/usr/bin/env python3
# Copyright (c) 2026 Paulneja. GPLv3, see LICENSE. https://github.com/paulneja/Linux-on-esp32-S3
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

target = os.environ.get('TARGET', 'esp32s3_16m')

targets_file = Path(__file__).resolve().with_name('targets.json')
with targets_file.open(encoding='utf-8') as f:
    targets = json.load(f)

if target not in targets:
    raise SystemExit('Unknown TARGET=%s (supported: %s)' %
                     (target, ' '.join(targets)))

target_config = targets[target]

profile = target_config['profile']

work = Path(sys.argv[1]).resolve(strict=True)
if work != Path('/work'):
    raise SystemExit('Run inside the isolated build container')
repo = work / 'Linux-on-esp32-S3'
build = work / 'refs/esp32-linux-build/build'
host = build / ('build-buildroot-' + profile) / 'host'
out = work / 'artifacts'
experiment = repo / 'experiments/mmu-poc/out'
firmware = build / 'esp-hosted/esp_hosted_ng/esp/esp_driver/network_adapter/build'
board = repo / 'new-files/board/espressif/esp32s3'

def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def elf_stack_size(path):
    """PT_GNU_STACK p_memsz for a 32-bit little-endian ELF, or 0 if absent."""
    data = path.read_bytes()
    if len(data) < 52 or data[:4] != b'\x7fELF' or data[4] != 1 or data[5] != 1:
        return 0
    phoff, = struct.unpack_from('<I', data, 28)
    phentsize, phnum = struct.unpack_from('<HH', data, 42)
    for n in range(phnum):
        base = phoff + n * phentsize
        if base + 32 > len(data):
            break
        p_type, = struct.unpack_from('<I', data, base)
        if p_type == 0x6474e551:          # PT_GNU_STACK
            p_memsz, = struct.unpack_from('<I', data, base + 20)
            return p_memsz
    return 0

parts = {}
partition_csv = repo / 'new-files/esp-hosted/network_adapter' / target_config['partition_csv']
for line in partition_csv.read_text().splitlines():
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
load = re.search(r'^CONFIG_KERNEL_LOAD_ADDRESS=(0x[0-9a-fA-F]+)$', config, re.M)
assert load, 'kernel has no CONFIG_KERNEL_LOAD_ADDRESS'
expected_load = 0x42000000 + parts['linux']['offset']
assert int(load[1], 16) == expected_load, (
    'kernel is linked at %s but the linux partition starts at %s. Moving the '
    'partition means moving CONFIG_KERNEL_LOAD_ADDRESS with it, or the board '
    'loops in the bootloader before Linux prints anything.'
    % (load[1], hex(expected_load)))
assert 'CONFIG_XTENSA_NOMMU_FORK=y' in config
assert '# CONFIG_XTENSA_VARIANT_MMU is not set' in config
assert not re.search(r'^CONFIG_MMU=[ym]$', config, re.M)
autoconf = (experiment / 'linux-fork/include/generated/autoconf.h').read_text()
assert not re.search(r'^#define CONFIG_MMU\s', autoconf, re.M)
run('python3', repo / 'experiments/mmu-poc/fork/check-kernel-config.py',
    board / 'devkit_c1_16m_linux.config', experiment / 'linux-fork/.config')

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
    # buildroot's board directory carries dropbear host keys that are tracked
    # in a public repository. trim-target.sh removes them so -R generates one
    # per board; this is the check that it actually happened.
    keys = sorted(str(path.relative_to(tree))
                  for path in tree.glob('etc/dropbear/*_host_key'))
    assert not keys, 'image carries dropbear private host keys: %s' % keys
    # A zero PT_GNU_STACK means the program runs on kernel.default_stack_size,
    # and on NOMMU that allocation has no guard page, so an overflow is silent
    # corruption rather than a SIGSEGV. Record which programs rely on it --
    # asserting would be wrong, because shared libraries legitimately have no
    # PT_GNU_STACK and the executable's value is what governs. Only real
    # programs are listed, so the set is small enough to read in a diff.
    stackless = sorted(
        str(path.relative_to(tree))
        for directory in ('bin', 'sbin', 'usr/bin', 'usr/sbin')
        for path in (tree / directory).glob('*')
        if path.is_file() and not path.is_symlink() and '.so' not in path.name
        and path.open('rb').read(4) == b'\x7fELF' and elf_stack_size(path) == 0)
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
    if target_config['has_home']:
        factory_home = Path(directory) / 'home'
        factory_home.mkdir(mode=0o755)
        run(host / 'sbin/mkfs.jffs2', '-l', '-e', '65536', '-U', '-f',
            '--pad=' + str(parts['home']['size']), '-d', factory_home, '-o', out / 'home.jffs2')
    else:
        (out / 'home.jffs2').unlink(missing_ok=True)
    run(host / 'bin/mkcramfs', '-X', '-q', tree, out / 'rootfs.cramfs')
    run(host / 'bin/cramfsck', out / 'rootfs.cramfs')

for name in ('bootloader.bin', 'partition-table.bin', 'network_adapter.bin'):
    shutil.copyfile(work / 'base-images' / name, out / name)

# The binary table is what the board reads; the CSV is what everything here
# computes from. They have disagreed before, and the kernel derives the rootfs
# XIP address from the table, so a mismatch panics with "Cannot open root
# device" rather than failing the build.
table = (out / 'partition-table.bin').read_bytes()
installed = {}
for pos in range(0, len(table) - 31, 32):
    magic, _, _, offset, size, label, _ = struct.unpack_from('<HBBII16sI', table, pos)
    if magic != 0x50AA:
        break
    installed[label.split(b'\0', 1)[0].decode('ascii')] = {'offset': offset, 'size': size}
assert installed == parts, (
    'partition-table.bin does not match %s:\n'
    '  table: %s\n  csv:   %s'
    % (target_config['partition_csv'], installed, parts))
shutil.copyfile(experiment / 'real-bins/xipImage-fork-quiet', out / 'xipImage')
files = {'factory': 'network_adapter.bin', 'etc': 'etc.jffs2', 'linux': 'xipImage',
         'rootfs': 'rootfs.cramfs'}
if target_config['has_home']:
    files['home'] = 'home.jffs2'
for partition, filename in files.items():
    assert (out / filename).stat().st_size <= parts[partition]['size'], (partition, filename)

run('esptool', '--chip', 'esp32s3', 'merge_bin', '-o', out / 'linux-esp32s3-native-full.bin',
    '--flash_mode', 'dio', '--flash_freq', '80m',
    '--flash_size', target_config['flash_size'],
    '--fill-flash-size', target_config['flash_size'],
    '0x0', out / 'bootloader.bin', '0x8000', out / 'partition-table.bin',
    *[arg for partition, filename in files.items() for arg in (hex(parts[partition]['offset']), out / filename)])
full = (out / 'linux-esp32s3-native-full.bin').read_bytes()
assert len(full) == target_config['flash_bytes']
for offset, filename in ((0, 'bootloader.bin'), (0x8000, 'partition-table.bin')):
    payload = (out / filename).read_bytes()
    assert full[offset:offset + len(payload)] == payload, filename
for partition, filename in files.items():
    payload = (out / filename).read_bytes()
    start = parts[partition]['offset']
    assert full[start:start + len(payload)] == payload
if target_config['has_home']:
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
    'default_stack_binaries': stackless,
}
configurations = {
    'toolchain.config': build / 'crosstool-NG/.config',
    'buildroot.config': build / ('build-buildroot-' + profile) / '.config',
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
