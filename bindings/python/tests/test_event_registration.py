"""Python event input/receipt boundaries; FFI is explicit fixture, not wire proof."""
import ctypes
import errno
import unittest
from unittest.mock import patch
from sparklink import ControllerId, LocalEvent, LocalMethod, MethodAccess
from sparklink.local_services import _Event, _Receipt
from test_local_services import Boundary, caller, definition

class EventBoundary(Boundary):
    def __init__(self):
        super().__init__()
        self.corrupt = lambda r: None
    def slk_client_register_local_entries(self, c, identity, uuid, n, properties, count,
            methods, method_count, events, event_count, authorization, deadline, output):
        self.request = (count, method_count, event_count, bytes(events[0].uuid[:events[0].uuid_length]))
        output._obj.value = 123
        return 0
    def slk_local_service_receipt(self, view, output):
        r = output._obj
        r.controller.index, r.controller.generation = 2, 7
        r.start, r.end = 16, 19
        r.property_count = r.method_count = r.event_count = 1
        r.handles[:3] = [17,18,19]
        self.corrupt(r)
        return 0

class EventRegistrationTests(unittest.TestCase):
    def test_mixed_receipt_has_distinct_handle_groups(self):
        self.assertEqual((ctypes.sizeof(_Event), _Event.uuid.offset), (20,4))
        self.assertEqual((ctypes.sizeof(_Receipt), _Receipt.event_count.offset, _Receipt.handles.offset), (160,24,32))
        b = EventBoundary()
        with patch('sparklink.local_services._configure'), caller(b) as client:
            with client.register_local_entries(ControllerId(2,7), b'ab', [definition()],
                    [LocalMethod(b'cd',MethodAccess(0))], events=[LocalEvent(b'ef')],deadline_ns=1) as service:
                self.assertEqual(b.request,(1,1,1,b'ef'))
                self.assertEqual((service.receipt.property_handles,service.receipt.method_handles,service.receipt.event_handles),((17,),(18,),(19,)))
    def test_invalid_events_and_shared_budget_fail_before_ffi(self):
        for uuid in [b'',b'\0\0',b'1',b'x'*17,'ab']:
            with self.assertRaises((ValueError,TypeError)):LocalEvent(uuid)
        b = EventBoundary()
        with patch('sparklink.local_services._configure'), caller(b) as client:
            for events in [[definition()],[LocalEvent(b'ef')]*64]:
                with self.assertRaises((ValueError,TypeError)):
                    client.register_local_entries(ControllerId(2,7),b'ab',[definition()],[],events=events,deadline_ns=1)
            self.assertFalse(hasattr(b,'request'))
    def test_bad_event_count_or_reserved_bytes_cannot_make_receipt(self):
        for mutate in [lambda r:setattr(r,'event_count',0), lambda r:r.reserved.__setitem__(1,1), lambda r:r.handles.__setitem__(2,18)]:
            b=EventBoundary();b.corrupt=mutate
            with patch('sparklink.local_services._configure'), caller(b) as client:
                with self.assertRaises(OSError) as error:
                    client.register_local_entries(ControllerId(2,7),b'ab',[definition()],
                        [LocalMethod(b'cd',MethodAccess(0))],events=[LocalEvent(b'ef')],deadline_ns=1)
                self.assertEqual(error.exception.errno,errno.EPROTO)
            self.assertEqual(b.freed,[123]);self.assertEqual(b.unregistered,[])
