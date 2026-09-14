#!/usr/bin/env python3
"""usr/bin/wifi: the configuration it writes, and one shape it must not have.

`wifi connect` never worked on the board. Its two heredocs sat inside a
( subshell ), and the busybox ash in the image cannot finish a heredoc whose
body ends inside parentheses -- "unexpected EOF in here document", and
nothing written. `sh -n` accepts it, the host's busybox accepts it, only the
board's does not, so no host check caught it. These tests run the script's
functions under whatever sh is here, and separately refuse the shape itself.
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
