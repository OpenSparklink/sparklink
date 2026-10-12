#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Scratch VM real established-link File gate; never emulate a controller reply."""
import argparse
import ctypes
import errno
import fcntl
import os
from pathlib import Path
import secrets
import struct
import subprocess
import time

from ws73_management_partial import standby
from ws73_management_setup import decode, setup, query, save_record
from ws73_resource_file_gate import announcement
from ws73_capture import CaptureError, discovery, marker_data, command_reply
from sparklink.native import NativeAdapter
from sparklink.structs import (SleConnectionSubmit, SleConnectionParameters,
    SleConnectionResult, SleControllerSnapshot, SleDiscoverySubmit, SleDiscoveryResult)


def duplicate_result(fd, generation, identifier):
    # Linux generic _IOWR('S', 0x9d, struct sle_connection_result).
    # The duplicate is the same open File, not another NativeAdapter/author.
    value = SleConnectionResult(version=1, generation=generation, request_id=identifier)
    raw = bytearray(bytes(value))
    fcntl.ioctl(fd, (3 << 30) | (ctypes.sizeof(value) << 16) | (ord('S') << 8) | 0x9d, raw, True)
    return SleConnectionResult.from_buffer_copy(raw)


def connection(snapshot, peer):
    return SleConnectionSubmit(version=1, profile=1, operation=1,
        generation=snapshot.generation, request_id=900, timeout_ms=10000,
        parameters=SleConnectionParameters(peer_address=peer.address,
            gt_negotiate=1, frame=1, scan_interval=32, scan_window=32,
            interval_min=12, interval_max=12, supervision_timeout=508))


