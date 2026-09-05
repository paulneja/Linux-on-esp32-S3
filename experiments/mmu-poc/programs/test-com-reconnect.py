#!/usr/bin/env python3
"""Board test: three real COM closes, then allow the nohup job to finish."""
import importlib.util
from pathlib import Path
import re
import sys
import time

spec = importlib.util.spec_from_file_location('probe', Path(__file__).resolve().parents[1] / 'serial-probe.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
c = p.Console(sys.argv[1])
c.login()

def cmd(text):
    result = c.command(text)
    print(result, flush=True)
    return result

directory = None
try:
    directory = re.search(r'(?m)^(/tmp/com-check\.[a-zA-Z0-9]+)$', cmd('mktemp -d /tmp/com-check.XXXXXX')).group(1)
    boot = re.search(r'(?m)^[a-f0-9-]{36}$', cmd('cat /proc/sys/kernel/random/boot_id')).group(0)
    cmd(f"nohup /bin/sh -c 'n=0; while test ! -e {directory}/go; do sleep 1; n=$((n+1)); test $n -lt 45 || exit 1; done; echo survived > {directory}/result' >{directory}/log 2>&1 </dev/null & bg=$!")
    for cycle in range(3):
        c.close()
        time.sleep(2)
        c = p.Console(sys.argv[1])
        c.login()
        assert boot in cmd('cat /proc/sys/kernel/random/boot_id')
        cmd('kill -0 "$bg"')
        print(f'PASS: COM reconnect {cycle + 1}, same boot and live background job', flush=True)
    cmd(f'test ! -e {directory}/result && touch {directory}/go')
    cmd(f'wait "$bg" && test "$(cat {directory}/result)" = survived')
    print('PASS: nohup job completes only after three COM reconnects', flush=True)
finally:
    if directory:
        cmd(f'touch {directory}/go; wait "$bg" 2>/dev/null; rm -f {directory}/go {directory}/result {directory}/log; rmdir {directory}')
    c.close()
