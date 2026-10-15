"""Exercise actual shared-library ABI/errors and Python handle lifetime.

/dev/null is deliberately not a SparkLink controller. Hardware success belongs
to the native KVM/physical gates, not this negative syscall/ABI suite.
"""
import ctypes
import errno
from pathlib import Path
import unittest

from sparklink import NativeAdapter, registration_snapshot
from sparklink.native import _get_native_lib, channel_info
from sparklink.structs import (
    SleControllerSnapshot, SleManagementQuery, SleDiscoverySubmit,
    SleDiscoveryResult, SleDiscoveryTiming, SleControllerEventQuery, SleSnoopQuery,
    SleDiagnosticResult, SleDiagnosticSubmit, SleConnectionSubmit, SleConnectionResult,
    SleLinkSnapshot, SleRegistrationSnapshot, SleChannelInfo, SleChannelTxStatus,
    SleSecurityNegotiationSubmit, SleSecurityNegotiationResult,
)


class NativeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = _get_native_lib()

    def setUp(self):
        self.handle = self.lib.slk_adapter_open(b"/dev/null")
        self.assertTrue(self.handle)
        self.addCleanup(self.lib.slk_adapter_free, self.handle)

    def test_limited_security_submit_is_real_ioctl_not_local_success(self):
        request=SleSecurityNegotiationSubmit(version=1,profile=1,flags=1,action=2,generation=1,lifetime=1,request_id=1,timeout_ms=5000)
        before=bytes(request)
        self.assertEqual(self.lib.slk_security_negotiation_submit(self.handle,ctypes.byref(request)),-errno.ENOTTY)
        self.assertEqual(bytes(request),before)
        self.assertEqual(self.lib.slk_security_negotiation_submit(None,ctypes.byref(request)),-errno.EINVAL)
        self.assertEqual(self.lib.slk_security_negotiation_submit(self.handle,None),-errno.EINVAL)

    def test_channel_info_errors_preserve_output_and_errno(self):
        out = SleChannelInfo(generation=99, reserved=123)
        before = bytes(out)
        self.assertEqual(self.lib.slk_channel_info(-1, ctypes.byref(out)), -errno.EBADF)
        self.assertEqual(bytes(out), before)
        self.assertEqual(self.lib.slk_channel_info(-1, None), -errno.EINVAL)
        with self.assertRaises(OSError) as caught:
            channel_info(-1)
        self.assertEqual(caught.exception.errno, errno.EBADF)
        with self.assertRaises(ValueError):
            channel_info(True)

    def test_tx_status_denies_bad_fd_without_overwriting(self):
        out=SleChannelTxStatus(generation=99,reserved=44)
        before=bytes(out)
        self.assertEqual(self.lib.slk_channel_tx_status(-1,ctypes.byref(out)),-errno.EBADF)
        self.assertEqual(bytes(out),before)
        self.assertEqual(self.lib.slk_channel_tx_status(-1,None),-errno.EINVAL)

    def test_registration_probe_rejects_invalid_index_and_closes_on_error(self):
        before = len(list(Path('/proc/self/fd').iterdir()))
        for _ in range(3):
            with self.assertRaises(OSError) as caught:
                registration_snapshot(0, 1, '/dev/null')
            self.assertEqual(caught.exception.errno, errno.ENOTTY)
        self.assertEqual(len(list(Path('/proc/self/fd').iterdir())), before)
        with self.assertRaises(ValueError):
            registration_snapshot(16, 1, '/dev/null')
        out = SleRegistrationSnapshot(generation=99)
        self.assertEqual(self.lib.slk_registration_snapshot(self.handle, 16, 1, ctypes.byref(out)), -errno.EINVAL)
        self.assertEqual(out.generation, 99)
        self.assertEqual(self.lib.slk_registration_snapshot(None, 0, 1, ctypes.byref(out)), -errno.EINVAL)

    def test_borrowed_fd_is_live_and_new_api_preserves_errno(self):
        fd = self.lib.slk_adapter_fd(self.handle)
        self.assertGreaterEqual(fd, 0)
        self.assertEqual(self.lib.slk_adapter_select(self.handle, 0), -errno.ENOTTY)
        self.assertEqual(self.lib.slk_adapter_select(self.handle, 65535), -errno.EINVAL)
        self.assertEqual(self.lib.slk_adapter_fd(None), -errno.EINVAL)
        # Legacy consumers retain their original error convention.
        self.assertEqual(self.lib.slk_device_count(self.handle), -1)

    def test_failed_queries_do_not_overwrite_caller_storage(self):
        for name, args, value in [
            ("slk_device_mask", [], ctypes.c_uint16(0xABCD)),
            ("slk_controller_snapshot", [1], SleControllerSnapshot(generation=99)),
            ("slk_registration_snapshot", [0, 1], SleRegistrationSnapshot(generation=99)),
            ("slk_link_snapshot", [1], SleLinkSnapshot(generation=99)),
            ("slk_security_negotiation_result", [1,1,0,1], SleSecurityNegotiationResult(generation=99)),
            ("slk_management_query", [1], SleManagementQuery(lease=99)),
            ("slk_management_acquire", [1, 1], ctypes.c_uint64(99)),
            ("slk_connection_result", [1, 1], SleConnectionResult(request_id=99)),
            ("slk_discovery_result", [1, 1], SleDiscoveryResult(request_id=99)),
            ("slk_discovery_timing", [1, 1], SleDiscoveryTiming(request_id=99)),
            ("slk_diagnostic_result", [1, 1], SleDiagnosticResult(seq=99)),
            ("slk_controller_event", [], SleControllerEventQuery(version=1, generation=1, after_seq=99)),
            ("slk_snoop", [], SleSnoopQuery(version=1, generation=1, after_seq=99)),
        ]:
            with self.subTest(function=name):
                original = bytes(value)
                function = getattr(self.lib, name)
                self.assertEqual(function(self.handle, *args, ctypes.byref(value)), -errno.ENOTTY)
                self.assertEqual(bytes(value), original)
                self.assertEqual(function(self.handle, *args, None), -errno.EINVAL)
                self.assertEqual(function(None, *args, ctypes.byref(value)), -errno.EINVAL)

    def test_zero_generation_cursors_and_result_are_rejected_before_ioctl(self):
        for name, value in [
            ("slk_controller_event", SleControllerEventQuery(version=1)),
            ("slk_snoop", SleSnoopQuery(version=1)),
        ]:
            original = bytes(value)
            self.assertEqual(getattr(self.lib, name)(self.handle, ctypes.byref(value)), -errno.EINVAL)
            self.assertEqual(bytes(value), original)
        timing = SleDiscoveryTiming(request_id=99)
        original = bytes(timing)
        for generation, request in [(0, 1), (1, 0)]:
            self.assertEqual(self.lib.slk_discovery_timing(self.handle, generation, request, ctypes.byref(timing)), -errno.EINVAL)
            self.assertEqual(bytes(timing), original)
        result = SleDiscoveryResult()
        for generation, request in [(0, 1), (1, 0)]:
            self.assertEqual(self.lib.slk_discovery_result(self.handle, generation, request, ctypes.byref(result)), -errno.EINVAL)
        diagnostic = SleDiagnosticResult(seq=99)
        original = bytes(diagnostic)
        for generation, seq in [(0, 1), (1, 0)]:
            self.assertEqual(self.lib.slk_diagnostic_result(self.handle, generation, seq, ctypes.byref(diagnostic)), -errno.EINVAL)
            self.assertEqual(bytes(diagnostic), original)

    def test_writer_calls_preserve_transport_errors_and_null_guards(self):
        request = SleDiscoverySubmit()
        self.assertEqual(self.lib.slk_discovery_submit(self.handle, ctypes.byref(request)), -errno.ENOTTY)
        self.assertEqual(self.lib.slk_discovery_submit(self.handle, None), -errno.EINVAL)
        self.assertEqual(self.lib.slk_management_release(self.handle, 1, 1, 1), -errno.ENOTTY)
        self.assertEqual(self.lib.slk_management_release(None, 1, 1, 1), -errno.EINVAL)

    def test_diagnostic_admission_fields_and_errno_preserve_request(self):
        good = dict(version=1, generation=7, request_id=1, timeout_ms=5000, opcode=0x0406, action=1)
        for changed in [dict(version=2), dict(flags=1), dict(generation=0), dict(request_id=0),
                        dict(timeout_ms=0), dict(timeout_ms=5001), dict(reserved=1), dict(seq=1),
                        dict(action=3), dict(opcode=0x0c05)]:
            value = SleDiagnosticSubmit(**(good | changed))
            original = bytes(value)
            self.assertEqual(self.lib.slk_diagnostic_submit(self.handle, ctypes.byref(value)), -errno.EINVAL)
            self.assertEqual(bytes(value), original)
        for action in (1, 2):
            value = SleDiagnosticSubmit(**(good | dict(action=action)))
            original = bytes(value)
            self.assertEqual(self.lib.slk_diagnostic_submit(self.handle, ctypes.byref(value)), -errno.ENOTTY)
            self.assertEqual(bytes(value), original)
        self.assertEqual(self.lib.slk_diagnostic_submit(None, ctypes.byref(value)), -errno.EINVAL)
        self.assertEqual(self.lib.slk_diagnostic_submit(self.handle, None), -errno.EINVAL)

    def test_failed_native_constructor_closes_its_handle(self):
        count = lambda: len(list(Path('/proc/self/fd').iterdir()))
        before = count()
        for _ in range(20):
            with self.assertRaises(OSError) as error:
                NativeAdapter(0, dev_path='/dev/null')
            self.assertEqual(error.exception.errno, errno.ENOTTY)
        self.assertEqual(count(), before)

    def test_unsigned_arguments_are_not_silently_wrapped(self):
        for index, generation in [(-1, 0), (65536, 0), (0, -1), (0, 1 << 64)]:
            with self.subTest(index=index, generation=generation):
                with self.assertRaises(ValueError):
                    NativeAdapter(index, generation, dev_path='/dev/null')


