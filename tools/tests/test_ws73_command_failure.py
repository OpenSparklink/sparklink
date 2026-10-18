# SPDX-License-Identifier: GPL-2.0-only
"""Real local subprocess failures, with no USB, D-Bus or RF simulation claims."""
import errno
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
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

    def output_barrier(self, process):
        # Observe actual pipe readiness without consuming either stream. The
        # fixture has printed both lines before the controlled failure occurs.
        pending = [process.stdout, process.stderr]
        deadline = time.monotonic() + 2
        while pending:
            ready, _, _ = select.select(pending, [], [], max(0, deadline-time.monotonic()))
            self.assertTrue(ready, 'fixture did not reach the output barrier')
            pending = [stream for stream in pending if stream not in ready]

    def test_barrier_error_keeps_original_exception_and_complete_child_output(self):
        run = self.run_object()
        error = RuntimeError('controlled barrier failure')

        def barrier(process, record):
            self.output_barrier(process)
            raise error

        with self.assertRaises(RuntimeError) as observed:
            run.command([str(self.binary)], 5, collection='commands', on_started=barrier)
        self.assertIs(observed.exception, error)
        record = self.assert_record(run, 'collector_error')
        self.assertEqual(record['error_type'], 'RuntimeError')
        self.assertLess(record['child_returncode'], 0)

    def test_barrier_interrupt_reaps_and_preserves_complete_child_output(self):
        run = self.run_object()

        def barrier(process, record):
            self.output_barrier(process)
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            run.command([str(self.binary)], 5, collection='commands', on_started=barrier)
        record = self.assert_record(run, 'interrupted')
        self.assertLess(record['child_returncode'], 0)

    def test_barrier_consumes_original_supervisor_budget(self):
        run = self.run_object()
        communicate = subprocess.Popen.communicate
        waits = []

        def barrier(process, record):
            self.output_barrier(process)
            # This is a supervisor fixture budget, not a protocol timeout.
            release = record['start_monotonic_ns']/1_000_000_000 + .1
            while time.monotonic() < release:
                time.sleep(min(.01, max(0, release-time.monotonic())))

        def actual_wait(process, *args, **kwargs):
            waits.append(kwargs.get('timeout'))
            return communicate(process, *args, **kwargs)

        with patch.object(subprocess.Popen, 'communicate', actual_wait):
            with self.assertRaisesRegex(ValueError, 'admitted operation may still exist'):
                run.command([str(self.binary)], .05, collection='commands', on_started=barrier)
        self.assertEqual(waits[0], 0)
        self.assert_record(run, 'timeout')

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

    def test_confirmed_idle_stop_is_requeried_without_another_off(self):
        run=self.run_object();identity=dict(self.identity,generation=1)
        output='NativeOperationResult: generation=1 request=23 operation=4 state=3 errno=0 status=0x00 opcode=0x1002 step=0/1 power=0 power_valid=0 adv=1 scan=1 profile=1\n'
        run.data['commands']=[{'args':[str(self.binary),'--adapter',identity['path'],'scan','off'],'exit':0,'stdout':output}]
        def query(owner,*words):
            self.assertEqual(words,('result','23'))
            record={'args':[str(self.binary),'--adapter',identity['path'],*words],'exit':0,'stdout':output}
            run.data['commands'].append(record);return record
        with patch.object(run,'check'),patch.object(run,'ctl',side_effect=query):run.stop(identity,'scan')
        self.assertEqual(run.data['stop_confirmations'][0]['source_command'],0)
        self.assertEqual(run.data['stop_confirmations'][0]['query_command'],1)

    def test_unused_business_domain_queries_actual_initializer_without_new_stop(self):
        for domain, operation, details in [('advertise', 5, '0c05 step=1/2 power=20 power_valid=1'),
                                           ('scan', 6, '1002 step=2/3 power=0 power_valid=0')]:
            self.args.output = self.root/domain
            run = self.run_object(); identity = dict(self.identity, generation=1)
            output = f'NativeOperationResult: generation=1 request=23 operation={operation} state=3 errno=0 status=0x00 opcode=0x{details} adv=1 scan=1 profile=1\n'
            def query(owner, *words):
                self.assertEqual(words, (domain, 'initialized-off'))
                row = {'args': [str(self.binary), '--adapter', owner['path'], *words], 'exit': 0, 'stdout': output}
                run.data['commands'].append(row); return row
            with patch.object(run, 'check'), patch.object(run, 'ctl', side_effect=query):
                run.stop(identity, domain)
            self.assertEqual(run.data['initialization_off_confirmations'][0]['operation'], operation)
            self.assertNotIn('stop_confirmations', run.data)

    def test_missing_initializer_provenance_does_not_fabricate_or_resubmit_off(self):
        run = self.run_object(); identity = dict(self.identity, generation=1)
        with patch.object(run, 'check'), patch.object(run, 'ctl', side_effect=ValueError('initializer result absent or evicted')) as ctl:
            with self.assertRaises(ValueError): run.stop(identity, 'scan')
        ctl.assert_called_once_with(identity, 'scan', 'initialized-off')
        self.assertNotIn('initialization_off_confirmations', run.data)

    def test_idle_confirmation_does_not_accept_unknown_radio_or_wrong_generation(self):
        good='NativeOperationResult: generation=1 request=23 operation=4 state=3 errno=0 status=0x00 opcode=0x1002 step=0/1 power=0 power_valid=0 adv=1 scan=1 profile=1\n'
        for number,changed in enumerate([good.replace('scan=1','scan=0'),good.replace('generation=1','generation=2')]):
            with self.subTest(changed=changed):
                # Separate fixture record; no real controller is involved.
                self.args.output=self.root/('confirmation-'+str(number))
                run=self.run_object();identity=dict(self.identity,generation=1)
                run.data['commands']=[{'args':[str(self.binary),'--adapter',identity['path'],'scan','off'],'exit':0,'stdout':good}]
                with patch.object(run,'check'),patch.object(run,'ctl',return_value={'stdout':changed}):
                    with self.assertRaises(ValueError):run.stop(identity,'scan')
                self.assertNotIn('stop_confirmations',run.data)

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