def verify_records(r):
    if (type(r.get('format_version')) is not int or r.get('format_version') != 1 or r.get('status') != 'CONNECTED_FILE_PASS'
            or r.get('case') not in ['release', 'close', 'dup'] or type(r.get('index')) is not int or r.get('index') not in [0, 1]
            or r.get('daemon_running') is not False or r.get('synthetic_support') is not False
            or r.get('physical_acceptance') is not False or r.get('automatic_recovery_acceptance') is not False):
        raise ValueError('explicit real pre-daemon connected File scope required')
    snapshots = [setup(raw, i) for i, raw in enumerate(r['initial_snapshots'])]
    if len(snapshots) != 2 or snapshots[0].generation == snapshots[1].generation:
        raise ValueError('two independent initial registrations required')
    i = r['index']; p = 1-i
    ordered = [(n,identifier,operation) for n in [0,1] for identifier,operation in [(101,5),(102,6)]] + [(p,103,1),(i,103,3),(i,104,4),(p,104,2),(p,105,3),(p,106,4)]
    if len(r['discovery']) != len(ordered):raise ValueError('complete original discovery and independent peer activity required')
    previous=r['start_wall_ns']
    for row,(n,identifier,operation) in zip(r['discovery'],ordered):
        request = announcement(snapshots[n],r['marker']) if operation==1 else standby(snapshots[n],identifier,'advertising' if operation==5 else 'scanning')
        if n==i and operation==4:
            request=SleDiscoverySubmit(version=1,profile=1,generation=snapshots[n].generation,request_id=identifier,operation=4)
        request.request_id=identifier;request.operation=operation
        if (row['index']!=n or row['input']!=bytes(request).hex()
                or not previous<=row['start_wall_ns']<row['end_wall_ns']<=r['end_wall_ns']):
            raise ValueError('exact ordered typed discovery inputs required')
        result=decode(SleDiscoveryResult,row['result'])
        if (result.generation!=snapshots[n].generation or result.request_id!=identifier or result.operation!=operation
                or result.state!=3 or result.error or result.status):
            raise ValueError('original successful discovery results required')
        previous=row['end_wall_ns']
    if r['connection_input'] != bytes(connection(snapshots[i], snapshots[p])).hex():
        raise ValueError('exact typed Create input required')
    value = decode(SleConnectionResult, r['connected'])
    expected = SleConnectionResult(version=1, profile=1, state=4, operation=1,
        generation=snapshots[i].generation, request_id=900, handle=value.handle, flags=7, dev_index=i)
    if bytes(value) != bytes(expected) or value.handle > 65535:
        raise ValueError('actual successful OUT/Status/outcome author receipt required')
    if r.get('author_result_after_release') != (r['connected'] if r['case']=='release' else None):
        raise ValueError('retained author result is historical; destroyed author is unobservable')
    if r['case'] == 'dup':
        if r['after_first_result'] != r['connected'] or r['duplicate_fd'] == r['original_fd']:
            raise ValueError('first duplicate close must preserve same File author result')
        query(r['after_first_management'], snapshots[i].generation, 1)
        if not 100_000_000 <= r['first_close_quiet_end_ns']-r['first_close_wall_ns'] <= 1_000_000_000:
            raise ValueError('bounded first-close quiet interval required')
    if r['case'] != 'release' and r.get('original_fd_errno') != errno.EBADF:
        raise ValueError('actual original descriptor close required')
    if r['case'] == 'dup' and r.get('duplicate_fd_errno') != errno.EBADF:
        raise ValueError('actual duplicate last descriptor close required')
    query(r['held'], snapshots[i].generation, 1)
    query(r['free'], snapshots[i].generation, 0)
    for n in [i, p]:
        ready = SleControllerSnapshot.from_buffer_copy(bytes(snapshots[n])); ready.flags = 1
        for key in ['before_snapshots', 'after_snapshots']:
            if r[key][n] != bytes(ready).hex():
                raise ValueError('full same-generation Ready metadata required')
    query(r['peer_before'], snapshots[p].generation, 1)
    if r['peer_after'] != r['peer_before']:
        raise ValueError('peer must retain its independent Managed lease')
    if (r['scan_match']['data'] != marker_data(r['marker']).hex()
            or r['scan_match']['address'] != ':'.join(f'{b:02X}' for b in snapshots[p].address)
            or r['scan_match']['elapsed_ms'] >= 10000):
        raise ValueError('fresh actual random advertisement match required')
    for n in [i,p]:
        for key, codes in [('up', [0x15,0x1401]), ('down', [5,0x1405])]:
            event = r[key][n]; body = bytes.fromhex(event['params'])
            if (event['event'] not in codes or event['generation'] != snapshots[n].generation
                    or event['lost'] or body[0] or len(body) < (11 if key=='up' else 4)):
                raise ValueError('both original loss-free physical link events required')
            if key == 'up' and (body[4] != 0 or body[5:11] != bytes(snapshots[1-n].address)):
                raise ValueError('original physical peer/type required')
        if r['up'][n]['params'][2:6] != r['down'][n]['params'][2:6]:
            raise ValueError('each controller must retire its own observed handle')
    if not r['start_wall_ns'] < r['release_before_wall_ns'] <= r['release_after_wall_ns'] < r['end_wall_ns']:
        raise ValueError('bounded original release observation interval required')
    if r['end_wall_ns'] - r['start_wall_ns'] > 60_000_000_000:
        raise ValueError('finite gate deadline required')
    return snapshots


