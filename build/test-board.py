#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description='Test an explicitly flashed image over COM; never flashes.')
parser.add_argument('port')
parser.add_argument('artifacts', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--reset-from-bootloader', action='store_true',
                    help='Reset via RTS after a flash with --after no-reset; capture startup.')
args = parser.parse_args()
repo = Path(__file__).resolve().parent.parent
exp = repo / 'experiments/mmu-poc'
manifest = json.loads((args.artifacts / 'build-manifest.json').read_text())
for name, expected in manifest['sha256'].items():
    assert hashlib.sha256((args.artifacts / name).read_bytes()).hexdigest() == expected, name
args.output.mkdir(parents=True, exist_ok=False)
spec = importlib.util.spec_from_file_location('probe', exp / 'serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
results = {'image_sha256': manifest['sha256']['linux-esp32s3-native-full.bin'],
           'source_commit': manifest['source_commit'],
           'test_runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'tests': [], 'status': 'running'}
console = None

def record(name, operation):
    started = time.monotonic()
    print('START:', name, flush=True)
    item = {'name': name, 'status': 'running'}
    results['tests'].append(item)
    try:
        operation()
        item['status'] = 'pass'
        print('PASS:', name, flush=True)
    except BaseException:
        item['status'] = 'fail'
        raise
    finally:
        item['seconds'] = round(time.monotonic() - started, 3)
        (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')

def command(text, seconds=60, expected=None):
    output = console.command(text, seconds)
    print(output, flush=True)
    with (args.output / 'commands.log').open('a') as log:
        log.write(output + '\n')
    if expected is not None:
        for marker in expected if isinstance(expected, tuple) else (expected,):
            assert marker in output, (text, marker)
    return output

def verify_installed():
    table = command('cat /proc/mtd')
    for label, filename in [('linux', 'xipImage'), ('rootfs', 'rootfs.cramfs')]:
        device = re.search(r'(?m)^mtd([0-9]+):[^\n]*"' + label + r'"$', table)
        assert device, (label, table)
        size = (args.artifacts / filename).stat().st_size
        output = command(f'head -c {size} /dev/mtdblock{device.group(1)} | sha256sum', 180)
        assert re.search(r'(?m)^' + manifest['sha256'][filename] + r'\s', output), filename

def external(name):
    with (args.output / (name + '.log')).open('w') as log:
        subprocess.run([sys.executable, str(exp / 'programs' / (name + '.py')), args.port],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)

def boot_from_flash():
    console.port.rts = True
    time.sleep(0.1)
    console.port.rts = False
    data = b''
    deadline = time.monotonic() + 240
    with (args.output / 'boot.log').open('wb') as log:
        while time.monotonic() < deadline:
            chunk = console.port.read(max(1, console.port.in_waiting))
            if not chunk:
                continue
            log.write(chunk)
            log.flush()
            print(chunk.decode(errors='replace'), end='', flush=True)
            data = (data + chunk)[-256:]
            if re.search(rb'buildroot login: ?', data):
                return
    raise RuntimeError('No login within 240 seconds; complete output saved in boot.log')

def benchmarks():
    console.port.write(b'exec /usr/bin/dash -c \'trap "sleep 1" EXIT; . /usr/share/program-tests/benchmark-suite.sh\'\n')
    output, _ = console.until(rb'buildroot login: ?', 180)
    text = output.decode(errors='replace')
    print(text, flush=True)
    (args.output / 'benchmarks.log').write_text(text)
    console.login()
    assert re.search(r'(?m)^BENCHMARK COMPLETE$', text), text
    command('test -n "$BASH_VERSION"')

try:
    console = probe.Console(args.port)
    if args.reset_from_bootloader:
        record('reset-and-boot', boot_from_flash)
    console.login()
    record('installed-kernel-and-rootfs-hashes', verify_installed)
    checks = [
        ('boot', 'uname -a && id && mount && free && dmesg',
         ('6.11.0-forkbank', 'esp32s3-rsa: selftest 512-bit PASS',
          'esp32s3-rsa: selftest 2048-bit PASS', 'Mounted root (cramfs filesystem) readonly')),
        ('shell-policy', 'test -n "$BASH_VERSION" && test "$(readlink /bin/sh)" = busybox && test "$HOME" = /home/root', None),
        ('first-boot-home', 'test -f /home/root/README.txt && test "$(stat -c %a /home/root)" = 700 && test -f /home/www/index.html && test -x /home/www/cgi-bin/status && test ! -e /www && set -- /home/.www-seed.* && test ! -e "$1"', None),
        ('excluded-programs', 'test ! -e /usr/bin/sqlite3 && test ! -e /usr/bin/sudo && test ! -e /usr/bin/doas && test ! -e /usr/bin/nvim && test ! -e /usr/bin/python3', None),
        ('mmu-executable-remap', 'mmu-run self-test', 'PASS: executable A -> B -> A -> B'),
        ('mmu-fibonacci', 'mmu-run run /usr/share/mmu/fib.elf 20', 'Result: 6765'),
        ('fork-static', 'fork-test', 'PASS: fork suite 5/5'),
        ('fork-dynamic', 'fork-test-dynamic', 'PASS: fork suite 5/5'),
        ('atfork', 'atfork-test', 'PASS'),
        ('process-compatibility', 'process-test', 'PASS: process suite 10/10'),
        ('bash', '/bin/bash /usr/share/program-tests/bash-test.sh', 'PASS'),
        ('dash', '/usr/bin/dash /usr/share/fork-real/dash-test.sh', 'PASS'),
        ('make', '/usr/bin/dash /usr/share/fork-real/make-test.sh', 'PASS'),
        ('micropython', '/usr/bin/micropython /usr/share/program-tests/micropython-test.py', 'PASS'),
        ('network-tools', '/usr/bin/dash /usr/share/program-tests/network-tools-test.sh', 'PASS'),
        ('hush-login', '/usr/bin/dash /usr/share/program-tests/hush-login-test.sh', 'PASS'),
        ('jobq', '/usr/bin/dash /usr/share/program-tests/jobq-test.sh', 'PASS'),
    ]
    for name, text, expected in checks:
        record(name, lambda text=text, expected=expected: command(text, 180, expected))
    record('benchmarks-lightweight-launcher', benchmarks)
    record('kernel-health', lambda: command('test "$(cat /proc/sys/kernel/tainted)" = 0 && ! dmesg | grep -E "Out of memory:|Kernel panic|BUG:|Oops:" && free'))
    console.close()
    console = None
    for name in ('test-home-users-board', 'test-cron-board', 'test-com-reconnect', 'test-home-reboot'):
        record(name, lambda name=name: external(name))
    results['status'] = 'pass'
except BaseException:
    results['status'] = 'fail'
    raise
finally:
    if console is not None:
        console.close()
    (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
