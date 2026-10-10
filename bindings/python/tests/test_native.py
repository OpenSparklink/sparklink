"""Exercise actual shared-library ABI/errors and Python handle lifetime.

/dev/null is deliberately not a SparkLink controller. Hardware success belongs
to the native KVM/physical gates, not this negative syscall/ABI suite.
"""
import ctypes
import errno
from pathlib import Path
import unittest

from sparklink import NativeAdapter
from sparklink.native import _get_native_lib
from sparklink.structs import (
    SleControllerSnapshot, SleManagementQuery, SleDiscoverySubmit,
    SleDiscoveryResult, SleControllerEventQuery, SleSnoopQuery,
)


class NativeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = _get_native_lib()

    def setUp(self):
        self.handle = self.lib.slk_adapter_open(b"/dev/null")
        self.assertTrue(self.handle)
        self.addCleanup(self.lib.slk_adapter_free, self.handle)

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
            ("slk_management_query", [1], SleManagementQuery(lease=99)),
            ("slk_management_acquire", [1, 1], ctypes.c_uint64(99)),
            ("slk_discovery_result", [1, 1], SleDiscoveryResult(request_id=99)),
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
        result = SleDiscoveryResult()
        for generation, request in [(0, 1), (1, 0)]:
            self.assertEqual(self.lib.slk_discovery_result(self.handle, generation, request, ctypes.byref(result)), -errno.EINVAL)

    def test_writer_calls_preserve_transport_errors_and_null_guards(self):
        request = SleDiscoverySubmit()
        self.assertEqual(self.lib.slk_discovery_submit(self.handle, ctypes.byref(request)), -errno.ENOTTY)
        self.assertEqual(self.lib.slk_discovery_submit(self.handle, None), -errno.EINVAL)
        self.assertEqual(self.lib.slk_management_release(self.handle, 1, 1, 1), -errno.ENOTTY)
        self.assertEqual(self.lib.slk_management_release(None, 1, 1, 1), -errno.EINVAL)

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
