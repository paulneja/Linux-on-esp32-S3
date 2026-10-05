#!/usr/bin/env python3
"""usr/sbin/remote-login, ssh-server and web-server on the host, against a fake /etc."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SBIN = ROOT / 'new-files/board/espressif/esp32s3/rootfs_overlay/usr/sbin'
WEB = '#80\tstream\ttcp\tnowait\twww-data\t/usr/sbin/httpd\thttpd -i -h /home/www\n'
OLD = ('ssh\tstream\ttcp\tnowait\troot\t/usr/sbin/dropbear\tdropbear -i -R -I 600\n'
       '#telnet\tstream\ttcp\tnowait\troot\t/usr/sbin/telnetd\ttelnetd -i\n')


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='remote-login-'))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.etc = self.dir / 'etc'
        self.etc.mkdir()
        self.home = self.dir / 'root'
        self.bin = self.dir / 'bin'
        self.bin.mkdir()
        self.dropbear = self.dir / 'dropbear'
        self.dropbear.write_text('')
        self.dropbear.chmod(0o755)
        self.www = self.dir / 'www'
        self.www.mkdir()
        (self.www / 'index.html').write_text('hi\n')
        self.inetd = self.etc / 'inetd.conf'
        self.inetd.write_text(WEB)
        self.fake('id', 'case "$*" in "-u") echo 0 ;; "-u www-data") echo 33 ;; *) exit 0 ;; esac')
        self.fake('killall', 'echo "$@" >> %s/killall.log' % self.dir)
        (self.bin / 'remote-login').symlink_to(SBIN / 'remote-login')

    def fake(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def run_sbin(self, name, *args):
        env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
               'REMOTE_LOGIN_ETC': str(self.etc), 'REMOTE_LOGIN_DROPBEAR': str(self.dropbear),
               'REMOTE_LOGIN_HOME': str(self.home), 'WEB_SERVER_CONF': str(self.inetd),
               'WEB_SERVER_DOCROOT': str(self.www)}
        return subprocess.run(['sh', str(SBIN / name), *args], capture_output=True,
                              text=True, env=env, timeout=20)

    def ok(self, name, *args):
        r = self.run_sbin(name, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def lines(self):
        return [line.split('\t') for line in self.inetd.read_text().splitlines() if line]

    def line(self, program):
        found = [f for f in self.lines() if f[5] == '/usr/sbin/' + program]
        self.assertEqual(len(found), 1, self.inetd.read_text())
        return found[0]

    def listening(self, program):
        return not self.line(program)[0].startswith('#')


class RemoteLoginTests(Base):
    def test_ssh_on_the_default_port_takes_password_and_keys(self):
        r = self.ok('remote-login', 'ssh')
        self.assertIn('SSH on port 22 (password or key)', r.stdout)
        ssh = self.line('dropbear')
        self.assertEqual((ssh[0], ssh[6]), ('22', 'dropbear -i -R -I 600'))
        self.assertFalse(self.listening('telnetd'))
        self.assertIn('-HUP inetd', (self.dir / 'killall.log').read_text())

    def test_port_moves_ssh_and_survives_switching(self):
        self.ok('remote-login', 'ssh')
        self.ok('remote-login', 'port', 'ssh', '2222')
        self.assertEqual(self.line('dropbear')[0], '2222')
        self.assertTrue(self.listening('dropbear'))
        self.ok('remote-login', 'telnet')
        self.ok('remote-login', 'ssh')
        self.assertEqual(self.line('dropbear')[0], '2222')
        self.assertIn('SSH_PORT=2222', (self.etc / 'remote-login.conf').read_text())
        self.ok('remote-login', 'port', 'ssh', 'default')
        self.assertEqual(self.line('dropbear')[0], '22')

    def test_telnet_port(self):
        self.ok('remote-login', 'telnet')
        r = self.ok('remote-login', 'port', 'telnet', '2323')
        self.assertIn('Telnet port is 2323', r.stdout)
        self.assertEqual(self.line('telnetd')[0], '2323')
        self.assertTrue(self.listening('telnetd'))
        self.assertFalse(self.listening('dropbear'))

    def test_auth_modes_pick_the_dropbear_flags(self):
        self.ok('remote-login', 'ssh')
        for mode, args, text in (('password', 'dropbear -i -R -I 600 -n', 'password only'),
                                 ('key', 'dropbear -i -R -I 600 -s', 'keys only'),
                                 ('both', 'dropbear -i -R -I 600', 'password or key')):
            r = self.ok('remote-login', 'auth', mode)
            self.assertIn(text, r.stdout)
            self.assertEqual(self.line('dropbear')[6], args)
            self.assertIn(f'SSH_AUTH={mode}', (self.etc / 'remote-login.conf').read_text())

    def test_keys_only_warns_without_a_key_and_not_with_one(self):
        r = self.ok('remote-login', 'auth', 'key')
        self.assertIn('authorized_keys yet', r.stderr)
        (self.home / '.ssh').mkdir(parents=True)
        (self.home / '.ssh/authorized_keys').write_text('ssh-ed25519 AAAA me\n')
        r = self.ok('remote-login', 'auth', 'key')
        self.assertEqual(r.stderr, '')

    def test_bad_ports_change_nothing(self):
        self.ok('remote-login', 'ssh')
        before = self.inetd.read_text()
        for port in ('0', '65536', 'abc', '022', '-1', ''):
            r = self.run_sbin('remote-login', 'port', 'ssh', port)
            self.assertNotEqual(r.returncode, 0, port)
        self.assertEqual(self.inetd.read_text(), before)
        self.assertFalse((self.etc / 'remote-login.conf').exists())

    def test_ssh_and_telnet_cannot_share_a_port_or_take_the_web_one(self):
        self.ok('remote-login', 'port', 'telnet', '2222')
        r = self.run_sbin('remote-login', 'port', 'ssh', '2222')
        self.assertIn('cannot share port 2222', r.stderr)
        r = self.run_sbin('remote-login', 'port', 'ssh', '80')
        self.assertIn('belongs to the web server', r.stderr)
        self.assertNotIn('SSH_PORT=80', (self.etc / 'remote-login.conf').read_text())

    def test_hand_edited_settings_take_effect_on_apply(self):
        self.ok('remote-login', 'ssh')
        (self.etc / 'remote-login.conf').write_text('SSH_PORT=2200\nSSH_AUTH=key\nJUNK\nTELNET_PORT=x\n')
        self.ok('remote-login', 'apply')
        ssh = self.line('dropbear')
        self.assertEqual((ssh[0], ssh[6]), ('2200', 'dropbear -i -R -I 600 -s'))
        self.assertEqual(self.line('telnetd')[0], '#23')

    def test_status_names_ports_and_auth(self):
        self.assertIn('Listening: nothing', self.ok('remote-login', 'status').stdout)
        self.ok('remote-login', 'ssh')
        self.ok('remote-login', 'port', 'ssh', '2022')
        self.ok('remote-login', 'auth', 'password')
        out = self.ok('remote-login').stdout
        self.assertIn('Listening: ssh', out)
        self.assertIn('SSH: port 2022, password only', out)
        self.assertIn('Telnet: port 23, off', out)

    def test_an_old_inetd_conf_is_rewritten_without_duplicates(self):
        self.inetd.write_text(WEB + OLD)
        (self.etc / 'remote-login').write_text('ssh\n')
        self.ok('remote-login', 'apply')
        self.assertEqual(len(self.lines()), 3)
        self.assertEqual(self.line('dropbear')[0], '22')
        self.assertTrue(self.listening('dropbear'))
        self.assertEqual(self.line('httpd')[0], '#80')

    def test_usage_on_nonsense(self):
        for args in (['port'], ['port', 'web', '81'], ['auth', 'maybe'], ['reboot']):
            r = self.run_sbin('remote-login', *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn('usage:', r.stderr)


class SshServerTests(Base):
    def test_on_adds_ssh_next_to_telnet_and_off_takes_it_away(self):
        self.ok('remote-login', 'telnet')
        self.ok('remote-login', 'port', 'ssh', '2222')
        self.ok('ssh-server', 'on')
        self.assertTrue(self.listening('dropbear'))
        self.assertTrue(self.listening('telnetd'))
        self.assertEqual(self.line('dropbear')[0], '2222')
        self.assertIn('SSH: enabled', self.ok('ssh-server', 'status').stdout)
        self.assertIn('Listening: ssh telnet', self.ok('remote-login', 'status').stdout)
        self.ok('ssh-server', 'off')
        self.assertFalse(self.listening('dropbear'))
        self.assertTrue(self.listening('telnetd'))
        self.assertIn('SSH: disabled', self.ok('ssh-server', 'status').stdout)

    def test_off_with_nothing_else_leaves_nothing(self):
        self.ok('ssh-server', 'on')
        self.assertEqual((self.etc / 'remote-login').read_text().split(), ['ssh'])
        self.ok('ssh-server', 'off')
        self.assertEqual((self.etc / 'remote-login').read_text().split(), ['off'])
        self.assertFalse(self.listening('dropbear'))


class WebServerTests(Base):
    def test_on_off_and_status_on_the_default_port(self):
        self.assertIn('disabled: port 80', self.ok('web-server', 'status').stdout)
        self.assertIn('enabled: port 80', self.ok('web-server', 'on').stdout)
        self.assertEqual(self.line('httpd')[0], '80')
        self.assertIn('already enabled', self.ok('web-server', 'on').stdout)
        self.ok('web-server', 'off')
        self.assertEqual(self.line('httpd')[0], '#80')

    def test_port_moves_the_page_and_keeps_its_state(self):
        self.ok('web-server', 'on')
        self.assertIn('port is 8080', self.ok('web-server', 'port', '8080').stdout)
        self.assertEqual(self.line('httpd')[0], '8080')
        self.assertIn('enabled: port 8080', self.ok('web-server', 'status').stdout)
        self.ok('web-server', 'off')
        self.assertEqual(self.line('httpd')[0], '#8080')
        self.ok('web-server', 'port', 'default')
        self.assertEqual(self.line('httpd')[0], '#80')

    def test_port_refuses_one_ssh_uses(self):
        self.ok('remote-login', 'ssh')
        r = self.run_sbin('web-server', 'port', '22')
        self.assertIn('already used', r.stderr)
        self.inetd.write_text(WEB + OLD)
        r = self.run_sbin('web-server', 'port', '22')
        self.assertIn('already used', r.stderr)
        for port in ('0', '70000', 'x'):
            self.assertNotEqual(self.run_sbin('web-server', 'port', port).returncode, 0)
        self.assertEqual(self.line('httpd')[0], '#80')

    def test_migrate_moves_an_old_www_line_to_home_www(self):
        self.inetd.write_text('80\tstream\ttcp\tnowait\troot\t/usr/sbin/httpd\thttpd -i -h /www\n')
        self.ok('web-server', 'migrate')
        self.assertEqual(self.line('httpd')[4:], ['www-data', '/usr/sbin/httpd', 'httpd -i -h /home/www'])
        self.assertEqual(self.line('httpd')[0], '80')
        self.assertTrue((self.etc / 'inetd.conf.before-home-www').exists())

    def test_migrate_leaves_a_custom_line_alone(self):
        custom = '80\tstream\ttcp\tnowait\troot\t/usr/sbin/httpd\thttpd -i -h /srv -p 9\n'
        self.inetd.write_text(custom)
        r = self.run_sbin('web-server', 'migrate')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('custom configuration', r.stderr)
        self.assertEqual(self.inetd.read_text(), custom)

    def test_no_line_yet_is_created_on_enable(self):
        self.inetd.write_text('')
        self.ok('web-server', 'on')
        self.assertEqual(self.line('httpd')[0], '80')


if __name__ == '__main__':
    unittest.main(verbosity=2)
