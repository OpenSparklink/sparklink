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
from sparklink.client import _SsapUpdate


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

    def slk_connection_ssap_read_description(self, *args):
        self.calls.append(('description',args[1],args[2],args[6]))
        args[3][:3] = [0x64,0x65,0x73]
        ctypes.cast(args[5], ctypes.POINTER(ctypes.c_size_t))[0] = 3
        return 0

    def slk_connection_ssap_write(self, *args):
        self.calls.append(bytes(args[3]))
        args[5][0] = 0x90
        ctypes.cast(args[7], ctypes.POINTER(ctypes.c_size_t))[0] = 1
        return 0

    def slk_connection_ssap_write_command(self, *args):
        self.calls.append(('command', args[1], args[2], bytes(args[3]), args[5]))
        return 0

    def _update(self, args, stage):
        self.calls.append(('update', stage))
        v = _SsapUpdate()
        raw = bytes([16 if stage == 2 else 15, 3, 17, 0, 1, 0, 0xab])
        v.stage, v.pdu_length = stage, len(raw)
        v.pdu[:len(raw)] = raw
        if stage == 2:
            v.acknowledgement_length = 3
            v.acknowledgement[:] = [17, 3, 1]
        ctypes.cast(args[3], ctypes.POINTER(_SsapUpdate))[0] = v
        return 0

    def slk_connection_ssap_receive(self, *args):
        return self._update(args, 3)

    def slk_connection_ssap_send_owned(self, *args):
        return self._update(args, 2 if args[2] else 1)

    def slk_connection_ssap_owned_configuration(self, *args):
        ctypes.cast(args[2], ctypes.POINTER(ctypes.c_uint8))[0] = 3
        return 0


def caller(bridge):
    client = object.__new__(Client)
    client._lib, client._handle = bridge, ctypes.c_void_p(42)
    client._pid, client._lock = os.getpid(), threading.RLock()
    return client


class PythonConnectionBoundary(unittest.TestCase):
    def test_update_layout_marshalling_and_distinct_completion_stages(self):
        self.assertEqual((ctypes.sizeof(_SsapUpdate),_SsapUpdate.pdu.offset,
                          _SsapUpdate.acknowledgement.offset),(2064,8,2056))
        bridge=Boundary()
        with caller(bridge) as client, client.connection(ControllerId(2,7),'/fixture',deadline_ns=1) as connection:
            remote=connection.ssap()
            self.assertEqual(remote.receive_update(17,deadline_ns=1).stage,3)
            self.assertEqual(remote.send_owned_update(17,deadline_ns=1).stage,1)
            self.assertEqual(remote.send_owned_update(17,deadline_ns=1,indication=True).acknowledgement,b'\x11\x03\x01')
            self.assertEqual(remote.owned_configuration(17,deadline_ns=1),3)
            for modes in (0,4,True):
                with self.assertRaises(ValueError):remote.receive_update(17,deadline_ns=1,modes=modes)
            with self.assertRaises(TypeError):remote.send_owned_update(17,deadline_ns=1,indication=1)

    def test_maximum_update_abi_keeps_the_complete_2042_byte_value(self):
        # ctypes/output contract fixture,not Native or remote delivery.
        bridge=Boundary()
        expected=b'\x0f\x03\x11\0\xfa\x07'+bytes(range(256))*7+bytes(range(250))
        self.assertEqual(len(expected),2048)
        def complete(*args):
            bridge._update(args,3)
            value=ctypes.cast(args[3],ctypes.POINTER(_SsapUpdate)).contents
            value.pdu_length=len(expected)
            value.pdu[:]=expected
            return 0
        bridge.slk_connection_ssap_receive=complete
        with caller(bridge) as client,client.connection(ControllerId(2,7),'/fixture',deadline_ns=1) as connection:
            self.assertEqual(connection.ssap().receive_update(17,deadline_ns=1,modes=1).pdu,expected)

    def test_malformed_update_receipts_are_rejected_without_retry(self):
        for mutation in ['stage','length','reserved','tail','ack']:
            bridge=Boundary()
            def corrupt(*args):
                bridge._update(args,3)
                value=ctypes.cast(args[3],ctypes.POINTER(_SsapUpdate)).contents
                if mutation=='stage':value.stage=1
                elif mutation=='length':value.pdu_length=2049
                elif mutation=='reserved':value.reserved[0]=1
                elif mutation=='tail':value.pdu[2041]=1
                else:value.acknowledgement_length=1
                return 0
            bridge.slk_connection_ssap_receive=corrupt
            with caller(bridge) as client, client.connection(ControllerId(2,7),'/fixture',deadline_ns=1) as connection:
                with self.assertRaises(OSError) as caught:connection.ssap().receive_update(17,deadline_ns=1)
                self.assertEqual(caught.exception.errno,errno.EPROTO)
            self.assertEqual(len(bridge.calls),1)
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

    def test_description_keeps_separate_method_value_result_and_errors(self):
        bridge=Boundary()
        with caller(bridge) as client,client.connection(ControllerId(2,7),'/fixture',deadline_ns=1) as link:
            remote=link.ssap()
            self.assertEqual(remote.read_description(17,minimum=2,deadline_ns=42),b'des')
            self.assertEqual(bridge.calls,[('description',17,2,42)])
            for handle,minimum in [(0,0),(True,0),(65536,0),(17,3),(17,True)]:
                with self.assertRaises(ValueError):remote.read_description(handle,minimum=minimum,deadline_ns=43)
            self.assertEqual(len(bridge.calls),1)
            for code in (errno.EACCES,errno.ETIMEDOUT,errno.ESTALE):
                bridge.slk_connection_ssap_read_description=lambda *args:-code
                with self.assertRaises(OSError) as e:remote.read_description(17,deadline_ns=44)
                self.assertEqual(e.exception.errno,code)
            old=link._pid;link._pid=-1
            with self.assertRaises(RuntimeError):remote.read_description(17,deadline_ns=45)
            link._pid=old

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


