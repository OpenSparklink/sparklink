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
from ws73_diagnostic_hold import HoldCoordinator, PROPERTIES, write_marker, corroborate_host_hold
from ws73_host_later_hold import LaterHostCoordinator, verify_selector_rows, corroborate as corroborate_later_hold
from sparklink.native import NativeAdapter
from sparklink.structs import (SleConnectionSubmit, SleConnectionParameters,
    SleConnectionResult, SleControllerSnapshot, SleDiscoverySubmit, SleDiscoveryResult, SleLinkSnapshot)


def duplicate_result(fd, generation, identifier):
    # Linux generic _IOWR('S', 0x9d, struct sle_connection_result).
    # The duplicate is the same open File, not another NativeAdapter/author.
    value = SleConnectionResult(version=1, generation=generation, request_id=identifier)
    raw = bytearray(bytes(value))
    fcntl.ioctl(fd, (3 << 30) | (ctypes.sizeof(value) << 16) | (ord('S') << 8) | 0x9d, raw, True)
    return SleConnectionResult.from_buffer_copy(raw)


def connection(snapshot, peer):
    return SleConnectionSubmit(version=2, profile=1, operation=1,
        generation=snapshot.generation, request_id=900, timeout_ms=10000,
        parameters=SleConnectionParameters(peer_address=peer.address,
            gt_negotiate=1, frame=1, scan_interval=32, scan_window=32,
            interval_min=12, interval_max=12, supervision_timeout=508))


def stop(snapshot, identifier, operation):
    if operation not in [2,4]:raise ValueError('typed radio stop only')
    return SleDiscoverySubmit(version=1,profile=1,generation=snapshot.generation,request_id=identifier,operation=operation)


def bound_disconnect(snapshot,link,identifier):
    request=SleConnectionSubmit(version=2,profile=1,operation=2,generation=snapshot.generation,
        request_id=identifier,timeout_ms=10000,handle=link.handle,reason=0x13,
        expected_lifetime=link.lifetime,expected_address_type=link.address_type,expected_role=link.role)
    request.expected_address[:]=link.address
    return request


def mutate_reference(request,mutation):
    if mutation=='lifetime':request.expected_lifetime+=1
    elif mutation=='type':request.expected_address_type^=1
    elif mutation=='address':request.expected_address[5]^=1
    elif mutation=='role':request.expected_role^=1
    elif mutation=='zero':request.expected_lifetime=0
    elif mutation=='generation':request.generation+=1
    elif mutation=='version':request.version=1
    else:raise ValueError('bounded known reference mutation required')


class ConnectedHoldCoordinator(HoldCoordinator):
    def __init__(self,share,record,index):
        super().__init__(share,record)
        self.folder=Path(share)/'connected-file';self.path=f'/machine/peripheral/ws73_{index}'


class ConnectedOutcomeCoordinator(LaterHostCoordinator):
    def __init__(self,share,record,index):
        super().__init__(share,record,1)
        self.folder=Path(share)/'connected-file';self.path=f'/machine/peripheral/ws73_{index}'


