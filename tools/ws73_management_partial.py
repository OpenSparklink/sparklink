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


def verify_preparation(record, snapshot):
    rows = record['preparation']
    if record['domain'] == 'advertising':
        if rows != []:
            raise ValueError('advertising first-step gate must start untouched')
        return
    if len(rows) != 1:
        raise ValueError('scan initialization requires completed advertising Off preparation')
    row = rows[0]
    if row['input'] != bytes(standby(snapshot, 2, 'advertising')).hex():
        raise ValueError('exact advertising preparation required')
    result = decode(SleDiscoveryResult, row['result'])
    if not -128 <= result.selected_power <= 127:
        raise ValueError('actual selected advertising power required')
    expected = SleDiscoveryResult(version=1, generation=snapshot.generation,
        request_id=2, profile=1, operation=5, state=3, count=2, step=1,
        opcode=0xc05, radio_adv=1, selected_power=result.selected_power, power_valid=1)
    if bytes(result) != bytes(expected):
        raise ValueError('only successful real preparation can establish advertising Off')
    start, end = row['start_wall_ns'], row['end_wall_ns']
    if (type(start) is not int or type(end) is not int or not 0 < start <= end
            or end-start >= 6_000_000_000 or end >= record['markers'][0]['wall_ns']):
        raise ValueError('bounded advertising preparation must finish before hold arm')


def verify_records(record, cleanup_rejected=False):
    synthetic=record.get('synthetic_support')
    status='MANAGED_PARTIAL_HELD_REPLY_SYNTHETIC_SUPPORT_PASS' if synthetic else 'MANAGED_PARTIAL_HELD_REPLY_PASS'
    if type(cleanup_rejected) is not bool or cleanup_rejected and synthetic is not True:
        raise ValueError('explicit model-only cleanup refusal verification required')
    if cleanup_rejected:
        status='FAIL'
        if (record.get('error')!='actual cleanup failed; preserve raw controller outcome'
                or record.get('error_type')!='ValueError' or record.get('errno') is not None):
            raise ValueError('an arbitrary failed VM is not the expected controller refusal')
    if (type(synthetic) is not bool or type(record.get('format_version')) is not int or record['format_version']!=3
            or record.get('status')!=status
            or record.get('physical_acceptance') is not False or record.get('automatic_fault_recovery_acceptance') is not False
            or record.get('daemon_running_during_hold') is not False
            or record.get('case') not in ('release','close','dup') or record.get('domain') not in ('advertising','scanning')):
        raise ValueError('limited partial held-reply gate format required')
    snapshots=[setup(raw,i) for i,raw in enumerate(record['initial_snapshots'])]
    if len(snapshots)!=2 or snapshots[0].generation==snapshots[1].generation:
        raise ValueError('two independent untouched controllers required')
    verify_preparation(record, snapshots[0])
    command=decode(SleDiscoverySubmit,record['input'])
    if bytes(command)!=bytes(standby(snapshots[0],1,record['domain'])):
        raise ValueError('exact typed standby policy required')
    opcode=0xc02 if record['domain']=='advertising' else 0x1001
    for key,state,error in [('pending',2,0),('cancelled',5,-errno.ECANCELED),('final_result',5,-errno.ECANCELED)]:
        result=decode(SleDiscoveryResult,record[key])
        expected=SleDiscoveryResult(version=1,generation=snapshots[0].generation,request_id=1,
            dev_index=0,profile=1,operation=command.operation,count=2 if opcode==0xc02 else 3,
            state=state,error=error,opcode=opcode,
            radio_adv=1 if key=='final_result' or record['domain']=='scanning' else 0,
            radio_scan=1 if key=='final_result' else 0)
        if cleanup_rejected and key=='final_result':
            expected.flags=1;expected.radio_adv=expected.radio_scan=0
        if bytes(result)!=bytes(expected):raise ValueError('exact pending/cancelled operation without fabricated success required')
    for key,state,mode in [('before_management',1,1),('revoking',2,0),('final_management',3 if cleanup_rejected else 0,0)]:
        q=decode(SleManagementQuery,record[key]);expected=SleManagementQuery(version=1,generation=snapshots[0].generation,state=state,mode=mode)
        if cleanup_rejected and key=='final_management':
            expected.flags=2;expected.error=-errno.EIO;expected.status=0x0b;expected.opcode=0x1002
        if bytes(q)!=bytes(expected):raise ValueError('exact independent ownership observation required')
    ready=decode(SleControllerSnapshot,record['final_snapshot'])
    expected=SleControllerSnapshot.from_buffer_copy(bytes(snapshots[0]));expected.flags=1
    if cleanup_rejected:expected.flags=4;expected.error=-errno.EIO;expected.command_credits=0
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
    markers=record['markers'];acks=record['hold_acknowledgements']
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
    observations=record['management_observations']
    if not observations or observations[-1]['raw']!=record['final_management']:
        raise ValueError('complete ownership observation interval required')
    previous=markers[2]['wall_ns']
    for i,row in enumerate(observations):
        if type(row['wall_ns']) is not int or row['wall_ns']<previous:
            raise ValueError('ownership observation time must follow held-reply release')
        previous=row['wall_ns']
        last=i==len(observations)-1
        expected=SleManagementQuery(version=1,generation=snapshots[0].generation,state=(3 if cleanup_rejected else 0) if last else 2)
        if cleanup_rejected and last:
            expected.flags=2;expected.error=-errno.EIO;expected.status=0x0b;expected.opcode=0x1002
        if bytes(decode(SleManagementQuery,row['raw']))!=bytes(expected):
            raise ValueError('only Revoking followed by exact Free is allowed')
    sequences=set()
    for i,row in enumerate(queries):
        submitted=decode(SleDiagnosticSubmit,row['input']);result=decode(SleDiagnosticResult,row['result'])
        expected=SleDiagnosticSubmit(version=1,generation=snapshots[1].generation,request_id=i+1,timeout_ms=5000,opcode=0x0406,action=1,seq=submitted.seq)
        reply=SleDiagnosticResult(version=1,generation=snapshots[1].generation,seq=submitted.seq,state=2,opcode=0x0406,data_len=6)
        reply.data[:6]=snapshots[1].address
        if not submitted.seq or submitted.seq in sequences or bytes(submitted)!=bytes(expected) or bytes(result)!=bytes(reply):
            raise ValueError('peer real query failed or wrong identity')
        sequences.add(submitted.seq)
        start,end=row['start_wall_ns'],row['end_wall_ns']
        if type(start) is not int or type(end) is not int or not 0<start<=end:
            raise ValueError('bounded actual peer query interval required')
        if (i==0 and end>=markers[0]['wall_ns'] or i==1 and not markers[1]['wall_ns']<start<=end<clocks[2]
                or i==2 and start<=observations[-1]['wall_ns']):
            raise ValueError('peer must be queried before, during and after target cleanup')
    return snapshots


