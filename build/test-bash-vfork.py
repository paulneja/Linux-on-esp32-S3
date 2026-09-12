#!/usr/bin/env python3
"""Host check for programs/bash-vfork.patch.

Builds the patched bash natively under AddressSanitizer and drives the vfork
path on a pty, so job control is on. This is how the use-after-free in the
first version of the patch was found: on the board it was a bare SIGSEGV with
no message, here it is a stack trace with a line number.

Needs: a C compiler, `script` from util-linux, and the bash tarball that
fetch-shell-tools.sh downloads. Skips cleanly when the tarball is absent.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
PROGRAMS = ROOT / 'experiments/mmu-poc/programs'
TARBALL_NAMES = ('bash-5.2.37.tar.gz',)
PATCHES = ('bash-fork.patch', 'bash-vfork.patch')


def find_tarball():
    for base in (ROOT / 'experiments/mmu-poc/out/programs/downloads',
                 *(ROOT / 'build-output').glob('reproduce.*/Linux-on-esp32-S3/experiments/mmu-poc/out/programs/downloads')):
        for name in TARBALL_NAMES:
            if (base / name).is_file():
                return base / name
    return None


class BashVforkTests(unittest.TestCase):
    bash = None

    @classmethod
    def setUpClass(cls):
        tarball = find_tarball()
        if tarball is None or shutil.which('script') is None or shutil.which('cc') is None:
            raise unittest.SkipTest('needs the bash tarball, cc and script(1)')
        cls.tmp = Path(tempfile.mkdtemp(prefix='bash-vfork-'))
        subprocess.run(['tar', '-xzf', str(tarball), '-C', str(cls.tmp)], check=True)
        src = next(cls.tmp.glob('bash-*'))
        for name in PATCHES:
            subprocess.run(['patch', '-p1', '--batch', '--forward', '-i', str(PROGRAMS / name)],
                           cwd=src, check=True, stdout=subprocess.DEVNULL)
        env = {**os.environ, 'CC': 'cc -std=gnu17',
               'CFLAGS': '-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -w',
               'LDFLAGS': '-fsanitize=address,undefined'}
        subprocess.run(['./configure', '--without-bash-malloc', '--disable-nls'], cwd=src,
                       env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['make', '-j', str(os.cpu_count() or 2), 'bash'], cwd=src,
                       env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.bash = src / 'bash'

    @classmethod
    def tearDownClass(cls):
        if cls.bash:
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_script(self, text):
        script = self.tmp / 'case.sh'
        script.write_text(text + '\n')
        # script(1) gives bash a real terminal, so job control is on and the
        # tcsetpgrp paths are exercised.
        result = subprocess.run(
            ['script', '-qec', f'{self.bash} --norc -i {script}', '/dev/null'],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        out = result.stdout.replace('\r', '')
        self.assertNotIn('AddressSanitizer', out, out[-3000:])
        self.assertNotIn('runtime error', out, out[-3000:])
        return out

    def check(self, text, marker):
        self.assertIn(marker, self.run_script(text))

    def test_plain_command_and_status(self):
        self.check('/bin/echo a; echo R=$?', 'R=0')
        self.check('/bin/false; echo R=$?', 'R=1')
        self.check('/bin/sh -c "exit 7"; echo R=$?', 'R=7')

    def test_exec_failures_report_like_a_shell(self):
        self.check('no_such_cmd_xyz 2>/dev/null; echo R=$?', 'R=127')
        self.check('/etc/passwd 2>/dev/null; echo R=$?', 'R=126')

    def test_debug_trap_with_prompt_command(self):
        # The combination that crashed the login shell on the board: a DEBUG
        # trap and PROMPT_COMMAND both run bash code around every command.
        self.check('trap "x=$?" DEBUG; PROMPT_COMMAND="y=1"; i=0\n'
                   'while [ $i -lt 50 ]; do /bin/true; i=$((i+1)); done; echo N=$i', 'N=50')

    def test_words_survive_the_vfork(self):
        # strvec_from_word_list(alloc=0) aliases the words; freeing them was
        # the use-after-free. $_ reads the last word after the command ran.
        self.check('/bin/echo one two; echo LAST=$_', 'LAST=two')

    def test_fork_paths_still_work(self):
        self.check('/bin/echo hello | /usr/bin/tr a-z A-Z', 'HELLO')
        self.check('/bin/echo out > "$TMPDIR_X/o"; /bin/cat "$TMPDIR_X/o"'.replace('$TMPDIR_X', str(self.tmp)), 'out')
        self.check('/bin/sleep 0.2 & wait; echo BG=$?', 'BG=0')
        self.check('(cd /tmp; /bin/pwd)', '/tmp')
        self.check('echo UP=$(/bin/echo yes)', 'UP=yes')
        self.check('/bin/cat <<< hs', 'hs')

    def test_signals_and_job_control(self):
        self.check('/bin/sleep 5 & p=$!; kill -INT $p; wait $p; echo K=$?', 'K=130')
        self.check('set -m; /bin/sleep 0.1; echo JC=$?', 'JC=0')

    def test_many_commands(self):
        self.check('i=0; while [ $i -lt 200 ]; do /bin/true; i=$((i+1)); done; echo N=$i', 'N=200')


if __name__ == '__main__':
    unittest.main(verbosity=2)
