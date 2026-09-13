#!/usr/bin/env python3
"""Boot the board from the factory state N times and classify every boot.

The corruption this hunts shows up on the first boot after a flash, when
home-init fills a freshly formatted /home with hundreds of forks and jffs2
writes, and hardly ever on a plain reset of an initialised board. So each
round rewrites /etc and /home from the artifacts -- a two-partition write,
about a minute -- and then watches the console.

Opening the port is what resets the board: on a CH340 adapter DTR and RTS are
wired to EN and IO0, so the boot observed is the one that open() triggers. No
extra RTS pulse -- one after esptool's own hard reset left the 0.7 release
hanging silently in pinctrl, which looked like a kernel fault and was not.

Every round ends in exactly one of three states, and a round is only a PASS
on positive evidence:

  PASS          the login prompt appeared, the last init script ran (the
                system reached the run level that does the work under test),
                and nothing in the fault list was printed
  FAIL          something in the fault list was printed
  INCONCLUSIVE  no fault, but no login prompt or no marker within the budget:
                the board hung, reset, or was simply not observed long enough

INCONCLUSIVE never counts as a pass. Five PASS rounds with a true fault rate
of 20% still happen a third of the time, so the summary prints a one-sided
95% upper bound on the rate alongside the count; ask for --rounds 20 before
reading anything into a zero.

Each run records the SHA-256 of the kernel and firmware partitions as read
back from the board, so a transcript can always be tied to the exact image it
came from. Never flashes the kernel or the rootfs: those are the image under
test.
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

# Kernel-side faults, plus the user-space signatures of the same corruption:
# a process taking an illegal instruction, and busybox's unhandled-exception
# line. "slab_debug" is deliberately absent -- it appears in the bootargs.
FAULT = re.compile(rb'Oops:|BUG:|Kernel panic|Illegal [Ii]nstruction'
                   rb'|kernel taint|Tainted:|crc error'
                   rb'|scheduling while atomic|Caught unhandled exception'
                   rb'|Redzone overwritten|Poison overwritten'
                   rb'|list_add corruption|list_del corruption'
                   rb'|corrupted stack end|Bad page state|WARNING: CPU')
LOGIN = re.compile(rb'buildroot login: ?')
# The last init script; once it has run, home-init and everything before it
# have finished, which is the work the boot has to have done to count.
MARKER = re.compile(rb'Starting cron: OK')
RESET_BANNER = re.compile(rb'ESP-ROM:esp32s3')
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
parser.add_argument('--no-flash', action='store_true', help='only reset; do not restore /etc and /home')
parser.add_argument('--no-identity', action='store_true', help='skip reading the kernel/firmware hashes back')
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
    command = [args.esptool, '--chip', 'esp32s3', '--port', args.port,
               '--before', 'default_reset', '--after', 'hard_reset', *words]
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
    # Only after a login prompt was seen: log in and read what was asked for.
    out = {}
    try:
        console.login()
        for command in args.probe:
            out[command] = console.command(command, 20, check=False)
    except Exception as error:  # a wedged console is itself a finding
        out['error'] = repr(error)
    return out


def boot_and_watch(transcript):
    console = probe.Console(args.port)
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
        probes = run_probes(console) if (args.probe and login_at is not None) else {}
        if probes:
            log.write(('\n--- probes ---\n' + json.dumps(probes, indent=1) + '\n').encode())
    console.port.close()
    return data, login_at, marker_at, time.monotonic() - started, probes


def classify(data, login_at, marker_at):
    hits = sorted(set(m.decode() for m in FAULT.findall(data)))
    resets = len(RESET_BANNER.findall(data))
    if hits:
        return 'FAIL', hits, resets
    if login_at is None or marker_at is None:
        return 'INCONCLUSIVE', [], resets
    if resets > 1:
        # It came up, but not on the first try: a silent reset happened.
        return 'INCONCLUSIVE', ['reset without a fault message'], resets
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


identity = {} if args.no_identity else read_identity()
rounds = []
for number in range(1, args.rounds + 1):
    if not args.no_flash:
        restore_factory()
    data, login_at, marker_at, observed, probes = boot_and_watch(args.output / f'boot-{number:02d}.log')
    state, hits, resets = classify(data, login_at, marker_at)
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
