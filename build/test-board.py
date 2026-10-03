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
parser.add_argument('port', nargs='?')
parser.add_argument('artifacts', nargs='?', type=Path)
parser.add_argument('--output', type=Path)
parser.add_argument('--plan-target', choices=('esp32s3_16m', 'esp32s3_8m', 'xiao_esp32s3_8m', 'xiao_esp32s3_8m_sd'))
parser.add_argument('--reset-from-bootloader', action='store_true',
                    help='Reset via RTS after a flash with --after no-reset; capture startup.')
args = parser.parse_args()
repo = Path(__file__).resolve().parent.parent

TARGETS_8M = {'esp32s3_8m', 'xiao_esp32s3_8m', 'xiao_esp32s3_8m_sd'}
XIAO_TARGETS = {'xiao_esp32s3_8m', 'xiao_esp32s3_8m_sd'}
SD_TARGET = 'xiao_esp32s3_8m_sd'
N16_ONLY_TESTS = {
    'shell-policy', 'first-boot-home', 'mmu-executable-remap', 'mmu-fibonacci',
    'fork-static', 'fork-dynamic', 'atfork', 'process-compatibility', 'bash',
    'dash', 'make', 'micropython', 'network-tools', 'hush-login', 'jobq',
    'benchmarks-lightweight-launcher', 'fork-exec-cycles',
    'test-home-users-board', 'test-cron-board', 'test-home-reboot',
}

def planned_counts(target):
    # run.sh always invokes the suite with --reset-from-bootloader. Keep the
    # number comparable with the historical N16R8 "36 tests" banner.
    base = 36
    if target == 'esp32s3_16m':
        return base, 0, 5

    # 8 MB targets add persistence, USB-console and target-aware /home checks.
    # One /home timing check is always skipped:
    # SD timing when flash /home is active, or JFFS2 timing when SD is mounted.
    extra = 4
    return base + extra, len(N16_ONLY_TESTS) + 1, 5

if args.plan_target:
    total, skipped, minutes = planned_counts(args.plan_target)
    print(f'{total} checks ({total - skipped} run, {skipped} skipped), about {minutes} minutes')
    raise SystemExit(0)

if args.port is None or args.artifacts is None or args.output is None:
    parser.error('port, artifacts and --output are required unless --plan-target is used')

def selected_target():
    # A build records its target next to artifacts. Prefer that over .target so
    # a later menu selection cannot change the meaning of an older image.
    build_target = args.artifacts.parent / 'target'
    if build_target.is_file():
        return build_target.read_text().strip()
    saved = repo / '.target'
    if saved.is_file():
        return saved.read_text().strip()
    return 'esp32s3_16m'

target = selected_target()
if target not in {'esp32s3_16m', *TARGETS_8M}:
    raise RuntimeError(f'unknown target: {target}')

exp = repo / 'experiments/mmu-poc'
manifest = json.loads((args.artifacts / 'build-manifest.json').read_text())
for name, expected in manifest['sha256'].items():
    assert hashlib.sha256((args.artifacts / name).read_bytes()).hexdigest() == expected, name
