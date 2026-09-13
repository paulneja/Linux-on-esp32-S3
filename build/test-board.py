#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
import os
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
results['test_files_sha256'] = {
    str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in [exp / 'serial-probe.py', *[
        exp / 'programs' / (name + '.py')
        for name in ('test-home-users-board', 'test-cron-board', 'test-com-reconnect', 'test-home-reboot')
    ]]
}
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

def quiesce():
    command('echo -500 > /proc/self/oom_score_adj && cat /proc/self/oom_score_adj',
            30, '-500')
    command('killall udhcpc 2>/dev/null; sleep 1; pidof udhcpc > /dev/null && echo DHCP_ALIVE'
            ' || echo DHCP_STOPPED', 60, 'DHCP_STOPPED')


def record_memory():
    # Phase 0 of the external-storage work turns on how much RAM is left once a
    # driver stack is added, and on NOMMU the number that decides an allocation
    # is contiguous pages, not MemAvailable -- MemAvailable counts reclaimable
    # cache the allocator cannot hand to a fork. So capture buddyinfo too, on
    # the clean image, while there is still a clean image to measure.
    meminfo = command('cat /proc/meminfo', 60, 'MemTotal:')
    buddyinfo = command('cat /proc/buddyinfo; echo BUDDY_DONE', 60, 'BUDDY_DONE')
    (args.output / 'memory-baseline.txt').write_text(meminfo + '\n' + buddyinfo + '\n')
    values = {key: int(size) for key, size in re.findall(r'(?m)^(\w+):\s+(\d+) kB$', meminfo)}
    for key in ('MemTotal', 'MemFree', 'MemAvailable'):
        assert values.get(key), (key, meminfo)
    baseline = {'meminfo_kb': values}
    zone = re.search(r'(?m)^Node \d+, zone\s+\S+((?:\s+\d+)+)\s*$', buddyinfo)
    if zone:
        orders = [int(count) for count in zone.group(1).split()]
        largest = max((order for order, count in enumerate(orders) if count), default=-1)
        baseline['free_pages_by_order'] = orders
        baseline['largest_free_block_kb'] = (4 << largest) if largest >= 0 else 0
    else:
        print('  note: /proc/buddyinfo gave nothing parseable; raw text kept', flush=True)
    results['memory_baseline'] = baseline
    print('  baseline: MemFree {} kB, MemAvailable {} kB, largest free block {} kB'.format(
        values['MemFree'], values['MemAvailable'],
        baseline.get('largest_free_block_kb', 'unknown')), flush=True)


def record_memory_after():
    """The same numbers as the baseline, at the end of the run.

    A leak in the fork backend, or a service that grows, shows up as a gap
    between these two and nowhere else: every individual test passes. The
    tolerance is loose on purpose -- page cache legitimately grows -- but a
    real leak of hundreds of kilobytes will not fit inside it.
    """
    meminfo = command('cat /proc/meminfo', 60, 'MemTotal:')
    buddyinfo = command('cat /proc/buddyinfo; echo BUDDY_DONE', 60, 'BUDDY_DONE')
    (args.output / 'memory-final.txt').write_text(meminfo + '\n' + buddyinfo + '\n')
    values = {key: int(size) for key, size in re.findall(r'(?m)^(\w+):\s+(\d+) kB$', meminfo)}
    final = {'meminfo_kb': values}
    results['memory_final'] = final
    baseline = results['memory_baseline']['meminfo_kb']
    shadow = values.get('ForkShadow')
    assert shadow == 0, (
        'ForkShadow is %s kB with no forked children left: the backend kept '
        'backup pages that nothing owns' % shadow)
    lost = baseline['MemAvailable'] - values['MemAvailable']
    print('  final: MemAvailable {} kB ({:+d} kB against the baseline)'.format(
        values['MemAvailable'], -lost), flush=True)
    assert lost < 512, (
        'MemAvailable fell %d kB across the suite, from %d to %d. Individual '
        'tests can all pass while something leaks; this is the check for that.'
        % (lost, baseline['MemAvailable'], values['MemAvailable']))


def fork_exec_cycles():
    """Five hundred fork+exec rounds, then assert nothing was kept.

    The longest fork loop elsewhere is 24 iterations. A backend that leaks one
    page per fork hides easily at that scale and not at all at this one.
    """
    before = command("grep -E '^(MemAvailable|ForkShadow)' /proc/meminfo", 60, 'MemAvailable')
    command('i=0; while [ $i -lt 500 ]; do /bin/true; i=$((i+1)); done; echo CYCLES_DONE',
            300, 'CYCLES_DONE')
    after = command("grep -E '^(MemAvailable|ForkShadow)' /proc/meminfo", 60, 'MemAvailable')
    grab = lambda text, key: int(re.search(r'(?m)^' + key + r':\s+(\d+) kB', text).group(1))
    assert grab(after, 'ForkShadow') == 0, 'ForkShadow left set after 500 fork+exec rounds'
    lost = grab(before, 'MemAvailable') - grab(after, 'MemAvailable')
    print('  500 rounds cost {:+d} kB'.format(-lost), flush=True)
    assert lost < 256, '500 fork+exec rounds lost %d kB' % lost


