"""Exercise actual shared-library ABI/errors and Python handle lifetime.

/dev/null is deliberately not a SparkLink controller. Hardware success belongs
to the native KVM/physical gates, not this negative syscall/ABI suite.
"""
import ctypes
import errno
from pathlib import Path
import unittest

from sparklink.native import NativeAdapter, registration_snapshot
from sparklink.native import _get_native_lib
from sparklink.channel import _get_channel_lib, channel_info
from sparklink.structs import (
    SleControllerSnapshot, SleManagementQuery, SleDiscoverySubmit,
    SleDiscoveryResult, SleDiscoveryTiming, SleControllerEventQuery, SleSnoopQuery,
    SleDiagnosticResult, SleDiagnosticSubmit, SleConnectionSubmit, SleConnectionResult,
    SleLinkSnapshot, SleRegistrationSnapshot, SleChannelInfo, SleChannelTxStatus, SleSessionTxStatus,
    SleSecurityNegotiationSubmit, SleSecurityNegotiationResult, SleSecurityNegotiationCancel, SleSecurityNumericConfirm, SleConnectionSecurity,
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
        request=SleSecurityNegotiationSubmit(version=2,deadline_monotonic_ns=1,profile=1,flags=1,action=2,generation=1,lifetime=1,request_id=1,timeout_ms=5000)
        before=bytes(request)
        self.assertEqual(self.lib.slk_security_negotiation_submit(self.handle,ctypes.byref(request)),-errno.ENOTTY)
        self.assertEqual(bytes(request),before)
        self.assertEqual(self.lib.slk_security_negotiation_submit(None,ctypes.byref(request)),-errno.EINVAL)
        self.assertEqual(self.lib.slk_security_negotiation_submit(self.handle,None),-errno.EINVAL)

    def test_security_cancel_is_original_file_ioctl_and_never_local_success(self):
        request = SleSecurityNegotiationCancel(version=1, generation=1, lifetime=1, request_id=1)
        before = bytes(request)
        self.assertEqual(self.lib.slk_security_negotiation_cancel(self.handle, ctypes.byref(request)), -errno.ENOTTY)
        self.assertEqual(bytes(request), before)
        self.assertEqual(self.lib.slk_security_negotiation_cancel(None, ctypes.byref(request)), -errno.EINVAL)
        self.assertEqual(self.lib.slk_security_negotiation_cancel(self.handle, None), -errno.EINVAL)

    def test_connection_security_requires_real_kernel_and_preserves_failed_output(self):
        out = SleConnectionSecurity(generation=99, security_epoch=123)
        before = bytes(out)
        self.assertEqual(self.lib.slk_connection_security(self.handle, 1, 1, 0, ctypes.byref(out)), -errno.ENOTTY)
        self.assertEqual(bytes(out), before)
        self.assertEqual(self.lib.slk_connection_security(None, 1, 1, 0, ctypes.byref(out)), -errno.EINVAL)
        self.assertEqual(self.lib.slk_connection_security(self.handle, 1, 1, 0, None), -errno.EINVAL)
        self.assertEqual(self.lib.slk_connection_security(self.handle, 0, 1, 0, ctypes.byref(out)), -errno.EINVAL)
        self.assertEqual(self.lib.slk_connection_security(self.handle, 1, 1, 4096, ctypes.byref(out)), -errno.EINVAL)
        self.assertEqual(bytes(out), before)

    def test_numeric_confirmation_is_real_ioctl_without_local_success(self):
        request = SleSecurityNumericConfirm(version=1, generation=1, lifetime=1, request_id=1, comparison_code=0, accept=1)
        before = bytes(request)
        self.assertEqual(self.lib.slk_security_numeric_confirm(self.handle, ctypes.byref(request)), -errno.ENOTTY)
        self.assertEqual(bytes(request), before)
        self.assertEqual(self.lib.slk_security_numeric_confirm(None, ctypes.byref(request)), -errno.EINVAL)
        self.assertEqual(self.lib.slk_security_numeric_confirm(self.handle, None), -errno.EINVAL)

    def test_message_context_requires_real_domain_and_preserves_failed_outputs(self):
        from sparklink.structs import SleMessageSecurity
        from sparklink.channel import channel_recv_security
        import socket
        out=SleMessageSecurity(generation=99,security_epoch=123)
        actual=ctypes.c_int(77);buffer=(ctypes.c_uint8 * 8)();before=bytes(out)
        fn=_get_channel_lib().slk_channel_recv_security
        self.assertEqual(fn(-1,buffer,8,0,ctypes.byref(out),ctypes.byref(actual)),-errno.EBADF)
        self.assertEqual(bytes(out),before);self.assertEqual(actual.value,77)
        self.assertEqual(fn(-1,None,8,0,ctypes.byref(out),ctypes.byref(actual)),-errno.EINVAL)
        self.assertEqual(fn(-1,buffer,8,0,None,ctypes.byref(actual)),-errno.EINVAL)
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as unix:
            with self.assertRaises(OSError) as caught:channel_recv_security(unix.fileno(),8,socket.MSG_DONTWAIT)
            self.assertEqual(caught.exception.errno,errno.EAFNOSUPPORT)
        for args in [(True,8,0),(0,True,0),(0,2048,0),(0,8,socket.MSG_WAITALL)]:
            with self.assertRaises(ValueError):channel_recv_security(*args)

    def test_typed_send_is_actual_syscall_without_plain_fallback(self):
        from sparklink.structs import SleSendConstraint
        from sparklink.channel import channel_send_constrained
        import socket
        c=SleSendConstraint(version=1,size=48,minimum=1,generation=7,lifetime=9,
            security_epoch=2,controller=1,handle=3,local_tcid=31,remote_tcid=31,pi=241,
            deadline_monotonic_ns=123456)
        payload=(ctypes.c_uint8*1)(42);before=bytes(c)
        self.assertEqual(_get_channel_lib().slk_channel_send_constrained(-1,payload,1,0,ctypes.byref(c)),-errno.EBADF)
        self.assertEqual(bytes(c),before)
        self.assertEqual(_get_channel_lib().slk_channel_send_constrained(-1,payload,1,0,None),-errno.EINVAL)
        self.assertEqual(_get_channel_lib().slk_channel_send_constrained(-1,None,1,0,ctypes.byref(c)),-errno.EINVAL)
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as unix:
            with self.assertRaises(OSError) as caught:channel_send_constrained(unix.fileno(),b'x',c,socket.MSG_DONTWAIT)
            self.assertEqual(caught.exception.errno,errno.EAFNOSUPPORT)
        c.minimum=3
        self.assertEqual(_get_channel_lib().slk_channel_send_constrained(-1,payload,1,0,ctypes.byref(c)),-errno.EINVAL)
        for args in [(True,b'x',c),(0,bytearray(b'x'),c),(0,b'x'*2043,c)]:
            with self.assertRaises(ValueError):channel_send_constrained(*args)

    def test_prepare_tx_requires_real_domain_and_preserves_failed_output(self):
        from sparklink.structs import SleSendConstraint
        from sparklink.channel import channel_prepare_tx
        import socket
        out=SleSendConstraint(generation=99,security_epoch=123);before=bytes(out)
        fn=_get_channel_lib().slk_channel_prepare_tx
        self.assertEqual(fn(-1,0,1,ctypes.byref(out)),-errno.EBADF)
        self.assertEqual(bytes(out),before)
        self.assertEqual(fn(-1,0,1,None),-errno.EINVAL)
        for minimum,deadline in [(3,1),(0,0)]:
            self.assertEqual(fn(-1,minimum,deadline,ctypes.byref(out)),-errno.EINVAL)
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as unix:
            with self.assertRaises(OSError) as caught:channel_prepare_tx(unix.fileno(),0,1)
            self.assertEqual(caught.exception.errno,errno.EAFNOSUPPORT)
        for args in [(True,0,1),(0,True,1),(0,0,True),(0,0,1<<64)]:
            with self.assertRaises(ValueError):channel_prepare_tx(*args)
        self.assertEqual(bytes(out),before)

    def test_channel_info_errors_preserve_output_and_errno(self):
        out = SleChannelInfo(generation=99, reserved=123)
        before = bytes(out)
        self.assertEqual(_get_channel_lib().slk_channel_info(-1, ctypes.byref(out)), -errno.EBADF)
        self.assertEqual(bytes(out), before)
        self.assertEqual(_get_channel_lib().slk_channel_info(-1, None), -errno.EINVAL)
        with self.assertRaises(OSError) as caught:
            channel_info(-1)
        self.assertEqual(caught.exception.errno, errno.EBADF)
        with self.assertRaises(ValueError):
            channel_info(True)

    def test_tx_status_denies_bad_fd_without_overwriting(self):
        out=SleChannelTxStatus(generation=99,reserved=44)
        before=bytes(out)
        self.assertEqual(_get_channel_lib().slk_channel_tx_status(-1,ctypes.byref(out)),-errno.EBADF)
        self.assertEqual(bytes(out),before)
        self.assertEqual(_get_channel_lib().slk_channel_tx_status(-1,None),-errno.EINVAL)

    def test_session_status_denies_bad_fd_without_overwriting(self):
        out=SleSessionTxStatus(generation=99)
        before=bytes(out)
        self.assertEqual(_get_channel_lib().slk_session_tx_status(-1,ctypes.byref(out)),-errno.EBADF)
        self.assertEqual(bytes(out),before)
        self.assertEqual(_get_channel_lib().slk_session_tx_status(-1,None),-errno.EINVAL)

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
        self.assertEqual(self.lib.slk_device_count.argtypes, [ctypes.c_void_p])
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
        limited=SleSecurityNegotiationSubmit(version=2,deadline_monotonic_ns=1,profile=1,flags=1,action=2,generation=1,lifetime=1,request_id=1,timeout_ms=5000)
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


class ApplicationNativeBoundary(unittest.TestCase):
    def test_default_package_and_actual_libraries_do_not_reexport_native_authority(self):
        import sparklink
        import importlib
        self.assertFalse(hasattr(sparklink, "Adapter"))
        self.assertFalse(hasattr(sparklink, "NativeAdapter"))
        self.assertFalse(hasattr(sparklink, "registration_snapshot"))
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("sparklink.adapter")
        app=_get_channel_lib()
        import re
        repo=Path(__file__).resolve().parents[3]
        native_names=re.findall(r'\b(slk_\w+)\s*\(', (repo/'crates/slk-native/include/sparklink_native.h').read_text())
        app_names=re.findall(r'\b(slk_\w+)\s*\(', (repo/'crates/libsparklink/include/sparklink.h').read_text())
        self.assertTrue(native_names)
        self.assertTrue(app_names)
        for name in native_names:
            with self.subTest(name=name),self.assertRaises(AttributeError):getattr(app,name)
        native=_get_native_lib()
        for name in ("slk_sec_info", "slk_pair", "slk_encrypt_on"):
            with self.subTest(retired=name),self.assertRaises(AttributeError):getattr(native,name)
        import sparklink.structs as structs
        for name in ("SleSecInfo","SlePairParams"):
            self.assertFalse(hasattr(structs,name))
        for name in app_names:
            with self.subTest(name=name),self.assertRaises(AttributeError):getattr(native,name)

    def test_concurrent_first_native_load_never_publishes_untyped_pointer_calls(self):
        import concurrent.futures
        import sparklink.native as module
        module._native_library=None
        def call(_):
            lib=module._get_native_lib()
            self.assertEqual(lib.slk_device_count.argtypes,[ctypes.c_void_p])
            self.assertEqual(lib.slk_adapter_open.restype,ctypes.c_void_p)
            handle=lib.slk_adapter_open(b"/dev/null")
            self.assertTrue(handle)
            try:self.assertEqual(lib.slk_device_count(handle),-1)
            finally:lib.slk_adapter_free(handle)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(call,range(64)))
