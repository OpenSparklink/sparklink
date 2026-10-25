# SPDX-License-Identifier: GPL-2.0-only
"""Execute the Python helper with explicit Client/clock/stdin fixtures.

Checks helper input, original barrier/deadline, exact-error and value comparison.
This does not load the C ABI, enter D-Bus, run an Engine, kernel or real peer.
The application_ffi integration test separately invokes both actual SDKs.
"""
import contextlib
import errno
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'testing/application_client/client.py'
PATH = '/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b'


class Fixture:
    def __init__(self, outcome=errno.EINVAL, construction_error=None, ssap_value=b''):
        self.outcome = outcome
        self.construction_error = construction_error
        self.ssap_value = ssap_value
        self.calls = []
        self.opened = False
        self.closed = False
        self.released = False
        self.require_barrier = True
        owner = self

        class Link:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def ssap(self):
                if owner.construction_error is not None:
                    raise OSError(owner.construction_error, 'explicit view construction fixture')
                return self

            def write_without_response(self, handle, value, *, minimum, deadline_ns):
                if not owner.closed or not owner.released:
                    raise AssertionError('original parent close/start barrier required')
                owner.calls.append((handle, value, minimum, deadline_ns))
                if owner.outcome is not None:
                    raise OSError(owner.outcome, 'explicit SDK-error fixture; not daemon/peer')
                return None

            def _ssap(self, operation, handle, value, deadline_ns):
                if not owner.closed or owner.require_barrier and not owner.released:
                    raise AssertionError('original parent close/start barrier required')
                owner.calls.append((operation, handle, value, deadline_ns))
                if owner.outcome is not None:
                    raise OSError(owner.outcome, 'explicit SDK-error fixture; not daemon/peer')
                return owner.ssap_value

            def read(self, handle, *, deadline_ns):
                return self._ssap('ssap-read', handle, None, deadline_ns)

            def read_description(self, handle, *, deadline_ns):
                return self._ssap('ssap-read-description', handle, None, deadline_ns)

            def write(self, handle, value, *, deadline_ns):
                return self._ssap('ssap-write', handle, value, deadline_ns)

        class Client:
            def __init__(self, *, deadline_ns):
                owner.opened = True
                self.deadline = deadline_ns

            def __enter__(self):
                return self

            def __exit__(self, *_):
                owner.closed = True
                return False

            def connection(self, identity, path, *, deadline_ns):
                if identity != (2, 7) or path != PATH or self.deadline != deadline_ns:
                    raise AssertionError('explicit finite connection identity fixture')
                return Link()

        sdk = ModuleType('sparklink')
        sdk.Client = Client
        sdk.ControllerId = lambda index, generation: (index, generation)
        sdk.channel_info = sdk.channel_recv_security = None  # Not exercised.
        spec = importlib.util.spec_from_file_location('application_command_helper_fixture', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'sparklink': sdk}):
            spec.loader.exec_module(self.module)

    def invoke(self, *, payload='a5' * 2043, mode='ssap-command-reject', minimum='0',
               times=(100, 110, 120), start=b'start\n', wait_error=None):
        args = [str(SCRIPT), mode, '2', '7', PATH, '17', payload, minimum]
        return self._invoke(args, times=times, start=start, wait_error=wait_error)

    def invoke_ssap(self, *, expected='', operation='ssap-read', value='01', mode='ssap',
                    times=(100, 110, 120), start=b'start\n', wait_error=None):
        args = [str(SCRIPT), mode, '2', '7', PATH, operation, '17', expected]
        if operation == 'ssap-write':
            args.append(value)
        self.require_barrier = mode != 'ssap-error'
        return self._invoke(args, times=times, start=start, wait_error=wait_error)

    def _invoke(self, args, *, times, start, wait_error):
        output = io.StringIO()

        def read(fd, count):
            if (fd, count) != (0, 6):
                raise AssertionError('one actual start read required')
            self.released = start == b'start\n'
            return start

        with patch.object(sys, 'argv', args), patch.object(self.module.time, 'monotonic_ns', side_effect=times), \
             patch.object(self.module, 'wait', side_effect=wait_error) as waited, \
             patch.object(self.module.os, 'read', side_effect=read), contextlib.redirect_stdout(output):
            error = None
            try:
                self.module.main()
            except Exception as caught:
                error = caught
        return output.getvalue(), error, waited.call_args_list