class PythonCommandBoundary(unittest.TestCase):
    def test_unit_result_empty_value_and_error_propagation_without_retry(self):
        bridge = Boundary()
        with caller(bridge) as client, client.connection(ControllerId(2, 7), '/fixture', deadline_ns=1) as connection:
            remote = connection.ssap()
            self.assertIsNone(remote.write_without_response(17, b'\x12', minimum=2, deadline_ns=1))
            self.assertIsNone(remote.write_without_response(17, b'', deadline_ns=2))
            def refuse(*args):
                bridge.calls.append(('refused', args[1]))
                return -errno.EACCES
            bridge.slk_connection_ssap_write_command = refuse
            with self.assertRaises(OSError) as caught:
                remote.write_without_response(17, b'\x12', deadline_ns=3)
            self.assertEqual(caught.exception.errno, errno.EACCES)
        self.assertEqual(bridge.calls, [('command', 17, 2, b'\x12', 1), ('command', 17, 0, b'', 2), ('refused', 17)])
        with self.assertRaises(ValueError):
            remote.write_without_response(17, b'', deadline_ns=1)

    def test_invalid_input_and_fork_never_reach_command_abi(self):
        bridge = Boundary()
        with caller(bridge) as client, client.connection(ControllerId(2, 7), '/fixture', deadline_ns=1) as connection:
            remote = connection.ssap()
            for handle in (0, True, -1, 65536):
                with self.assertRaises(ValueError):
                    remote.write_without_response(handle, b'', deadline_ns=1)
            for minimum in (3, True, -1):
                with self.assertRaises(ValueError):
                    remote.write_without_response(17, b'', minimum=minimum, deadline_ns=1)
            with self.assertRaises(TypeError):
                remote.write_without_response(17, 42, deadline_ns=1)
            for value in (b'x'*65536, memoryview(bytearray(65536)).cast('I')):
                with self.assertRaises(OSError) as caught:
                    remote.write_without_response(17, value, deadline_ns=1)
                self.assertEqual(caught.exception.errno, errno.EMSGSIZE)
            with patch('sparklink.client.os.getpid', return_value=connection._pid+1):
                with self.assertRaises(RuntimeError):
                    remote.write_without_response(17, b'', deadline_ns=1)
        self.assertEqual(bridge.calls, [])
