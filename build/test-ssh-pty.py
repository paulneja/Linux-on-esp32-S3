#!/usr/bin/env python3
"""ssh -tt against the board, issue #9. needs wifi already set up."""
import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

try:
    import paramiko
except ImportError:
    print('paramiko not installed (pip install paramiko); see build/README.md', file=sys.stderr)
    sys.exit(2)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('port')
parser.add_argument('--password', default='changeme123')
parser.add_argument('--output', type=Path, default=Path('build-output/test-ssh-pty'))
args = parser.parse_args()

repo = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('probe', repo / 'experiments/mmu-poc/serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

c = probe.Console(args.port)
c.login()

status = c.command('wifi status', 15, check=False)
m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/\d+.*scope global espsta0', status)
if not m:
    print('SKIP: no WiFi configured on this board (wifi connect "SSID" "PASS" first)')
    c.close()
    sys.exit(0)
ip = m.group(1)
print(f'board at {ip}')

if 'SSH: enabled' not in c.command('ssh-server status', 10, check=False):
    c.command('ssh-server on', 10, check=False)
c.close()

args.output.mkdir(parents=True, exist_ok=True)
result = {'ip': ip, 'status': 'FAIL', 'detail': ''}
try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username='root', password=args.password, timeout=15,
                    look_for_keys=False, allow_agent=False)
    try:
        chan = client.get_transport().open_session()
        # if this fails, blame dropbear. I don't wanna hear about it anymore...
        chan.get_pty()
        chan.invoke_shell()
        time.sleep(1)
        chan.send('tty; id; exit\n')
        time.sleep(1.5)
        out = b''
        while chan.recv_ready():
            out += chan.recv(4096)
        chan.close()
        out = out.decode(errors='replace')
        assert '/dev/pts/' in out, f'no PTY in output: {out!r}'
        result['status'] = 'PASS'
        result['detail'] = next(line for line in out.splitlines() if '/dev/pts/' in line).strip()
    finally:
        client.close()
except Exception as e:
    result['detail'] = f'{type(e).__name__}: {e}'

(args.output / 'results.json').write_text(json.dumps(result, indent=1) + '\n')
print(f'{result["status"]}: ssh-pty  -- {result["detail"]}')
sys.exit(0 if result['status'] == 'PASS' else 1)
