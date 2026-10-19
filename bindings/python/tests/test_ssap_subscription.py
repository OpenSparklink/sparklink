"""ctypes/ownership input fixtures only;not actual C library,daemon or RF."""
import ctypes
import errno
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from sparklink.client import Connection
from sparklink.ssap_subscription import SsapSubscription, _Info, _Packet, _Batch, _batch


def info():
    value=_Info(generation=7,lifetime=11,security_epoch=13,token=17,expires_ns=100,
                version=1,controller=2,handle=3,capacity=16,handle_count=1,modes=2,state=1)
    value.handles[0]=17
    return value


def batch():
    value=_Batch(info=info(),last_sequence=1,count=1)
    p=value.packets[0]
    p.sequence,p.security_epoch,p.security_level,p.indication,p.pdu_length=1,13,2,1,7
    p.pdu[:7]=[16,3,17,0,1,0,0xab]
    return value


class Boundary:
    def __init__(self):self.calls=[];self.freed=[];self.release_error=0
    def slk_connection_ssap_subscribe(self,parent,handles,count,modes,duration,deadline,out):
        self.calls.append(('subscribe',tuple(handles),count,modes,duration,deadline));out._obj.value=123;return 0
    def slk_ssap_subscription_info(self,view,out):ctypes.memmove(out,ctypes.byref(info()),120);return 0
    def slk_ssap_subscription_read(self,view,wait,out,deadline):
        self.calls.append(('read',wait,deadline));ctypes.memmove(out,ctypes.byref(batch()),33312);return 0
    def slk_ssap_subscription_renew(self,view,duration,out,deadline):
        self.calls.append(('renew',duration,deadline));value=info();value.expires_ns=200
        ctypes.memmove(out,ctypes.byref(value),120);return 0
    def slk_ssap_subscription_release(self,view,out,deadline):
        self.calls.append(('release',deadline))
        if self.release_error:return self.release_error
        value=_Batch(info=info(),flags=1,reason=1);value.info.state=3
        ctypes.memmove(out,ctypes.byref(value),33312);return 0
    def slk_ssap_subscription_free(self,view):self.freed.append(view.value)
    def slk_connection_close(self,parent):self.calls.append(('parent-close',parent.value))


def connection(boundary):
    view=Connection._empty(boundary);view._handle=ctypes.c_void_p(42);return view


