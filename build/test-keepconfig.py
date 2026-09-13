#!/usr/bin/env python3
"""Host tests for etc/init.d/S03keepconfig.

/etc is its own jffs2 partition and every flash rewrites it, so an update
takes the wifi credentials and the root password with it. This script copies
them to /home, which flash.sh --parts preserves, and puts them back when /etc
comes back from the factory. The rules it has to get right are all about when
NOT to restore, so that is most of what is tested here.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'new-files/board/espressif/esp32s3/rootfs_overlay/etc/init.d/S03keepconfig'


class KeepConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='keepconfig-'))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.etc = self.dir / 'etc'
        self.backup = self.dir / 'home/.etc-backup'
        (self.etc / 'dropbear').mkdir(parents=True)
        (self.dir / 'home').mkdir(exist_ok=True)
        self.mounts = self.dir / 'mounts'
        self.mounts.write_text('mtd:home /home jffs2 rw,relatime 0 0\n')

    def run_script(self, action):
        env = {**os.environ, 'KEEP_ETC': str(self.etc), 'KEEP_BACKUP': str(self.backup),
               'KEEP_MOUNTS': str(self.mounts)}
        result = subprocess.run(['sh', str(SCRIPT), action], capture_output=True,
                                text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def write(self, name, text, mode=0o644):
        path = self.etc / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)

    def configure(self):
        """A board someone has set up."""
        self.write('wpa_supplicant.conf', 'network={\n ssid="MyNet"\n psk="secret"\n}\n', 0o600)
        self.write('shadow', 'root:$6$MINE:19000:0:99999:7:::\n', 0o600)
        self.write('passwd', 'root:x:0:0:root:/home/root:/usr/bin/user-shell\n')
        self.write('group', 'root:x:0:\n')
        self.write('dropbear/dropbear_rsa_host_key', 'KEYDATA\n', 0o600)

    def reflash_etc(self):
        """What an update leaves behind: a factory /etc, no wifi."""
        shutil.rmtree(self.etc)
        (self.etc / 'dropbear').mkdir(parents=True)
        self.write('shadow', 'root:$6$FACTORY:19000:0:99999:7:::\n', 0o600)
        self.write('passwd', 'root:x:0:0:root:/home/root:/usr/bin/user-shell\n')

    def test_saves_every_file_with_its_mode(self):
        self.configure()
        self.run_script('stop')
        for name, mode in [('wpa_supplicant.conf', 0o600), ('shadow', 0o600),
                           ('passwd', 0o644), ('group', 0o644),
                           ('dropbear/dropbear_rsa_host_key', 0o600)]:
            saved = self.backup / name
            self.assertTrue(saved.is_file(), name)
            self.assertEqual(saved.stat().st_mode & 0o777, mode, name)

    def test_backup_directory_is_private(self):
        self.configure()
        self.run_script('stop')
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o700)

    def test_restores_after_an_update(self):
        self.configure()
        self.run_script('stop')
        self.reflash_etc()
        out = self.run_script('start')
        self.assertIn('ssid="MyNet"', (self.etc / 'wpa_supplicant.conf').read_text())
        self.assertIn('$6$MINE', (self.etc / 'shadow').read_text())
        self.assertEqual((self.etc / 'dropbear/dropbear_rsa_host_key').read_text(), 'KEYDATA\n')
        self.assertIn('restored /etc/wpa_supplicant.conf', out)

    def test_restored_modes_are_preserved(self):
        self.configure()
        self.run_script('stop')
        self.reflash_etc()
        self.run_script('start')
        self.assertEqual((self.etc / 'wpa_supplicant.conf').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.etc / 'shadow').stat().st_mode & 0o777, 0o600)

    def test_a_normal_boot_changes_nothing(self):
        # wifi is configured, so /etc was not reflashed: hands off, even
        # though a backup exists and differs.
        self.configure()
        self.run_script('stop')
        self.write('shadow', 'root:$6$CHANGED:19000:0:99999:7:::\n', 0o600)
        out = self.run_script('start')
        self.assertEqual(out, '')
        self.assertIn('$6$CHANGED', (self.etc / 'shadow').read_text())

    def test_no_backup_means_no_restore(self):
        self.reflash_etc()
        out = self.run_script('start')
        self.assertEqual(out, '')
        self.assertFalse((self.etc / 'wpa_supplicant.conf').exists())

    def test_disabled_marker_stops_both_halves(self):
        self.configure()
        self.run_script('stop')
        (self.backup / 'disabled').write_text('')
        self.write('wpa_supplicant.conf', 'network={\n ssid="Other"\n}\n', 0o600)
        self.run_script('stop')
        self.assertIn('MyNet', (self.backup / 'wpa_supplicant.conf').read_text())
        self.reflash_etc()
        self.assertEqual(self.run_script('start'), '')

    def test_read_only_home_is_not_an_error(self):
        self.configure()
        self.mounts.write_text('mtd:home /home jffs2 ro,relatime 0 0\n')
        self.assertEqual(self.run_script('stop'), '')
        self.assertFalse(self.backup.exists())

    def test_missing_files_are_skipped(self):
        # A board that never joined a network has no wpa_supplicant.conf,
        # but it may well have its own root password, and that must come
        # back after an update just the same.
        self.write('shadow', 'root:$6$MINE:19000:0:99999:7:::\n', 0o600)
        self.run_script('stop')
        self.assertTrue((self.backup / 'shadow').is_file())
        self.assertFalse((self.backup / 'wpa_supplicant.conf').exists())
        self.reflash_etc()
        self.assertIn('restored /etc/shadow', self.run_script('start'))
        self.assertIn('MINE', (self.etc / 'shadow').read_text())
        self.assertFalse((self.etc / 'wpa_supplicant.conf').exists())

    def test_deleting_the_wifi_config_does_not_bring_the_old_password_back(self):
        # The case that was wrong: the old gate took "no wpa_supplicant.conf"
        # as proof of a factory /etc. A user who removes the network and then
        # changes the password would get the old password restored on the
        # next boot -- and the network they deleted.
        self.configure()
        self.run_script('stop')
        (self.etc / 'wpa_supplicant.conf').unlink()
        self.write('shadow', 'root:$6$NEWER:19100:0:99999:7:::\n', 0o600)
        self.assertEqual(self.run_script('start'), '')
        self.assertIn('NEWER', (self.etc / 'shadow').read_text())
        self.assertFalse((self.etc / 'wpa_supplicant.conf').exists())

    def test_a_live_etc_is_stamped_and_the_stamp_survives_saves(self):
        self.configure()
        self.run_script('stop')
        stamp = (self.etc / '.keepconfig-generation').read_text()
        self.assertTrue(stamp.strip())
        self.assertEqual((self.backup / 'generation').read_text(), stamp)
        self.run_script('stop')
        self.assertEqual((self.etc / '.keepconfig-generation').read_text(), stamp)

    def test_a_restored_etc_is_stamped_so_the_next_boot_is_quiet(self):
        self.configure()
        self.run_script('stop')
        self.reflash_etc()
        self.assertIn('restored', self.run_script('start'))
        self.assertTrue((self.etc / '.keepconfig-generation').is_file())
        # second boot: live /etc now, nothing to do
        self.assertEqual(self.run_script('start'), '')

    def test_save_action_is_the_same_as_stop(self):
        self.configure()
        out = self.run_script('save')
        self.assertIn('Configuration saved', out)
        self.assertTrue((self.backup / 'wpa_supplicant.conf').is_file())

    def test_no_temporary_files_are_left_behind(self):
        self.configure()
        self.run_script('stop')
        self.reflash_etc()
        self.run_script('start')
        leftovers = [str(p) for p in list(self.etc.rglob('*.new')) + list(self.backup.rglob('*.new'))]
        self.assertEqual(leftovers, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
