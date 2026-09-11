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
        self.resume = self.dir / 'resume'
        self.stub = self.dir / 'dash'
        self.stub.write_text('#!/bin/sh\nexec /bin/sh "$@"\n')
        self.stub.chmod(0o755)
        # Running a file that exists but is not executable is how a test gets
        # bash to exit 126 without having to exhaust the machine's memory,
        # which is the status a failed fork produces on the board.
        self.unrunnable = self.dir / 'cannot-exec'
        self.unrunnable.write_text('#!/bin/sh\ntrue\n')
        self.unrunnable.chmod(0o644)

    def run_shell(self, script, threshold, answer=''):
        # LC_ALL=C so the assertions below match bash's own messages rather
        # than whatever language the developer's host is set to.
        env = {**os.environ, 'LOWMEM_DASH': str(self.stub), 'LOWMEM_ENV': str(ENV_FILE),
               'LOWMEM_RESUME': str(self.resume), 'LOWMEM_THRESHOLD': str(threshold),
               'LC_ALL': 'C', 'LANG': 'C'}
        return subprocess.run(['bash', '--rcfile', str(HOOK), '-i'], input=script + answer,
                              env=env, capture_output=True, text=True, timeout=30)

    def resume_files(self):
        return sorted(p.name for p in self.dir.glob('resume.*'))

    def test_switches_when_a_fork_fails_and_memory_is_low(self):
        result = self.run_shell(f'{self.unrunnable}\n', threshold=99999999, answer='n\n')
        self.assertIn('could not fork', result.stderr)
        self.assertIn('switching this session to dash', result.stderr)

    def test_it_asks_before_rerunning_and_honours_no(self):
        result = self.run_shell(f'{self.unrunnable}\n', threshold=99999999, answer='n\n')
        self.assertIn('This command did not run:', result.stderr)
        self.assertIn('Run it now in dash?', result.stderr)
        self.assertIn('Not run.', result.stderr)

    def test_yes_runs_the_command(self):
        script = 'echo MARKER_BEFORE; %s\n' % self.unrunnable
        result = self.run_shell(script, threshold=99999999, answer='y\n')
        self.assertIn('Permission denied', result.stderr)
        self.assertNotIn('Not run.', result.stderr)

    def test_an_ordinary_failure_never_switches(self):
        # grep with no match, a failed test, a command that exits 1: none of
        # these is a fork failure and none of them may be retried.
        for command in ('false', 'grep -q nothing /dev/null', 'test 1 = 2'):
            with self.subTest(command=command):
                result = self.run_shell(command + '\necho STILL_BASH_$BASH_VERSION\n',
                                        threshold=99999999)
                self.assertNotIn('switching this session to dash', result.stderr)
                self.assertIn('STILL_BASH_', result.stdout)

    def test_a_missing_command_never_switches(self):
        # 127, not 126: nothing was ever forked for it.
        result = self.run_shell('no_such_command_here\necho STILL_BASH\n', threshold=99999999)
        self.assertNotIn('switching this session to dash', result.stderr)
        self.assertIn('STILL_BASH', result.stdout)

    def test_stays_in_bash_when_memory_is_fine(self):
        result = self.run_shell(f'{self.unrunnable}\necho STILL_BASH_$BASH_VERSION\n', threshold=1)
        self.assertNotIn('switching this session to dash', result.stderr)
        self.assertIn('STILL_BASH_', result.stdout)

    def test_a_successful_command_never_switches(self):
        result = self.run_shell('true\n', threshold=99999999)
        self.assertNotIn('switching this session to dash', result.stderr)

    def test_the_resume_file_is_per_process_and_consumed(self):
        self.run_shell(f'{self.unrunnable}\n', threshold=99999999, answer='n\n')
        self.assertEqual(self.resume_files(), [], 'the resume file must be removed once read')

    def test_the_resume_path_is_not_shared_between_sessions(self):
        text = (ENV_FILE.read_text(), HOOK.read_text())
        for body in text:
            self.assertIn('$$', body, 'the resume file has to be per process')

    def test_detection_uses_no_command_substitution(self):
        for path in (HOOK, ENV_FILE):
            with self.subTest(path=path.name):
                body = path.read_text()
                self.assertNotIn('$(', body, 'a command substitution forks, which is what must be avoided')
                self.assertNotIn('`', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