def jffs2_write_timing():
    """How long a write to /home takes, recorded rather than asserted.

    build/verification/2026-09-06-jffs2-erase.md measured writes stalling for
    minutes when blocks had to be reclaimed. Nothing has watched the number
    since; this puts it in results.json every run.
    """
    output = command('time_start=$(cut -d. -f1 /proc/uptime); '
                     'dd if=/dev/zero of=/home/.write-probe bs=4096 count=64 2>/dev/null; '
                     'sync; time_end=$(cut -d. -f1 /proc/uptime); '
                     'rm -f /home/.write-probe; '
                     'echo WRITE_SECONDS=$((time_end - time_start))', 300, 'WRITE_SECONDS=')
    seconds = int(re.search(r'WRITE_SECONDS=(\d+)', output).group(1))
    results['jffs2_write_256k_seconds'] = seconds
    print('  256 KiB to /home took {} s'.format(seconds), flush=True)


def benchmarks():
    console.port.write(b'exec /usr/bin/dash -c \'trap "sleep 1" EXIT; . /usr/share/program-tests/benchmark-suite.sh\'\n')
    output, _ = console.until(rb'buildroot login: ?', 180)
    text = output.decode(errors='replace')
    print(text, flush=True)
    (args.output / 'benchmarks.log').write_text(text)
    console.login()
    if not re.search(r'(?m)^BENCHMARK COMPLETE$', text):
        if re.search(r'oom-kill:|Out of memory: Killed', text):
            killer = re.search(r'(?m)^\[[^]]*\] (\S+) invoked oom-killer', text)
            raise AssertionError(
                'a measured program was killed by the OOM killer'
                + (f', triggered by {killer.group(1)}' if killer else '')
                + '; the suite retries a killed run, so this means it happened repeatedly.'
                  ' Full transcript in benchmarks.log')
        raise AssertionError(text)
    for retry in re.findall(r'(?m)^BENCH RETRY .*$', text):
        print('  note:', retry, flush=True)
    command('test -n "$BASH_VERSION"')

try:
    console = probe.Console(args.port)
    if args.reset_from_bootloader:
        record('reset-and-boot', boot_from_flash)
    console.login()
    record('quiesce-background-forks', quiesce)
    record('memory-baseline', record_memory)
    record('installed-kernel-and-rootfs-hashes', verify_installed)
    checks = [
        ('boot', 'uname -a && id && mount && free && dmesg',
         ('6.11.0-forkbank', 'Mounted root (cramfs filesystem) readonly')),
        # The self-test no longer runs on every boot (esp32s3_rsa.selftest=1
        # brings it back). What matters is that the driver came up and
        # registered, which is what the crypto API reports.
        ('hardware-rsa-registered', 'grep -A2 "^name *: rsa$" /proc/crypto | grep -B2 esp32s3 || grep -c rsa-esp32s3 /proc/crypto',
         'esp32s3'),
        ('no-driver-timeout', '! dmesg | grep -q "accelerator did not report ready" && echo RSA_OK', 'RSA_OK'),
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
        # The console switch: default quiet, verbose raises the level for real,
        # and it goes back. Left as it was found, which is the default.
        ('bootlog-default-is-quiet', 'bootlog status', 'quiet (the default)'),
        ('bootlog-verbose-raises-the-level',
         'bootlog verbose >/dev/null && cut -f1 /proc/sys/kernel/printk', '8'),
        ('bootlog-quiet-restores-it',
         'bootlog quiet >/dev/null && cut -f1 /proc/sys/kernel/printk', '4'),
    ]
    for name, text, expected in checks:
        record(name, lambda text=text, expected=expected: command(text, 180, expected))
    record('benchmarks-lightweight-launcher', benchmarks)
    record('fork-exec-cycles', fork_exec_cycles)
    record('jffs2-write-timing', jffs2_write_timing)
    record('kernel-health', lambda: command('test "$(cat /proc/sys/kernel/tainted)" = 0 && ! dmesg | grep -E "Out of memory:|Kernel panic|BUG:|Oops:" && free'))
    record('memory-final', record_memory_after)
    console.close()
    console = None
    for name in ('test-home-users-board', 'test-cron-board', 'test-com-reconnect', 'test-home-reboot'):
        record(name, lambda name=name: external(name))
    console = probe.Console(args.port)
    console.login()
    record('final-kernel-health', lambda: command('test "$(cat /proc/sys/kernel/tainted)" = 0 && ! dmesg | grep -E "Out of memory:|Kernel panic|BUG:|Oops:" && free'))
    results['status'] = 'pass'
    results['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    manifest['board_verification'] = {
        'status': 'pass', 'image_sha256': results['image_sha256'],
        'finished_utc': results['finished_utc'],
        'report': os.path.relpath(args.output.resolve() / 'results.json', args.artifacts.resolve()),
        'test_runner_sha256': results['test_runner_sha256'],
        'scope': 'Local COM, memory, programs, users, loopback network, cron and persistence; no external WiFi test',
    }
    (args.artifacts / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
except BaseException:
    results['status'] = 'fail'
    raise
finally:
    if console is not None:
        console.close()
    (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