def corroborate(record, host, capture, stderr, expected, cleanup_rejected=False):
    snapshots=verify_records(record,cleanup_rejected)
    preparation=[]
    if record['domain']=='scanning':
        row=record['preparation'][0]
        commands=[v for v in capture['commands'] if v['bus']==1 and v['device']==2
                  and row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns']]
        if [v['opcode'] for v in commands]!=[0xc02,0xc05] or commands[1]['params']!='0000000000':
            raise ValueError('real advertising configure and STOP preparation required')
        params=bytes.fromhex(commands[0]['params'])
        if len(params)!=49 or params[0]!=0 or params[12:18]!=bytes(snapshots[0].address):
            raise ValueError('advertising preparation must address this real controller')
        result=decode(SleDiscoveryResult,row['result'])
        previous=row['start_wall_ns']
        for i,command in enumerate(commands):
            matches=[v for v in capture['complete'] if v['bus']==1 and v['device']==2
                     and v['opcode']==command['opcode'] and command['wall_ns']<=v['wall_ns']<=row['end_wall_ns']]
            if len(matches)!=1 or matches[0]['status'] or command['wall_ns']<previous:
                raise ValueError('ordered actual successful preparation replies required')
            reply=matches[0];previous=reply['wall_ns']
            if reply['value'] != (bytes([result.selected_power & 255]).hex() if i==0 else ''):
                raise ValueError('preparation power and STOP must match actual replies')
            preparation.append(dict(command=command,reply=reply))
    from ws73_diagnostic_hold import corroborate_host_hold
    start=record['submit_before_wall_ns'];end=record['management_observations'][-1]['wall_ns']
    rows=[v for v in capture['commands'] if v['bus']==1 and v['device']==2 and start<=v['wall_ns']<=end]
    opcode=0xc02 if record['domain']=='advertising' else 0x1001
    opcodes=[opcode,0xc05,0x1002] if record['domain']=='advertising' else [opcode,0x1002]
    if [v['opcode'] for v in rows]!=opcodes or any(v['params']!={0xc05:'0000000000',0x1002:'0000'}[v['opcode']] for v in rows[1:]):
        raise ValueError('only required actual stops may follow the held first step')
    if preparation:
        all_commands=[v for v in capture['commands'] if v['bus']==1 and v['device']==2
                      and record['preparation'][0]['start_wall_ns']<=v['wall_ns']<=end]
        if all_commands!=[v['command'] for v in preparation]+rows:
            raise ValueError('confirmed advertising Off must have no intervening target traffic')
    replies=[]
    for index,command in enumerate(rows):
        matches=[v for v in capture['complete'] if v['bus']==1 and v['device']==2 and v['opcode']==command['opcode'] and command['wall_ns']<=v['wall_ns']<=end]
        status=0x0b if cleanup_rejected and index==len(rows)-1 else 0
        if len(matches)!=1 or matches[0]['status']!=status:raise ValueError('every reply must match its actual success or exact model cleanup refusal')
        replies.append(matches[0])
    if record['synthetic_support']:
        from ws73_model_hold import corroborate_model_hold
        proof=corroborate_model_hold(host,record,replies[0],stderr)
    else:
        proof=corroborate_host_hold(host,{'records':record['markers'],'host_hold_acknowledgements':record['hold_acknowledgements']},
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
    return dict(scope=('one partial first-step and retained simulated terminal frame, actual kernel fd'
                       if record['synthetic_support'] else 'one partial first-step and actual held late reply'),case=record['case'],domain=record['domain'],
        commands=rows,replies=replies,host_hold=proof,peer_queries=peer,preparation=preparation,
        retained_advertising_off=preparation[-1] if preparation else None,
        synthetic_support=record['synthetic_support'],
        managed_partial_case_live_acceptance=not record['synthetic_support'] and not cleanup_rejected,
        managed_partial_case_synthetic_support_acceptance=record['synthetic_support'] and not cleanup_rejected,
        expected_model_cleanup_refusal_observed=cleanup_rejected,
        full_cleanup_acceptance=False,active_ready_peer_isolation_acceptance=False,
        automatic_fault_recovery_acceptance=False,natural_fault_root_cause_closed=False)


def run(args):
    synthetic=getattr(args,'synthetic_support',False)
    cmdline=Path('/proc/cmdline').read_text().split()
    if type(synthetic) is not bool or synthetic!=('ws73.managed_partial_support=1' in cmdline):
        raise ValueError('matching explicit model boot and collector required')
    if synthetic and (Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU' or not Path('/scratch-root-uuid').is_file()):
        raise ValueError('model support requires dedicated QEMU scratch VM')
    if 'ws73.managed_partial=1' not in Path('/proc/cmdline').read_text().split() or os.geteuid()!=0:
        raise ValueError('explicit root scratch VM gate required')
    if subprocess.run(['/bin/pidof','slkd'],capture_output=True).returncode==0:
        raise ValueError('partial gate requires untouched Setup before daemon')
    folder=args.output; folder.mkdir(parents=True,exist_ok=False)
    record=dict(format_version=3,status='STARTING',case=args.case,domain=args.domain,preparation=[],synthetic_support=synthetic,
        physical_acceptance=False,automatic_fault_recovery_acceptance=False,
        daemon_running_during_hold=False,hold_acknowledgements=[],markers=[],peer_queries=[])
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
        record['hold_acknowledgements'].append(response);save()
    handles=[];alias=None;observers=[];peer_probe=None
    try:
        snapshots=[];record['initial_snapshots']=[]
        for i in [0,1]:
            deadline=time.monotonic()+90
            while True:
                adapter=None
                try:
                    adapter=NativeAdapter(i);snapshot=adapter.snapshot();setup(bytes(snapshot).hex(),i);break
                except OSError as error:
                    if not synthetic or error.errno not in (errno.ENODEV,errno.EAGAIN):raise
                    if adapter is not None:adapter.close()
                if time.monotonic()>deadline:raise TimeoutError('independent model Setup availability')
                time.sleep(.01)
            observers.append(adapter);handles.append(adapter);snapshots.append(snapshot)
            record['initial_snapshots'].append(bytes(snapshot).hex());save()
            if synthetic and i==0:write_marker(folder/'metadata-0.json',dict(slot=0,initial_snapshot=bytes(snapshot).hex()))
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
        peer_probe=peer_query
        peer_query(1)
        lease=target.acquire_management(1);original=target.fileno()
        if args.domain=='scanning':
            # ScanInitializeOff contains a real START. Its admission requires
            # confirmed advertising Off and no pending advertising operation.
            # Never manufacture Off from the untouched Setup snapshot.
            preparation=standby(snapshots[0],2,'advertising')
            row=dict(input=bytes(preparation).hex(),start_wall_ns=time.time_ns())
            record['preparation'].append(row);save()
            target.submit_discovery(preparation);deadline=time.monotonic()+6
            while True:
                result=observers[0].discovery_result(2)
                if result is not None and result.is_terminal:break
                if time.monotonic()>deadline:raise TimeoutError('advertising Off preparation')
                time.sleep(.002)
            row.update(result=bytes(result).hex(),end_wall_ns=time.time_ns());save()
            # Validate before arming any hold or submitting the scan recipe.
            verify_preparation(dict(record,markers=[dict(wall_ns=time.time_ns())]),snapshots[0])
        if args.case=='dup':alias=os.dup(original)
        record.update(original_fd=original,duplicate_fd=alias if alias is not None else -1,lease=lease)
        stage('arm_ready','armed')
        command=standby(snapshots[0],1,args.domain);record['input']=bytes(command).hex()
        record['submit_before_wall_ns']=time.time_ns();target.submit_discovery(command);record['submit_after_wall_ns']=time.time_ns();save()
        stage('wait_held','held')
        pending=observers[0].discovery_result(1);record['pending']=bytes(pending).hex();save()
        expected=0xc02 if args.domain=='advertising' else 0x1001
        if pending.state!=2 or pending.opcode!=expected or pending.step or pending.status or pending.error or pending.radio_adv!=(1 if args.domain=='scanning' else 0) or pending.radio_scan:
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
        record['status']='MANAGED_PARTIAL_HELD_REPLY_SYNTHETIC_SUPPORT_PASS' if synthetic else 'MANAGED_PARTIAL_HELD_REPLY_PASS'
        verify_records(record);save()
        print('WS73_TARGET_MANAGED_PARTIAL_SYNTHETIC_SUPPORT_PASS' if synthetic else 'WS73_TARGET_MANAGED_PARTIAL_PASS',flush=True)
    except BaseException as e:
        record.update(status='FAIL',error=str(e),error_type=type(e).__name__,errno=getattr(e,'errno',None));save()
        # Preserve the target error even if its registration disappeared. A
        # separate peer probe is still valuable failure-isolation evidence;
        # its outcome must never turn this failed target case into a pass.
        if peer_probe is not None:
            failure_peer={}
            for key,read in [('snapshot',observers[1].snapshot),('management',observers[1].management_status)]:
                try:failure_peer[key]=bytes(read()).hex()
                except Exception as peer_error:failure_peer[key+'_error']=str(peer_error)
            if len(record['peer_queries'])==2:
                try:peer_probe(3)
                except Exception as peer_error:failure_peer['query_error']=str(peer_error)
            record['failure_peer_observation']=failure_peer;save()
        raise
    finally:
        if alias is not None:os.close(alias)
        for a in reversed(handles):a.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',choices=['release','close','dup'],required=True)
    p.add_argument('--domain',choices=['advertising','scanning'],required=True)
    p.add_argument('--synthetic-support',action='store_true',help='dedicated simulated USB VM only; never physical qualification')
    run(p.parse_args())
