#!/usr/bin/env python3
"""Explicit board reboot; assert persistent home/account files are unchanged."""
import importlib.util
from pathlib import Path
import re
import sys

spec = importlib.util.spec_from_file_location('probe', Path(__file__).resolve().parents[1] / 'serial-probe.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
c = p.Console(sys.argv[1])
try:
    c.login()
    files = '/home/root/sudoku.py /home/root/README.txt /home/www/index.html /home/www/cgi-bin/status /etc/passwd /etc/shadow /etc/inetd.conf'
    def hashes():
        return re.findall(r'(?m)^([a-f0-9]{64})\s+(/\S+)$', c.command('sha256sum ' + files))
    before = hashes()
    assert len(before) == 7
    boot = re.search(r'(?m)^[a-f0-9-]{36}$', c.command('cat /proc/sys/kernel/random/boot_id')).group(0)
    assert 'Web server disabled:' in c.command('web-server status')
    c.port.write(b'sync; reboot\n')
    c.until(rb'buildroot login: ?', 45)
    c.login()
    assert boot not in c.command('cat /proc/sys/kernel/random/boot_id')
    assert hashes() == before
    c.command('test ! -e /www && test -x /etc/init.d/S06home-users && test "$(stat -c %a /home/root)" = 700 && test "$(stat -c %a /bin/busybox)" = 4755 && test "$(cat /proc/sys/kernel/tainted)" = 0')
    assert 'Web server disabled:' in c.command('web-server status')
    print('PASS: explicit reboot; seven persistent files unchanged; private root home; SUID; web stays disabled; taint 0')
    print(c.command('process-test', 60))
finally:
    c.close()