class SubscriptionBoundary(unittest.TestCase):
    def test_generated_c_contract_native_and_i386_have_exact_fixed_layout(self):
        root=Path(__file__).resolve().parents[3]
        source='''#include <stddef.h>
#include "sparklink.h"
_Static_assert(sizeof(struct SlkSsapSubscriptionInfo)==120,"info size");
_Static_assert(_Alignof(struct SlkSsapSubscriptionInfo)==8,"info alignment");
_Static_assert(offsetof(struct SlkSsapSubscriptionInfo,handles)==56,"handles");
_Static_assert(sizeof(struct SlkSsapSubscriptionPacket)==2072,"packet size");
_Static_assert(_Alignof(struct SlkSsapSubscriptionPacket)==8,"packet alignment");
_Static_assert(offsetof(struct SlkSsapSubscriptionPacket,pdu)==24,"pdu");
_Static_assert(sizeof(struct SlkSsapSubscriptionBatch)==33312,"batch size");
_Static_assert(_Alignof(struct SlkSsapSubscriptionBatch)==8,"batch alignment");
_Static_assert(offsetof(struct SlkSsapSubscriptionBatch,packets)==160,"packets");
'''
        with tempfile.TemporaryDirectory(prefix='slk-subscription-abi-') as temp:
            directory=Path(temp);c=directory/'layout.c';c.write_text(source)
            for name,flags in [('native',[]),('i386',['-m32','-ffreestanding'])]:
                subprocess.run([os.environ.get('CC','clang'),'-std=c11','-Wall','-Wextra','-Werror',
                    *flags,'-I',str(root/'crates/libsparklink/include'),'-c',str(c),
                    '-o',str(directory/(name+'.o'))],check=True)

    def test_layout_parent_close_and_explicit_remote_release(self):
        self.assertEqual((ctypes.sizeof(_Info),_Info.handles.offset,ctypes.sizeof(_Packet),
                          _Packet.pdu.offset,ctypes.sizeof(_Batch),_Batch.packets.offset),
                         (120,56,2072,24,33312,160))
        b=Boundary();parent=connection(b)
        with patch('sparklink.ssap_subscription._configure'):
            sub=parent.ssap().subscribe([17],modes=2,duration_ms=1000,deadline_ns=1)
        parent.close()
        self.assertEqual(sub.info().token,17)
        value=sub.read(wait=False,deadline_ns=2)
        self.assertEqual(value.packets[0].pdu,b'\x10\x03\x11\0\x01\0\xab')
        self.assertEqual(sub.renew(2000,deadline_ns=3).expires_ns,200)
        self.assertEqual(sub.release(deadline_ns=4).flags,1)
        sub.close();sub.close();self.assertEqual(b.freed,[123])
        self.assertEqual(b.calls,[('subscribe',(17,),1,2,1000,1),('parent-close',42),
                                  ('read',0,2),('renew',2000,3),('release',4)])
        with self.assertRaises(ValueError):sub.read(deadline_ns=5)
        with self.assertRaises(TypeError):SsapSubscription()

    def test_invalid_input_and_bounded_handle_iterator_never_enter_native_call(self):
        b=Boundary();parent=connection(b)
        with patch('sparklink.ssap_subscription._configure'):
            for handles,kwargs in [([],{}),([0],{}),([17,17],{}),([True],{}),([65536],{}),
                ([17],dict(modes=True)),([17],dict(modes=4)),([17],dict(duration_ms=249)),
                ([17],dict(duration_ms=60001)),([17],dict(duration_ms=True))]:
                with self.subTest(handles=handles,kwargs=kwargs),self.assertRaises((TypeError,ValueError)):
                    parent.ssap().subscribe(handles,deadline_ns=1,**kwargs)
            visited=[]
            def forever():
                for n in range(100000):visited.append(n);yield n+1
            with self.assertRaises(ValueError):parent.ssap().subscribe(forever(),deadline_ns=1)
            self.assertEqual(len(visited),33)
        self.assertEqual(b.calls,[]);parent.close()

    def test_uncertain_release_and_fork_never_report_cleanup_or_free_implicitly(self):
        b=Boundary();parent=connection(b)
        with patch('sparklink.ssap_subscription._configure'):
            sub=parent.ssap().subscribe([17],deadline_ns=1)
        b.release_error=-errno.ETIMEDOUT
        with self.assertRaises(OSError) as error:sub.release(deadline_ns=2)
        self.assertEqual(error.exception.errno,errno.ETIMEDOUT)
        self.assertTrue(sub._handle);self.assertEqual(b.freed,[])
        for args in [dict(wait=1),dict(wait=0)]:
            with self.assertRaises(TypeError):sub.read(deadline_ns=3,**args)
        sub._pid=os.getpid()+1
        for operation in [sub.info,sub.close,lambda:sub.read(deadline_ns=3)]:
            with self.assertRaises(RuntimeError):operation()
        self.assertEqual(b.freed,[]);sub._pid=os.getpid();sub.close();parent.close()
        self.assertEqual(b.freed,[123])

    def test_malformed_result_tails_lengths_and_reserved_fields_are_rejected(self):
        self.assertEqual(_batch(batch()).packets[0].security_epoch,13)
        for case in range(13):
            raw=batch()
            if case==0:raw.count=17
            elif case==1:raw.info.handle_count=33
            elif case==2:raw.info.reserved[0]=1
            elif case==3:raw.info.handles[31]=1
            elif case==4:raw.packets[0].pdu_length=2049
            elif case==5:raw.packets[0].pdu[2047]=1
            elif case==6:raw.packets[1].sequence=1
            elif case==7:raw.packets[0].reserved[0]=1
            elif case==8:raw.packets[0].indication=2
            elif case==9:raw.flags=2
            elif case==10:raw.info.token=0
            elif case==11:raw.info.state=4
            else:raw.packets[0].security_level=3
            with self.subTest(case=case),self.assertRaises(OSError) as error:_batch(raw)
            self.assertEqual(error.exception.errno,errno.EPROTO)
