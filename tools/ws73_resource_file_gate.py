#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit VM-only advertising resource File cancellation; no synthetic reply."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

from ws73_management_partial import standby
from ws73_management_setup import setup, decode, save_record
from ws73_management_ready_peer import ReadyPeer, ready_bytes, verify as verify_peer, corroborate as peer_wire
from ws73_diagnostic_hold import write_marker, corroborate_host_hold
from ws73_capture import command_reply, marker_data, CaptureError
from sparklink.native import NativeAdapter
from sparklink.structs import SleDiscoverySubmit, SleDiscoveryResult, SleControllerSnapshot, SleManagementQuery


def announcement(snapshot, marker):
    r = standby(snapshot, 1, 'advertising')
    r.operation = 1
    r.advertising.mode = 3
    r.advertising.gt_role = 0
    r.advertising.max_requests = 1
    r.advertising.conn_interval_min = r.advertising.conn_interval_max = 100
    data = marker_data(marker)
    r.data_len = len(data)
    r.data[:len(data)] = data
    return r


def verify_records(r):
    if (type(r.get('format_version')) is not int or r.get('format_version') != 1 or r.get('status') != 'RESOURCE_FILE_HELD_REPLY_PASS'
            or r.get('resource_recreation') is not True or r.get('synthetic_support') is not False
            or r.get('active_ready_peer') is not True or r.get('daemon_running_during_hold') is not False
            or r.get('physical_acceptance') is not False or r.get('automatic_fault_recovery_acceptance') is not False
            or r.get('selected_domain_cleanup') is not True
            or r.get('case') not in ['release','close','dup']
            or type(r.get('initialization_step')) is not int or r.get('initialization_step') not in [0,1]):
        raise ValueError('explicit bounded real resource File scope required')
    snapshots = [setup(raw,i) for i,raw in enumerate(r['initial_snapshots'])]
    if len(snapshots) != 2 or snapshots[0].generation == snapshots[1].generation:
        raise ValueError('distinct initial controller registrations required')
    target = snapshots[0]
    if r['input'] != bytes(announcement(target,r['marker'])).hex():
        raise ValueError('exact changed announcement request required')
    if r['target_ready'] != ready_bytes(target):
        raise ValueError('actual initialized target before removal required')
    for row, identifier, operation in zip(r['preparation'],[2,3],[5,6]):
        request = standby(target,identifier,'advertising' if operation == 5 else 'scanning')
        value = decode(SleDiscoveryResult,row['result'])
        if (row['input'] != bytes(request).hex() or value.state != 3 or value.error or value.status
                or value.operation != operation or value.generation != target.generation
                or value.request_id != identifier or value.radio_adv != 1
                or value.radio_scan != (0 if operation == 5 else 1)
                or not 0 < row['start_wall_ns'] <= row['end_wall_ns'] < r['markers'][0]['wall_ns']):
            raise ValueError('actual target preparation must precede hold')
        from ws73_management_ready_peer import expected_result
        if bytes(value) != bytes(expected_result(target,identifier,operation,value.selected_power if operation==5 else 0)):
            raise ValueError('exact target preparation receipt required')
    if len(r['preparation']) != 2:
        raise ValueError('both target preparations required')
    step = r['initialization_step']
    for key, state, error in [('pending',2,0),('cancelled',5,-errno.ECANCELED),('final_result',5,-errno.ECANCELED)]:
        value = decode(SleDiscoveryResult,r[key])
        expected = SleDiscoveryResult(version=1,generation=target.generation,dev_index=0,profile=1,
            request_id=1,operation=1,state=state,error=error,step=step,count=4,
            opcode=0xc08 if step == 0 else 0xc02,radio_adv=1 if key == 'final_result' else 0,radio_scan=1)
        if bytes(value) != bytes(expected):
            raise ValueError('cancelled author must retain exact selected step and no fake success/power')
    for key,state in [('before_management',1),('revoking',2),('final_management',0)]:
        actual = decode(SleManagementQuery,r[key])
        expected = SleManagementQuery(version=1,generation=target.generation,state=state,mode=1 if state else 0)
        if bytes(actual) != bytes(expected):
            raise ValueError('exact Held/Revoking/Free observer truth required')
    final = SleControllerSnapshot.from_buffer_copy(bytes(target))
    final.flags = int(step == 1)
    if r['final_snapshot'] != bytes(final).hex():
        raise ValueError('deleted set alone is Setup; acknowledged creation may restore Ready')
    if r['case'] == 'dup' and r['after_first_management'] != r['before_management']:
        raise ValueError('dup first close must preserve Held')
    if r['case'] != 'release' and r.get('original_fd_errno') != errno.EBADF:
        raise ValueError('actual last File close required')
    if r['case'] == 'dup' and r.get('duplicate_fd_errno') != errno.EBADF:
        raise ValueError('actual duplicate last close required')
    verify_peer(r,snapshots[1])
    return snapshots


