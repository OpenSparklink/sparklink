"""C-boundary fixtures only: Python ownership/marshalling, not D-Bus/SSAP/RF.

The actual cdylib and private-bus test is application_ffi.rs. These explicit
fixtures cover Python exceptions and fork guards without calling invalid C
pointers or representing fixture bytes as a protocol reply.
"""
import ctypes
import errno
import os
import threading
import unittest
from unittest.mock import patch

from sparklink import Client, ControllerId


class Boundary:
    def __init__(self, fail=False):
        self.fail = fail
        self.closed, self.calls = [], []

    def slk_client_connection(self, *args):
        ctypes.cast(args[-1], ctypes.POINTER(ctypes.c_void_p))[0] = 123
        if self.fail:
            raise RuntimeError("explicit Python interruption after native result")
        return 0

    def slk_connection_close(self, handle):
        self.closed.append(handle.value)

    def slk_client_close(self, _):
        pass

    def slk_connection_ssap_read(self, *args):
        self.calls.append('read')
        args[3][0] = 0x34
        ctypes.cast(args[5], ctypes.POINTER(ctypes.c_size_t))[0] = 1
        return 0

    def slk_connection_ssap_write(self, *args):
        self.calls.append(bytes(args[3]))
        args[5][0] = 0x90
        ctypes.cast(args[7], ctypes.POINTER(ctypes.c_size_t))[0] = 1
        return 0


def caller(bridge):
    client = object.__new__(Client)
    client._lib, client._handle = bridge, ctypes.c_void_p(42)
    client._pid, client._lock = os.getpid(), threading.RLock()
    return client


class PythonConnectionBoundary(unittest.TestCase):
    def test_delivered_native_view_is_closed_once_on_python_exception(self):
        bridge = Boundary(fail=True)
        with caller(bridge) as client:
            with self.assertRaisesRegex(RuntimeError, 'after native'):
                client.connection(ControllerId(2, 7), '/explicit-fixture', deadline_ns=1)
        self.assertEqual(bridge.closed, [123])

    def test_parent_close_and_view_close_are_distinct_and_bytes_not_echoed(self):
        bridge = Boundary()
        with caller(bridge) as client:
            connection = client.connection(ControllerId(2, 7), '/explicit-fixture', deadline_ns=1)
        with connection:
            remote = connection.ssap()
            self.assertEqual(remote.read(17, deadline_ns=1), b'\x34')
            self.assertEqual(remote.write(17, b'\x12', deadline_ns=1), b'\x90')
            self.assertEqual(remote.write(17, b'', deadline_ns=1), b'\x90')
        self.assertEqual(bridge.calls, ['read', b'\x12', b''])
        self.assertEqual(bridge.closed, [123])
        with self.assertRaises(ValueError):
            remote.read(17, deadline_ns=1)
        connection.close()
        self.assertEqual(bridge.closed, [123])

    def test_invalid_and_oversized_inputs_never_enter_boundary(self):
        bridge = Boundary()
        with caller(bridge) as client, client.connection(ControllerId(2, 7), '/fixture', deadline_ns=1) as connection:
            remote = connection.ssap()
            for handle in (0, True, -1, 65536):
                with self.subTest(handle=handle), self.assertRaises(ValueError):
                    remote.read(handle, deadline_ns=1)
            with self.assertRaises(ValueError):
                remote.read(17, minimum=3, deadline_ns=1)
            with self.assertRaises(TypeError):
                remote.write(17, 42, deadline_ns=1)
            # Non-byte-format memoryview len differs from nbytes.
            values = [b'x' * 65536, memoryview(bytearray(65536)).cast('I')]
            for value in values:
                with self.assertRaises(OSError) as error:
                    remote.write(17, value, deadline_ns=1)
                self.assertEqual(error.exception.errno, errno.EMSGSIZE)
        self.assertEqual(bridge.calls, [])

    def test_fork_rejection_precedes_inherited_mutex_or_native_calls(self):
        class NeverLock:
            def __enter__(self):
                raise AssertionError('inherited lock touched')
            def __exit__(self, *_):
                pass
        bridge = Boundary()
        with caller(bridge) as client:
            connection = client.connection(ControllerId(2, 7), '/fixture', deadline_ns=1)
        lock = connection._lock
        connection._lock = NeverLock()
        with patch('sparklink.client.os.getpid', return_value=connection._pid + 1):
            for action in (connection.close, connection.__enter__, connection.ssap,
                           lambda: connection.ssap().read(17, deadline_ns=1)):
                with self.assertRaises(RuntimeError):
                    action()
        connection._lock = lock
        connection.close()
        self.assertEqual(bridge.calls, [])
        self.assertEqual(bridge.closed, [123])