def corroborate(r, capture):
    snapshots = verify_records(r); i=r['index']; p=1-i
    def belongs(row,n,start,end):
        usb=r['usb'][n]
        return (row['bus'],row['device'])==(usb['bus'],usb['device']) and start<=row['wall_ns']<=end
    proofs=[]
    for row in r['discovery']:
        n=row['index']; value=decode(SleDiscoveryResult,row['result']); request=decode(SleDiscoverySubmit,row['input'])
        recipes={1:[0xc08,0xc02,0xc03,0xc05],2:[0xc05],3:[0x1001,0x1002],4:[0x1002],5:[0xc02,0xc05],6:[0x1001,0x1002,0x1002]}
        commands=[c for c in capture['commands'] if belongs(c,n,row['start_wall_ns'],row['end_wall_ns'])]
        if [c['opcode'] for c in commands]!=recipes[request.operation] or value.state!=3 or value.error or value.status:
            raise CaptureError('exact original successful discovery recipe required')
        for j,c in enumerate(commands):
            upper=commands[j+1]['wall_ns']-1 if j+1<len(commands) else row['end_wall_ns']
            params=(bytes(1) if c['opcode']==0xc08 else bytes([int(request.operation==1),0,0,0,0]) if c['opcode']==0xc05
                else bytes([0,3,len(marker_data(r['marker']))])+marker_data(r['marker']) if c['opcode']==0xc03
                else bytes([int(request.operation==3 or request.operation==6 and j==1),0]) if c['opcode']==0x1002 else None)
            proofs.append(command_reply(capture,r['usb'][n],c['opcode'],c['wall_ns'],upper,params,
                bytes([value.selected_power&255]).hex() if c['opcode']==0xc02 else ''))
    heard=[e for e in capture['reports'] if belongs(e,i,r['scan_start_wall_ns'],r['scan_end_wall_ns'])
        and all(e[k]==r['scan_match'][k] for k in ['address','data','rssi'])]
    if not heard:raise CaptureError('independent actual random marker RX required')
    links=[]
    for operation,opcode,start,end,key in [(1,0x1401,r['connect_before_wall_ns'],r['connect_after_wall_ns'],'up'),
            (2,0x1403,r['release_before_wall_ns'],r['end_wall_ns'],'down')]:
        commands=[c for c in capture['commands'] if belongs(c,i,start,end)]
        # Connected revocation has no radio obligations on this target.
        if len(commands)!=1 or commands[0]['opcode']!=opcode:raise CaptureError('exact actual Create/cleanup Disconnect required')
        command=commands[0]
        status=[e for e in capture['native_events'] if belongs(e,i,start,end) and e['event']==1
            and len(bytes.fromhex(e['params']))==4 and bytes.fromhex(e['params'])[:2]==opcode.to_bytes(2,'little')
            and bytes.fromhex(e['params'])[3]==0]
        if len(status)!=1 or command['completion']['wall_ns']>end:raise CaptureError('real OUT and successful Status required')
        body=bytes.fromhex(command['params'])
        expected_create=bytes(3)+bytes(snapshots[p].address)+bytes([1,1])+struct.pack('<8H',32,32,12,12,0,508,0,0)
        if operation==1 and body!=expected_create:
            raise CaptureError('Create must target actual peer')
        handle=decode(SleConnectionResult,r['connected']).handle
        if operation==2 and body!=handle.to_bytes(2,'little')+b'\x13':raise CaptureError('exact cleanup handle/reason required')
        outcomes=[]
        for n in [i,p]:
            receipt=r[key][n]
            events=[e for e in capture['native_events'] if belongs(e,n,start,end)
                and e['event']==receipt['event'] and e['params']==receipt['params']]
            if len(events)!=1:raise CaptureError('one independent exact physical outcome on each device required')
            outcomes.append(events[0])
        links.append(dict(command=command,status=status[0],outcomes=outcomes))
    if r['case']=='dup':
        if any(belongs(c,i,r['first_close_wall_ns'],r['first_close_quiet_end_ns']) and c['opcode']==0x1403 for c in capture['commands']):
            raise CaptureError('first dup close must not disconnect')
    expected_commands=[v['command'] for v in proofs]+[v['command'] for v in links]
    actual=[c for c in capture['commands'] if any(belongs(c,n,r['start_wall_ns'],r['end_wall_ns']) for n in [0,1])]
    if actual!=sorted(expected_commands,key=lambda c:c['wall_ns']):
        raise CaptureError('unrecorded reset, disconnect or peer command in connected File gate')
    if any(r['start_wall_ns']<=e['wall_ns']<=r['end_wall_ns'] for e in capture['failures']):
        raise CaptureError('USB transport failure inside connected File gate')
    return dict(scope='pre-daemon established link actual File release/last-close/dup; not in-flight or natural recovery',
        discovery=proofs,heard=heard,links=links,connected_file_support_acceptance=True,
        daemon_running_lifecycle_acceptance=False,inflight_acceptance=False,automatic_recovery_acceptance=False)