def corroborate(r, hold, capture, stderr, expected):
    snapshots = verify_records(r)
    owner = dict(bus=expected['bus'],device=expected['address'])
    preparation = []
    for row in r['preparation']:
        value = decode(SleDiscoveryResult,row['result'])
        sequence = ([0xc02,0xc05] if value.operation == 5 else [0x1001,0x1002,0x1002])
        selected = [c for c in capture['commands'] if (c['bus'],c['device']) == (owner['bus'],owner['device'])
            and row['start_wall_ns'] <= c['wall_ns'] <= row['end_wall_ns']]
        if [c['opcode'] for c in selected] != sequence:
            raise CaptureError('complete actual target bootstrap sequence required')
        for i,c in enumerate(selected):
            upper = selected[i+1]['wall_ns']-1 if i+1<len(selected) else row['end_wall_ns']
            params = (bytes(5) if c['opcode']==0xc05 else bytes.fromhex('0000010040062003') if c['opcode']==0x1001
                else bytes([int(i==1),0]) if c['opcode']==0x1002 else None)
            proof = command_reply(capture,owner,c['opcode'],c['wall_ns'],upper,params,
                bytes([value.selected_power & 255]).hex() if c['opcode']==0xc02 else '')
            if c['opcode']==0xc02:
                raw=bytes.fromhex(c['params'])
                if len(raw)!=49 or raw[:3]!=b'\0\0\2' or raw[12:18]!=bytes(snapshots[0].address):
                    raise CaptureError('initial set must be actual target mode0/GT2')
            preparation.append(proof)
    start,end = r['submit_before_wall_ns'],r['management_observations'][-1]['wall_ns']
    removal = command_reply(capture,owner,0xc08,start,end,bytes(1),'')
    replies = [removal['reply']]
    steps = [removal]
    if r['initialization_step'] == 1:
        params = bytearray(49)
        params[1]=3;params[3:6]=(1200).to_bytes(3,'little');params[6:9]=params[3:6]
        params[9]=7;params[12:18]=bytes(snapshots[0].address);params[25]=127
        params[34]=1;params[37:39]=(100).to_bytes(2,'little');params[39:41]=params[37:39];params[43]=200
        configuration = command_reply(capture,owner,0xc02,start,end,bytes(params))
        if removal['reply']['wall_ns'] > configuration['command']['wall_ns']:
            raise CaptureError('creation preceded actual removal acknowledgement')
        steps.append(configuration);replies.append(configuration['reply'])
    commands = [c for c in capture['commands'] if (c['bus'],c['device']) == (owner['bus'],owner['device'])
                and start <= c['wall_ns'] <= end]
    if commands != [s['command'] for s in steps]:
        raise CaptureError('cancelled resource recipe emitted extra data/enable or missing-set STOP')
    if r['initialization_step']:
        from ws73_host_later_hold import corroborate as later
        held = later(hold,r,replies,stderr,expected)
    else:
        guest = dict(records=r['markers'],host_hold_acknowledgements=r['hold_acknowledgements'])
        held = corroborate_host_hold(hold,guest,[],stderr,expected,held_reply=replies[0])
    return dict(scope='actual resource File and held original replies only; not connected revocation or automatic recovery',
        actual_target_preparation=preparation,actual_resource_commands=steps,actual_host_hold=held,ready_peer=peer_wire(r,snapshots[1],capture),
        real_resource_file_support_acceptance=True,connected_lifecycle_acceptance=False,
        automatic_recovery_acceptance=False,full_cleanup_acceptance=False)


