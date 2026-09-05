#!/usr/bin/env python3
"""Host tests: actual children, admission refusal, failures and deadlines."""
from pathlib import Path
import subprocess

out = Path(__file__).resolve().parent.parent / 'out/programs'
q = str(out / 'jobq-host')
b = str(out / 'programbench-host')

def run(args, code=0):
    r = subprocess.run(args, text=True, capture_output=True, timeout=15)
    assert r.returncode == code, (args, r.returncode, r.stdout, r.stderr)
    return r.stdout + r.stderr

log = run([q, '-j', '2', '--', '/bin/sleep', '0.2', ':::', '/bin/sleep', '0.2', ':::', '/bin/true'])
assert 'active=2' in log and 'active=3' not in log and log.count('START ') == 3
log = run([q, '-r', '2147483647', '-w', '1', '--', '/bin/true'], 1)
assert 'START ' not in log and 'ADMISSION_TIMEOUT' in log
assert 'code=127' in run([q, '--', '/does-not-exist'], 1)
assert 'code=137' in run([q, '-t', '1', '--', '/bin/sleep', '3'], 1)
assert 'code=7' in run([q, '--', '/bin/sh', '-c', 'exit 7'], 1)
run([q, '--', '/bin/true', ':::'], 2)
print('PASS: jobq concurrency, admission refusal, failed exec, timeout, exit codes, syntax')
assert 'exit=0' in run([b, '--', '/bin/true'])
assert 'exit=7' in run([b, '--', '/bin/sh', '-c', 'exit 7'], 7)
run([b, '--', '/does-not-exist'], 1)
run([b, '-t', '1', '--', '/bin/sleep', '3'], 124)
print('PASS: programbench exec-stop, status, failed exec and timeout')