class CommandRejectHelper(unittest.TestCase):
    def test_exact_rejection_is_after_sdk_call_and_preserves_full_identity_and_deadline(self):
        fixture = Fixture()
        out, error, waits = fixture.invoke()
        self.assertIsNone(error)
        self.assertEqual(len(waits), 1)
        self.assertEqual(fixture.calls, [(17, bytes([0xa5]) * 2043, 0, 5_000_000_100)])
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), dict(stage='ssap_command_start_barrier', api='python',
            deadline_ns=5_000_000_100, client_closed=True, mode='ssap-command-reject', schema_version=1))
        self.assertTrue(lines[1].startswith('SSAP_COMMAND_REJECTED: '))
        self.assertEqual(json.loads(lines[1].split(': ', 1)[1]), dict(schema_version=1,
            mode='ssap-command-reject', api='python', method='WriteSsapCommand', index=2,
            generation=7, path=PATH, handle=17, value='a5' * 2043, application_bytes=2043,
            minimum=0, sdk_entered=True, errno=errno.EINVAL, operation_success=False,
            peer_delivery_confirmed=False, deadline_ns=5_000_000_100, call_ns=110, returned_ns=120))

    def test_other_error_or_unexpected_success_is_not_a_rejection_pass(self):
        for outcome in (None, errno.ETIMEDOUT, errno.EACCES, errno.ESTALE, errno.EMSGSIZE):
            with self.subTest(outcome=outcome):
                fixture = Fixture(outcome)
                out, error, _ = fixture.invoke()
                self.assertIsNotNone(error)
                self.assertEqual(len(fixture.calls), 1)
                self.assertNotIn('SSAP_COMMAND_REJECTED:', out)
                self.assertNotIn('SSAP_COMMAND_ADMITTED:', out)
                if outcome is not None:
                    self.assertEqual(error.errno, outcome)

    def test_exact_size_minimum_and_hex_fail_before_client_open(self):
        cases = [dict(payload=''), dict(payload='a5' * 2042), dict(payload='a5' * 2044),
                 dict(payload='gg' * 2043), dict(minimum='1'), dict(minimum='3')]
        for case in cases:
            with self.subTest(case={k: len(v) if k == 'payload' else v for k, v in case.items()}):
                fixture = Fixture()
                out, error, waits = fixture.invoke(**case)
                self.assertIsInstance(error, ValueError)
                self.assertEqual((out, waits, fixture.calls, fixture.opened), ('', [], [], False))

    def test_eof_wrong_start_and_expired_wait_never_call_sdk(self):
        for case in (dict(start=b''), dict(start=b'wrong\n'),
                     dict(wait_error=TimeoutError(errno.ETIMEDOUT, 'explicit original wait expiry'))):
            with self.subTest(case=case):
                fixture = Fixture()
                out, error, _ = fixture.invoke(**case)
                self.assertIsNotNone(error)
                self.assertEqual(fixture.calls, [])
                self.assertNotIn('SSAP_COMMAND_REJECTED:', out)

    def test_expiry_before_call_or_late_rejection_cannot_pass(self):
        for times, calls in (((100, 5_000_000_100), 0), ((100, 110, 5_000_000_100), 1),
                             ((100, 110, 5_000_000_101), 1), ((100, 110, 110), 1)):
            with self.subTest(times=times):
                fixture = Fixture()
                out, error, _ = fixture.invoke(times=times)
                self.assertIsInstance(error, TimeoutError)
                self.assertEqual(len(fixture.calls), calls)
                self.assertNotIn('SSAP_COMMAND_REJECTED:', out)

    def test_view_construction_einval_is_not_command_sdk_entry(self):
        fixture = Fixture(construction_error=errno.EINVAL)
        out, error, _ = fixture.invoke()
        self.assertEqual(error.errno, errno.EINVAL)
        self.assertEqual(fixture.calls, [])
        self.assertNotIn('SSAP_COMMAND_REJECTED:', out)

    def test_original_positive_mode_and_2043_input_rejection_remain_unchanged(self):
        for payload in ('', 'a5' * 32, 'a5' * 2042):
            with self.subTest(size=len(payload) // 2):
                fixture = Fixture(None)
                out, error, _ = fixture.invoke(mode='ssap-command', payload=payload)
                self.assertIsNone(error)
                lines = out.splitlines()
                self.assertEqual(len(lines), 2)
                self.assertEqual(json.loads(lines[0]), dict(stage='ssap_command_start_barrier',
                    api='python', deadline_ns=5_000_000_100, client_closed=True))
                self.assertEqual(json.loads(lines[1].removeprefix('SSAP_COMMAND_ADMITTED: ')),
                    dict(api='python', handle=17, value=payload, minimum=0, admission_only=True,
                         peer_delivery_confirmed=False, deadline_ns=5_000_000_100, call_ns=110, returned_ns=120))
        fixture = Fixture(None)
        out, error, _ = fixture.invoke(mode='ssap-command')
        self.assertIsInstance(error, ValueError)
        self.assertEqual((out, fixture.calls, fixture.opened), ('', [], False))


class SsapReadHelper(unittest.TestCase):
    def test_empty_read_calls_sdk_after_original_barrier_and_compares_actual_empty_value(self):
        fixture = Fixture(None)
        out, error, waits = fixture.invoke_ssap()
        self.assertIsNone(error)
        self.assertEqual(fixture.calls, [('ssap-read', 17, None, 5_000_000_100)])
        self.assertEqual(len(waits), 1)
        self.assertEqual(waits[0].args, (0, fixture.module.select.POLLIN, 5_000_000_100))
        lines = out.splitlines()
        self.assertEqual(json.loads(lines[0]), dict(stage='ssap_start_barrier', api='python',
                                                   client_closed=True))
        self.assertEqual(lines[1:], [f'SsapPeerValue: operation=ssap-read path={PATH} handle=17 value='])

    def test_nonempty_read_bounds_and_exact_length_and_content_comparison_remain(self):
        for value in (b'\x01', b'\xa5' * 2042):
            fixture = Fixture(None, ssap_value=value)
            out, error, _ = fixture.invoke_ssap(expected=value.hex())
            self.assertIsNone(error)
            self.assertIn(f'handle=17 value={value.hex()}\n', out)
            self.assertEqual(len(fixture.calls), 1)
        for expected, actual in (('', b'\x01'), ('01', b''), ('01', b'\x02')):
            with self.subTest(expected=expected, actual=actual):
                fixture = Fixture(None, ssap_value=actual)
                out, error, _ = fixture.invoke_ssap(expected=expected)
                self.assertIsInstance(error, ValueError)
                self.assertEqual(len(fixture.calls), 1)
                self.assertNotIn('SsapPeerValue:', out)

    def test_only_literal_empty_read_is_admitted_and_other_input_bounds_remain(self):
        for operation in ('ssap-write', 'ssap-read-description'):
            fixture = Fixture(None, ssap_value=b'\x01')
            out, error, _ = fixture.invoke_ssap(operation=operation, expected='01')
            self.assertIsNone(error)
            self.assertEqual(fixture.calls, [(operation, 17,
                b'\x01' if operation == 'ssap-write' else None, 5_000_000_100)])
            self.assertIn(f'SsapPeerValue: operation={operation}', out)
        for case in (dict(operation='ssap-write'), dict(operation='ssap-write', expected='01', value=''),
                     dict(operation='ssap-read-description'), dict(expected=' '),
                     dict(expected='a5' * 2043), dict(expected='0'), dict(expected='gg')):
            with self.subTest(case=case):
                fixture = Fixture(None)
                out, error, waits = fixture.invoke_ssap(**case)
                self.assertIsInstance(error, ValueError)
                self.assertEqual((out, waits, fixture.calls, fixture.opened), ('', [], [], False))

    def test_empty_read_bad_or_expired_barrier_never_calls_sdk(self):
        for case in (dict(start=b''), dict(start=b'wrong\n'),
                     dict(wait_error=TimeoutError(errno.ETIMEDOUT, 'explicit original wait expiry'))):
            fixture = Fixture(None)
            out, error, _ = fixture.invoke_ssap(**case)
            self.assertIsNotNone(error)
            self.assertEqual(fixture.calls, [])
            self.assertNotIn('SsapPeerValue:', out)

    def test_error_read_keeps_actual_sdk_errno_receipts_without_a_new_barrier(self):
        fixture = Fixture(errno.EIO)
        out, error, waits = fixture.invoke_ssap(mode='ssap-error', expected=str(errno.EIO))
        self.assertIsNone(error)
        self.assertEqual(waits, [])
        self.assertEqual(fixture.calls, [('ssap-read', 17, None, 5_000_000_100)])
        self.assertEqual([json.loads(line) for line in out.splitlines()], [
            dict(stage='ssap_call', api='python', deadline_ns=5_000_000_100, call_ns=110, client_closed=True),
            dict(stage='ssap_error', api='python', errno=errno.EIO, operation_success=False,
                 deadline_ns=5_000_000_100, returned_ns=120)])
        for outcome in (None, errno.EACCES):
            fixture = Fixture(outcome)
            out, error, _ = fixture.invoke_ssap(mode='ssap-error', expected=str(errno.EIO))
            self.assertIsNotNone(error)
            self.assertEqual(len(fixture.calls), 1)
            self.assertNotIn('SsapPeerValue:', out)
        fixture = Fixture(errno.EIO)
        out, error, waits = fixture.invoke_ssap(mode='ssap-error', expected='')
        self.assertIsInstance(error, ValueError)
        self.assertEqual((out, waits, fixture.calls, fixture.opened), ('', [], [], False))


if __name__ == '__main__':
    unittest.main()
