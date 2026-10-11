#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit scratch-VM Managed partial initialization with a real held reply."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / ('python' if (HERE.parent/'python').is_dir() else 'bindings/python')))
from sparklink.native import NativeAdapter
from sparklink.structs import SleDiscoverySubmit, SleDiagnosticSubmit, SleDiagnosticResult, SleDiscoveryResult, SleControllerSnapshot, SleManagementQuery
from ws73_diagnostic_hold import HoldCoordinator, write_marker
from ws73_management_setup import decode, setup, save_record


class PartialCoordinator(HoldCoordinator):
    def __init__(self, share, record):
        super().__init__(share, record)
        self.folder = Path(share)/'managed-partial'


def standby(snapshot, request_id, domain):
    request = SleDiscoverySubmit(version=1, generation=snapshot.generation,
        request_id=request_id, profile=1, operation=5 if domain == 'advertising' else 6)
    if domain == 'advertising':
        p = request.advertising
        p.gt_role=2; p.interval_min=p.interval_max=1200; p.channel_map=7
        p.tx_power=127; p.supervision_timeout=200; p.own_address[:]=snapshot.address
    else:
        request.scanning.frame_types=1; request.scanning.interval=1600; request.scanning.window=800
    return request


def verify_records(record):
    if (type(record.get('format_version')) is not int or record['format_version']!=1
            or record.get('status')!='MANAGED_PARTIAL_HELD_REPLY_PASS'
            or record.get('physical_acceptance') is not False or record.get('automatic_fault_recovery_acceptance') is not False
            or record.get('daemon_running_during_hold') is not False
            or record.get('case') not in ('release','close','dup') or record.get('domain') not in ('advertising','scanning')):
        raise ValueError('limited partial held-reply gate format required')
    snapshots=[setup(raw,i) for i,raw in enumerate(record['initial_snapshots'])]
    if len(snapshots)!=2 or snapshots[0].generation==snapshots[1].generation:
        raise ValueError('two independent untouched controllers required')
    command=decode(SleDiscoverySubmit,record['input'])
    if bytes(command)!=bytes(standby(snapshots[0],1,record['domain'])):
        raise ValueError('exact typed standby policy required')
    opcode=0xc02 if record['domain']=='advertising' else 0x1001
    for key,state,error in [('pending',2,0),('cancelled',5,-errno.ECANCELED),('final_result',5,-errno.ECANCELED)]:
        result=decode(SleDiscoveryResult,record[key])
        expected=SleDiscoveryResult(version=1,generation=snapshots[0].generation,request_id=1,
            dev_index=0,profile=1,operation=command.operation,count=2 if opcode==0xc02 else 3,
            state=state,error=error,opcode=opcode,
            radio_adv=1 if key=='final_result' else 0,radio_scan=1 if key=='final_result' else 0)
        if bytes(result)!=bytes(expected):raise ValueError('exact pending/cancelled operation without fabricated success required')
    for key,state,mode in [('before_management',1,1),('revoking',2,0),('final_management',0,0)]:
        q=decode(SleManagementQuery,record[key]);expected=SleManagementQuery(version=1,generation=snapshots[0].generation,state=state,mode=mode)
        if bytes(q)!=bytes(expected):raise ValueError('exact independent ownership observation required')
    ready=decode(SleControllerSnapshot,record['final_snapshot'])
    expected=SleControllerSnapshot.from_buffer_copy(bytes(snapshots[0]));expected.flags=1
    if bytes(ready)!=bytes(expected):raise ValueError('only real successful cleanup may establish Ready')
    if record['peer_after']!=record['initial_snapshots'][1] or record['peer_management_before']!=record['peer_management_after']:
        raise ValueError('peer registration/metadata/owner changed')
    peerq=decode(SleManagementQuery,record['peer_management_before'])
    if bytes(peerq)!=bytes(SleManagementQuery(version=1,generation=snapshots[1].generation,state=1,mode=2)):
        raise ValueError('independent peer Diagnostic ownership required')
    if type(record['original_fd']) is not int or record['original_fd']<0 or type(record['lease']) is not int or not record['lease']:
        raise ValueError('actual owner descriptor/lease required')
    if record['case']!='release' and record.get('original_fd_errno')!=errno.EBADF:raise ValueError('actual original close required')
    if record['case']=='dup':
        if type(record['duplicate_fd']) is not int or record['duplicate_fd']<0 or record['duplicate_fd']==record['original_fd'] or record.get('duplicate_fd_errno')!=errno.EBADF:
            raise ValueError('actual distinct duplicate last-close required')
        if record['after_first_management']!=record['before_management']:raise ValueError('first dup close revoked owner')
    elif record['duplicate_fd']!=-1:raise ValueError('unexpected alias')
    markers=record['markers'];acks=record['host_hold_acknowledgements']
    if len(markers)!=3 or [m['hold_phase'] for m in markers]!=['arm_ready','wait_held','release_ready']:
        raise ValueError('ordered arm/held/release markers required')
    clocks=[record[k] for k in ['submit_before_wall_ns','submit_after_wall_ns','release_before_wall_ns','release_after_wall_ns']]
    if any(type(v) is not int or v<=0 for v in clocks) or clocks!=sorted(clocks) or clocks[-1]-clocks[0]>=400_000_000:
        raise ValueError('release must occur before the original 500ms deadline')
    if len(acks)!=3 or [v['request'] for v in acks]!=markers or [v['stage'] for v in acks]!=['armed','held','released']:
        raise ValueError('actual three host acknowledgements required')
    if not markers[0]['wall_ns']<clocks[0]<=clocks[1]<markers[1]['wall_ns']<clocks[2]<=clocks[3]<markers[2]['wall_ns']:
        raise ValueError('actual hold causality required')
    queries=record['peer_queries']
    if len(queries)!=3:raise ValueError('three peer wire probes required')
    for i,row in enumerate(queries):
        submitted=decode(SleDiagnosticSubmit,row['input']);result=decode(SleDiagnosticResult,row['result'])
        expected=SleDiagnosticSubmit(version=1,generation=snapshots[1].generation,request_id=i+1,timeout_ms=5000,opcode=0x0406,action=1,seq=submitted.seq)
        if not submitted.seq or bytes(submitted)!=bytes(expected) or result.state!=2 or result.opcode!=0x0406 or result.seq!=submitted.seq or result.generation!=submitted.generation or result.status or result.error or result.data_len!=6 or bytes(result.data[:6])!=bytes(snapshots[1].address):
            raise ValueError('peer real query failed or wrong identity')
    return snapshots


