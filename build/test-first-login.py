#!/usr/bin/env python3
"""usr/sbin/first-login and usr/sbin/remote-login on the host, with fake passwd."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SH = os.environ.get('BOARD_SH', 'sh')
SBIN = ROOT / 'new-files/board/espressif/esp32s3/rootfs_overlay/usr/sbin'
FACTORY = '$5$salt$FACTORY'
INETD = ('#ssh\tstream\ttcp\tnowait\troot\t/usr/sbin/dropbear\tdropbear -i -R -I 600\n'
         '#telnet\tstream\ttcp\tnowait\troot\t/usr/sbin/telnetd\ttelnetd -i\n'
         'www\tstream\ttcp\tnowait\twww-data\t/usr/sbin/httpd\thttpd -i -h /home/www\n')


class FirstLoginTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='first-login-'))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.etc = self.dir / 'etc'
        self.etc.mkdir()
        self.bin = self.dir / 'bin'
        self.bin.mkdir()
        self.dropbear = self.dir / 'dropbear'
        self.dropbear.write_text('')
        self.dropbear.chmod(0o755)
        (self.etc / 'inetd.conf').write_text(INETD)
        self.set_hash(FACTORY)
        self.fake('id', 'echo 0')
        self.fake('killall', 'exit 0')
        self.fake('mkpasswd', '[ "$3" = changeme123 ] || { echo \'$5$salt$OTHER\'; exit; }\n'
                              'case $2 in md5) echo \'$1$salt$FACTORY\' ;; *) echo \'%s\' ;; esac' % FACTORY)
        self.fake('passwd', f'''read -r a || exit 1
read -r b || exit 1
[ "$a" = "$b" ] || exit 1
if [ "$a" = changeme123 ]; then h='{FACTORY}'; else h='$5$salt$NEW'; fi
echo "root:$h:19000:0:99999:7:::" > {self.etc}/shadow''')
        self.fake('remote-login', f'exec {SH} {SBIN / "remote-login"} "$@"')

    def fake(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def set_hash(self, value):
        (self.etc / 'shadow').write_text(f'root:{value}:19000:0:99999:7:::\n')

    def run_first_login(self, answers, dropbear=True):
        env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
               'FIRST_LOGIN_ETC': str(self.etc), 'REMOTE_LOGIN_ETC': str(self.etc),
               'FIRST_LOGIN_DROPBEAR': str(self.dropbear if dropbear else self.dir / 'none'),
               'REMOTE_LOGIN_DROPBEAR': str(self.dropbear if dropbear else self.dir / 'none')}
        return subprocess.run([SH, str(SBIN / 'first-login')], input=answers,
                              capture_output=True, text=True, env=env, timeout=20)

    def listening(self):
        names = {'dropbear': 'ssh', 'telnetd': 'telnet', 'httpd': 'www'}
        lines = (self.etc / 'inetd.conf').read_text().splitlines()
        return sorted(names[line.split('\t')[5].rsplit('/', 1)[1]]
                      for line in lines if line and not line.startswith('#'))

    def test_factory_board_changes_the_password_and_picks_ssh(self):
        r = self.run_first_login('hunter22\nhunter22\n1\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('$5$salt$NEW', (self.etc / 'shadow').read_text())
        self.assertEqual((self.etc / 'remote-login').read_text(), 'ssh\n')
        self.assertEqual(self.listening(), ['ssh', 'www'])

    def test_the_factory_password_hashed_with_md5_still_counts(self):
        self.set_hash('$1$salt$FACTORY')
        r = self.run_first_login('hunter22\nhunter22\n3\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('factory password', r.stdout)
        self.assertIn('$5$salt$NEW', (self.etc / 'shadow').read_text())

    def test_the_factory_password_is_refused_as_the_new_one(self):
        r = self.run_first_login('changeme123\nchangeme123\nhunter22\nhunter22\n2\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('That is the factory password', r.stdout)
        self.assertEqual(self.listening(), ['telnet', 'www'])

    def test_a_closed_terminal_gives_up(self):
        r = self.run_first_login('')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.etc / 'remote-login').exists())
        self.assertEqual(self.listening(), ['www'])

    def test_an_updated_board_is_only_asked_the_way_in(self):
        self.set_hash('$5$salt$MINE')
        r = self.run_first_login('2\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('factory password', r.stdout)
        self.assertEqual(self.listening(), ['telnet', 'www'])

    def test_nothing_happens_once_chosen(self):
        (self.etc / 'remote-login').write_text('ssh\n')
        r = self.run_first_login('')
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_none_leaves_only_the_console(self):
        r = self.run_first_login('hunter22\nhunter22\n3\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.etc / 'remote-login').read_text(), 'off\n')
        self.assertEqual(self.listening(), ['www'])

    def test_no_ssh_server_offers_telnet_or_none(self):
        self.set_hash('$5$salt$MINE')
        r = self.run_first_login('1\n', dropbear=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn(') SSH', r.stdout)
        self.assertEqual(self.listening(), ['telnet', 'www'])
        (self.etc / 'remote-login').unlink()
        r = self.run_first_login('2\n', dropbear=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.listening(), ['www'])

    def test_switching_later_keeps_only_one(self):
        self.set_hash('$5$salt$MINE')
        self.run_first_login('1\n')
        env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
               'REMOTE_LOGIN_ETC': str(self.etc), 'REMOTE_LOGIN_DROPBEAR': str(self.dropbear)}
        r = subprocess.run([SH, str(SBIN / 'remote-login'), 'telnet'],
                           capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.listening(), ['telnet', 'www'])
        self.assertEqual((self.etc / 'remote-login').read_text(), 'telnet\n')
        r = subprocess.run([SH, str(SBIN / 'remote-login'), 'off'],
                           capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.listening(), ['www'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
