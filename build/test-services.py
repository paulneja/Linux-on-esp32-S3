#!/usr/bin/env python3
"""Small board scripts on the host: S01clock, 50-set-clock, use-shell, S46blewifi,
ble-prov, usb-console and S47usbconsole. Absolute paths are pointed at a temp
dir and kill at a fake, so nothing here touches the host."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
SH = os.environ.get('BOARD_SH', 'sh')
OVERLAY = ROOT / 'new-files/board/espressif/esp32s3/rootfs_overlay'


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='services-'))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.bin = self.dir / 'bin'
        self.bin.mkdir()
        self.log = self.dir / 'calls'
        self.log.write_text('')
        self.fake('id', 'echo 0')
        self.fake('fakekill', 'echo "kill $*" >> %s' % self.log)
        self.env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}'}

    def fake(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def install(self, rel, paths=()):
        text = (OVERLAY / rel).read_text()
        for old, new in paths:
            text = text.replace(old, str(new))
        text = re.sub(r'(?<![\w-])kill (?=[-"$])', 'fakekill ', text)
        self.assertIsNone(re.search(r'(?<![\w-])kill\b', text), f'{rel} would signal a host process')
        path = self.dir / Path(rel).name
        path.write_text(text)
        path.chmod(0o755)
        return path

    def run_script(self, path, *args, env=None):
        return subprocess.run([SH, str(path), *args], capture_output=True, text=True,
                              env={**self.env, **(env or {})}, timeout=30)

    def calls(self):
        return self.log.read_text()


class ClockTests(Base):
    def setUp(self):
        super().setUp()
        self.stamp = self.dir / 'clock'
        self.fake('date', f'''case "$*" in
"-u +%s") echo "$NOW" ;;
"-u -s @"*) echo "set $3" >> {self.log} ;;
*) echo 2026-10-05 ;;
esac''')
        self.script = self.install('etc/init.d/S01clock', [('/home/.clock', self.stamp)])

    def test_a_newer_stamp_sets_the_clock(self):
        self.stamp.write_text('1790000000\n')
        r = self.run_script(self.script, 'start', env={'NOW': '10'})
        self.assertEqual(r.returncode, 0)
        self.assertIn('set @1790000000', self.calls())
        self.assertIn('Clock restored', r.stdout)

    def test_an_older_or_broken_stamp_is_left_alone(self):
        for saved in ('5\n', 'garbage\n', '\n', '17x9\n'):
            self.stamp.write_text(saved)
            r = self.run_script(self.script, 'start', env={'NOW': '1790000000'})
            self.assertEqual((r.returncode, r.stdout), (0, ''), saved)
        self.assertEqual(self.calls(), '')

    def test_no_stamp_is_fine(self):
        self.assertEqual(self.run_script(self.script, 'start', env={'NOW': '1'}).returncode, 0)

    def test_stop_saves_now_and_never_fails(self):
        r = self.run_script(self.script, 'stop', env={'NOW': '1791234567'})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.stamp.read_text(), '1791234567\n')
        self.stamp.unlink()
        self.stamp.mkdir()
        self.assertEqual(self.run_script(self.script, 'stop', env={'NOW': '1'}).returncode, 0)


class NtpHookTests(Base):
    def setUp(self):
        super().setUp()
        self.ntpd = self.bin / 'ntpd'
        self.fake('ntpd', f'echo "ntpd $*" >> {self.log}; exit ${{NTP_RC:-0}}')
        self.fake('date', 'case "$*" in "+%Y") echo "$YEAR" ;; *) echo "Mon Oct 5 2026" ;; esac')
        self.netlog = self.dir / 'network.log'
        self.pidfile = self.dir / 'ntpd.pid'
        self.script = self.install('usr/share/udhcpc/default.script.d/50-set-clock',
                                   [('/usr/sbin/ntpd', self.ntpd), ('/var/log/network.log', self.netlog),
                                    ('/run/set-clock.ntpd.pid', self.pidfile)])

    def wait_for(self, text):
        end = time.time() + 10
        while time.time() < end:
            if self.netlog.exists() and text in self.netlog.read_text():
                return
            time.sleep(0.05)
        self.fail(f'{text!r} never reached the log: {self.netlog.read_text() if self.netlog.exists() else None}')

    def test_bound_asks_ntp_and_logs_the_result(self):
        self.assertEqual(self.run_script(self.script, 'bound', env={'YEAR': '1970'}).returncode, 0)
        self.wait_for('clock: set to')
        self.assertIn('ntpd -n -q -p pool.ntp.org', self.calls())

    def test_a_failed_ntp_says_so(self):
        self.run_script(self.script, 'bound', env={'YEAR': '1970', 'NTP_RC': '1'})
        self.wait_for('NTP did not answer')

    def test_renew_only_asks_while_the_clock_is_wrong(self):
        self.run_script(self.script, 'renew', env={'YEAR': '2026'})
        time.sleep(0.3)
        self.assertNotIn('ntpd', self.calls())
        self.run_script(self.script, 'renew', env={'YEAR': '1970'})
        self.wait_for('clock: set to')

    def test_other_events_do_nothing(self):
        for event in ('deconfig', 'leasefail', 'nak'):
            self.assertEqual(self.run_script(self.script, event, env={'YEAR': '1970'}).returncode, 0)
        time.sleep(0.3)
        self.assertEqual(self.calls(), '')

    def test_a_previous_run_is_stopped_first(self):
        self.pidfile.write_text('4242\n')
        self.run_script(self.script, 'bound', env={'YEAR': '1970'})
        self.wait_for('clock: set to')
        self.assertIn('kill 4242', self.calls())


class UseShellTests(Base):
    def setUp(self):
        super().setUp()
        self.home = self.dir / 'home'
        self.home.mkdir()
        self.bash = self.dir / 'bash'
        self.dash = self.dir / 'dash'
        for p in (self.bash, self.dash):
            p.write_text('')
            p.chmod(0o755)
        self.script = self.install('usr/bin/use-shell', [('/bin/bash', self.bash), ('/usr/bin/dash', self.dash)])

    def use(self, *args, home=True):
        env = {'HOME': str(self.home)} if home else {'HOME': ''}
        return self.run_script(self.script, *args, env=env)

    def test_status_defaults_to_bash_and_follows_the_choice(self):
        self.assertIn('preference: bash', self.use().stdout)
        self.assertEqual(self.use('dash').returncode, 0)
        self.assertEqual((self.home / '.shell').read_text(), 'dash\n')
        self.assertIn('preference: dash', self.use('status').stdout)
        self.use('bash')
        self.assertEqual((self.home / '.shell').read_text(), 'bash\n')

    def test_a_missing_shell_or_home_is_refused(self):
        self.dash.unlink()
        r = self.use('dash')
        self.assertEqual(r.returncode, 1)
        self.assertIn('not installed', r.stderr)
        self.assertFalse((self.home / '.shell').exists())
        self.assertEqual(self.use('bash', home=False).returncode, 1)
        self.assertEqual(self.use('zsh').returncode, 2)


class BleTests(Base):
    def setUp(self):
        super().setUp()
        self.ble = self.dir / 'esp-ble'
        self.ble.write_text('')
        self.prov = self.dir / 'ble-prov.d'
        self.wpa = self.dir / 'wpa_supplicant.conf'
        self.fake('start-stop-daemon', f'echo "ssd $*" >> {self.log}; '
                                       f'case "$*" in *-K*-t*) [ -e {self.dir}/running ] ;; esac')
        self.fake('sleep', 'exit 0')
        paths = [('/dev/esp-ble', self.ble), ('/etc/ble-prov', self.prov),
                 ('/etc/wpa_supplicant.conf', self.wpa), ('/var/run/', f'{self.dir}/')]
        self.init = self.install('etc/init.d/S46blewifi', paths)
        self.cmd = self.install('usr/sbin/ble-prov', paths + [('/etc/init.d/S46blewifi', self.init)])

    def started(self):
        return 'ssd -S' in self.calls()

    def test_starts_only_until_wifi_is_configured(self):
        r = self.run_script(self.init, 'start')
        self.assertTrue(self.started())
        self.log.write_text('')
        self.wpa.write_text('network={}\n')
        r = self.run_script(self.init, 'start')
        self.assertIn('not started (wifi already configured', r.stdout)
        self.assertFalse(self.started())

    def test_no_ble_device_means_nothing(self):
        self.ble.unlink()
        r = self.run_script(self.init, 'start')
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertFalse(self.started())

    def test_on_off_auto_switch_the_files_and_the_service(self):
        self.wpa.write_text('network={}\n')
        r = self.run_script(self.cmd, 'on')
        self.assertTrue((self.prov / 'always').exists())
        self.assertTrue(self.started())
        self.assertIn('setting: on', self.run_script(self.cmd, 'status').stdout)
        self.log.write_text('')
        self.run_script(self.cmd, 'off')
        self.assertTrue((self.prov / 'never').exists())
        self.assertFalse((self.prov / 'always').exists())
        self.assertIn('ssd -K', self.calls())
        self.log.write_text('')
        r = self.run_script(self.init, 'start')
        self.assertFalse(self.started())
        self.assertIn('disabled (ble-prov on', self.run_script(self.init, 'status').stdout)
        self.run_script(self.cmd, 'auto')
        self.assertEqual(sorted(p.name for p in self.prov.iterdir()), [])
        self.assertIn('setting: auto', self.run_script(self.cmd, 'status').stdout)

    def test_status_says_running(self):
        (self.dir / 'running').write_text('')
        self.assertIn('BLE WiFi setup: running', self.run_script(self.init, 'status').stdout)

    def test_bad_argument(self):
        self.assertEqual(self.run_script(self.cmd, 'maybe').returncode, 1)


class UsbConsoleTests(Base):
    def setUp(self):
        super().setUp()
        self.tab = self.dir / 'inittab'
        self.tab.write_text('::sysinit:/etc/init.d/rcS\nconsole::respawn:/sbin/getty -L console 0 vt100\n')
        self.fake('pidof', 'exit 1')
        self.fake('sleep', 'exit 0')
        self.cmd = self.install('usr/sbin/usb-console', [('/etc/inittab', self.tab)])
        self.init = self.install('etc/init.d/S47usbconsole', [('/etc/inittab', self.tab)])

    def test_on_adds_one_getty_and_off_comments_it(self):
        self.assertIn('kernel messages only', self.run_script(self.cmd, 'status').stdout)
        self.assertEqual(self.run_script(self.cmd, 'on').returncode, 0)
        self.assertEqual(self.tab.read_text().count('ttyGS3::respawn'), 1)
        self.assertIn('kill -HUP 1', self.calls())
        self.assertIn('already enabled', self.run_script(self.cmd, 'on').stdout)
        self.assertEqual(self.tab.read_text().count('ttyGS3::'), 1)
        self.run_script(self.cmd, 'off')
        self.assertIn('#ttyGS3::respawn', self.tab.read_text())
        self.run_script(self.cmd, 'on')
        self.assertEqual(self.tab.read_text().count('ttyGS3::'), 1)
        self.assertIn('login enabled', self.run_script(self.cmd, 'status').stdout)

    def test_boot_only_pokes_init_when_enabled(self):
        self.run_script(self.init, 'start')
        self.assertEqual(self.calls(), '')
        self.run_script(self.cmd, 'on')
        self.log.write_text('')
        self.assertEqual(self.run_script(self.init, 'start').returncode, 0)
        self.assertIn('kill -HUP 1', self.calls())


if __name__ == '__main__':
    unittest.main(verbosity=2)