args.output.mkdir(parents=True, exist_ok=False)
spec = importlib.util.spec_from_file_location('probe', exp / 'serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
results = {'target': target,
           'image_sha256': manifest['sha256']['linux-esp32s3-native-full.bin'],
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

def skip(name, reason):
    print('SKIP:', name, '--', reason, flush=True)
    results['tests'].append({'name': name, 'status': 'skipped', 'reason': reason, 'seconds': 0.0})
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
    if target == 'esp32s3_16m':
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
    count = 64 if target == 'esp32s3_16m' else 16
    kib = count * 4

    output = command(
        'time_start=$(cut -d. -f1 /proc/uptime); '
        'dd if=/dev/zero of=/home/.write-probe bs=4096 count={} 2>/dev/null; '
        'sync; time_end=$(cut -d. -f1 /proc/uptime); '
        'rm -f /home/.write-probe; '
        'echo WRITE_SECONDS=$((time_end - time_start))'.format(count),
        300, 'WRITE_SECONDS=')

    seconds = int(re.search(r'WRITE_SECONDS=(\d+)', output).group(1))
    results['jffs2_write_{}k_seconds'.format(kib)] = seconds
    print('  {} KiB to /home took {} s'.format(kib, seconds), flush=True)

def wait_for_login(seconds=240):
    data = b''
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        chunk = console.port.read(max(1, console.port.in_waiting))
        if not chunk:
            continue
        print(chunk.decode(errors='replace'), end='', flush=True)
        data = (data + chunk)[-512:]
        if re.search(rb'buildroot login: ?', data):
            return
    raise RuntimeError('No login after reboot')


def etc_persistence():
    marker = 'board-test-etc-persistence'
    command(f"printf '%s\\n' {marker} > /etc/.board-test-persist && sync && cat /etc/.board-test-persist",
            60, marker)
    console.port.write(b'sync; reboot\n')
    wait_for_login()
    console.login()
    command('cat /etc/.board-test-persist', 60, marker)
    command('rm -f /etc/.board-test-persist && sync')


def usb_console_getty():
    output = command("ps | grep '[g]etty.*ttyGS3' || true; echo GETTY_CHECK_DONE", 60,
                     'GETTY_CHECK_DONE')
    running = bool(re.search(r'getty[^\n]*ttyGS3|ttyGS3[^\n]*getty', output))
    expected = target in XIAO_TARGETS
    assert running == expected, 'ttyGS3 getty is {} but target {} expects {}'.format(
        'on' if running else 'off', target, 'on' if expected else 'off')


def sd_home():
    output = command("awk '$2==\"/home\" {print $1, $2, $3, $4}' /proc/mounts", 60,
                     '/dev/mmcblk0p1 /home ext2')
    line = next(line for line in output.splitlines() if '/dev/mmcblk0p1 /home ext2' in line)
    fields = line.split()
    assert 'rw' in fields[3].split(','), line
    command('test -f /home/README.txt && echo HOME_INIT_OK', 60, 'HOME_INIT_OK')
    token = 'sd-persist-{}'.format(int(time.time()))
    command(f"printf '%s\\n' {token} > /home/.board-test-persist && sync && cat /home/.board-test-persist",
            60, token)
    console.port.write(b'sync; reboot\n')
    wait_for_login()
    console.login()
    command('cat /home/.board-test-persist', 60, token)
    command('rm -f /home/.board-test-persist && sync')

def home_filesystem():
    output = command(
        "awk '$2==\"/home\" {print $1, $3}' /proc/mounts",
        60, '/home')
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == '/dev/mmcblk0p1' and fields[1] == 'ext2':
            return 'sd'
        if len(fields) >= 2 and fields[1] == 'jffs2':
            return 'flash'
    raise AssertionError('unexpected /home mount: {}'.format(output))

def flash_home():
    output = command(
        "awk '$2==\"/home\" {print $1, $2, $3, $4}' /proc/mounts",
        60, '/home jffs2')
    line = next(line for line in output.splitlines() if '/home jffs2' in line)
    fields = line.split()
    assert 'rw' in fields[3].split(','), line

    token = 'flash-home-persist-{}'.format(int(time.time()))
    command(
        f"printf '%s\\n' {token} > /home/.board-test-persist && "
        "sync && cat /home/.board-test-persist",
        60, token)

    console.port.write(b'sync; reboot\n')
    wait_for_login()
    console.login()

    command('cat /home/.board-test-persist', 60, token)
    command('rm -f /home/.board-test-persist && sync')

def home_write_timing():
    output = command('time_start=$(cut -d. -f1 /proc/uptime); '
                     'dd if=/dev/zero of=/home/.write-probe bs=4096 count=64 2>/dev/null; '
                     'sync; time_end=$(cut -d. -f1 /proc/uptime); '
                     'rm -f /home/.write-probe; '
                     'echo WRITE_SECONDS=$((time_end - time_start))', 300, 'WRITE_SECONDS=')
    seconds = int(re.search(r'WRITE_SECONDS=(\d+)', output).group(1))
    results['home_write_256k_seconds'] = seconds
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
        ('hardware-rsa-registered', 'grep -A2 "^name *: rsa$" /proc/crypto | grep -B2 esp32s3 || grep -c rsa-esp32s3 /proc/crypto', 'esp32s3'),
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
        ('bootlog-default-is-quiet', 'bootlog status', 'quiet (the default)'),
        ('bootlog-verbose-raises-the-level', 'bootlog verbose >/dev/null && cut -f1 /proc/sys/kernel/printk', '8'),
        ('bootlog-quiet-restores-it', 'bootlog quiet >/dev/null && cut -f1 /proc/sys/kernel/printk', '4'),
    ]
    for name, text, expected in checks:
        if target in TARGETS_8M and name in N16_ONLY_TESTS:
            skip(name, 'not available in the reduced 8MB Buildroot image')
            continue
        if target in TARGETS_8M and name == 'boot':
            expected = 'Mounted root (cramfs filesystem) readonly'
        record(name, lambda text=text, expected=expected: command(text, 180, expected))

    if target == 'esp32s3_16m':
        record('benchmarks-lightweight-launcher', benchmarks)
        record('fork-exec-cycles', fork_exec_cycles)
        record('jffs2-write-timing', jffs2_write_timing)
    else:
        skip('benchmarks-lightweight-launcher', 'dash/benchmark suite is not in the reduced 8MB image')
        skip('fork-exec-cycles', 'forkbank is not available on 8MB targets')
    record('kernel-health', lambda: command('test "$(cat /proc/sys/kernel/tainted)" = 0 && ! dmesg | grep -E "Out of memory:|Kernel panic|BUG:|Oops:" && free'))
    record('memory-final', record_memory_after)

    if target in TARGETS_8M:
        record('etc-persistence-after-reboot', etc_persistence)
        record('usb-console-getty-state', usb_console_getty)

        home_fs = home_filesystem()

        if home_fs == 'sd':
            skip('jffs2-write-timing', 'SD-backed /home is mounted over the flash JFFS2 /home')
            record('sd-home-ext2-rw-and-persistence', sd_home)
            record('sd-home-write-timing', home_write_timing)
        else:
            record('jffs2-write-timing', jffs2_write_timing)
            record('flash-home-jffs2-rw-and-persistence', flash_home)
            skip('sd-home-write-timing', 'SD is not mounted on /home')

    console.close()
    console = None
    for name in ('test-home-users-board', 'test-cron-board', 'test-com-reconnect', 'test-home-reboot'):
        if target in TARGETS_8M and name in N16_ONLY_TESTS:
            skip(name, 'test assumes the N16R8 writable /home and full userspace')
        else:
            record(name, lambda name=name: external(name))
    console = probe.Console(args.port)
    console.login()
    record('final-kernel-health', lambda: command('test "$(cat /proc/sys/kernel/tainted)" = 0 && ! dmesg | grep -E "Out of memory:|Kernel panic|BUG:|Oops:" && free'))
    results['status'] = 'pass'
    results['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    passed = sum(t['status'] == 'pass' for t in results['tests'])
    skipped = sum(t['status'] == 'skipped' for t in results['tests'])
    results['summary'] = {'passed': passed, 'skipped': skipped, 'failed': 0, 'total': len(results['tests'])}
    manifest['board_verification'] = {
        'status': 'pass', 'target': target, 'image_sha256': results['image_sha256'],
        'finished_utc': results['finished_utc'],
        'report': os.path.relpath(args.output.resolve() / 'results.json', args.artifacts.resolve()),
        'test_runner_sha256': results['test_runner_sha256'],
        'scope': 'Local COM, memory, target-aware storage/persistence and applicable programs; no external WiFi test',
    }
    (args.artifacts / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
except BaseException:
    results['status'] = 'fail'
    raise
finally:
    if console is not None:
        console.close()
    (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
