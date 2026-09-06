#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import re
import shlex
import sys
import time

spec = importlib.util.spec_from_file_location('probe', Path(__file__).resolve().parents[1] / 'serial-probe.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
c = p.Console(sys.argv[1])
c.login()
users = []

def cmd(text, seconds=30):
    result = c.command(text, seconds)
    print(result, flush=True)
    return result

def schedule(user, lines):
    cmd('printf "%s\\n" ' + ' '.join(shlex.quote(line) for line in lines) + f' | crontab -u {user} -')

try:
    cmd('cron-setup --prepare && test ! -e /etc/cron/disabled')
    for user in ('cronalpha', 'cronbeta'):
        cmd(f'! id {user} >/dev/null 2>&1 && test ! -e /home/{user} && test ! -e /etc/cron/crontabs/{user}')
        cmd(f'adduser -D -s /usr/bin/user-shell {user}')
        users.append(user)
    schedule('cronalpha', ['SHELL=/usr/bin/dash', 'PATH=/cron-alpha-only',
        '* * * * * /usr/bin/id -u > /home/cronalpha/uid; echo "$HOME|$SHELL|$PATH" > /home/cronalpha/env',
        '@reboot echo reboot-ok > /home/cronalpha/reboot-result'])
    schedule('cronbeta', [
        '* * * * * /usr/bin/id -u > /home/cronbeta/uid; echo "$HOME|$SHELL|$PATH" > /home/cronbeta/env'])
    cmd('cron-setup && cron-server status')
    cmd("su - cronalpha -c 'crontab -l >/dev/null && test ! -r /etc/cron/crontabs/cronbeta && ! crontab -u root -l >/dev/null 2>&1'")
    cmd("su - cronbeta -c 'crontab -l > /home/cronbeta/saved && crontab /home/cronbeta/saved'")
    result = cmd("su - cronalpha -c 'VISUAL=/bin/cat EDITOR=/bin/cat crontab -e'")
    assert 'Permission denied' not in result
    assert re.search(r'(?m)^PATH=/cron-alpha-only$', result)
    print('Waiting for actual minute-boundary jobs (no clock changes)...', flush=True)
    deadline = time.monotonic() + 85
    while time.monotonic() < deadline:
        result = cmd('test -s /home/cronalpha/env && test -s /home/cronbeta/env && echo CRON_READY || true')
        if re.search(r'(?m)^CRON_READY$', result): break
        time.sleep(5)
    else: raise AssertionError('cron jobs did not execute at a minute boundary')
    for user in users:
        cmd(f'test "$(cat /home/{user}/uid)" = "$(id -u {user})" && test "$(stat -c %u /home/{user}/uid)" = "$(id -u {user})"')
    cmd('test "$(cat /home/cronalpha/env)" = "/home/cronalpha|/usr/bin/dash|/cron-alpha-only"')
    cmd('test "$(cat /home/cronbeta/env)" = "/home/cronbeta|/bin/sh|/usr/bin:/bin:/usr/sbin:/sbin"')
    print('PASS: real scheduled jobs, user UID/home ownership, crontab permissions, isolated PATH/SHELL', flush=True)
    cmd('cron-server off && ! cron-server status && test -f /etc/cron/disabled')
    cmd('cron-server on && cron-server status')
    cmd('rm -f /home/cronalpha/reboot-result; sync')
    c.port.write(b'reboot\n')
    c.until(rb'buildroot login: ?', 45)
    c.login()
    cmd('cron-server status && test "$(cat /home/cronalpha/reboot-result)" = reboot-ok')
    cmd('test "$(stat -c %u /home/cronalpha/reboot-result)" = "$(id -u cronalpha)"')
    cmd('test "$(cat /proc/sys/kernel/tainted)" = 0 && test ! -e /usr/bin/sqlite3 && test ! -e /home/.system/bin/sqlite3')
    print('PASS: persistent schedules, daemon startup, @reboot as its owner, no SQLite, taint 0', flush=True)
finally:
    for user in reversed(users):
        cmd(f'crontab -u {user} -r; deluser {user}; rm -r /home/{user}')
    c.close()
