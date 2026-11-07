"""Independent ctypes/error fixtures; actual external SDK calls are tested separately."""
import ctypes
import errno
import os
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from sparklink import (ControllerId, LocalProperty, SsapOperations, SsapAccess,
                       WriteProvider, WriteProviderRequest)
from sparklink.service_provider import _WriteInfo
from test_service_provider import ProviderBoundary
from test_local_services import caller

class WriteBoundary(ProviderBoundary):
    slk_local_service_bind_write_provider=ProviderBoundary.slk_local_service_bind_read_provider
    slk_write_provider_fd=ProviderBoundary.slk_read_provider_fd
    slk_write_provider_next=ProviderBoundary.slk_read_provider_next
    slk_write_provider_free=ProviderBoundary.slk_read_provider_free
    slk_write_provider_request_free=ProviderBoundary.slk_read_provider_request_free
    slk_write_provider_request_reply=ProviderBoundary.slk_read_provider_request_reply
    def slk_write_provider_request_info(self, request, output):
        r=output._obj
        r.controller.index,r.controller.generation=2,7
        r.token,r.request_id,r.connection_lifetime=1,19,23
        r.security_epoch,r.deadline_ns=31,self.original_deadline
        r.connection_handle,r.property=3,17
        r.value_length=3;r.operation=13;r.verify=1
        r.local_tcid,r.remote_tcid=10,10
        self.corrupt(r)
        return 0
    def slk_write_provider_request_value(self, request, buffer, capacity, length):
        if capacity<3:return -errno.ENOSPC
        ctypes.memmove(buffer,b'\x00\x92\x31',3);length._obj.value=3
        return 0

class WriteProviderTests(unittest.TestCase):
    def setUp(self):
        self.b=WriteBoundary()
        self.config=patch('sparklink.local_services._configure');self.config.start()
        self.provider_config=patch('sparklink.service_provider._configure_write');self.provider_config.start()
        self.client=caller(self.b)
        self.service=self.client.register_local_service(ControllerId(2,7),b'ab',
            [LocalProperty(b'cd',SsapOperations(6),SsapAccess(0),b'old')],deadline_ns=1)
        self.provider=self.service.bind_write_provider(17,deadline_ns=2)
    def tearDown(self):
        self.provider.close();self.service.close();self.client.close()
        self.config.stop();self.provider_config.stop();os.close(self.b.event)
    def test_actual_view_snapshot_reply_and_original_stop_errors(self):
        for cls in (WriteProvider,WriteProviderRequest):
            with self.assertRaises(TypeError):cls()
        self.b.pending=True
        with self.provider.next_request() as request:
            self.assertEqual(request.value,b'\x00\x92\x31')
            self.assertEqual((request.info.operation,request.info.offset,request.info.verify),(13,0,True))
            with self.assertRaises(ValueError):request.reply(b'',status=7)
            with self.assertRaises(OSError) as e:request.reply(b'four')
            self.assertEqual(e.exception.errno,errno.EMSGSIZE)
            request.reply(request.value)
            self.assertEqual(self.b.replies,[(555,0,b'\x00\x92\x31')])
        self.assertEqual(self.b.released,[555])
    def test_corrupt_write_context_releases_view_without_snapshot_or_reply(self):
        for field,value in [('operation',11),('data_type',1),('offset',1),('verify',2),('value_length',2043),('connection_handle',4096)]:
            with self.subTest(field=field):
                self.b.pending=True;self.b.corrupt=lambda r:setattr(r,field,value)
                with self.assertRaises(OSError) as e:self.provider.next_request()
                self.assertEqual(e.exception.errno,errno.EPROTO)
        self.assertEqual(self.b.released,[555]*6);self.assertEqual(self.b.replies,[])
    def test_c_and_python_layout_and_new_value_getter_signature(self):
        self.assertEqual((ctypes.sizeof(_WriteInfo),ctypes.alignment(_WriteInfo)),(80,8))
        header=Path(__file__).resolve().parents[3]/'crates/libsparklink/include/sparklink.h'
        lines=['#include <stdbool.h>','#include <stddef.h>',f'#include "{header}"',
            '_Static_assert(sizeof(SlkWriteProviderRequestInfo)==80,"size");']
        for field,kind in _WriteInfo._fields_:
            lines.append(f'_Static_assert(offsetof(SlkWriteProviderRequestInfo,{field})=={getattr(_WriteInfo,field).offset},"{field}");')
        lines+=['int (*value_fn)(const SlkWriteProviderRequest *,uint8_t *,size_t,size_t *)=slk_write_provider_request_value;',
                'int (*bind_fn)(SlkLocalService *,uint16_t,uint64_t,SlkWriteProvider **)=slk_local_service_bind_write_provider;']
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'layout.c';source.write_text('\n'.join(lines))
            result=subprocess.run([os.environ.get('CC','cc'),'-std=c11','-Wall','-Wextra','-Werror','-c',str(source),'-o',str(Path(tmp)/'layout.o')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
