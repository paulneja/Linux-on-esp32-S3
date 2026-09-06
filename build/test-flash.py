#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
TABLE = Path('new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r')


class FlashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='esp32 flash test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / 'images'
        self.images.mkdir()
        shutil.copy2(REPO / 'flash.sh', self.root / 'flash.sh')
        self.table = self.root / TABLE
        self.table.parent.mkdir(parents=True)
        shutil.copy2(REPO / TABLE, self.table)
        shutil.copy2(REPO / 'images/partition-table.bin', self.images)
        for name, size in {
            'bootloader.bin': 4096, 'network_adapter.bin': 4096,
            'etc.jffs2': 4096, 'xipImage': 4096, 'rootfs.cramfs': 4096,
            'home.jffs2': 0x340000, 'linux-esp32s3-native-full.bin': 0x1000000,
        }.items():
            with (self.images / name).open('wb') as stream:
                stream.truncate(size)
        self.log = self.root / 'calls.jsonl'
        mock_dir = self.root / 'bin'
        mock_dir.mkdir()
        mock = mock_dir / 'esptool.py'
        mock.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
with open(os.environ['FLASH_TEST_LOG'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if 'erase_flash' in sys.argv and os.environ.get('FAIL_ERASE') == '1':
    sys.exit(9)
if 'write_flash' in sys.argv and os.environ.get('FAIL_WRITE') == '1':
    sys.exit(8)
''')
        mock.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(mock_dir) + ':' + os.environ['PATH'],
                    'FLASH_TEST_LOG': str(self.log)}

    def run_flash(self, *args):
        result = subprocess.run(['sh', self.root / 'flash.sh', '-p', 'COM test', *args],
                                env=self.env, capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls

    def reject(self, *args):
        result, calls = self.run_flash(*args)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(calls, [], 'esptool must not run after a failed preflight')
        self.assertIn('preflight failed', result.stderr)

    def test_full_write_without_erase(self):
        result, calls = self.run_flash()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn('COM test', calls[0])
        self.assertEqual(calls[0][-2:], ['0x0', str(self.images / 'linux-esp32s3-native-full.bin')])
        self.assertIn('even without --erase', result.stdout)

    def test_full_erase_then_write(self):
        result, calls = self.run_flash('--erase')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertIn('erase_flash', calls[0])
        self.assertIn('write_flash', calls[1])

    def test_parts_preserve_home_but_write_etc(self):
        (self.images / 'home.jffs2').unlink()
        result, calls = self.run_flash('--parts')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(str(self.images / 'home.jffs2'), calls[0])
        self.assertIn(str(self.images / 'etc.jffs2'), calls[0])
        self.assertIn('preserves /home but overwrites /etc', result.stdout)

    def test_parts_erase_with_paths_containing_spaces(self):
        result, calls = self.run_flash('--parts', '--erase')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertIn('erase_flash', calls[0])
        self.assertEqual(calls[1][-2:], [str(0xcc0000), str(self.images / 'home.jffs2')])
        self.assertIn('COM test', calls[1])

    def test_missing_each_part_never_erases(self):
        for name in ('bootloader.bin', 'partition-table.bin', 'network_adapter.bin',
                     'etc.jffs2', 'xipImage', 'rootfs.cramfs', 'home.jffs2'):
            with self.subTest(name=name):
                path = self.images / name
                saved = path.with_suffix('.saved')
                path.rename(saved)
                try:
                    self.reject('--parts', '--erase')
                finally:
                    saved.rename(path)

    def test_missing_full_image_never_erases(self):
        (self.images / 'linux-esp32s3-native-full.bin').unlink()
        self.reject('--erase')

    def test_truncated_full_image_never_erases(self):
        (self.images / 'linux-esp32s3-native-full.bin').write_bytes(b'bad')
        self.reject('--erase')

    def test_oversized_full_image_never_erases(self):
        with (self.images / 'linux-esp32s3-native-full.bin').open('ab') as stream:
            stream.write(b'x')
        self.reject('--erase')

    def test_empty_part_never_erases(self):
        (self.images / 'xipImage').write_bytes(b'')
        self.reject('--parts', '--erase')

    def test_oversized_part_never_erases(self):
        with (self.images / 'xipImage').open('wb') as stream:
            stream.truncate(0x400001)
        self.reject('--parts', '--erase')

    def test_truncated_home_never_erases(self):
        (self.images / 'home.jffs2').write_bytes(b'bad')
        self.reject('--parts', '--erase')

    def test_missing_csv_never_erases(self):
        self.table.unlink()
        self.reject('--parts', '--erase')

    def test_bad_csv_never_erases(self):
        original = self.table.read_text()
        for text in (
            original.replace('0x00cc0000', 'not-a-number'),
            original.replace('0x00cc0000', '$(touch injected)'),
            original.replace('0x00cc0000', '0x00cb0000'),
            original.replace('0x00cc0000', '0x00cc0001'),
            original.replace('0x00340000', '0x00350000'),
            original.replace('0x00340000', '0'),
            original.replace('0x00340000', '-4096'),
            original.replace('0x00340000', '0x00330000'),
            original + original.splitlines()[-1] + '\n',
            '\n'.join(original.splitlines()[:-1]),
        ):
            with self.subTest(csv=text):
                self.table.write_text(text)
                self.reject('--parts', '--erase')

    def test_corrupt_binary_table_never_erases(self):
        (self.images / 'partition-table.bin').write_bytes(b'bad' * 100)
        self.reject('--parts', '--erase')

    def test_failed_erase_stops_before_write(self):
        self.env['FAIL_ERASE'] = '1'
        result, calls = self.run_flash('--erase')
        self.assertEqual(result.returncode, 9)
        self.assertEqual(len(calls), 1)
        self.assertIn('erase_flash', calls[0])
        self.assertNotIn('Done.', result.stdout)

    def test_failed_write_is_not_success(self):
        self.env['FAIL_WRITE'] = '1'
        result, calls = self.run_flash()
        self.assertEqual(result.returncode, 8)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('Done.', result.stdout)

    def test_help_without_images_or_device_access(self):
        shutil.rmtree(self.images)
        result, calls = self.run_flash('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        self.assertIn('Usage:', result.stdout)
        self.assertNotIn('set -eu', result.stdout)

    def test_unknown_option_never_accesses_device(self):
        result, calls = self.run_flash('--wrong')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertIn('unknown option', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
