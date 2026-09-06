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
           'source_commit': manifest['source_commit'], 'tests': [], 'status': 'running'}
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
        assert expected in output, (text, expected)
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

try:
    console = probe.Console(args.port)
    console.login()
    record('installed-kernel-and-rootfs-hashes', verify_installed)
    checks = [
        ('boot', 'uname -a && id && mount && free && dmesg', None),
        ('shell-policy', 'test -n "$BASH_VERSION" && test "$(readlink /bin/sh)" = busybox && test "$HOME" = /home/root', None),
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
        ('benchmarks', '/usr/bin/dash /usr/share/program-tests/benchmark-suite.sh', 'BENCHMARK COMPLETE'),
        ('kernel-health', 'test "$(cat /proc/sys/kernel/tainted)" = 0 && free', None),
    ]
    for name, text, expected in checks:
        record(name, lambda text=text, expected=expected: command(text, 180, expected))
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
