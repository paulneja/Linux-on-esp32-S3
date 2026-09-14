#!/usr/bin/env python3
"""Boot the board from the factory state N times and classify every boot.

Each round rewrites /etc and /home from the artifacts, holds the board in
reset until the port is listening, watches the console, then logs in and
reads dmesg and the taint flags back (a quiet console shows KERN_ERR and
worse only). A round ends in exactly one of three states:

  PASS          login prompt, last init script ran, kernel log and taint
                flags read back clean, nothing in the fault list printed
  FAIL          something in the fault list was printed
  INCONCLUSIVE  no fault, but no login, no marker, or no log read back

INCONCLUSIVE never counts as a pass. The summary carries a one-sided 95%
upper bound on the fault rate; twenty rounds are the least that means much.
--identity records the SHA-256 of the kernel and firmware partitions read
back from the board (about seven minutes). Never flashes the kernel or the
rootfs: those are the image under test.
"""
import argparse
import hashlib
import importlib.util
import json
from math import comb
from pathlib import Path
import re
import subprocess
import sys
import time

# Kernel faults plus the user-space signatures of the same corruption.
# "slab_debug" is deliberately absent: it appears in the bootargs.
FAULT = re.compile(rb'Oops:|BUG:|Kernel panic|Illegal [Ii]nstruction'
                   rb'|kernel taint|Tainted:|crc error'
                   rb'|scheduling while atomic|Caught unhandled exception'
                   rb'|Redzone overwritten|Poison overwritten'
                   rb'|list_add corruption|list_del corruption'
                   rb'|corrupted stack end|Bad page state|WARNING: CPU')
LOGIN = re.compile(rb'buildroot login: ?')
# The last init script: once it ran, home-init and everything before it did.
MARKER = re.compile(rb'Starting cron: OK')
RESET_BANNER = re.compile(rb'ESP-ROM:esp32s3')
# A quiet console types KERN_ERR and worse only; a user-space illegal
# instruction (pr_info) and a WARN never reach it. The ring buffer has them,
# so every round that logs in reads it back, with the taint flags.
HEALTH = ('cat /proc/sys/kernel/tainted', 'dmesg')
TAINTED = re.compile(rb'^\s*(\d+)\s*$', re.M)
OFFSETS = {'etc.jffs2': '0xd0000', 'home.jffs2': '0xcc0000'}
# Kernel and firmware partitions, read back to identify what actually booted.
IDENTITY = {'linux': ('0x140000', 0x400000), 'factory': ('0x10000', 0xc0000)}

parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
parser.add_argument('port')
parser.add_argument('artifacts', type=Path, help='directory with etc.jffs2 and home.jffs2')
parser.add_argument('--output', type=Path, required=True, help='directory for the transcripts; must not exist')
parser.add_argument('--rounds', type=int, default=5)
parser.add_argument('--boot-seconds', type=int, default=120,
                    help='total observation budget per round, from reset')
parser.add_argument('--settle-seconds', type=int, default=25,
                    help='keep watching this long after login and marker: the network and BLE come up later')
parser.add_argument('--esptool', default='esptool')
parser.add_argument('--baud', type=int, default=460800,
                    help='esptool transfer rate for the restore. At 115200 the 3.8 MB rewrite takes '
                         'longer than the boot it sets up, and it is the flash traffic that heats the board')
parser.add_argument('--no-flash', action='store_true', help='only reset; do not restore /etc and /home')
parser.add_argument('--identity', action='store_true',
                    help='read the kernel and firmware partitions back and record their hashes; '
                         'about seven minutes at 115200 baud, so off by default')
parser.add_argument('--label', default='', help='free text stored in the summary (which variant this is)')
parser.add_argument('--probe', action='append', default=[],
                    help='after a round that reached login, log in and run this command; its output is '
                         'stored per round (repeatable). Used to read counters the kernel exposes.')
args = parser.parse_args()

