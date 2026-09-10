#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / 'experiments/mmu-poc/fork/check-kernel-config.py'
CALLERS = ['experiments/mmu-poc/fork/build-kernel.sh',
           'experiments/mmu-poc/fork/build-kernel-reclaim.sh',
           'build/package-final.py']


class KernelConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def check(self, seed, built):
        (self.dir / 'seed').write_text(seed)
        (self.dir / 'built').write_text(built)
        return subprocess.run([sys.executable, str(CHECK), str(self.dir / 'seed'),
                               str(self.dir / 'built')],
                              capture_output=True, text=True, timeout=30)

    def test_a_matching_config_passes(self):
        result = self.check('CONFIG_A=y\n# CONFIG_B is not set\n',
                            'CONFIG_A=y\n# CONFIG_B is not set\nCONFIG_C=m\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_symbol_the_build_dropped_is_caught(self):
        result = self.check('CONFIG_USB_SUPPORT=y\n', 'CONFIG_A=y\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('CONFIG_USB_SUPPORT: seed says y, built has absent', result.stderr)

    def test_a_symbol_the_build_changed_is_caught(self):
        result = self.check('CONFIG_EXT4_FS=y\n', 'CONFIG_EXT4_FS=m\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('seed says y, built has m', result.stderr)

    def test_a_symbol_the_seed_disabled_but_the_build_enabled_is_caught(self):
        result = self.check('# CONFIG_MMC_SPI is not set\n', 'CONFIG_MMC_SPI=y\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('seed says not set, built has y', result.stderr)

    def test_an_absent_symbol_satisfies_a_seed_not_set(self):
        # olddefconfig drops symbols whose dependencies are unmet, so absence is
        # disabled just as surely as an explicit "is not set".
        result = self.check('# CONFIG_SCHED_DEBUG is not set\n', 'CONFIG_A=y\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_symbols_the_seed_never_mentions_are_ignored(self):
        result = self.check('CONFIG_A=y\n',
                            'CONFIG_A=y\nCONFIG_LOCALVERSION="-forkbank"\n'
                            'CONFIG_XTENSA_NOMMU_FORK=y\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_divergence_is_listed_not_just_the_first(self):
        result = self.check('CONFIG_A=y\nCONFIG_B=y\n', '')
        self.assertEqual(result.returncode, 1)
        self.assertIn('2 statement(s)', result.stderr)
        self.assertIn('CONFIG_A', result.stderr)
        self.assertIn('CONFIG_B', result.stderr)

    def test_the_failure_explains_how_to_recover(self):
        result = self.check('CONFIG_A=y\n', '')
        self.assertIn('rm -rf experiments/mmu-poc/out/linux-fork', result.stderr)

    def test_comments_and_blank_lines_are_ignored(self):
        result = self.check('\n# Automatically generated file\n#\nCONFIG_A=y\n',
                            '\n# some other comment\nCONFIG_A=y\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_wrong_argument_count_is_refused(self):
        result = subprocess.run([sys.executable, str(CHECK)], capture_output=True,
                                text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('usage', result.stderr)

    def test_every_build_path_runs_the_check(self):
        for caller in CALLERS:
            with self.subTest(caller=caller):
                self.assertIn('check-kernel-config.py', (ROOT / caller).read_text(),
                              'a build path that skips the check cannot detect a stale tree')


if __name__ == '__main__':
    unittest.main(verbosity=2)