def run(args):
    if (f'ws73.connected_case={args.case}' not in Path('/proc/cmdline').read_text().split()
            or os.geteuid()!=0 or not Path('/scratch-root-uuid').is_file()
            or Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU'
            or subprocess.run(['/bin/pidof','slkd'],capture_output=True).returncode==0):
        raise ValueError('explicit pre-daemon scratch VM required')
    args.output.mkdir(parents=True,exist_ok=False)
    r=dict(format_version=1,status='STARTING',case=args.case,index=args.index,daemon_running=False,
        synthetic_support=False,physical_acceptance=False,automatic_recovery_acceptance=False,
        start_wall_ns=time.time_ns(),discovery=[],events=[[],[]],marker=secrets.token_hex(16))
    def save():save_record(args.output,r)
    handles=[];alias=None
    try:
        observers=[NativeAdapter(n) for n in [0,1]];handles+=observers
        snapshots=[a.snapshot() for a in observers];r['initial_snapshots']=[bytes(s).hex() for s in snapshots]
        for n,s in enumerate(snapshots):setup(bytes(s).hex(),n)
        r['usb']=[]
        for n in [0,1]:
            path=Path(f'/sys/bus/usb/devices/1-{n+1}')
            r['usb'].append(dict(bus=int((path/'busnum').read_text()),device=int((path/'devnum').read_text())))
        writers=[NativeAdapter(n,snapshots[n].generation) for n in [0,1]];handles+=writers
        leases=[a.acquire_management(1) for a in writers];r['leases']=leases;save()
        def drain():
            for n,a in enumerate(observers):
                while (event:=a.poll_event()) is not None:
                    r['events'][n].append(dict(event=event.event_code,params=bytes(event.payload[:event.payload_len]).hex(),
                        generation=event.generation,seq=event.seq,lost=event.lost,wall_ns=time.time_ns()))
        def discover(n,request):
            row=dict(index=n,input=bytes(request).hex(),start_wall_ns=time.time_ns());r['discovery'].append(row);save()
            writers[n].submit_discovery(request); deadline=time.monotonic()+8
            while True:
                value=observers[n].discovery_result(request.request_id);drain()
                if value is not None and value.is_terminal:break
                if time.monotonic()>deadline:raise TimeoutError('real discovery')
                time.sleep(.002)
            row.update(result=bytes(value).hex(),end_wall_ns=time.time_ns());save()
            if value.state!=3 or value.error or value.status:raise ValueError('real discovery failed')
        for n in [0,1]:
            for identifier,domain in [(101,'advertising'),(102,'scanning')]:discover(n,standby(snapshots[n],identifier,domain))
        i=args.index;p=1-i
        advertisement=announcement(snapshots[p],r['marker']);advertisement.request_id=103;discover(p,advertisement)
        scan=standby(snapshots[i],103,'scanning');scan.operation=3;r['scan_start_wall_ns']=time.time_ns();discover(i,scan)
        deadline=time.monotonic()+10
        while True:
            drain();matches=[]
            for e in r['events'][i]:
                if e['event']==0x180b and e['wall_ns']>=r['scan_start_wall_ns']:
                    body=bytes.fromhex(e['params']);match=discovery(b'\xa2'+struct.pack('<HH',0x180b,len(body))+body)
                    if match and match['data']==marker_data(r['marker']).hex():matches.append(match)
            if matches:break
            if time.monotonic()>deadline:raise TimeoutError('fresh actual random advertisement')
            time.sleep(.002)
        r['scan_match']=matches[0]|dict(elapsed_ms=(time.time_ns()-r['scan_start_wall_ns'])//1_000_000)
        r['scan_end_wall_ns']=time.time_ns();stop=SleDiscoverySubmit(version=1,profile=1,generation=snapshots[i].generation,request_id=104,operation=4);discover(i,stop)
        request=connection(snapshots[i],snapshots[p]);r['connection_input']=bytes(request).hex();r['connect_before_wall_ns']=time.time_ns()
        writers[i].submit_connection(request);deadline=time.monotonic()+12
        while True:
            result=writers[i].connection_result(snapshots[i].generation,900);drain()
            if result is not None and result.state>=4:break
            if time.monotonic()>deadline:raise TimeoutError('actual connection')
            time.sleep(.002)
        if result.state!=4:raise ValueError('actual Create failed')
        def outcomes(key,codes):
            deadline=time.monotonic()+8
            while True:
                drain();values=[[e for e in events if e['event'] in codes] for events in r['events']]
                if all(len(v)==1 for v in values):return [v[0] for v in values]
                if time.monotonic()>deadline:raise TimeoutError('both actual '+key+' events')
                time.sleep(.002)
        r['up']=outcomes('up',[0x15,0x1401]);r['connected']=bytes(result).hex();r['connect_after_wall_ns']=time.time_ns()
        r['before_snapshots']=[bytes(a.snapshot()).hex() for a in observers]
        r['held']=bytes(observers[i].management_status()).hex();r['peer_before']=bytes(observers[p].management_status()).hex()
        fd=writers[i].fileno();r['original_fd']=fd;r['duplicate_fd']=-1
        if args.case=='dup':
            alias=os.dup(fd);r['duplicate_fd']=alias;r['first_close_wall_ns']=time.time_ns();writers[i].close()
            time.sleep(.15);drain();r['first_close_quiet_end_ns']=time.time_ns()
            r['after_first_result']=bytes(duplicate_result(alias,snapshots[i].generation,900)).hex()
            r['after_first_management']=bytes(observers[i].management_status()).hex()
            if any(e['event'] in [5,0x1405] for events in r['events'] for e in events):raise ValueError('first dup close disconnected actual link')
        r['release_before_wall_ns']=time.time_ns();save()
        if args.case=='release':writers[i].release_management(leases[i],1)
        elif args.case=='close':writers[i].close()
        else:os.close(alias);alias=None
        r['release_after_wall_ns']=time.time_ns()
        if args.case!='release':
            for key,descriptor in [('original_fd_errno',fd)]+([('duplicate_fd_errno',r['duplicate_fd'])] if args.case=='dup' else []):
                try:fcntl.fcntl(descriptor,fcntl.F_GETFD)
                except OSError as error:r[key]=error.errno
                else:raise ValueError('descriptor remained open')
        r['down']=outcomes('down',[5,0x1405]);deadline=time.monotonic()+8
        while (value:=observers[i].management_status()).state==2:
            if time.monotonic()>deadline:raise TimeoutError('actual connected revocation')
            time.sleep(.002)
        r['free']=bytes(value).hex();r['after_snapshots']=[bytes(a.snapshot()).hex() for a in observers]
        r['peer_after']=bytes(observers[p].management_status()).hex();save()
        r['author_result_after_release']=bytes(writers[i].connection_result(snapshots[i].generation,900)).hex() if args.case=='release' else None
        # Intended link loss must not prevent independent peer radio control.
        for identifier,operation in [(104,2),(105,3),(106,4)]:
            req=standby(snapshots[p],identifier,'scanning');req.operation=operation;discover(p,req)
        writers[p].release_management(leases[p],1)
        r.update(end_wall_ns=time.time_ns(),status='CONNECTED_FILE_PASS');verify_records(r);save()
        print('WS73_TARGET_CONNECTED_FILE_PASS',flush=True)
    except BaseException as error:
        r.update(status='FAIL',error=str(error),error_type=type(error).__name__);save();raise
    finally:
        if alias is not None:os.close(alias)
        for handle in handles:handle.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['release','close','dup'],required=True)
    parser.add_argument('--index',type=int,choices=[0,1],required=True)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args())
