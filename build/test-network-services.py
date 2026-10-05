#!/usr/bin/env python3
"""remote-login and web-server end to end: ports and SSH auth modes, checked
from the host over WiFi. Needs wifi already set up and paramiko on the host.
Puts back /etc/remote-login, remote-login.conf and authorized_keys as they
were, and leaves the web server off on port 80."""
import argparse
import importlib.util
import io
import json
import os
import re
import socket
import sys
import time
import urllib.request
from pathlib import Path

try:
    import paramiko
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
except ImportError:
    print('paramiko not installed (pip install paramiko); see build/README.md', file=sys.stderr)
    sys.exit(2)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('port')
parser.add_argument('--password', help='defaults to the one the serial login used')
parser.add_argument('--output', type=Path, default=Path('build-output/test-network-services'))
args = parser.parse_args()

repo = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('probe', repo / 'experiments/mmu-poc/serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

c = probe.Console(args.port)
c.login()
password = args.password or os.environ['MMU_BOARD_PASSWORD']
status = c.command('wifi status', 15, check=False)
m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/\d+.*scope global espsta0', status)
if not m:
    print('SKIP: no WiFi configured on this board (wifi connect "SSID" "PASS" first)')
    c.close()
    sys.exit(0)
ip = m.group(1)
print(f'board at {ip}')

KEYS = '/home/root/.ssh/authorized_keys'
raw = ed25519.Ed25519PrivateKey.generate().private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
key = paramiko.Ed25519Key.from_private_key(io.StringIO(raw.decode()))
public = f'{key.get_name()} {key.get_base64()} network-services-test'

results = []


def record(name, fn):
    t0 = time.monotonic()
    try:
        detail = fn() or ''
        state = 'PASS'
    except Exception as e:
        detail = f'{type(e).__name__}: {e}'[:400]
        state = 'FAIL'
    results.append({'name': name, 'status': state, 'detail': detail,
                    'seconds': round(time.monotonic() - t0, 1)})
    print(f'{state}: {name}' + (f'  -- {detail}' if detail else ''), flush=True)


def board(cmd, seconds=30):
    return c.command(cmd, seconds, check=False)


def ssh(port, use_key=False, use_password=False):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, port=port, username='root', timeout=20, banner_timeout=60, auth_timeout=60,
                       password=password if use_password else None, pkey=key if use_key else None,
                       look_for_keys=False, allow_agent=False)
        _, out, _ = client.exec_command('echo in-$((6*7))', timeout=60)
        return 'in-42' in out.read().decode()
    except paramiko.AuthenticationException:
        return False
    finally:
        client.close()


def listening(port):
    with socket.socket() as s:
        s.settimeout(5)
        return s.connect_ex((ip, port)) == 0


def wait_listening(port, want=True, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if listening(port) == want:
            return True
        time.sleep(1)
    return False


def state(status):
    return [line.strip() for line in status.splitlines() if re.match(r'(Listening|SSH|Telnet):', line.strip())]


before = board('remote-login status')
old_port = re.search(r'SSH: port (\d+)', before)
old_port = old_port.group(1) if old_port else '22'
ssh_was_on = re.search(r'Listening:.*\bssh\b', before) is not None
board('for f in /etc/remote-login /etc/remote-login.conf /home/root/.ssh/authorized_keys; do '
      '[ -e $f ] && cp -p $f $f.network-test; done; true')
board(f'mkdir -p /home/root/.ssh; chmod 700 /home/root/.ssh; echo "{public}" >> {KEYS}; chmod 600 {KEYS}')
board('remote-login ssh; remote-login auth both')


def port_moves():
    board('remote-login port ssh 2222')
    assert wait_listening(2222), 'nothing on 2222'
    assert wait_listening(int(old_port), want=False) or old_port == '2222', f'{old_port} still open'
    assert ssh(2222, use_password=True), 'password refused on 2222'
    return 'SSH answered on 2222 and the old port closed'
record('ssh-port-moves', port_moves)


def auth_both():
    board('remote-login auth both')
    assert ssh(2222, use_key=True), 'key refused'
    assert ssh(2222, use_password=True), 'password refused'
    return 'password and key both let in'
record('ssh-auth-both', auth_both)


def auth_key():
    board('remote-login auth key')
    assert ssh(2222, use_key=True), 'key refused'
    assert not ssh(2222, use_password=True), 'password let in with keys only'
    return 'key in, password turned away'
record('ssh-auth-key-only', auth_key)


def auth_password():
    board('remote-login auth password')
    assert ssh(2222, use_password=True), 'password refused'
    assert not ssh(2222, use_key=True), 'key let in with password only'
    return 'password in, key turned away'
record('ssh-auth-password-only', auth_password)


def telnet_port():
    board('remote-login port telnet 2323; remote-login telnet')
    assert wait_listening(2323), 'nothing on 2323'
    assert wait_listening(2222, want=False), 'SSH still open after switching to telnet'
    with socket.create_connection((ip, 2323), timeout=10) as s:
        s.settimeout(10)
        data = b''
        end = time.monotonic() + 15
        while b'login' not in data and time.monotonic() < end:
            try:
                data += s.recv(512)
            except socket.timeout:
                break
    assert b'login' in data, f'no login prompt: {data[-80:]!r}'
    return 'telnet login prompt on 2323, SSH closed'
record('telnet-port', telnet_port)


def web_port():
    board('web-server port 8080; web-server on')
    assert wait_listening(8080), 'nothing on 8080'
    with urllib.request.urlopen(f'http://{ip}:8080/', timeout=20) as r:
        assert r.status == 200, r.status
    board('web-server off; web-server port default')
    assert wait_listening(8080, want=False), '8080 still open after web-server off'
    return 'page served on 8080, closed again'
record('web-server-port', web_port)


def restore():
    board('for f in /etc/remote-login /etc/remote-login.conf /home/root/.ssh/authorized_keys; do '
          'if [ -e $f.network-test ]; then mv $f.network-test $f; else rm -f $f; fi; done; '
          'remote-login apply')
    if ssh_was_on:
        assert wait_listening(int(old_port)), f'SSH not back on {old_port}'
    after = board('remote-login status')
    assert state(after) == state(before), f'{state(before)} -> {state(after)}'
    return '; '.join(state(after))
record('restored', restore)

c.close()
args.output.mkdir(parents=True, exist_ok=True)
(args.output / 'results.json').write_text(json.dumps({'ip': ip, 'results': results}, indent=1) + '\n')
n = len(results)
f = sum(r['status'] == 'FAIL' for r in results)
print(f'\n{n - f}/{n} passed' + (f', {f} FAILED' if f else ''))
sys.exit(1 if f else 0)
