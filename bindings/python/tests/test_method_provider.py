"""Python input/layout/decoder boundaries; not Rust admission or wire proof.

Actual C/Python consumers and callback lifetimes run in application_ffi.
"""
import ctypes
import errno
import unittest
from unittest.mock import patch

from sparklink import ControllerId, LocalMethod, MethodAccess
from sparklink.local_services import _Method, _Receipt
from sparklink.service_authorization import _Info as AuthorizationRaw
from sparklink.service_provider import _MethodInfo, MethodProviderRequest
from test_local_services import Boundary, caller, definition


class MethodBoundary(Boundary):
    def __init__(self):
        super().__init__()
        self.corrupt = lambda receipt: None

    def slk_client_register_local_entries(self, client, identity, uuid, size,
            properties, count, methods, method_count, authorization, deadline, output):
        self.request = (count, method_count, methods[0].access, authorization, deadline)
        output._obj.value = 123
        return 0

    def slk_local_service_receipt(self, view, output):
        value = output._obj
        value.controller.index, value.controller.generation = 2, 7
        value.start, value.end = 16, 18
        value.property_count, value.method_count = 1, 1
        value.handles[0], value.handles[1] = 17, 18
        self.corrupt(value)
        return 0


class MethodBoundaryTests(unittest.TestCase):
    def test_layout_and_distinct_access(self):
        self.assertEqual((ctypes.sizeof(_Method), _Method.uuid.offset), (24, 8))
        self.assertEqual((ctypes.sizeof(_Receipt), _Receipt.method_count.offset), (152, 22))
        self.assertEqual((ctypes.sizeof(_MethodInfo), _MethodInfo.method.offset), (80, 62))
        self.assertEqual((ctypes.sizeof(AuthorizationRaw), AuthorizationRaw.value.offset), (2120, 72))
        self.assertEqual(len(AuthorizationRaw().value), 2043)
        for bits in range(8):
            self.assertEqual(MethodAccess(bits).bits, bits)
        for bits in [True, -1, 8, 32, 2**32, '4']:
            with self.assertRaises((TypeError, ValueError)):
                MethodAccess(bits)

    def test_combined_receipt_keeps_targets_separate(self):
        boundary = MethodBoundary()
        with patch('sparklink.local_services._configure'), caller(boundary) as client:
            with client.register_local_entries(ControllerId(2, 7), b'ab', [definition()],
                    [LocalMethod(b'cd', MethodAccess(4))], authorization='requests',
                    deadline_ns=1) as service:
                self.assertEqual(boundary.request, (1, 1, 4, 1, 1))
                self.assertEqual(service.receipt.handles, (17, 18))
                self.assertEqual(service.receipt.property_handles, (17,))
                self.assertEqual(service.receipt.method_handles, (18,))

    def test_invalid_combined_inputs_do_not_call_ffi(self):
        boundary = MethodBoundary()
        with patch('sparklink.local_services._configure'), caller(boundary) as client:
            method = LocalMethod(b'cd', MethodAccess(0))
            for properties, methods in [([], []), ([definition()] * 64, [method]),
                                         ([], [definition()]), ([method], [])]:
                with self.assertRaises((TypeError, ValueError)):
                    client.register_local_entries(ControllerId(2, 7), b'ab', properties,
                        methods, deadline_ns=1)
            self.assertFalse(hasattr(boundary, 'request'))

    def test_corrupt_receipt_frees_view_without_guessed_unregister(self):
        for corrupt in [lambda r: setattr(r, 'method_count', 0),
                        lambda r: setattr(r, 'property_count', 0),
                        lambda r: r.handles.__setitem__(1, 17),
                        lambda r: r.handles.__setitem__(2, 19)]:
            boundary = MethodBoundary()
            boundary.corrupt = corrupt
            with patch('sparklink.local_services._configure'), caller(boundary) as client:
                with self.assertRaises(OSError) as error:
                    client.register_local_entries(ControllerId(2, 7), b'ab', [definition()],
                        [LocalMethod(b'cd', MethodAccess(0))], deadline_ns=1)
                self.assertEqual(error.exception.errno, errno.EPROTO)
            self.assertEqual(boundary.freed, [123])
            self.assertEqual(boundary.unregistered, [])

    def test_decoder_budgets_and_command_semantics(self):
        identity = ControllerId(2, 7)
        for op, arguments, result in [(19, 2043, 2045), (18, 2043, 0), (19, 0, 0)]:
            raw = _MethodInfo(operation=op, argument_length=arguments, maximum_result_bytes=result)
            decoded = MethodProviderRequest._decode_info(identity, raw)
            self.assertEqual((decoded.operation, decoded.argument_length, decoded.maximum_result_bytes),
                             (op, arguments, result))
        for op, arguments, result in [(18, 1, 1), (19, 2044, 0), (19, 0, 2046), (20, 0, 0)]:
            with self.assertRaises(OSError) as error:
                MethodProviderRequest._decode_info(identity, _MethodInfo(
                    operation=op, argument_length=arguments, maximum_result_bytes=result))
            self.assertEqual(error.exception.errno, errno.EPROTO)
