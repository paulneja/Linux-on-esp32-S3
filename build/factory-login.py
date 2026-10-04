#!/usr/bin/env python3
"""Put the board's login back to how a fresh flash leaves it.

The test harness answers the first login itself, so after a run root has the
test password and SSH is on. This sets changeme123 again, turns SSH and Telnet
off and forgets the choice, here and in the copy S03keepconfig keeps in /home,
so the next login on the console asks for a password and a way in.
"""
import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('probe', ROOT / 'experiments/mmu-poc/serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

parser = argparse.ArgumentParser()
parser.add_argument('port')
args = parser.parse_args()

pw = probe.FACTORY_PASSWORD
c = probe.Console(args.port)
c.login()
c.command(f'printf "{pw}\\n{pw}\\n" | passwd root >/dev/null 2>&1', 30)
c.command('remote-login off >/dev/null', 30)
c.command('rm -f /etc/remote-login /home/.etc-backup/remote-login', 10)
c.command('/etc/init.d/S03keepconfig save >/dev/null; sync', 60)
state = c.command('remote-login status; ls /etc/remote-login 2>&1', 30, check=False)
c.port.write(b'exit\n')
c.close()
if 'Listening: nothing' not in state or 'No such file' not in state:
    raise SystemExit('factory-login: the board did not end up at the factory login:\n' + state)
print(f'root is back to {pw}, nothing listens on the network, the first login will ask again')