def corroborate(record, host, capture, stderr, expected):
    snapshots=verify_records(record)
    from ws73_diagnostic_hold import corroborate_host_hold
    start=record['submit_before_wall_ns'];end=record['management_observations'][-1]['wall_ns']
    rows=[v for v in capture['commands'] if v['bus']==1 and v['device']==2 and start<=v['wall_ns']<=end]
    opcode=0xc02 if record['domain']=='advertising' else 0x1001
    if [v['opcode'] for v in rows]!=[opcode,0xc05,0x1002] or rows[1]['params']!='0000000000' or rows[2]['params']!='0000':
        raise ValueError('one initial step followed only by actual advertising/scan stops required')
    replies=[]
    for command in rows:
        matches=[v for v in capture['complete'] if v['bus']==1 and v['device']==2 and v['opcode']==command['opcode'] and command['wall_ns']<=v['wall_ns']<=end]
        if len(matches)!=1 or matches[0]['status']:raise ValueError('every cleanup Complete must be actual and successful')
        replies.append(matches[0])
    proof=corroborate_host_hold(host,{'records':record['markers'],'host_hold_acknowledgements':record['host_hold_acknowledgements']},
        [{'caller':'C held active cancel','reply':replies[0]}],stderr,expected)
    if replies[0]['wall_ns']<record['release_after_wall_ns'] or rows[1]['wall_ns']<replies[0]['wall_ns']:
        raise ValueError('old reply must precede cleanup without escaping cancelled recipe')
    peer=[]
    for row in record['peer_queries']:
        commands=[v for v in capture['commands'] if v['bus']==1 and v['device']==3 and row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns']]
        completions=[v for v in capture['complete'] if v['bus']==1 and v['device']==3 and row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns']]
        if len(commands)!=1 or commands[0]['opcode']!=0x406 or len(completions)!=1 or completions[0]['opcode']!=0x406 or completions[0]['status'] or completions[0]['value']!=bytes(snapshots[1].address).hex():
            raise ValueError('peer queries require independent wire proof')
        peer.append(dict(command=commands[0],reply=completions[0]))
    return dict(scope='one partial first-step and actual held late reply',case=record['case'],domain=record['domain'],
        commands=rows,replies=replies,host_hold=proof,peer_queries=peer,
        managed_partial_case_live_acceptance=True,full_cleanup_acceptance=False,
        automatic_fault_recovery_acceptance=False,natural_fault_root_cause_closed=False)


def run(args):
    if 'ws73.managed_partial=1' not in Path('/proc/cmdline').read_text().split() or os.geteuid()!=0:
        raise ValueError('explicit root scratch VM gate required')
    if subprocess.run(['/bin/pidof','slkd'],capture_output=True).returncode==0:
        raise ValueError('partial gate requires untouched Setup before daemon')
    folder=args.output; folder.mkdir(parents=True,exist_ok=False)
    record=dict(format_version=1,status='STARTING',case=args.case,domain=args.domain,
        physical_acceptance=False,automatic_fault_recovery_acceptance=False,
        daemon_running_during_hold=False,host_hold_acknowledgements=[],markers=[],peer_queries=[])
    def save(): save_record(folder,record)
    def stage(phase,ack):
        value=dict(hold_phase=phase,wall_ns=time.time_ns());record['markers'].append(value);save()
        write_marker(folder/f'hold-{phase}.json',value)
        deadline=time.monotonic()+6
        while not (folder/f'hold-{ack}-ack.json').exists():
            if time.monotonic()>deadline:raise TimeoutError('real host hold acknowledgement')
            time.sleep(.002)
        response=json.loads((folder/f'hold-{ack}-ack.json').read_text())
        if response['stage']!=ack or response['request']!=value:raise ValueError('wrong acknowledgement')
        record['host_hold_acknowledgements'].append(response);save()
    handles=[];alias=None
    try:
        observers=[NativeAdapter(i) for i in [0,1]];handles+=observers
        snapshots=[a.snapshot() for a in observers]
        for i,s in enumerate(snapshots):setup(bytes(s).hex(),i)
        record['initial_snapshots']=[bytes(s).hex() for s in snapshots];save()
        target=NativeAdapter(0,snapshots[0].generation);peer=NativeAdapter(1,snapshots[1].generation);handles += [target,peer]
        peer_lease=peer.acquire_management(2)
        record['peer_management_before']=bytes(observers[1].management_status()).hex()
        def peer_query(request_id):
            command=SleDiagnosticSubmit(version=1,generation=peer.generation,request_id=request_id,timeout_ms=5000,opcode=0x0406,action=1)
            start=time.time_ns();peer.submit_diagnostic(command);deadline=time.monotonic()+6
            while True:
                result=peer.diagnostic_result(command.seq)
                if result is not None and result.state!=1:break
                if time.monotonic()>deadline:raise TimeoutError('peer MAC query')
                time.sleep(.002)
            record['peer_queries'].append(dict(input=bytes(command).hex(),result=bytes(result).hex(),start_wall_ns=start,end_wall_ns=time.time_ns()));save()
            if result.state!=2 or result.status or result.error or result.data_len!=6 or bytes(result.data[:6])!=bytes(snapshots[1].address):
                raise ValueError('peer query must remain successful')
        peer_query(1)
        lease=target.acquire_management(1);original=target.fileno()
        if args.case=='dup':alias=os.dup(original)
        record.update(original_fd=original,duplicate_fd=alias if alias is not None else -1,lease=lease)
        stage('arm_ready','armed')
        command=standby(snapshots[0],1,args.domain);record['input']=bytes(command).hex()
        record['submit_before_wall_ns']=time.time_ns();target.submit_discovery(command);record['submit_after_wall_ns']=time.time_ns();save()
        stage('wait_held','held')
        pending=observers[0].discovery_result(1);record['pending']=bytes(pending).hex();save()
        expected=0xc02 if args.domain=='advertising' else 0x1001
        if pending.state!=2 or pending.opcode!=expected or pending.step or pending.status or pending.error or pending.radio_adv or pending.radio_scan:
            raise ValueError('actual first-step in-flight recipe required')
        peer_query(2)
        record['before_management']=bytes(observers[0].management_status()).hex()
        record['release_before_wall_ns']=time.time_ns()
        if args.case=='release':target.release_management(lease,1)
        else:
            target.close()
            try:fcntl.fcntl(original,fcntl.F_GETFD)
            except OSError as e:record['original_fd_errno']=e.errno
            else:raise ValueError('original fd did not close')
            if args.case=='dup':
                record['after_first_management']=bytes(observers[0].management_status()).hex()
                if observers[0].management_status().state!=1:raise ValueError('dup first close revoked owner')
                time.sleep(.04)
                if observers[0].management_status().state!=1:raise ValueError('dup reference did not retain owner')
                os.close(alias)
                try:fcntl.fcntl(alias,fcntl.F_GETFD)
                except OSError as e:record['duplicate_fd_errno']=e.errno
                else:raise ValueError('duplicate did not close')
                alias=None
        record['release_after_wall_ns']=time.time_ns()
        record['revoking']=bytes(observers[0].management_status()).hex()
        record['cancelled']=bytes(observers[0].discovery_result(1)).hex();save()
        if observers[0].management_status().state!=2:raise ValueError('in-flight release must retain Revoking')
        stage('release_ready','released')
        deadline=time.monotonic()+6
        record['management_observations']=[]
        while True:
            q=observers[0].management_status();record['management_observations'].append(dict(wall_ns=time.time_ns(),raw=bytes(q).hex()));save()
            if q.state!=2:break
            if time.monotonic()>deadline:raise TimeoutError('bounded real cleanup')
            time.sleep(.005)
        record['final_management']=bytes(q).hex()
        record['final_snapshot']=bytes(observers[0].snapshot()).hex()
        record['final_result']=bytes(observers[0].discovery_result(1)).hex()
        record['peer_after']=bytes(observers[1].snapshot()).hex()
        record['peer_management_after']=bytes(observers[1].management_status()).hex();save()
        peer_query(3)
        peer.release_management(peer_lease,2)
        if q.state!=0 or q.error or q.status or q.opcode or q.flags:raise ValueError('actual cleanup failed; preserve raw controller outcome')
        if record['peer_after']!=record['initial_snapshots'][1] or record['peer_management_before']!=record['peer_management_after']:
            raise ValueError('peer changed during target cleanup')
        record['status']='MANAGED_PARTIAL_HELD_REPLY_PASS';verify_records(record);save()
        print('WS73_TARGET_MANAGED_PARTIAL_PASS',flush=True)
    except BaseException as e:
        record['status']='FAIL';record['error']=str(e);save();raise
    finally:
        if alias is not None:os.close(alias)
        for a in reversed(handles):a.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',choices=['release','close','dup'],required=True)
    p.add_argument('--domain',choices=['advertising','scanning'],required=True)
    run(p.parse_args())