def verify_records(r):
    if 'security_capabilities' in r:
        from ws73_security_capabilities import verify
        verify(r)
        return [setup(raw,n) for n,raw in enumerate(r['initial_snapshots'])]
    if 'data_deadline' in r:
        from ws73_channel_deadline import verify
        verify(r)
        return [setup(raw,n) for n,raw in enumerate(r['initial_snapshots'])]
    if 'data_link_down' in r:
        from ws73_channel_link_down import verify
        verify(r)
        return [setup(raw,n) for n,raw in enumerate(r['initial_snapshots'])]
    held_reply=r.get('reply_hold')
    if held_reply not in [None,'status','outcome']:raise ValueError('explicit bounded real reply stage required')
    if (type(r.get('format_version')) is not int or r.get('format_version') != 1 or r.get('status') != ('INFLIGHT_FILE_PASS' if held_reply else 'CONNECTED_FILE_PASS')
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
        if operation in [2,4]:
            request=stop(snapshots[n],identifier,operation)
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
    author_receipt = r['pending'] if held_reply else r['connected']
    value = decode(SleConnectionResult, author_receipt)
    expected = SleConnectionResult(version=1, profile=1, state=(2 if held_reply=='status' else 3) if held_reply else 4, operation=1,
        generation=snapshots[i].generation, request_id=900, handle=0 if held_reply else value.handle,
        flags=(0 if held_reply=='status' else 1) if held_reply else 7, dev_index=i)
    if bytes(value) != bytes(expected) or value.handle > 65535:
        raise ValueError('exact author OUT/Status/outcome facts before withdrawal required')
    final_author = r.get('author_result_after_release')
    if held_reply:
        query(r['revoking'],snapshots[i].generation,2)
        if r['case']=='release':
            cancelled=SleConnectionResult.from_buffer_copy(bytes(value));cancelled.state=6;cancelled.error=-errno.ECANCELED
            if r['cancelled']!=bytes(cancelled).hex():raise ValueError('held author must cancel without invented outcome')
            cancelled.flags=7;cancelled.handle=int.from_bytes(bytes.fromhex(r['up'][i]['params'])[1:3],'little')
            if final_author!=bytes(cancelled).hex():raise ValueError('late actual outcome must not turn cancelled author into Succeeded')
        elif r.get('cancelled') is not None or final_author is not None:
            raise ValueError('destroyed File author is not observable')
        markers=r['markers']
        if ([v['hold_phase'] for v in markers]!=['arm_ready','wait_held','release_ready']
                or len(r['hold_acknowledgements'])!=3
                or not markers[0]['wall_ns']<r['connect_before_wall_ns']<markers[1]['wall_ns']<r['release_before_wall_ns']
                or not r['release_after_wall_ns']<markers[2]['wall_ns']<r['end_wall_ns']):
            raise ValueError('exact causal hold/author withdrawal/delivery handshake required')
        for n,(ack,marker) in enumerate(zip(r['hold_acknowledgements'],markers)):
            if ack['stage']!=['armed','held','released'][n] or ack['request']!=marker:
                raise ValueError('original guest marker and host acknowledgement must agree')
            if held_reply=='status':
                values=[n==0,n==1,int(n>0),int(n==2),0,0,False,0]
                if (ack['state']!=dict(zip(PROPERTIES,values))
                        or any(type(ack['state'][k]) is not type(v) for k,v in zip(PROPERTIES,values))):
                    raise ValueError('exact typed original Status hold readbacks required')
        if held_reply=='outcome':verify_selector_rows(r['hold_acknowledgements'],1)
    elif final_author != (r['connected'] if r['case']=='release' else None):
        raise ValueError('retained author result is historical; destroyed author is unobservable')
    if r['case'] == 'dup':
        if r['after_first_result'] != author_receipt or r['duplicate_fd'] == r['original_fd']:
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
            expected_ready=SleControllerSnapshot.from_buffer_copy(bytes(ready))
            if held_reply=='status' and n==i and key=='before_snapshots':expected_ready.command_credits=0
            if r[key][n] != bytes(expected_ready).hex():
                raise ValueError('exact same-generation Ready metadata and real credit consumption required')
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
    if r.get('link_snapshot_gate'):
        if held_reply:raise ValueError('established snapshot gate must not borrow in-flight timing')
        for phase,revision,count in [('before',0,0),('up',1,1),('down',2,0)]:
            for n,raw in enumerate(r['link_snapshots'][phase]):
                value=decode(SleLinkSnapshot,raw)
                expected=SleLinkSnapshot(version=1,profile=1,generation=snapshots[n].generation,
                    event_seq=value.event_seq,revision=revision,flags=1,count=count,dev_index=n)
                if phase=='up':
                    body=bytes.fromhex(r['up'][n]['params']);link=expected.links[0]
                    link.lifetime=1;link.handle=int.from_bytes(body[1:3],'little');link.role=body[3]
                    link.address_type=body[4];link.address[:]=body[5:11]
                if bytes(value)!=bytes(expected):raise ValueError('exact canonical table, lifetime, zero tail and observed identity required')
                if phase!='before' and value.event_seq<r['up' if phase=='up' else 'down'][n]['seq']:
                    raise ValueError('atomic snapshot replay barrier must cover observed physical event')
        if r['snapshot_errors']!=[errno.EFAULT,errno.EINVAL,errno.EINVAL,errno.ENODEV]:
            raise ValueError('actual VFS pointer/reserved/tail/generation rejection required')
        before,after=[decode(SleLinkSnapshot,v) for v in r['snapshot_error_observations']]
        if bytes(before)!=bytes(after):raise ValueError('rejected copy/input must not mutate physical table or consume events')
    if r.get('peer_binding_gate'):
        table=decode(SleLinkSnapshot,r['binding_before'])
        if table.flags!=1 or table.count!=1 or table.revision!=1 or table.generation!=snapshots[i].generation:
            raise ValueError('actual established canonical reference required')
        link=table.links[0];body=bytes.fromhex(r['up'][i]['params'])
        if (link.lifetime!=1 or link.handle!=int.from_bytes(body[1:3],'little')
                or link.role!=body[3] or link.address_type!=body[4] or bytes(link.address)!=body[5:11]):
            raise ValueError('actual physical peer/lifetime required before mismatch tests')
        expected=[('lifetime',errno.ESTALE),('type',errno.ESTALE),('address',errno.ESTALE),('role',errno.ESTALE),
            ('zero',errno.EINVAL),('generation',errno.ENODEV),('version',errno.EOPNOTSUPP)]
        if [(v['mutation'],v['errno']) for v in r['binding_rejections']]!=expected:
            raise ValueError('all actual VFS peer/reference/version rejections required')
        for offset,row in enumerate(r['binding_rejections']):
            value=bound_disconnect(snapshots[i],link,901+offset);mutate_reference(value,row['mutation'])
            if row['input']!=bytes(value).hex() or row['author_result'] is not None:
                raise ValueError('rejected reference must not admit a procedure or fabricate result')
        if r['binding_after']!=r['binding_before']:raise ValueError('failed reference must preserve current physical table')
    if not r['start_wall_ns'] < r['release_before_wall_ns'] <= r['release_after_wall_ns'] < r['end_wall_ns']:
        raise ValueError('bounded original release observation interval required')
    if r['end_wall_ns'] - r['start_wall_ns'] > 60_000_000_000:
        raise ValueError('finite gate deadline required')
    if "channel_grant" in r:
        from ws73_channel_grant import verify
        verify(r["channel_grant"],r)
    return snapshots


def _corroborate(r, capture, hold=None, stderr=None, expected=None, prelude=None):
    if 'security_capabilities' in r:
        if hold is not None:raise CaptureError('limited capability gate excludes reply hold/recovery')
        from ws73_security_capabilities import corroborate as capability_corroborate
        return capability_corroborate(r,capture)
    if 'data_deadline' in r:
        from ws73_channel_deadline import corroborate as deadline_corroborate
        return deadline_corroborate(r,capture,hold,stderr,expected)
    if 'data_link_down' in r:
        if 'prefix_hold' in r:
            from ws73_channel_prefix_hold import corroborate as corroborate_prefix_hold
            barrier_proof=corroborate_prefix_hold(r,capture,hold,stderr,expected)
        elif hold is not None:raise CaptureError('unexpected direct Down hold')
        from ws73_channel_link_down import corroborate as down_corroborate
        proof=down_corroborate(r,capture)
        if 'prefix_hold' in r:proof['prefix_hold']=barrier_proof
        return proof
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
                else bytes([int(request.operation==3 or request.operation==6 and j==1),0]) if c['opcode']==0x1002
                else bytes.fromhex('0000010040062003') if c['opcode']==0x1001 else None)
            if c['opcode']==0xc02:
                params=bytearray(49);params[2]=2;params[3:6]=(1200).to_bytes(3,'little');params[6:9]=params[3:6]
                params[9]=7;params[12:18]=bytes(snapshots[n].address);params[25]=127;params[43]=200
                if request.operation==1:
                    params[1]=3;params[2]=0;params[34]=1;params[37:39]=(100).to_bytes(2,'little');params[39:41]=params[37:39]
                params=bytes(params)
            proofs.append(command_reply(capture,r['usb'][n],c['opcode'],c['wall_ns'],upper,params,
                bytes([value.selected_power&255]).hex() if c['opcode']==0xc02 else ''))
    heard=[e for e in capture['reports'] if belongs(e,i,r['scan_start_wall_ns'],r['scan_end_wall_ns'])
        and all(e[k]==r['scan_match'][k] for k in ['address','data','rssi'])]
    if not heard:raise CaptureError('independent actual random marker RX required')
    links=[]
    for operation,opcode,start,end,key in [(1,0x1401,r['connect_before_wall_ns'],r['connect_after_wall_ns'],'up'),
            (2,0x1403,r['release_before_wall_ns'],r['end_wall_ns'],'down')]:
        commands=[c for c in capture['commands'] if belongs(c,i,start,end) and c['opcode']==opcode]
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
        handle=int.from_bytes(bytes.fromhex(r['up'][i]['params'])[1:3],'little')
        if not r.get('reply_hold') and handle!=decode(SleConnectionResult,r['connected']).handle:
            raise CaptureError('author result must match actual physical handle')
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
    if prelude is not None:
        from ws73_protected_grant import command_records
        expected_commands+=command_records(prelude,capture)
    actual=[c for c in capture['commands'] if any(belongs(c,n,r['start_wall_ns'],r['end_wall_ns']) for n in [0,1])]
    if actual!=sorted(expected_commands,key=lambda c:c['wall_ns']):
        raise CaptureError('unrecorded reset, disconnect or peer command in connected File gate')
    if any(r['start_wall_ns']<=e['wall_ns']<=r['end_wall_ns'] for e in capture['failures']):
        raise CaptureError('USB transport failure inside connected File gate')
    if r.get('peer_binding_gate'):
        for row in r['binding_rejections']:
            if any(belongs(c,n,row['start_wall_ns'],row['end_wall_ns']) for c in capture['commands'] for n in [0,1]):
                raise CaptureError('rejected binding must emit no target or peer wire command')
    held=None
    if r.get('reply_hold'):
        create=links[0];status=create['status'];outcome=create['outcomes'][0]
        combined=(status['record']==outcome['record'])
        if r['reply_hold']=='outcome' and combined:raise CaptureError('outcome-only hold requires prior Status in a distinct real USB frame')
        reply=status if r['reply_hold']=='status' else outcome
        # usbmon and these markers use the guest clock. QMP host_wall_ns is
        # host provenance; never compare the two clocks as one timeline.
        if not r['markers'][2]['wall_ns']<=reply['wall_ns']<=r['up'][i]['wall_ns']:
            raise CaptureError('actual original held frame must reach guest after explicit release')
        if max(status['wall_ns'],outcome['wall_ns'],create['command']['completion']['wall_ns'])>links[1]['command']['wall_ns']:
            raise CaptureError('cleanup must follow actual OUT, Status and physical handle evidence')
        held=dict(actual_reply_stage='status-and-outcome' if combined else r['reply_hold'],
            original_frame_sha256=reply['usb_sha256'],original_frame_bytes=reply['usb_length'])
        if hold is not None:
            if r['reply_hold']=='outcome':
                held['host']=corroborate_later_hold(hold,dict(r,initialization_step=1),[status,outcome],stderr,expected)
            else:
                guest=dict(records=r['markers'],host_hold_acknowledgements=r['hold_acknowledgements'])
                held['host']=corroborate_host_hold(hold,guest,[],stderr,expected,held_reply=reply)
    elif 'prefix_hold' in r:
        from ws73_channel_prefix_hold import corroborate as corroborate_prefix_hold
        held=corroborate_prefix_hold(r,capture,hold,stderr,expected)
    elif hold is not None:raise CaptureError('unexpected host hold in completed connection gate')
    proof=dict(scope='pre-daemon actual Create reply File withdrawal and late-link cleanup; not natural recovery' if r.get('reply_hold') else 'pre-daemon established link actual File release/last-close/dup; not in-flight or natural recovery',
        discovery=proofs,heard=heard,links=links,connected_file_support_acceptance=True,
        daemon_running_lifecycle_acceptance=False,inflight_acceptance=bool(r.get('reply_hold')),automatic_recovery_acceptance=False)
    if 'channel_grant' in r:
        from ws73_channel_grant import corroborate as grant_corroborate
        proof['channel_grant']=grant_corroborate(r['channel_grant'],r,capture)
    if held is not None:proof['held_reply']=held
    return proof


