#!/usr/bin/env python3
"""Join the board to WIFI_SSID / WIFI_PASS over the console and print its address."""
import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('port')
args = parser.parse_args()
ssid, password = os.environ.get('WIFI_SSID'), os.environ.get('WIFI_PASS')
if not ssid or not password:
    sys.exit('board-wifi: set WIFI_SSID and WIFI_PASS')
if '"' in ssid + password or '\\' in ssid + password or '$' in ssid + password:
    sys.exit('board-wifi: quotes, backslashes and $ in the SSID or password are not handled')

repo = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('probe', repo / 'experiments/mmu-poc/serial-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

c = probe.Console(args.port)
c.login()
c.command(f'wifi connect "{ssid}" "{password}" >/dev/null 2>&1', 120, check=False)
status = c.command('wifi status', 20, check=False)
c.close()
m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/\d+.*scope global espsta0', status)
if not m:
    sys.exit('board-wifi: no address after wifi connect:\n' + status[-400:])
print(m.group(1))
