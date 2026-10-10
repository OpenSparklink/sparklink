#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual ctypes/cdylib/native ioctl gate, explicit synthetic support only."""
import errno
import json
import os
from pathlib import Path
import sys
import select
import time

sys.path.insert(0,'/usr/share/sparklink/python')
os.environ['LIBSPARKLINK_PATH']='/usr/lib/libsparklink.so'
from sparklink import NativeAdapter
from sparklink.structs import SleDiscoverySubmit


def denied(code, function):
    try:function()
    except OSError as error:assert error.errno==code,(error.errno,code)
    else:raise AssertionError('protected/stale operation succeeded')


def observe(index,generation):
    with NativeAdapter(index,generation) as a, NativeAdapter(index,generation) as b:
        assert a.fileno()!=b.fileno() and index in a.device_indices()
        snapshot=a.snapshot();assert snapshot.flags==1 and snapshot.profile==1 and snapshot.valid_fields==1
        denied(errno.ENODEV,lambda:a.snapshot(generation+100))
        owner=a.management_status();assert (owner.state,owner.mode,owner.flags,owner.lease)==(1,1,0,0)
        denied(errno.EPERM if os.getuid() else errno.EBUSY,lambda:a.acquire_management(1))
        first=a.poll_event();other=b.poll_event();assert first and other and bytes(first)==bytes(other)
        retained=bytes(first);a.poll_event();assert bytes(first)==retained
        for _ in range(64):
            if a.poll_event() is None:break
        else:raise AssertionError('event reader did not become quiet')
        quiet=bytes(a._events);assert a.poll_event() is None and bytes(a._events)==quiet
        if os.getuid():
            denied(errno.EPERM,lambda:a.submit_discovery(SleDiscoverySubmit(version=1,profile=1,operation=4,generation=generation,request_id=0x5042494e44494e47)))
    with NativeAdapter(index,generation) as a, NativeAdapter(index,generation) as b:
        if os.getuid():
            denied(errno.EPERM,a.poll_snoop);assert a._snoop.after_seq==0
        else:
            first=a.poll_snoop();other=b.poll_snoop();assert first and other and bytes(first)==bytes(other)
            retained=bytes(first);a.poll_snoop();assert bytes(first)==retained
            for _ in range(64):
                if a.poll_snoop() is None:break
            else:raise AssertionError('snoop reader did not become quiet')
            quiet=bytes(a._snoop);assert a.poll_snoop() is None and bytes(a._snoop)==quiet
            denied(errno.EBUSY,a.poll_event)
    denied(errno.EBADF,a.fileno)


def writer(index,generation):
    assert os.getuid()==0
    with NativeAdapter(index,generation) as a, NativeAdapter(index,generation) as b:
        lease=a.acquire_management(1);assert lease and a.management_status().lease==lease
        assert b.management_status().lease==0
        denied(errno.EBUSY,lambda:b.acquire_management(1))
        denied(errno.EPERM,lambda:b.release_management(lease,1))
        request=SleDiscoverySubmit(version=1,profile=1,operation=2,generation=generation,request_id=0x5042494e44494e47)
        assert a.discovery_result(request.request_id) is None
        denied(errno.EPERM,lambda:b.submit_discovery(request))
        started=time.time_ns();a.submit_discovery(request);deadline=time.monotonic()+2
        while True:
            result=a.discovery_result(request.request_id);assert result is not None
            if result.is_terminal:break
            assert time.monotonic()<deadline;time.sleep(.01)
        assert (result.state,result.status,result.error,result.radio_adv)==(3,0,0,1)
        print('WS73_NATIVE_BINDING_RESULT: '+json.dumps({'generation':generation,'request_id':request.request_id,
            'operation':2,'opcode':result.opcode,'state':result.state,'status':result.status,'error':result.error,
            'started_wall_ns':started,'finished_wall_ns':time.time_ns()}),flush=True)
        a.release_management(lease,1);deadline=time.monotonic()+2
        while b.management_status().state!=0:
            assert time.monotonic()<deadline;time.sleep(.01)
        other=b.acquire_management(2);assert other and other!=lease;b.release_management(other,2)
    denied(errno.EBADF,a.fileno)


def stale(index,generation,trace):
    assert os.getuid()==0
    with NativeAdapter(index,generation) as old:
        (old.poll_snoop if trace else old.poll_event)()
        poll=select.poll();poll.register(old.fileno(),select.POLLIN)
        deadline=time.monotonic()+120
        while True:
            try:old.snapshot()
            except OSError as error:
                assert error.errno==errno.ENODEV;break
            assert time.monotonic()<deadline;time.sleep(.05)
        events=poll.poll(0);assert len(events)==1 and events[0][1] & (select.POLLERR|select.POLLHUP)==select.POLLERR|select.POLLHUP
        denied(errno.ENODEV,old.poll_snoop if trace else old.poll_event)
        while True:
            assert time.monotonic()<deadline
            try:new=NativeAdapter(index)
            except OSError as error:
                assert error.errno==errno.ENODEV;time.sleep(.05);continue
            if new.generation!=generation and new.snapshot().flags==1:break
            new.close();time.sleep(.05)
        with new:
            assert new.index==index and new.generation>generation
            denied(errno.ENODEV,old.snapshot)
            denied(errno.ENODEV,lambda:new.snapshot(generation))
            print(f'WS73_NATIVE_PYTHON_STALE: PASS mode={"trace" if trace else "event"} index={index} old={generation} new={new.generation} poll=ERR|HUP',flush=True)


if __name__=='__main__':
    mode,index,generation=sys.argv[1:];index=int(index);generation=int(generation)
    assert mode in ['observe','writer','stale-event','stale-trace']
    if mode.startswith('stale-'):stale(index,generation,mode=='stale-trace')
    else:(observe if mode=='observe' else writer)(index,generation)
    print(f'WS73_NATIVE_PYTHON_BINDINGS: PASS mode={mode} uid={os.getuid()} index={index} generation={generation}',flush=True)
