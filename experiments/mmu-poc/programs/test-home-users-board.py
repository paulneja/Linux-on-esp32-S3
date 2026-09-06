#!/usr/bin/env python3
"""Explicit hardware test: temporary users, HTTP and detached sessions; no flash."""
import argparse
import importlib.util
from pathlib import Path
import re
import secrets
import time

spec = importlib.util.spec_from_file_location('probe', Path(__file__).resolve().parents[1] / 'serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('port')
args = parser.parse_args()
c = probe.Console(args.port)
c.login()
attached = None

def cmd(command, seconds=30):
    result = c.command(command, seconds)
    print(result, flush=True)
    return result

def attach(name):
    global attached
    c.port.write(('session ' + name + '; echo SESSION_RETURNED\r').encode())
    c.until(rb'Detach: Ctrl-\]. Reattach:', 15)
    attached = name
    cmd('echo INSIDE_SESSION')

def detach():
    global attached
    c.port.write(b'\x1d')
    c.until(rb'\nSESSION_RETURNED\n', 15)
    attached = None

def end_session():
    global attached
    c.port.write(b'exit\r')
    c.until(rb'\nSESSION_RETURNED\n', 15)
    sessions.remove(attached)
    attached = None

users = []
sessions = []
web_changed = False
try:
    cmd('stty icrnl')
    cmd('home-users-setup && test ! -e /www && test "$(stat -c %a /bin/busybox)" = 4755 && test "$(stat -c %a /home/root)" = 700')
    cmd('sha256sum /home/www/index.html /home/root/README.txt && head -n 1 /home/root/README.txt')
    for user in ('hwchecka', 'hwcheckb'):
        cmd(f'! id {user} >/dev/null 2>&1 && test ! -e /home/{user}')
        cmd(f'adduser -D -s /usr/bin/user-shell {user}')
        users.append(user)
        cmd(f'test "$(stat -c %a /home/{user})" = 700 && test "$(stat -c %u /home/{user})" = "$(id -u {user})"')
    cmd("su - hwchecka -c 'test \"$(id -u)\" != 0 && test \"$HOME\" = /home/hwchecka && test ! -r /etc/shadow && test ! -r /home/root/README.txt && test ! -x /home/hwcheckb && touch own-file && test -O own-file && echo USER_PERMISSIONS_PASS'")
    cmd('addgroup hwchecka wheel && groups hwchecka && delgroup hwchecka wheel && groups hwchecka')
    password = secrets.token_urlsafe(18)
    c.port.write(b'passwd hwcheckb\r')
    c.until(rb'New password: ?', 15)
    c.port.write(password.encode() + b'\n')
    c.until(rb'Retype password: ?', 15)
    c.port.write(password.encode() + b'\n')
    c.until(rb'password for hwcheckb changed', 15)
    c.port.write(b"su - hwchecka -c 'su - hwcheckb -c id'; echo AUTH_RETURNED\r")
    c.until(rb'Password: ?', 15)
    c.port.write(password.encode() + b'\n')
    data, _ = c.until(rb'\nAUTH_RETURNED\n', 15)
    assert b'(hwcheckb)' in data, data
    print('PASS: su password authentication from an unprivileged user', flush=True)
    c.port.write(b"su - hwchecka -c 'su - hwcheckb -c id'; echo AUTH_DENIED:$?\r")
    c.until(rb'Password: ?', 15)
    c.port.write(b'wrong-test-password\n')
    data, _ = c.until(rb'\nAUTH_DENIED:([0-9]+)\n', 15)
    assert b'AUTH_DENIED:0' not in data and b'(hwcheckb)' not in data, data
    print('PASS: wrong password rejected', flush=True)
    cmd("su - hwchecka -c 'session start hwcheck-user /bin/sh -c \"sleep 1; echo USER_SESSION_PASS > /home/hwchecka/session-result\"'")
    cmd('sleep 2; test "$(cat /home/hwchecka/session-result)" = USER_SESSION_PASS')
    state = cmd('web-server status')
    if 'Web server disabled:' in state:
        cmd('web-server on')
        web_changed = True
    cmd('wget -qO /tmp/home-web-check http://127.0.0.1/ && cmp /tmp/home-web-check /home/www/index.html')
    cmd('wget -qO- http://127.0.0.1/cgi-bin/status')
    cmd("su -s /bin/sh www-data -c 'test -r /home/www/index.html && test -x /home/www/cgi-bin/status && test ! -r /etc/shadow && test ! -w /home/www/index.html && echo WEB_PERMISSIONS_PASS'")
    if web_changed:
        cmd('web-server off')
        web_changed = False
    c.port.write(b"export PS1='MMU_SHELL> '; exec /usr/bin/dash -i\r")
    c.until(rb'\nMMU_SHELL> $', 15)
    c.port.write(b'stty icrnl\n')
    c.until(rb'\nMMU_SHELL> $', 15)
    for name in ('hwcheck-a', 'hwcheck-b'):
        cmd(f'test ! -e /tmp/dtach-0/{name} && session start {name}')
        sessions.append(name)
        attach(name)
        cmd(f'export SESSION_PROOF={name}')
        detach()
    cmd('session list')
    before = cmd('read -r boot_id < /proc/sys/kernel/random/boot_id; printf "%s\\n" "$boot_id"')
    boot = re.search(r'(?m)^[a-f0-9-]{36}$', before).group(0)
    c.close()
    time.sleep(4)
    c = probe.Console(args.port)
    c.login()
    assert boot in cmd('read -r boot_id < /proc/sys/kernel/random/boot_id; printf "%s\\n" "$boot_id"')
    for name in list(sessions):
        attach(name)
        cmd(f'test "$SESSION_PROOF" = {name} && echo REATTACH_PASS')
        end_session()
    print('PASS: two independent lightweight sessions, detach/reattach, COM reconnect, lightweight primary console', flush=True)
    cmd('session start hwcheck-bash /bin/bash --noprofile --norc')
    sessions.append('hwcheck-bash')
    attach('hwcheck-bash')
    cmd('test -n "$BASH_VERSION" && id && echo BASH_SESSION_PASS')
    end_session()
    print('PASS: additional Bash session with lightweight primary console', flush=True)
    c.port.write(b'exec /bin/bash -l\r')
    c.until(rb'# $', 15)
    cmd('test -n "$BASH_VERSION"')
    cmd('test "$(cat /proc/sys/kernel/tainted)" = 0 && session list')
finally:
    try:
        c.port.write(b'\x03\n')
        c.until(rb'(?:# |MMU_SHELL> |login: ?)', 15)
        if attached is not None:
            end_session()
        for name in list(sessions):
            attach(name)
            end_session()
        if web_changed:
            cmd('web-server off')
        for user in reversed(users):
            cmd(f'deluser {user} && rm -r /home/{user}')
        cmd('rm -f /tmp/home-web-check')
    finally:
        c.close()
        if sessions:
            print('ATTENTION: test sessions may remain: ' + ', '.join(sessions), flush=True)