def corroborate(r, capture, hold=None, stderr=None, expected=None):
    from ws73_protected_grant import requirement,corroborate as protected_wire
    security=requirement(r)
    prelude=protected_wire(r,capture) if security else None
    proof=_corroborate(r,capture,hold,stderr,expected,prelude)
    if security:proof['protected_security']=prelude
    if r.get('channel_grant',{}).get('tx_constraint_required'):
        from ws73_channel_grant import verify_intents
        proof['tx_constraints']=verify_intents(r['channel_grant'],r)
    return proof


def run(args):
    reply_hold=getattr(args,'reply_hold',None)
    snapshot_gate=getattr(args,'link_snapshot',False)
    binding_gate=getattr(args,'peer_binding',False)
    channel_gate=getattr(args,'channel_grant',False)
    protected=int(next((v.split('=',1)[1] for v in Path('/proc/cmdline').read_text().split() if v.startswith('ws73.channel_security=')), '0'))
    if protected not in (0,1,2):raise ValueError('unknown protected lifecycle requirement')
    original_deadline='ws73.security_original_deadline=1' in Path('/proc/cmdline').read_text().split()
    cancel_pending='ws73.security_cancel_pending=1' in Path('/proc/cmdline').read_text().split()
    encryption='ws73.security_encryption=1' in Path('/proc/cmdline').read_text().split()
    agreement='ws73.security_key_agreement=1' in Path('/proc/cmdline').read_text().split()
    numeric=next((v.split('=',1)[1] for v in Path('/proc/cmdline').read_text().split() if v.startswith('ws73.security_numeric=')),None)
    capabilities='ws73.security_capabilities=1' in Path('/proc/cmdline').read_text().split()
    idle_trace='ws73.session_idle=1' in Path('/proc/cmdline').read_text().split()
    idle_observer=None
    data_deadline='ws73.channel_deadline=1' in Path('/proc/cmdline').read_text().split()
    link_down='ws73.channel_link_down=1' in Path('/proc/cmdline').read_text().split()
    if protected and (not channel_gate or capabilities or reply_hold or idle_trace or getattr(args,'channel_directions',False) or getattr(args,'channel_scm_rights',False)):raise ValueError('separate protected bidirectional lifecycle required')
    if idle_trace and (not channel_gate or args.case!='release' or reply_hold or data_deadline or link_down or capabilities or not 'ws73.channel_revoke_prefix=1' in Path('/proc/cmdline').read_text().split()):raise ValueError('separate established ordinary prefix/idle VM required')
    if link_down and (not channel_gate or args.case!='release' or reply_hold or getattr(args,'channel_directions',False) or getattr(args,'channel_scm_rights',False) or not 'ws73.channel_revoke_prefix=1' in Path('/proc/cmdline').read_text().split()):
        raise ValueError('direct Down requires separate bidirectional begun-PDU release-mode environment')
    if data_deadline and (link_down or not channel_gate or args.case!='release' or reply_hold or getattr(args,'channel_directions',False) or getattr(args,'channel_scm_rights',False) or not 'ws73.channel_revoke_prefix=1' in Path('/proc/cmdline').read_text().split()):raise ValueError('separate bidirectional begun-PDU original-deadline environment required')
    if numeric and (numeric not in ('numeric-approve','numeric-reject','numeric-late') or not capabilities or agreement or encryption or cancel_pending):raise ValueError('separate numeric mechanism gate required')
    if original_deadline and not cancel_pending:raise ValueError('original deadline requires passive author gate')
    if cancel_pending and (not capabilities or agreement or encryption):raise ValueError('separate passive author cancellation gate required')
    if encryption and not agreement:raise ValueError('installation requires same Session candidate proof gate')
    if agreement and not capabilities:raise ValueError('key agreement requires explicit security gate')
    if capabilities and (data_deadline or link_down or not channel_gate or args.case!='release' or reply_hold or getattr(args,'channel_directions',False) or getattr(args,'channel_scm_rights',False) or 'ws73.channel_revoke_prefix=1' in Path('/proc/cmdline').read_text().split()):raise ValueError('separate limited capability-only bidirectional channel gate required')
    scm_rights=getattr(args,'channel_scm_rights',False)
    if scm_rights and not channel_gate:raise ValueError('fd transfer requires real channel Grant gate')
    directional=getattr(args,'channel_directions',False)
    if directional and not channel_gate:raise ValueError('directional scope requires real channel Grant gate')
    if channel_gate and reply_hold:raise ValueError("separate established channel Grant gate required")
    if snapshot_gate and reply_hold:raise ValueError('separate established snapshot gate required')
    if binding_gate and reply_hold:raise ValueError('separate established peer binding gate required')
    if (f'ws73.connected_case={args.case}' not in Path('/proc/cmdline').read_text().split()
            or os.geteuid()!=0 or not Path('/scratch-root-uuid').is_file()
            or Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU'
            or subprocess.run(['/bin/pidof','slkd'],capture_output=True).returncode==0):
        raise ValueError('explicit pre-daemon scratch VM required')
    boot=[v.split('=',1)[1] for v in Path('/proc/cmdline').read_text().split() if v.startswith('ws73.connected_reply=')]
    if boot!=([reply_hold] if reply_hold else []):raise ValueError('explicit matching reply hold boot mode required')
    if snapshot_gate != ('ws73.link_snapshot=1' in Path('/proc/cmdline').read_text().split()):
        raise ValueError('explicit matching link snapshot boot mode required')
    if binding_gate != ('ws73.peer_binding=1' in Path('/proc/cmdline').read_text().split()):raise ValueError('explicit peer binding boot mode required')
    if channel_gate != ("ws73.channel_grant=1" in Path("/proc/cmdline").read_text().split()):raise ValueError("explicit channel Grant boot mode required")
    if directional != ('ws73.channel_directions=1' in Path('/proc/cmdline').read_text().split()):raise ValueError('explicit directional Grant boot mode required')
    if scm_rights != ('ws73.channel_scm_rights=1' in Path('/proc/cmdline').read_text().split()):raise ValueError('explicit SCM_RIGHTS boot mode required')
    args.output.mkdir(parents=True,exist_ok=False)
    r=dict(format_version=1,status='STARTING',case=args.case,index=args.index,daemon_running=False,
        synthetic_support=False,physical_acceptance=False,automatic_recovery_acceptance=False,
        start_wall_ns=time.time_ns(),discovery=[],events=[[],[]],marker=secrets.token_hex(16))
    if reply_hold:r.update(reply_hold=reply_hold,markers=[],hold_acknowledgements=[])
    if snapshot_gate:r.update(link_snapshot_gate=True,link_snapshots={})
    if binding_gate:r.update(peer_binding_gate=True,binding_rejections=[])
    def save():save_record(args.output,r)
    def stage(phase,ack):
        marker=dict(hold_phase=phase,wall_ns=time.time_ns());r['markers'].append(marker);save()
        write_marker(args.output/f'hold-{phase}.json',marker);deadline=time.monotonic()+6
        while not (args.output/f'hold-{ack}-ack.json').exists():
            if time.monotonic()>deadline:raise TimeoutError('actual connection frame hold handshake')
            time.sleep(.002)
        import json
        value=json.loads((args.output/f'hold-{ack}-ack.json').read_text())
        if value['stage']!=ack or value['request']!=marker:raise ValueError('exact actual frame acknowledgement required')
        r['hold_acknowledgements'].append(value);save()
    handles=[];alias=None;grant=None
    try:
        observers=[NativeAdapter(n) for n in [0,1]];handles+=observers
        snapshots=[a.snapshot() for a in observers];r['initial_snapshots']=[bytes(s).hex() for s in snapshots]
        for n,s in enumerate(snapshots):setup(bytes(s).hex(),n)
        r['usb']=[]
        for n in [0,1]:
            path=Path(f'/sys/bus/usb/devices/1-{n+1}')
            r['usb'].append(dict(bus=int((path/'busnum').read_text()),device=int((path/'devnum').read_text())))
        models=[v.split('=',1)[1].split(',') for v in Path('/proc/cmdline').read_text().split() if v.startswith('ws73.expected_models=')]
        if models:
            if len(models)!=1 or len(models[0])!=2:raise ValueError('exact selected Native board models required')
            from ws73_lab_resources import observe_guest_hcc
            r['hcc_observations']=[observe_guest_hcc(dict(r['usb'][n],port=f'1-{n+1}',index=n,
                generation=s.generation,address=':'.join(f'{v:02X}' for v in s.address)),models[0][n]) for n,s in enumerate(snapshots)]
            save()
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
        r['scan_end_wall_ns']=time.time_ns();discover(i,stop(snapshots[i],104,4))
        if snapshot_gate:r['link_snapshots']['before']=[bytes(a.link_snapshot()).hex() for a in observers];save()
        if reply_hold:stage('arm_ready','armed')
        request=connection(snapshots[i],snapshots[p]);r['connection_input']=bytes(request).hex();r['connect_before_wall_ns']=time.time_ns()
        writers[i].submit_connection(request);deadline=time.monotonic()+12
        if reply_hold:
            stage('wait_held','held');result=writers[i].connection_result(snapshots[i].generation,900);drain()
            r['pending']=bytes(result).hex();save()
            if (result.state,result.flags)!=((2,0) if reply_hold=='status' else (3,1)):
                raise ValueError('unexpected original author stage while real reply held')
        else:
            while True:
                result=writers[i].connection_result(snapshots[i].generation,900);drain()
                if result is not None and result.state>=4:break
                if time.monotonic()>deadline:raise TimeoutError('actual connection')
                time.sleep(.002)
            if result.state!=4:raise ValueError('actual Create failed')
        def outcomes(key,codes,index=None):
            deadline=time.monotonic()+8
            while True:
                drain();values=[[e for e in events if e['event'] in codes] for events in r['events']]
                if index is not None and len(values[index])==1:return values[index][0]
                if index is None and all(len(v)==1 for v in values):return [v[0] for v in values]
                if time.monotonic()>deadline:raise TimeoutError('both actual '+key+' events')
                time.sleep(.002)
        if not reply_hold:
            r['up']=outcomes('up',[0x15,0x1401]);r['connected']=bytes(result).hex();r['connect_after_wall_ns']=time.time_ns()
            if snapshot_gate:r['link_snapshots']['up']=[bytes(a.link_snapshot()).hex() for a in observers];save()
            if binding_gate:
                table=observers[i].link_snapshot();r['binding_before']=bytes(table).hex();save()
                if table.flags!=1 or table.count!=1:raise ValueError('one actual established physical link required')
                command=(1<<30)|(ctypes.sizeof(SleConnectionSubmit)<<16)|(ord('S')<<8)|0x9c
                for offset,mutation in enumerate(['lifetime','type','address','role','zero','generation','version']):
                    value=bound_disconnect(snapshots[i],table.links[0],901+offset);mutate_reference(value,mutation)
                    row=dict(mutation=mutation,input=bytes(value).hex(),start_wall_ns=time.time_ns());r['binding_rejections'].append(row);save()
                    try:fcntl.ioctl(writers[i].fileno(),command,bytearray(bytes(value)),True)
                    except OSError as error:row['errno']=error.errno
                    else:raise ValueError('mismatching/old reference accepted')
                    result=writers[i].connection_result(snapshots[i].generation,901+offset)
                    row.update(author_result=bytes(result).hex() if result is not None else None,end_wall_ns=time.time_ns());save()
                r['binding_after']=bytes(observers[i].link_snapshot()).hex();save()
        if channel_gate:
            from ws73_channel_grant import Gate
            if protected:
                from ws73_protected_grant import execute as protect
                protect(r,save,observers,writers,snapshots,protected)
            grant=Gate(observers,snapshots,leases,i,r,save,directional,scm_rights,security=protected)
            if idle_trace:
                from ws73_session_idle import SessionIdleTrace
                idle_observer=SessionIdleTrace(r,save)
            grant.exchange('before')
            if idle_observer:idle_observer.idle(grant)
            if capabilities:
                if numeric:r['numeric_comparison']=numeric
                if cancel_pending:r['security_cancel_pending']=True
                if original_deadline:r['security_original_deadline']=True
                r['key_agreement']=agreement
                if encryption:r['unauthenticated_encryption']=True
                from ws73_security_capabilities import exercise
                exercise(r,save,grant,observers,writers,snapshots,leases,outcomes,bound_disconnect,discover,standby,stop)
                grant.close();grant=None
                return
            if data_deadline:
                from ws73_channel_deadline import exercise
                exercise(r,save,grant,observers,writers,snapshots,leases,discover,outcomes,standby,stop,bound_disconnect)
                grant.close();grant=None
                return
            if link_down:
                from ws73_channel_link_down import exercise
                exercise(r,save,grant,observers,writers,snapshots,leases,discover,outcomes,standby,stop,bound_disconnect)
                grant.close();grant=None
                return
        r['before_snapshots']=[bytes(a.snapshot()).hex() for a in observers]
        r['held']=bytes(observers[i].management_status()).hex();r['peer_before']=bytes(observers[p].management_status()).hex()
        fd=writers[i].fileno();r['original_fd']=fd;r['duplicate_fd']=-1
        if args.case=='dup':
            alias=os.dup(fd);r['duplicate_fd']=alias;r['first_close_wall_ns']=time.time_ns();writers[i].close()
            time.sleep(.15);drain();r['first_close_quiet_end_ns']=time.time_ns()
            r['after_first_result']=bytes(duplicate_result(alias,snapshots[i].generation,900)).hex()
            r['after_first_management']=bytes(observers[i].management_status()).hex()
            if any(e['event'] in [5,0x1405] for events in r['events'] for e in events):raise ValueError('first dup close disconnected actual link')
        if grant and args.case=='dup':grant.exchange('after_first_control_close')
        prefix_barrier=None
        if grant and not directional:
            if 'ws73.channel_revoke_prefix=1' in Path('/proc/cmdline').read_text().split():
                from ws73_channel_prefix_hold import PrefixBarrier
                prefix_barrier=PrefixBarrier(r,save);prefix_barrier.arm(grant)
            else:grant.arm()
        r['release_before_wall_ns']=time.time_ns();save()
        if args.case=='release':writers[i].release_management(leases[i],1)
        elif args.case=='close':writers[i].close()
        else:os.close(alias);alias=None
        r['release_after_wall_ns']=time.time_ns()
        if prefix_barrier:prefix_barrier.release()
        if reply_hold:
            r['revoking']=bytes(observers[i].management_status()).hex()
            r['cancelled']=bytes(writers[i].connection_result(snapshots[i].generation,900)).hex() if args.case=='release' else None
            if observers[i].management_status().state!=2:raise ValueError('original reply must retain connection cleanup reservation')
            save();stage('release_ready','released')
            r['up']=outcomes('up',[0x15,0x1401]);r['connect_after_wall_ns']=time.time_ns()
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
        if snapshot_gate:r['link_snapshots']['down']=[bytes(a.link_snapshot()).hex() for a in observers];save()
        r['author_result_after_release']=bytes(writers[i].connection_result(snapshots[i].generation,900)).hex() if args.case=='release' else None
        if grant:
            grant.withdrawn()
            grant.successor(observers[i],snapshots[i].generation)
            grant.close();grant=None
        # Intended link loss must not prevent independent peer radio control.
        for identifier,operation in [(104,2),(105,3),(106,4)]:
            req=standby(snapshots[p],identifier,'scanning') if operation==3 else stop(snapshots[p],identifier,operation)
            req.operation=operation;discover(p,req)
        writers[p].release_management(leases[p],1)
        if snapshot_gate:
            command=(3<<30)|(ctypes.sizeof(SleLinkSnapshot)<<16)|(ord('S')<<8)|0x9e
            r['snapshot_error_observations']=[bytes(observers[i].link_snapshot()).hex()];r['snapshot_errors']=[]
            libc=ctypes.CDLL(None,use_errno=True);libc.ioctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_void_p];libc.ioctl.restype=ctypes.c_int
            if libc.ioctl(observers[i].fileno(),command,ctypes.c_void_p(1))!=-1:raise ValueError('bad user pointer accepted')
            r['snapshot_errors'].append(ctypes.get_errno())
            for kind in ['reserved','tail','generation']:
                value=SleLinkSnapshot(version=1,generation=snapshots[i].generation)
                if kind=='reserved':value.reserved[0]=1
                elif kind=='tail':value.links[15].lifetime=1
                else:value.generation+=1
                original=bytes(value);buffer=bytearray(original)
                try:fcntl.ioctl(observers[i].fileno(),command,buffer,True)
                except OSError as error:r['snapshot_errors'].append(error.errno)
                else:raise ValueError('malformed/stale snapshot input accepted')
                if bytes(buffer)!=original:raise ValueError('failed query modified caller input')
            r['snapshot_error_observations'].append(bytes(observers[i].link_snapshot()).hex());save()
        if idle_observer:idle_observer.finish()
        r.update(end_wall_ns=time.time_ns(),status='INFLIGHT_FILE_PASS' if reply_hold else 'CONNECTED_FILE_PASS');verify_records(r);save()
        print('WS73_TARGET_CONNECTED_FILE_PASS',flush=True)
    except BaseException as error:
        r.update(status='FAIL',error=str(error),error_type=type(error).__name__);save();raise
    finally:
        if idle_observer:idle_observer.close()
        if grant:grant.close()
        if alias is not None:os.close(alias)
        for handle in handles:handle.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['release','close','dup'],required=True)
    parser.add_argument('--index',type=int,choices=[0,1],required=True)
    parser.add_argument('--reply-hold',choices=['status','outcome'],help='retain actual original Create reply before File withdrawal')
    parser.add_argument('--link-snapshot',action='store_true',help='actual established physical table/lifetime/barrier and VFS read errors')
    parser.add_argument('--peer-binding',action='store_true',help='real mismatching peer/lifetime references reject before any wire traffic')
    parser.add_argument('--channel-scm-rights',action='store_true',help='transfer native channel fd after ordinary worker closes inherited authority')
    parser.add_argument('--channel-directions',action='store_true',help='real TX-only to RX-only scope, forbidden actions and protected request rejection')
    parser.add_argument('--channel-grant',action='store_true',help='ordinary duplicated sockets and witnessed blocking RX across actual control withdrawal')
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args())
