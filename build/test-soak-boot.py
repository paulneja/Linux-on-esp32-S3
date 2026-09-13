#!/usr/bin/env python3
"""The soak runner's classifier must never call a boot a PASS on silence.

It ran for a whole afternoon reporting "0/5 faulted" for rounds that never
reached the login prompt, and missed busybox's "Caught unhandled exception"
and a user-space illegal instruction. These tests drive classify() and the
fault list with transcripts shaped like the real ones.
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parent.parent


def load():
    # soak-boot.py parses argv and touches the port at import time; stub both.
    src = (ROOT / 'build/soak-boot.py').read_text()
    head = src.split("parser = argparse.ArgumentParser")[0]
    body = src.split("identity = {} if args.no_identity else read_identity()")[0]
    body = body.split("def esptool(")[0]  # keep only definitions up to the I/O helpers
    module = types.ModuleType('soak')
    exec(head, module.__dict__)
    # classify and upper_bound_95 live after the parser; pull them in verbatim
    for name in ('def classify(', 'def upper_bound_95('):
        start = src.index(name)
        end = src.index('\n\n\n', start)
        exec(src[start:end], module.__dict__)
    return module


soak = load()

CLEAN = (b'ESP-ROM:esp32s3-20210327\nLinux version 6.11.0\nStarting cron: OK\n'
         b'\nWelcome to Buildroot\nbuildroot login: ')
# A round that reached a login always reads the ring buffer and the taint
# flags back; a quiet console says almost nothing without them.
OK_PROBES = {'dmesg': 'Linux version 6.11.0\nRun /sbin/init as init process\n',
             'cat /proc/sys/kernel/tainted': '0\n'}


def classify(data, login_at, marker_at, probes=OK_PROBES):
    return soak.classify(data, login_at, marker_at, probes)


class ClassifyTests(unittest.TestCase):
    def test_a_full_boot_is_a_pass(self):
        self.assertEqual(classify(CLEAN, 30.0, 12.0)[0], 'PASS')

    def test_no_login_is_never_a_pass(self):
        data = b'ESP-ROM:esp32s3\nRunning sysctl: OK\n'
        self.assertEqual(classify(data, None, None, {})[0], 'INCONCLUSIVE')

    def test_login_without_the_marker_is_inconclusive(self):
        data = b'ESP-ROM:esp32s3\nbuildroot login: '
        self.assertEqual(classify(data, 30.0, None, {})[0], 'INCONCLUSIVE')

    def test_a_silent_reset_before_login_is_inconclusive(self):
        data = b'ESP-ROM:esp32s3\nRunning sysctl: OK\n' + CLEAN
        state, hits, resets = classify(data, 60.0, 40.0)
        self.assertEqual(resets, 2)
        self.assertEqual(state, 'INCONCLUSIVE')

    def test_kernel_faults_are_fails_even_with_a_login(self):
        for line in (b'[    7.0] Oops: sig: 11 [#1] PREEMPT',
                     b'[    7.0] BUG: failure at mm/nommu.c:459/add_nommu_region()!',
                     b'[    7.0] Kernel panic - not syncing: BUG!',
                     b'[    7.0] Illegal instruction in kernel: sig: 9',
                     b'[    7.0] BUG: Bad page state in process swapper  pfn:3dc32',
                     b'[    7.0] list_del corruption. prev->next should be 1, but was 2',
                     b'[    7.0] WARNING: CPU: 0 PID: 73 at lib/list_debug.c:62'):
            with self.subTest(line=line):
                state, hits, _ = classify(CLEAN + line + b'\n', 30.0, 12.0)
                self.assertEqual(state, 'FAIL', line)
                self.assertTrue(hits)

    def test_the_user_space_signatures_the_reviewer_found_are_fails(self):
        for line in (b"[   38.8] Illegal Instruction in 'sleep' (pid = 75, pc = 0x426d66da)",
                     b'Caught unhandled exception',
                     b'gzip: invalid compressed data--crc error'):
            with self.subTest(line=line):
                self.assertEqual(classify(CLEAN + line + b'\n', 30.0, 12.0)[0], 'FAIL')

    def test_slab_debug_in_the_bootargs_is_not_a_fault(self):
        data = CLEAN + b'Kernel command line: rw panic=10 slab_nomerge slab_debug=FZPU\n'
        self.assertEqual(classify(data, 30.0, 12.0)[0], 'PASS')


class QuietConsoleTests(unittest.TestCase):
    """The shipping image boots with `quiet`. Everything below KERN_ERR --
    a user-space illegal instruction, a WARN, list corruption -- reaches the
    ring buffer and never the console, so the console alone cannot decide."""

    def test_a_fault_only_in_dmesg_is_a_fail(self):
        probes = dict(OK_PROBES, dmesg="[   38.8] Illegal Instruction in 'sleep' "
                                       "(pid = 75, pc = 0x426d66da)\n")
        state, hits, _ = classify(CLEAN, 30.0, 12.0, probes)
        self.assertEqual(state, 'FAIL')
        self.assertTrue(any(h.startswith('dmesg: ') for h in hits), hits)

    def test_a_warn_only_in_dmesg_is_a_fail(self):
        probes = dict(OK_PROBES, dmesg='[ 7.0] WARNING: CPU: 0 PID: 73 at lib/list_debug.c:62\n')
        self.assertEqual(classify(CLEAN, 30.0, 12.0, probes)[0], 'FAIL')

    def test_a_tainted_kernel_is_a_fail_even_with_a_silent_log(self):
        probes = dict(OK_PROBES, **{'cat /proc/sys/kernel/tainted': '512\n'})
        state, hits, _ = classify(CLEAN, 30.0, 12.0, probes)
        self.assertEqual(state, 'FAIL')
        self.assertIn('tainted=512', hits)

    def test_tainted_zero_is_clean(self):
        self.assertEqual(classify(CLEAN, 30.0, 12.0)[0], 'PASS')

    def test_a_login_whose_log_could_not_be_read_is_not_a_pass(self):
        state, hits, _ = classify(CLEAN, 30.0, 12.0, {})
        self.assertEqual(state, 'INCONCLUSIVE')
        self.assertIn('kernel log not read back', hits)

    def test_a_wedged_console_after_login_is_a_fail(self):
        probes = {'error': "TimeoutError('no prompt')"}
        state, hits, _ = classify(CLEAN, 30.0, 12.0, probes)
        self.assertEqual(state, 'FAIL')
        self.assertTrue(any('wedged' in h for h in hits), hits)


class BoundTests(unittest.TestCase):
    def test_zero_of_five_is_not_zero(self):
        self.assertGreater(soak.upper_bound_95(0, 5), 0.44)
        self.assertLess(soak.upper_bound_95(0, 5), 0.46)

    def test_zero_of_twenty_is_tighter(self):
        self.assertLess(soak.upper_bound_95(0, 20), 0.15)

    def test_one_of_five_bounds_above_the_point_estimate(self):
        self.assertGreater(soak.upper_bound_95(1, 5), 0.2)

    def test_nothing_decided_is_unbounded(self):
        self.assertEqual(soak.upper_bound_95(0, 0), 1.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