if __name__ == '__main__':
    unittest.main()


class NativeConnectionBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = _get_native_lib()

    def test_null_submit_and_zero_identity_are_rejected_without_output_change(self):
        handle = self.lib.slk_adapter_open(b"/dev/null")
        self.assertTrue(handle)
        self.addCleanup(self.lib.slk_adapter_free, handle)
        request = SleConnectionSubmit(version=1, generation=1, request_id=1)
        self.assertEqual(self.lib.slk_connection_submit_v2(None, ctypes.byref(request)), -errno.EINVAL)
        self.assertEqual(self.lib.slk_connection_submit_v2(handle, None), -errno.EINVAL)
        self.assertEqual(self.lib.slk_connection_submit_v2(handle, ctypes.byref(request)), -errno.ENOTTY)
        result = SleConnectionResult(request_id=99)
        original = bytes(result)
        for generation, request_id in [(0, 1), (1, 0)]:
            self.assertEqual(self.lib.slk_connection_result(handle, generation, request_id, ctypes.byref(result)), -errno.EINVAL)
            self.assertEqual(bytes(result), original)


class NativeConnectionMethodTests(unittest.TestCase):
    def setUp(self):
        import threading
        self.adapter = object.__new__(NativeAdapter)
        self.adapter._handle = None
        self.adapter._lock = threading.RLock()
        self.adapter._handle = _get_native_lib().slk_adapter_open(b"/dev/null")
        self.adapter.index, self.adapter.generation = 0, 1
        self.addCleanup(self.adapter.close)

    def test_actual_python_methods_preserve_abi_errors(self):
        request = SleConnectionSubmit(version=1, generation=1, request_id=1)
        limited=SleSecurityNegotiationSubmit(version=1,profile=1,flags=1,action=2,generation=1,lifetime=1,request_id=1,timeout_ms=5000)
        for call in [lambda:self.adapter.submit_security_negotiation(limited),
                     lambda:self.adapter.security_negotiation(1,0,1),
                     lambda: self.adapter.submit_connection(request),
                     lambda: self.adapter.connection_result(1, 1)]:
            with self.assertRaises(OSError) as error:
                call()
            self.assertEqual(error.exception.errno, errno.ENOTTY)

    def test_methods_reject_wrong_identity_before_call_and_serialize_close(self):
        for request in [SleConnectionSubmit(generation=2, request_id=1),
                        SleConnectionSubmit(generation=1)]:
            with self.assertRaises(ValueError):
                self.adapter.submit_connection(request)
        for gen, identifier in [(2,1),(1,0),(0,1)]:
            with self.assertRaises(ValueError):
                self.adapter.connection_result(gen, identifier)
        self.adapter.close()
        with self.assertRaises(OSError) as error:
            self.adapter.connection_result(1, 1)
        self.assertEqual(error.exception.errno, errno.EBADF)
