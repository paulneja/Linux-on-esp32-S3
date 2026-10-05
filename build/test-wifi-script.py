#!/usr/bin/env python3
"""usr/bin/wifi: the configuration it writes, and one shape it must not have.
The image's busybox ash cannot finish a heredoc that ends inside a
( subshell ); sh -n and the host's busybox accept it, so the shape is refused
here by inspection.
"""
import os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIFI = ROOT / 'new-files/board/espressif/esp32s3/rootfs_overlay/usr/bin/wifi'


class WifiScriptTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='wifi-'))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.conf = self.dir / 'wpa_supplicant.conf'

    def run_function(self, call):
        # Source the script with an argument that only defines things, then
        # call one of its functions with CONF pointed at a scratch file.
        script = f'CONF={self.conf}\n. {WIFI} __define_only__ 2>/dev/null\nCONF={self.conf}\n{call}\n'
        return subprocess.run(['sh', '-c', script], capture_output=True, text=True, timeout=20)

    def test_psk_config_is_written_complete_and_private(self):
        r = self.run_function('write_conf_psk "Workshop" "correct-horse-1"; echo rc=$?')
        self.assertIn('rc=0', r.stdout, r.stderr)
        text = self.conf.read_text()
        self.assertIn('ssid="Workshop"', text)
        self.assertIn('psk="correct-horse-1"', text)
        self.assertIn('key_mgmt=WPA-PSK', text)
        self.assertEqual(text.count('}'), 1, 'the network block must be closed')
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o600)

    def test_open_config_is_written(self):
        r = self.run_function('write_conf_open "Cafe"; echo rc=$?')
        self.assertIn('rc=0', r.stdout, r.stderr)
        self.assertIn('key_mgmt=NONE', self.conf.read_text())

    def test_umask_is_put_back(self):
        r = self.run_function('umask 022; write_conf_psk a b; umask')
        self.assertTrue(r.stdout.strip().endswith('022'), r.stdout)

    def test_no_heredoc_ends_inside_a_subshell(self):
        # The exact shape the board's ash cannot run: a heredoc opened on a
        # line with "(" whose terminator is followed by a ")" line.
        src = WIFI.read_text().splitlines()
        for i, line in enumerate(src):
            if '<<' in line and re.search(r'\(\s*[^)]*<<', line):
                self.fail(f'line {i+1}: heredoc inside a ( subshell ): {line.strip()}')

    def test_quote_and_newline_in_credentials_are_refused(self):
        for bad in ('a"b', 'a\\b', 'a\nb', ''):
            r = self.run_function(f'write_conf_psk "net" {bad!r}; echo rc=$?')
            self.assertIn('rc=1', r.stdout, f'{bad!r} was accepted')

    def connect_with(self, ifup_body, ip_out=''):
        log = self.dir / 'wpa.log'
        calls = self.dir / 'calls'
        fakes = f'''
WPALOG={log}
CONNECT_WAIT=3
ifup() {{ {ifup_body}; }}
ifdown() {{ echo ifdown >> {calls}; }}
killall() {{ echo "killall $*" >> {calls}; }}
ip() {{ printf '%s' "{ip_out}"; }}
sleep() {{ :; }}
'''
        r = self.run_function(fakes + 'apply_conf "Home"; echo rc=$?')
        return r, calls.read_text() if calls.exists() else ''

    def test_wrong_password_is_reported_and_the_retries_stop(self):
        r, calls = self.connect_with(
            f'echo "espsta0: CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid=\\"Home\\" reason=WRONG_KEY" > {self.dir}/wpa.log')
        self.assertIn('rc=2', r.stdout, r.stderr)
        self.assertIn('Wrong password', r.stderr)
        self.assertGreaterEqual(calls.count('killall -q wpa_supplicant'), 2, calls)

    def test_connect_prints_the_address(self):
        r, _ = self.connect_with(':', '    inet 192.168.1.86/24 brd 192.168.1.255 scope global espsta0\n')
        self.assertIn('rc=0', r.stdout, r.stderr)
        self.assertIn('192.168.1.86', r.stdout)

    def test_connect_gives_up_waiting_but_leaves_it_running(self):
        r, calls = self.connect_with(':')
        self.assertIn('rc=3', r.stdout, r.stderr)
        self.assertEqual(calls.count('killall -q wpa_supplicant'), 1, calls)

    def test_scan_stops_a_wrong_password_loop_first(self):
        log = self.dir / 'wpa.log'
        log.write_text('reason=WRONG_KEY\n')
        calls = self.dir / 'calls'
        fakes = f'''
WPALOG={log}
ifdown() {{ echo ifdown >> {calls}; }}
killall() {{ echo "killall $*" >> {calls}; }}
ip() {{ :; }}
mktemp() {{ echo {self.dir}/raw; }}
iw() {{
    case "$*" in
    *link*) echo "Not connected." ;;
    *scan*) printf 'BSS 00:11 (on espsta0)\\n\\tsignal: -50.00 dBm\\n\\tSSID: Home\\n\\tRSN:\\t * Version: 1\\n' ;;
    esac
}}
'''
        r = self.run_function(fakes + 'raw_scan')
        self.assertIn('-50\tSEC\tHome', r.stdout, r.stderr)
        self.assertIn('killall -q wpa_supplicant', calls.read_text())
        self.assertFalse((self.dir / 'raw').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
