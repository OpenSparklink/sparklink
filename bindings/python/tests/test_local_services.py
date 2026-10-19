"""Python input/ABI/ownership fixtures only;not daemon,wire or RF proof."""
import ctypes
import errno
import gc
import os
import threading
import unittest
from unittest.mock import patch
from sparklink import Client, ControllerId, LocalProperty, LocalService, SsapOperations, SsapAccess
from sparklink.local_services import _Property, _Receipt


class Boundary:
    def __init__(self):self.freed=[];self.unregistered=[];self.closed=[];self.reads=[];self.error=0;self.bad=False
    def slk_client_register_local_service(self,c,i,u,n,ps,count,authorization,d,out):
        self.request=(bytes(u),n,count,d,ps[0].operations,ps[0].access,bytes(ps[0].value[:ps[0].value_length]));out._obj.value=123;return 0
    def slk_local_service_receipt(self,v,r):
        r=r._obj;r.controller.index=2;r.controller.generation=7;r.start=16;r.end=17;r.property_count=1;r.handles[0]=99 if self.bad else 17;return 0
    def slk_local_service_read(self,v,h,buf,cap,n,d):
        self.reads.append((h,cap,d))
        if self.error:return self.error
        if cap<3:n._obj.value=3;return -errno.ENOBUFS
        buf[:3]=b'abc';n._obj.value=3;return 0
    def slk_local_service_unregister(self,v,d):self.unregistered.append((v.value,d));return self.error
    def slk_local_service_free(self,v):self.freed.append(v.value)
    def slk_client_close(self,v):self.closed.append(v.value)


def caller(b):
    c=object.__new__(Client);c._lib=b;c._handle=ctypes.c_void_p(42);c._pid=os.getpid();c._lock=threading.RLock();return c

def definition():return LocalProperty(b'\x02\0',SsapOperations(5),SsapAccess(0),b'abc')


class LocalServicesBoundary(unittest.TestCase):
    def test_layouts_and_parent_close_explicit_unregister_local_free(self):
        self.assertEqual((ctypes.sizeof(_Property),_Property.value.offset),(2076,32))
        self.assertEqual((ctypes.sizeof(_Receipt),_Receipt.handles.offset),(152,24))
        b=Boundary()
        with patch('sparklink.local_services._configure'),caller(b) as c:
            v=c.register_local_service(ControllerId(2,7),b'\x01\0',[definition()],deadline_ns=1)
        self.assertEqual(b.closed,[42]);self.assertEqual(v.receipt.handles,(17,))
        self.assertEqual(b.request,(b'\x01\0',2,1,1,5,0,b'abc'))
        with v:
            self.assertEqual(v.read_local(17,deadline_ns=2),b'abc')
            with self.assertRaises(OSError) as e:v.read_local(17,capacity=1,deadline_ns=3)
            self.assertEqual(e.exception.errno,errno.ENOBUFS)
            v.unregister(deadline_ns=4)
        v.close();del v;gc.collect();self.assertEqual(b.freed,[123]);self.assertEqual(b.unregistered,[(123,4)])
        with self.assertRaises(TypeError):LocalService()

    def test_invalid_input_and_bad_receipt_fail_without_guessed_cleanup(self):
        b=Boundary()
        with patch('sparklink.local_services._configure'),caller(b) as c:
            for u,ps in [(b'', [definition()]),(b'\0\0',[definition()]),('aa',[definition()]),(b'ab',[]),(b'ab',[object()]),(b'ab',[definition()]*65)]:
                with self.assertRaises((TypeError,ValueError)):c.register_local_service(ControllerId(2,7),u,ps,deadline_ns=1)
            self.assertFalse(hasattr(b,'request'))
            for value in [b'x'*2043,'abc']:
                with self.assertRaises(ValueError):LocalProperty(b'ab',SsapOperations(5),SsapAccess(0),value)
            with self.assertRaises(TypeError):LocalProperty(b'ab',5,SsapAccess(0))
            b.bad=True
            with self.assertRaises(OSError) as e:c.register_local_service(ControllerId(2,7),b'ab',[definition()],deadline_ns=1)
            self.assertEqual(e.exception.errno,errno.EPROTO)
            gc.collect();self.assertEqual(b.freed,[123]);self.assertEqual(b.unregistered,[])

    def test_uncertain_withdrawal_and_fork_before_lock(self):
        b=Boundary()
        with patch('sparklink.local_services._configure'),caller(b) as c:
            v=c.register_local_service(ControllerId(2,7),b'ab',[definition()],deadline_ns=1)
            b.error=-errno.ETIMEDOUT
            with self.assertRaises(OSError) as e:v.unregister(deadline_ns=2)
            self.assertEqual(e.exception.errno,errno.ETIMEDOUT);self.assertTrue(v._handle.value)
            b.error=0;self.assertEqual(v.read_local(17,deadline_ns=3),b'abc')
            original=v._pid;v._pid=-1
            class Poison:
                def __enter__(self):raise AssertionError('fork touched inherited mutex')
            old=v._lock;v._lock=Poison()
            for call in [lambda:v.read_local(17,deadline_ns=4),lambda:v.unregister(deadline_ns=4),v.close]:
                with self.assertRaises(RuntimeError):call()
            v._pid=original;v._lock=old;v.close()
        self.assertEqual(b.freed,[123]);self.assertEqual(b.unregistered,[(123,2)])