def run(args):
    cmdline=Path('/proc/cmdline').read_text().split()
    if ('ws73.managed_recreate=1' not in cmdline or os.geteuid()!=0
            or not Path('/scratch-root-uuid').is_file()
            or Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU'
            or subprocess.run(['/bin/pidof','slkd'],capture_output=True).returncode == 0):
        raise ValueError('explicit pre-daemon scratch VM gate required')
    folder=args.output;folder.mkdir(parents=True,exist_ok=False)
    step = args.initialization_step
    r=dict(format_version=1,status='STARTING',resource_recreation=True,case=args.case,domain='advertising',
        initialization_step=step,selected_domain_cleanup=True,synthetic_support=False,active_ready_peer=True,real_later_step=bool(step),
        physical_acceptance=False,automatic_fault_recovery_acceptance=False,daemon_running_during_hold=False,
        markers=[],hold_acknowledgements=[],initial_snapshots=[],preparation=[],peer_queries=[])
    def save(): save_record(folder,r)
    def stage(phase,ack):
        value=dict(hold_phase=phase,wall_ns=time.time_ns());r['markers'].append(value);save()
        write_marker(folder/f'hold-{phase}.json',value);deadline=time.monotonic()+6
        while not (folder/f'hold-{ack}-ack.json').exists():
            if time.monotonic()>deadline:raise TimeoutError('actual hold handshake')
            time.sleep(.002)
        response=json.loads((folder/f'hold-{ack}-ack.json').read_text())
        if response['stage']!=ack or response['request']!=value:raise ValueError('wrong actual hold acknowledgement')
        r['hold_acknowledgements'].append(response);save()
    handles=[];alias=None
    try:
        observers=[NativeAdapter(i) for i in [0,1]];handles.extend(observers)
        snapshots=[x.snapshot() for x in observers]
        for i,snapshot in enumerate(snapshots):setup(bytes(snapshot).hex(),i)
        r['initial_snapshots']=[bytes(x).hex() for x in snapshots]
        target=NativeAdapter(0,snapshots[0].generation);peer=NativeAdapter(1,snapshots[1].generation);handles += [target,peer]
        peer_lease=peer.acquire_management(1);ready_peer=ReadyPeer(peer,observers[1],snapshots[1],r,save)
        ready_peer.phase(1);r['peer_management_before']=bytes(observers[1].management_status()).hex()
        lease=target.acquire_management(1)
        for identifier,domain in [(2,'advertising'),(3,'scanning')]:
            request=standby(snapshots[0],identifier,domain);row=dict(input=bytes(request).hex(),start_wall_ns=time.time_ns());r['preparation'].append(row);save()
            target.submit_discovery(request);deadline=time.monotonic()+6
            while True:
                result=observers[0].discovery_result(identifier)
                if result is not None and result.is_terminal:break
                if time.monotonic()>deadline:raise TimeoutError('target preparation')
                time.sleep(.002)
            if result.state!=3 or result.status or result.error:raise ValueError('target preparation failed')
            row.update(result=bytes(result).hex(),end_wall_ns=time.time_ns());save()
        r['target_ready']=bytes(observers[0].snapshot()).hex();original=target.fileno()
        if args.case=='dup':alias=os.dup(original)
        r.update(original_fd=original,duplicate_fd=alias if alias is not None else -1,lease=lease,marker=secrets.token_hex(16))
        stage('arm_ready','armed');request=announcement(snapshots[0],r['marker']);r['input']=bytes(request).hex()
        r['submit_before_wall_ns']=time.time_ns();target.submit_discovery(request);r['submit_after_wall_ns']=time.time_ns();save()
        stage('wait_held','held');r['pending']=bytes(observers[0].discovery_result(1)).hex();save()
        ready_peer.phase(2);r['before_management']=bytes(observers[0].management_status()).hex();r['release_before_wall_ns']=time.time_ns()
        if args.case=='release':target.release_management(lease,1)
        else:
            target.close()
            try:fcntl.fcntl(original,fcntl.F_GETFD)
            except OSError as error:r['original_fd_errno']=error.errno
            else:raise ValueError('original File not closed')
            if args.case=='dup':
                r['after_first_management']=bytes(observers[0].management_status()).hex();time.sleep(.04)
                if observers[0].management_status().state!=1:raise ValueError('dup first close revoked owner')
                os.close(alias)
                try:fcntl.fcntl(alias,fcntl.F_GETFD)
                except OSError as error:r['duplicate_fd_errno']=error.errno
                else:raise ValueError('duplicate File not closed')
                alias=None
        r['release_after_wall_ns']=time.time_ns();r['revoking']=bytes(observers[0].management_status()).hex()
        r['cancelled']=bytes(observers[0].discovery_result(1)).hex();save()
        if observers[0].management_status().state!=2:raise ValueError('held response must retain Revoking')
        stage('release_ready','released');deadline=time.monotonic()+6;r['management_observations']=[]
        while True:
            q=observers[0].management_status();r['management_observations'].append(dict(wall_ns=time.time_ns(),raw=bytes(q).hex()));save()
            if q.state!=2:break
            if time.monotonic()>deadline:raise TimeoutError('finite actual resource cleanup')
            time.sleep(.005)
        r.update(final_management=bytes(q).hex(),final_snapshot=bytes(observers[0].snapshot()).hex(),
            final_result=bytes(observers[0].discovery_result(1)).hex(),peer_after=bytes(observers[1].snapshot()).hex(),
            peer_management_after=bytes(observers[1].management_status()).hex());save()
        ready_peer.phase(3);peer.release_management(peer_lease,1)
        r['ready_peer']['released_management']=bytes(observers[1].management_status()).hex()
        r['status']='RESOURCE_FILE_HELD_REPLY_PASS';verify_records(r);save();print('WS73_TARGET_RESOURCE_FILE_PASS',flush=True)
    except BaseException as error:
        r.update(status='FAIL',error=str(error),error_type=type(error).__name__);save();raise
    finally:
        if alias is not None:os.close(alias)
        for handle in handles:handle.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',choices=['release','close','dup'],required=True)
    p.add_argument('--initialization-step',type=int,choices=[0,1],default=0)
    p.add_argument('--output',type=Path,required=True)
    run(p.parse_args())
