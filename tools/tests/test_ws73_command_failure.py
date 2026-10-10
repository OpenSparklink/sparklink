# SPDX-License-Identifier: GPL-2.0-only
"""Real local subprocess failures, with no USB, D-Bus or RF simulation claims."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import ws73_north_star as recorder


class CommandFailureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.binary = self.root / 'slctl-fixture'
        self.binary.write_text(
            f'#!{sys.executable}\nimport sys, time\n'
            'print("admitted fixture request", flush=True)\n'
            'print("fixture stderr", file=sys.stderr, flush=True)\n'
            'time.sleep(60)\n')
        self.binary.chmod(0o700)
        self.args = SimpleNamespace(output=self.root/'run', slctl=self.binary,
                                    slkd_pid=os.getpid(), ports=['1-1', '1-2'], artifact=[])
        self.identity = {'path': '/org/sparklink/slk0_g1'}

    def run_object(self, cls=recorder.Run):
        run = cls(self.args)
        run.pid = recorder.daemon_identity(os.getpid())
        return run

    def assert_record(self, run, expected, reaped=True, location='commands'):
        evidence = json.loads((run.output/'run.json').read_text())
        record = evidence[location]
        if isinstance(record, list):
            self.assertEqual(len(record), 1)  # no automatic retry
            record = record[0]
        self.assertEqual(record['exit'], expected)
        for clock in ['wall', 'monotonic', 'boottime']:
            self.assertGreaterEqual(record[f'end_{clock}_ns'], record[f'start_{clock}_ns'])
        if reaped:
            self.assertEqual(record['stdout'], 'admitted fixture request\n')
            self.assertEqual(record['stderr'], 'fixture stderr\n')
            with self.assertRaises(ChildProcessError):
                os.waitpid(record['pid'], os.WNOHANG)
        return record

    def interrupted_communicate(self, exception):
        original = subprocess.Popen.communicate
        seen = set()

        def communicate(process, *args, **kwargs):
            if process.args[0] != str(self.binary):
                return original(process, *args, **kwargs)
            if process.pid not in seen:
                seen.add(process.pid)
                # Exercise communicate's real partial-output buffers. Only the
                # test's wait is shortened; production command deadlines stay.
                try:
                    original(process, timeout=1)
                except subprocess.TimeoutExpired:
                    if exception is KeyboardInterrupt:
                        raise KeyboardInterrupt()
                    raise
                self.fail('fixture unexpectedly exited before interruption')
            return original(process, *args, **kwargs)

        return patch.object(subprocess.Popen, 'communicate', communicate)

    def test_timeout_reaps_cli_and_preserves_complete_output(self):
        run = self.run_object()
        with self.interrupted_communicate(subprocess.TimeoutExpired):
            with self.assertRaisesRegex(ValueError, 'admitted operation may still exist'):
                run.ctl(self.identity, 'scan', 'on')
        record = self.assert_record(run, 'timeout')
        self.assertLess(record['child_returncode'], 0)

    def test_interrupt_reaps_cli_and_preserves_complete_output(self):
        run = self.run_object()
        with self.interrupted_communicate(KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            run.ctl(self.identity, 'scan', 'on')
        record = self.assert_record(run, 'interrupted')
        self.assertLess(record['child_returncode'], 0)

    def test_launch_failure_is_durable_and_has_no_child(self):
        self.binary.unlink()
        run = self.run_object()
        with self.assertRaisesRegex(ValueError, 'could not start'):
            run.ctl(self.identity, 'scan', 'on')
        record = self.assert_record(run, 'launch_error', reaped=False)
        self.assertEqual(record['errno'], errno.ENOENT)
        self.assertNotIn('pid', record)

    def test_failed_exit_retains_output_and_exit_code(self):
        self.binary.write_text(self.binary.read_text().replace('time.sleep(60)', 'sys.exit(17)'))
        run = self.run_object()
        with self.assertRaisesRegex(ValueError, 'preserve command 1'):
            run.ctl(self.identity, 'scan', 'on')
        self.assert_record(run, 17)

    def test_success_retains_output_and_exit_code(self):
        self.binary.write_text(self.binary.read_text().replace('time.sleep(60)', 'sys.exit(0)'))
        run = self.run_object()
        run.ctl(self.identity, 'scan', 'on')
        self.assert_record(run, 0)

    def test_bus_identity_interrupt_retains_output(self):
        run = self.run_object()
        with self.interrupted_communicate(KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            run.bus_identity()
        self.assert_record(run, 'interrupted', location='bus_observations')

    def test_stale_selection_interrupt_retains_output(self):
        run = self.run_object()
        with self.interrupted_communicate(KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            run.command([str(self.binary), '--adapter', self.identity['path'], 'show'],
                        15, field='stale_selection')
        self.assert_record(run, 'interrupted', location='stale_selection')

    def test_evidence_write_error_after_launch_reaps_child(self):
        run = self.run_object()
        save = run.save
        calls = 0

        def fail_once_after_launch():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(errno.ENOSPC, 'synthetic evidence write error')
            save()

        with patch.object(run, 'save', fail_once_after_launch):
            with self.assertRaises(OSError):
                run.ctl(self.identity, 'scan', 'on')
        record = json.loads((run.output/'run.json').read_text())['commands'][0]
        self.assertEqual(record['exit'], 'collector_error')
        self.assertEqual(record['error_type'], 'OSError')
        self.assertLess(record['child_returncode'], 0)
        with self.assertRaises(ChildProcessError):
            os.waitpid(record['pid'], os.WNOHANG)

    def test_interrupt_keeps_run_failed_after_cleanup(self):
        parent = self

        class FixtureRun(recorder.Run):
            def bus_identity(self):
                return {'owner': ':1.1', 'pid': os.getpid(), 'uid': os.getuid()}

            def read_registration(self, port):
                return dict(parent.identity, port=port, address=port, bus=1,
                            device=int(port[-1]), generation=int(port[-1]))

            def ready(self, port):
                return self.read_registration(port)

            def phase(self, a, b, count, phase):
                self.ctl(a, 'scan', 'on')
                parent.fail('interruption must prevent phase success')

            def stop(self, identity, domain):
                self.data.setdefault('test_cleanup_domains', []).append((identity['port'], domain))

        usb = self.root/'usb'
        for port in self.args.ports:
            (usb/port).mkdir(parents=True)
        run = self.run_object(FixtureRun)
        with patch.object(recorder, 'USB_ROOT', usb), \
             patch.object(recorder, 'ordinary_identity', return_value={'test_only': True}), \
             self.interrupted_communicate(KeyboardInterrupt):
            self.assertEqual(run.execute(), 1)
        self.assert_record(run, 'interrupted')
        evidence = json.loads((run.output/'run.json').read_text())
        self.assertEqual(evidence['status'], 'FAIL')
        self.assertEqual(evidence['error'], 'KeyboardInterrupt')
        self.assertEqual(evidence['rounds'], [])
        self.assertEqual(evidence['test_cleanup_domains'],
                         [['1-1', 'advertise'], ['1-1', 'scan'],
                          ['1-2', 'advertise'], ['1-2', 'scan']])
        self.assertEqual([r['status'] for r in evidence['cleanup']], ['STOP_CONFIRMED']*2)


if __name__ == '__main__':
    unittest.main()
