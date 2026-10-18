"""Python ABI/ownership fixtures; not controller, wire or real-bus qualification."""
import ctypes
import errno
import os
import threading
import unittest
from unittest.mock import patch
from sparklink import Client, ControllerId, DiscoverySession
from sparklink.discovery import _Batch, _Report, _decode


class Boundary:
    def __init__(self):self.freed=[];self.flags=[];self.closed=[];self.stop=0
    def slk_client_discover(self,c,controller,prefix,length,rssi,duration,deadline,out):
        self.request=(bytes(prefix),length,rssi,duration,deadline);out._obj.value=123;return 0
    def slk_discovery_identity(self,v,c,s):c._obj.index=2;c._obj.generation=7;s._obj.value=9;return 0
    def slk_discovery_read(self,v,m,rows,capacity,count,flags,deadline):
        self.flags.append(flags);m._obj.version=1;m._obj.generation=7;m._obj.session=9
        r=rows[0];r.sequence=1;r.rssi=-42;r.rssi_known=1;r.data_length=2;r.data[0]=0xab;r.data[1]=0xff;count._obj.value=1;return 0
    def slk_discovery_release(self,v,deadline,stopped):
        if self.stop<0:return self.stop
        stopped._obj.value=self.stop;return 0
    def slk_discovery_free(self,v):self.freed.append(v.value)
    def slk_client_close(self,c):self.closed.append(c.value)


def caller(b):
    c=object.__new__(Client);c._lib=b;c._handle=ctypes.c_void_p(42);c._pid=os.getpid();c._lock=threading.RLock();return c


class DiscoveryBoundary(unittest.TestCase):
    def test_parent_close_read_flags_and_explicit_release(self):
        b=Boundary()
        with patch('sparklink.discovery._configure'),caller(b) as c:d=c.discover(ControllerId(2,7),prefix=b'\xab',deadline_ns=1)
        self.assertEqual(b.closed,[42]);self.assertEqual((d.controller,d.session_id),(ControllerId(2,7),9))
        with d:
            value=d.read(deadline_ns=1,peek=True);self.assertEqual((value.reports[0].data,value.reports[0].rssi),(b'\xab\xff',-42))
            d.read(deadline_ns=1,wait=False);self.assertEqual(b.flags,[3,0]);self.assertIs(d.release(deadline_ns=1),False)
        d.close();self.assertEqual(b.freed,[123])
        with self.assertRaises(ValueError):d.read(deadline_ns=1)
        with self.assertRaises(TypeError):DiscoverySession()

    def test_invalid_input_and_interrupted_identity(self):
        b=Boundary()
        with patch('sparklink.discovery._configure'),caller(b) as c:
            for args in [dict(prefix=b'x'*65),dict(prefix='x'),dict(minimum_rssi=True),dict(minimum_rssi=21),dict(duration_ms=249),dict(duration_ms=True)]:
                with self.assertRaises((TypeError,ValueError)):c.discover(ControllerId(2,7),deadline_ns=1,**args)
            self.assertFalse(hasattr(b,'request'))
            def interrupted(*_):raise RuntimeError('interrupted identity result')
            b.slk_discovery_identity=interrupted
            with self.assertRaisesRegex(RuntimeError,'interrupted identity'):c.discover(ControllerId(2,7),deadline_ns=1)
            self.assertEqual(b.freed,[123])

    def test_uncertain_release_bad_decode_and_fork(self):
        b=Boundary()
        with patch('sparklink.discovery._configure'),caller(b) as c:
            d=c.discover(ControllerId(2,7),deadline_ns=1);b.stop=-errno.ETIMEDOUT
            with self.assertRaises(OSError) as e:d.release(deadline_ns=1)
            self.assertEqual(e.exception.errno,errno.ETIMEDOUT);self.assertTrue(d._handle)
            for kwargs in [dict(peek=1),dict(wait=0)]:
                with self.assertRaises(ValueError):d.read(deadline_ns=1,**kwargs)
            d._pid+=1
            with self.assertRaises(RuntimeError):d.close()
            d._pid-=1
            with patch('sparklink.discovery._decode',side_effect=OSError(errno.EPROTO,'bad ABI')):
                with self.assertRaises(OSError):d.read(deadline_ns=1)
            self.assertEqual(b.freed,[123])

    def test_layout_and_malformed_rows(self):
        self.assertEqual((ctypes.sizeof(_Batch),ctypes.sizeof(_Report),_Report.data.offset),(40,312,51))
        m=_Batch(generation=7,session=9,version=1);rows=(_Report*32)();rows[0].sequence=1;rows[0].rssi=127
        self.assertIsNone(_decode(m,rows,1,ControllerId(2,7),9).reports[0].rssi)
        for case in ['generation','version','count','reserved','length','rssi','known','tail','address','sequence']:
            m=_Batch(generation=7,session=9,version=1);rows=(_Report*32)();rows[0].sequence=1;rows[0].rssi=127;n=1
            if case=='generation':m.generation=8
            elif case=='version':m.version=2
            elif case=='count':n=33
            elif case=='reserved':rows[0].reserved[0]=1
            elif case=='length':rows[0].data_length=256
            elif case=='rssi':rows[0].rssi=128
            elif case=='known':rows[0].rssi_known=1
            elif case=='tail':rows[0].data[254]=1
            elif case=='address':rows[0].address[0]=1
            else:rows[0].sequence=0
            with self.subTest(case=case),self.assertRaises(OSError):_decode(m,rows,n,ControllerId(2,7),9)
