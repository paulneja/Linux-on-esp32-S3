#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / 'new-files/board/espressif/esp32s3/rootfs_overlay/etc/profile.d/low-memory-shell.sh'
ENV_FILE = ROOT / 'new-files/board/espressif/esp32s3/rootfs_overlay/etc/dash-resume'


class ShellFallbackTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.pref = self.dir / 'pref'
        self.resume = self.dir / 'resume'
        self.stub = self.dir / 'dash'
        self.stub.write_text('#!/bin/sh\nexec /bin/sh "$@"\n')
        self.stub.chmod(0o755)

    def run_shell(self, script, threshold):
        env = {**os.environ, 'LOWMEM_DASH': str(self.stub), 'LOWMEM_ENV': str(ENV_FILE),
               'LOWMEM_RESUME': str(self.resume), 'LOWMEM_PREF': str(self.pref),
               'LOWMEM_THRESHOLD': str(threshold)}
        return subprocess.run(['bash', '--rcfile', str(HOOK), '-i'], input=script,
                              env=env, capture_output=True, text=True, timeout=30)

    def read(self, path):
        return path.read_text().strip() if path.exists() else ''

    def test_switches_and_retries_when_memory_is_low(self):
        result = self.run_shell('false\n', threshold=99999999)
        self.assertIn('switching to dash and retrying', result.stderr)
        self.assertIn('retrying: false', result.stderr)
        self.assertEqual(self.read(self.pref), 'dash')

    def test_reports_the_available_memory_it_saw(self):
        result = self.run_shell('false\n', threshold=99999999)
        self.assertRegex(result.stderr, r'cannot fork with \d+ KiB free')

    def test_stays_in_bash_when_memory_is_fine(self):
        result = self.run_shell('false\necho STILL_BASH_$BASH_VERSION\n', threshold=1)
        self.assertNotIn('switching to dash', result.stderr)
        self.assertIn('STILL_BASH_', result.stdout)
        self.assertEqual(self.read(self.pref), '')

    def test_a_successful_command_never_switches(self):
        result = self.run_shell('true\n', threshold=99999999)
        self.assertNotIn('switching to dash', result.stderr)
        self.assertEqual(self.read(self.pref), '')

    def test_the_resume_file_is_consumed_once(self):
        self.run_shell('false\n', threshold=99999999)
        self.assertEqual(self.read(self.resume), '')

    def test_detection_uses_no_command_substitution(self):
        text = HOOK.read_text()
        self.assertNotIn('$(', text, 'a command substitution forks, which is what must be avoided')
        self.assertNotIn('`', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
