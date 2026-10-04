#!/usr/bin/env python3
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

parser = argparse.ArgumentParser(description='fill /home in stages, then churn it, and time the writes')
parser.add_argument('port')
parser.add_argument('--output', type=Path, default=Path('build-output/test-home-write'))
parser.add_argument('--stages', default='25,50,70,85', help='percent of /home to fill to')
parser.add_argument('--chunk-kb', type=int, default=64)
parser.add_argument('--budget', type=int, default=1500, help='seconds before giving up')
parser.add_argument('--keep', action='store_true', help='leave the files on the board')
parser.add_argument('--churn', type=int, default=1, help='delete-half-and-rewrite rounds')
args = parser.parse_args()

repo = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('probe', repo / 'experiments/mmu-poc/serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

started = time.monotonic()
c = probe.Console(args.port)
c.login()


def run(cmd, seconds=120):
    return c.command(cmd, seconds, check=False)


def last(cmd):
    return run(cmd).splitlines()[-1].strip()


def usage():
    out = run('df -k /home | tail -1')
    m = re.search(r'^\S+\s+(\d+)\s+(\d+)\s+\d+\s+\d+%\s+/home\s*$', out, re.M)
    return int(m[1]), int(m[2])


def flashstat():
    out = run('cat /proc/flashstat 2>/dev/null')
    stat = {}
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) == 11 and f[0] in ('erase', 'read', 'write'):
            stat[f[0]] = dict(zip(('count', 'bytes', 'total_us', 'max_us', 'lt100us', 'lt1ms',
                                   'lt10ms', 'lt50ms', 'lt200ms', 'ge200ms'), map(int, f[1:])))
    return stat


def timed_write(name):
    out = run(f'a=$(cut -d" " -f1 /proc/uptime); cp /tmp/bench-src /home/bench/{name}; sync; '
              f'b=$(cut -d" " -f1 /proc/uptime); echo "T $a $b"', 300)
    m = re.search(r'T ([\d.]+) ([\d.]+)', out)
    return float(m[2]) - float(m[1]) if m else None


def stage(label, files):
    before = flashstat()
    times, aborted = [], False
    for name in files:
        if time.monotonic() - started > args.budget:
            aborted = True
            break
        t = timed_write(name)
        if t is None:
            aborted = True
            break
        times.append(t)
    size, used = usage()
    total = sum(times)
    result = {'stage': label, 'files': len(times), 'kb': len(times) * args.chunk_kb,
              'seconds': round(total, 2), 'kb_per_s': round(len(times) * args.chunk_kb / total, 1) if total else None,
              'slowest_s': round(max(times), 2) if times else None, 'home_used_pct': round(100 * used / size, 1),
              'aborted': aborted, 'flash_before': before, 'flash_after': flashstat()}
    print(json.dumps({k: v for k, v in result.items() if not k.startswith('flash')}), flush=True)
    return result


run('rm -rf /home/bench; mkdir -p /home/bench; sync')
run(f'dd if=/dev/urandom of=/tmp/bench-src bs=1024 count={args.chunk_kb} 2>/dev/null')
size, used = usage()
results = {'home_kb': size, 'start_used_kb': used, 'chunk_kb': args.chunk_kb,
           'uname': last('uname -r'), 'stages': []}
written = []
for pct in (int(x) for x in args.stages.split(',')):
    size, used = usage()
    need = max(0, (size * pct // 100 - used) // args.chunk_kb)
    names = [f'f{len(written) + i}' for i in range(need)]
    r = stage(f'fill-{pct}', names)
    written += names[:r['files']]
    results['stages'].append(r)
    if r['aborted']:
        break
else:
    for n in range(args.churn):
        gone, written = written[::2], written[1::2]
        run('cd /home/bench && rm -f ' + ' '.join(gone) + '; sync', 300)
        fresh = [f'c{n}-{i}' for i in range(len(gone))]
        r = stage(f'churn-{n + 1}', fresh)
        written += fresh[:r['files']]
        results['stages'].append(r)
        if r['aborted']:
            break

results['tainted'] = last('cat /proc/sys/kernel/tainted')
results['mem_available'] = last('grep MemAvailable /proc/meminfo')
if not args.keep:
    run('rm -rf /home/bench /tmp/bench-src; sync', 600)
c.close()

args.output.mkdir(parents=True, exist_ok=True)
(args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
print(f'results in {args.output / "results.json"}')
