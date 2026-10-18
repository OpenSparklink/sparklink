"""Python ABI/ownership fixtures only. Actual cdylib/private bus is application_ffi.rs.

No hardware/controller/power/Native event or protocol success is represented.
"""
import ctypes
import errno
import os
import threading
import unittest
from unittest.mock import patch
from sparklink import Client, ControllerId, ControllerEvents
from sparklink.controller_events import _Event, _decode
from sparklink.client import _ControllerId


class Boundary:
    def __init__(self, interrupt=False):self.interrupt=interrupt;self.closed=[];self.flags=[]
    def slk_client_controller_events(self, client, deadline, out):
        out._obj.value=123
        if self.interrupt:raise RuntimeError('interrupt after delivered observation view')
        return 0
    def slk_controller_events_close(self, handle):self.closed.append(handle.value)
    def slk_client_close(self, handle):pass
    def slk_controller_events_next(self, handle, output, ids, capacity, count, flags, deadline):
        self.flags.append(flags);row=output._obj;row.kind=2;row.sequence=7
        ids[0].index=2;ids[0].generation=9;count._obj.value=1;return 0


def caller(bridge):
    client=object.__new__(Client);client._lib=bridge;client._handle=ctypes.c_void_p(42)
    client._pid=os.getpid();client._lock=threading.RLock();return client


class DirectoryLanguageBoundary(unittest.TestCase):
    def test_delivered_view_released_on_python_exception(self):
        bridge=Boundary(True)
        with caller(bridge) as client,patch('sparklink.controller_events._configure'):
            with self.assertRaisesRegex(RuntimeError,'interrupt after'):
                client.controller_events(deadline_ns=1)
        self.assertEqual(bridge.closed,[123])

    def test_parent_close_derived_own_close_and_peek_flags(self):
        bridge=Boundary()
        with caller(bridge) as client,patch('sparklink.controller_events._configure'):
            view=client.controller_events(deadline_ns=1)
        with view:
            value=view.next(deadline_ns=1,peek=True)
            self.assertEqual((value.kind,value.sequence,value.controllers),('published',7,(ControllerId(2,9),)))
            self.assertEqual(view.next(deadline_ns=1),value)
            for bad in [1,None,'yes']:
                with self.assertRaises(ValueError):view.next(deadline_ns=1,peek=bad)
        view.close();self.assertEqual(bridge.closed,[123]);self.assertEqual(bridge.flags,[1,0])
        with self.assertRaises(ValueError):view.next(deadline_ns=1)
        with self.assertRaises(TypeError):ControllerEvents()

    def test_fork_guard_precedes_mutex_and_ffi(self):
        bridge=Boundary()
        with caller(bridge) as client,patch('sparklink.controller_events._configure'):
            view=client.controller_events(deadline_ns=1)
        with patch('sparklink.controller_events.os.getpid',return_value=-1):
            for call in [view.close,view.__enter__,lambda:view.next(deadline_ns=1)]:
                with self.assertRaises(RuntimeError):call()
        view.close();self.assertEqual(bridge.flags,[])

    def test_independent_abi_shape_and_malformed_outputs(self):
        self.assertEqual(ctypes.sizeof(_Event),32);self.assertEqual(_Event.kind.offset,24)
        ids=(_ControllerId*2)();ids[0].index=2;ids[0].generation=9
        self.assertEqual(_decode(_Event(0,0,0,1,0),ids,0).controllers,())
        self.assertEqual(_decode(_Event(0,2,65,4,0),ids,0).kind,'gap')
        for value,count in [(_Event(1,0,0,0,0),0),(_Event(1,0,0,5,0),0),
                            (_Event(1,0,0,2,0),0),(_Event(0,0,0,2,0),1),
                            (_Event(1,0,0,1,1),1),(_Event(0,1,0,4,0),0),
                            (_Event(0,2,65,4,0),1),(_Event(1,2,0,2,0),1),
                            (_Event(1,0,0,1,0),257)]:
            with self.assertRaises(OSError) as error:_decode(value,ids,count)
            self.assertEqual(error.exception.errno,errno.EPROTO)
        for field,value in [('generation',0),('reserved',(ctypes.c_uint8*6)(1))]:
            old=getattr(ids[0],field);setattr(ids[0],field,value)
            with self.assertRaises(OSError):_decode(_Event(1,0,0,2,0),ids,1)
            setattr(ids[0],field,old)