repo = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('probe', repo / 'experiments/mmu-poc/serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

for name in OFFSETS:
    assert (args.artifacts / name).is_file(), f'{args.artifacts / name} is missing'
args.output.mkdir(parents=True, exist_ok=False)


def esptool(*words):
    # The underscore spellings work with both esptool 4.8.1 and 5.x.
    command = [args.esptool, '--chip', 'esp32s3', '--port', args.port, '--baud', str(args.baud),
               '--before', 'default_reset', '--after', 'no_reset', *words]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def restore_factory():
    words = ['write_flash']
    for name, offset in OFFSETS.items():
        words += [offset, str(args.artifacts / name)]
    esptool(*words)


def read_identity():
    identity = {}
    for name, (offset, size) in IDENTITY.items():
        dump = args.output / f'{name}.bin'
        esptool('read_flash', offset, hex(size), str(dump))
        identity[name] = hashlib.sha256(dump.read_bytes()).hexdigest()
        dump.unlink()
    return identity


def run_probes(console):
    # Only after a login prompt was seen: log in, read the kernel's own record
    # of the boot, then whatever else was asked for.
    out = {}
    try:
        console.login()
        for command in HEALTH + tuple(args.probe):
            out[command] = console.command(command, 30, check=False)
    except Exception as error:  # a wedged console is itself a finding
        out['error'] = repr(error)
    return out


def release_reset(port):
    # EN low, IO0 high: a plain reset into the flash boot, from a known state.
    port.dtr = False
    port.rts = True
    time.sleep(0.1)
    port.rts = False


def boot_and_watch(transcript):
    console = probe.Console(args.port)
    release_reset(console.port)
    started = time.monotonic()
    data = b''
    login_at = marker_at = None
    deadline = started + args.boot_seconds
    with transcript.open('wb') as log:
        while time.monotonic() < deadline:
            chunk = console.port.read(max(1, console.port.in_waiting))
            if chunk:
                log.write(chunk)
                data += chunk
            if marker_at is None and MARKER.search(data):
                marker_at = time.monotonic() - started
            if login_at is None and LOGIN.search(data):
                login_at = time.monotonic() - started
            if marker_at is not None and login_at is not None:
                deadline = min(deadline, started + max(marker_at, login_at) + args.settle_seconds)
        probes = run_probes(console) if login_at is not None else {}
        if probes:
            log.write(('\n--- probes ---\n' + json.dumps(probes, indent=1) + '\n').encode())
    console.port.close()
    return data, login_at, marker_at, time.monotonic() - started, probes


def classify(data, login_at, marker_at, probes=None):
    probes = probes or {}
    hits = set(m.decode() for m in FAULT.findall(data))
    resets = len(RESET_BANNER.findall(data))

    # What the console was too quiet to say, read out of the ring buffer.
    log = probes.get('dmesg')
    if log:
        hits |= set('dmesg: ' + m.decode() for m in FAULT.findall(log.encode()))
    flags = probes.get('cat /proc/sys/kernel/tainted')
    if flags:
        found = TAINTED.search(flags.encode())
        if found and found.group(1) != b'0':
            hits.add('tainted=' + found.group(1).decode())
    if 'error' in probes:
        hits.add('console wedged after login: ' + str(probes['error'])[:80])

    hits = sorted(hits)
    if hits:
        return 'FAIL', hits, resets
    if login_at is None or marker_at is None:
        return 'INCONCLUSIVE', [], resets
    if resets > 1:
        # It came up, but not on the first try: a silent reset happened.
        return 'INCONCLUSIVE', ['reset without a fault message'], resets
    if not probes.get('dmesg'):
        # Reached a login but the kernel log could not be read: on a quiet
        # image that is most of the evidence, so this is not a pass.
        return 'INCONCLUSIVE', ['kernel log not read back'], resets
    return 'PASS', [], resets


def upper_bound_95(fails, n):
    """One-sided 95% upper bound on the fault rate, so "0 of 5" reads as what
    it is: a rate somewhere below 45%."""
    if n == 0 or fails == n:
        return 1.0
    if fails == 0:
        return 1 - 0.05 ** (1 / n)
    lo, hi = fails / n, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        tail = sum(comb(n, k) * mid ** k * (1 - mid) ** (n - k) for k in range(fails + 1))
        if tail > 0.05:
            lo = mid
        else:
            hi = mid
    return hi


identity = read_identity() if args.identity else {}
rounds = []
for number in range(1, args.rounds + 1):
    if not args.no_flash:
        restore_factory()
    data, login_at, marker_at, observed, probes = boot_and_watch(args.output / f'boot-{number:02d}.log')
    state, hits, resets = classify(data, login_at, marker_at, probes)
    record = {'round': number, 'state': state, 'faults': hits, 'resets_seen': resets, 'probes': probes,
              'login_s': None if login_at is None else round(login_at, 1),
              'marker_s': None if marker_at is None else round(marker_at, 1),
              'observed_s': round(observed, 1), 'bytes': len(data)}
    rounds.append(record)
    print(f'round {number:2d}: {state:<12} login={str(record["login_s"] or "-"):>6} '
          f'marker={str(record["marker_s"] or "-"):>6} observed={record["observed_s"]:>6}s '
          f'{hits}' + (f' probes={ {k: str(v)[:60] for k, v in probes.items()} }' if probes else ''), flush=True)

counts = {s: sum(r['state'] == s for r in rounds) for s in ('PASS', 'FAIL', 'INCONCLUSIVE')}
decided = counts['PASS'] + counts['FAIL']
bound = upper_bound_95(counts['FAIL'], decided) if decided else 1.0
verdict = (f'{counts["FAIL"]} FAIL, {counts["PASS"]} PASS, {counts["INCONCLUSIVE"]} INCONCLUSIVE '
           f'of {args.rounds}; fault rate <= {bound:.0%} (95% one-sided, over the {decided} decided)')
print(verdict)
summary = {'label': args.label, 'identity': identity, 'artifacts': str(args.artifacts.resolve()),
           'rounds': rounds, 'counts': counts, 'fault_rate_upper_95': round(bound, 3),
           'verdict': verdict}
(args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
(args.output / 'summary.txt').write_text(
    '\n'.join(f'round {r["round"]:2d}: {r["state"]:<12} {r["faults"]}' for r in rounds)
    + '\n' + verdict + '\n')
sys.exit(1 if counts['FAIL'] else (2 if counts['INCONCLUSIVE'] else 0))
