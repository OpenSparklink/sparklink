#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""VM-only real Native volatile setup/File probe; no transport or wire Engine."""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import time

from ws73_diagnostic_hold import write_marker, corroborate_host_hold
from ws73_north_star import file_record, registration
from ws73_runtime_address import decode_query
from ws73_capture import command_reply, CaptureError

CASES=('release','close','dup','deadline')


def setter_complete(data):
    # Filter the existing seam observation only; its credit byte is not an
    # authorization and raw USB/QMP corroboration remains independent.
    return len(data)==9 and data[:7]==bytes.fromhex('a2020004000504') and data[8]==0


def late_ingress(record):
    """Current-generation native RX observation,not callback/worker drain."""
    from sparklink.structs import SleSnoopRecord
    from ws73_management_setup import decode
    owner=record['owners'][0];last=record['snoop_base_seq'];found=[]
    if type(last)is not int or last<0:raise CaptureError('typed trace base cursor required')
    for raw in record['late_trace']:
        item=decode(SleSnoopRecord,raw)
        if (item.generation!=owner['generation']or item.dev_index!=owner['index']or item.seq!=last+1
                or item.lost or item.flags or item.status or item.profile!=1 or item.format!=1
                or item.direction not in (1,2)or item.original_length!=item.captured_length):
            raise CaptureError('complete current-generation contiguous Native seam trace required')
        last=item.seq;data=bytes(item.payload[:item.captured_length])
        if item.direction==1 and setter_complete(data):found.append(item)
    if len(found)!=1 or record['late_trace'][-1]!=record['late_reply_trace']:
        raise CaptureError('one actual late setter ingress required before metadata recheck')
    return found[0]


def verify_records(r):
    """Actual syscall bytes only; raw USB/QMP association remains mandatory."""
    from sparklink.structs import SleControllerSnapshot, SleManagementQuery
    from ws73_management_setup import decode, setup
    from ws73_diagnostic_cancel import result as expected_result
    from ws73_management_ready_peer import verify_row, ready_bytes
    if (type(r.get('version'))is not int or r.get('version')!=1 or r.get('status')!='RUNTIME_ADDRESS_FILE_PENDING_RAW_CORROBORATION'
            or r.get('case')not in CASES or r.get('runtime_only')is not True
            or any(r.get(k)is not False for k in ['official_identity','daemon_running',
                'automatic_recovery_acceptance','whole_lifecycle_acceptance','peer_business_delivery_acceptance'])
            or type(r.get('probe_exit'))is not int or r['probe_exit']!=0 or type(r.get('uid'))is not int or r['uid']!=0):
        raise CaptureError('explicit bounded Native address File scope required')
    owners=r['owners']
    if len(owners)!=2 or [x['index']for x in owners]!=[0,1]or owners[0]['generation']==owners[1]['generation']:
        raise CaptureError('two independent original controller registrations required')
    snapshots=[setup(raw,i,owners[i]['generation'])for i,raw in enumerate(r['initial_snapshots'])]
    if len(snapshots)!=2:raise CaptureError('two initial snapshots required')
    target,peer=snapshots;g=target.generation;kind=r['case'];timeout=500 if kind=='deadline'else 5000
    if type(r['timeout_ms'])is not int or r['timeout_ms']!=timeout or r['probe_command'][1:]!=['0',str(g),kind,'a67b7310e001',str(timeout)]:
        raise CaptureError('exact probe invocation and original deadline required')
    expected=['owner','initialized','admitted','pending-result','held']
    if kind=='dup':expected+=['dup-first-close-result','dup-first-close']
    if kind=='deadline':expected+=['expired-result']
    expected+=['before-fault-assert','withdrawn']+(['late-result']if kind=='deadline'else[])+['after-late-reply']
    if [e.get('stage')for e in r['events']]!=expected:raise CaptureError('missing/extra probe syscall stages')
    events={e['stage']:e for e in r['events']};admitted=events['admitted']
    first=events['before-fault-assert']
    for start,end in [('start_wall_ns','wall_ns'),('start_monotonic_ns','monotonic_ns')]:
        if any(type(first.get(k))is not int or first[k]<=0 for k in (start,end))or first[start]>first[end]:
            raise CaptureError('original first snapshot syscall clock interval required')
    decode(SleControllerSnapshot,first['snapshot'])
    if first['snapshot']!=events['withdrawn']['snapshot']:
        raise CaptureError('later snapshot cannot replace original failed-assert operands')
    late_ingress(r)
    if not r['markers'][2]['wall_ns']<r['late_trace_observed_wall_ns']<events['after-late-reply']['wall_ns']:
        raise CaptureError('actual late Native ingress must precede final metadata query')
    author=events['owner']
    if (type(author['writer_fd'])is not int or author['writer_fd']<0
            or type(author['duplicate_fd'])is not int
            or (kind=='dup' and (author['duplicate_fd']<0 or author['duplicate_fd']==author['writer_fd']))
            or (kind!='dup' and author['duplicate_fd']!=-1)):
        raise CaptureError('actual distinct File/dup descriptor records required')
    lease=bytes.fromhex(author['lease'])
    if len(lease)!=32:raise CaptureError('complete original management acquisition required')
    lg,token,version,mode,flags,reserved=struct.unpack('<QQIIII',lease)
    if (lg,version,mode,flags,reserved)!=(g,1,2,0,0)or not token:raise CaptureError('original Diagnostic lease required')
    previous=0
    for row in r['events']:
        if row['stage']=='owner':continue
        key='start_wall_ns'if row['stage']in ('admitted','before-fault-assert')else'wall_ns'
        if type(row[key])is not int or row[key]<=previous:raise CaptureError('ordered typed syscall evidence clocks required')
        previous=row[key]
        if row['stage']=='admitted':
            if type(row['end_wall_ns'])is not int or not row[key]<=row['end_wall_ns']:raise CaptureError('admission clock interval required')
            previous=row['end_wall_ns']
        elif row['stage']=='before-fault-assert':previous=row['wall_ns']
    if len(bytes.fromhex(admitted['input']))!=48 or len(bytes.fromhex(admitted['output']))!=48:
        raise CaptureError('actual 48-byte UAPI address submit required')
    output=struct.unpack('<IIQQIII6s6s',bytes.fromhex(admitted['output']));seq=output[5]
    if type(seq)is not int or not seq:raise CaptureError('nonzero original admission sequence required')
    fields=(1,0,g,1,timeout,0,1,bytes.fromhex('a67b7310e001'),bytes(6))
    if admitted['input']!=struct.pack('<IIQQIII6s6s',*fields).hex() or output!=fields[:5]+(seq,)+fields[6:] or admitted['retry_output']!=admitted['output']:
        raise CaptureError('exact admission/retry fields required')
    pending=expected_result(g,seq,0x0405,1)
    if events['pending-result']['result']!=pending:raise CaptureError('real setter Pending result required')
    if kind=='dup' and events['dup-first-close-result']['result']!=pending:raise CaptureError('first dup close prematurely ended author')
    if kind=='deadline':
        failed=expected_result(g,seq,0x0405,3,-errno.ETIMEDOUT)
        if events['expired-result']['result']!=failed or events['late-result']['result']!=failed:
            raise CaptureError('late physical reply changed original timeout result')
        elapsed=events['expired-result']['wall_ns']-admitted['start_wall_ns']
        if not timeout*1_000_000<=elapsed<(timeout+1500)*1_000_000:raise CaptureError('original timeout not observed')
    for stage in ['initialized','held','withdrawn','after-late-reply']+(['dup-first-close']if kind=='dup'else[]):
        row=events[stage];s=decode(SleControllerSnapshot,row['snapshot']);q=decode(SleManagementQuery,row['management'])
        wanted=SleControllerSnapshot.from_buffer_copy(bytes(target));wanted.command_credits=1 if stage=='initialized'else 0
        if stage!='initialized':wanted.valid_fields=0
        if stage in ['withdrawn','after-late-reply']:wanted.flags=4;wanted.error=-errno.ETIMEDOUT if kind=='deadline'else -errno.EIO
        if bytes(s)!=bytes(wanted):raise CaptureError('unverified or quarantined metadata gained qualification')
        fault=stage in ['withdrawn','after-late-reply']and kind!='deadline'
        expected_q=SleManagementQuery(version=1,generation=g,state=3 if fault else 1,mode=0 if fault else 2,error=-errno.EIO if fault else 0)
        if bytes(q)!=bytes(expected_q):raise CaptureError('quarantined File cannot report Free or retain author authority')
    ready=r['ready_peer']
    if r['peer_after']!=ready['ready_snapshot']or ready['ready_snapshot']!=ready_bytes(peer):raise CaptureError('peer Ready identity changed')
    held=bytes(SleManagementQuery(version=1,generation=peer.generation,state=1,mode=1)).hex()
    if r['peer_management_before']!=held or r['peer_management_after']!=held:raise CaptureError('peer lease changed')
    if ready['released_management']!=bytes(SleManagementQuery(version=1,generation=peer.generation)).hex():raise CaptureError('peer cleanup failed')
    groups=[('bootstrap',[(101,5),(102,6)]),('before',[(201,3),(202,4)]),('during',[(203,3)]),('after',[(204,4),(205,3),(206,4)])]
    for phase,operations in groups:
        if len(ready[phase])!=len(operations):raise CaptureError('peer activity phase missing')
        for row,(identifier,operation)in zip(ready[phase],operations):verify_row(row,peer,identifier,operation)
    if not r['markers'][1]['wall_ns']<ready['during'][0]['start_wall_ns']<ready['during'][0]['end_wall_ns']<r['withdraw_before_wall_ns']:
        raise CaptureError('peer actual START must finish during target hold')
    for key in ['on_before_cancel','on_after_quarantine']:
        observation=ready[key]
        if observation['snapshot']!=ready['ready_snapshot']or observation['management']!=held or observation['result']!=ready['during'][0]['result']:
            raise CaptureError('peer On/Ready changed across target quarantine')
    if not (ready['during'][0]['end_wall_ns']<ready['on_before_cancel']['wall_ns']<r['withdraw_before_wall_ns']
            and events['after-late-reply']['wall_ns']<r['after_reply_wall_ns']<ready['on_after_quarantine']['wall_ns']<ready['after'][0]['start_wall_ns']):
        raise CaptureError('peer On observations must bracket withdrawal and actual late ingress')
    return snapshots


def corroborate(r,hold,capture,stderr,host_identity):
    from ws73_management_ready_peer import corroborate_activity_rows
    snapshots=verify_records(r);owner=r['owners'][0];events={e['stage']:e for e in r['events']}
    admitted=events['admitted'];end=events['after-late-reply']['wall_ns']
    proof=command_reply(capture,owner,0x0405,admitted['start_wall_ns'],end,bytes.fromhex('a67b7310e001'),'')
    if proof['reply']['wall_ns']<=r['withdraw_after_wall_ns']:raise CaptureError('actual old reply did not arrive after withdrawal/timeout')
    if not events['withdrawn']['wall_ns']<r['markers'][2]['wall_ns']<proof['reply']['wall_ns']:
        raise CaptureError('quarantine/release/actual old reply timeline mismatch')
    commands=[v for v in capture['commands']if(v['bus'],v['device'])==(owner['bus'],owner['device'])and admitted['start_wall_ns']<=v['wall_ns']<=end]
    if commands!=[proof['command']]:raise CaptureError('replay/close emitted another command or setter')
    original=[]
    for target,row in zip(r['owners'],r['original_queries']):
        value=decode_query(row,target)
        original.append(command_reply(capture,target,0x0406,row['start_wall_ns'],row['end_wall_ns'],b'',value))
    guest=dict(records=r['markers'],host_hold_acknowledgements=r['hold_acknowledgements'])
    held=corroborate_host_hold(hold,guest,[],stderr,host_identity,held_reply=proof['reply'])
    peer=corroborate_activity_rows(r['ready_peer'],snapshots[1],capture,r['owners'][1])
    return dict(status='SCOPED_ACTUAL_ADDRESS_FILE_QUARANTINE_CORROBORATED',case=r['case'],original_queries=original,
        setter=proof,actual_host_hold=held,peer_wire=peer,peer_ready_control_isolation=True,
        peer_business_delivery_acceptance=False,whole_lifecycle_acceptance=False,automatic_recovery_acceptance=False,
        scope='Root Native File/actuallate0405/metadataquarantine;active Ready peer control only,not peerbusiness,refdrain,naturalrecovery orwholeaddressqualification')


def run(args):
    from sparklink.native import NativeAdapter
    from ws73_lab_resources import observe_guest_hcc
    from ws73_management_ready_peer import ReadyPeer
    words=Path('/proc/cmdline').read_text().split()
    if (os.geteuid()!=0 or Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU'
            or words.count('ws73.runtime_address_lifecycle=1')!=1
            or subprocess.run(['/bin/pidof','slkd'],capture_output=True).returncode==0):
        raise ValueError('explicit pre-daemon QEMU runtime address gate required')
    if args.case not in CASES or args.address!='A6:7B:73:10:E0:01':
        raise ValueError('explicit original E slot0 experiment required;no address allocation')
    folder=args.output;folder.mkdir(parents=True,exist_ok=False)
    r=dict(version=1,status='RUNNING_NOT_QUALIFIED',case=args.case,
        runtime_only=True,official_identity=False,daemon_running=False,
        automatic_recovery_acceptance=False,whole_lifecycle_acceptance=False,
        peer_business_delivery_acceptance=False,markers=[],hold_acknowledgements=[],
        owners=[],original_queries=[],events=[],peer_queries=[],
        sources=[file_record(Path(__file__)),file_record(args.probe)],uid=os.geteuid())
    def save(): (folder/'run.json').write_text(json.dumps(r,indent=2)+'\n')
    def stage(phase,ack):
        row=dict(hold_phase=phase,wall_ns=time.time_ns());r['markers'].append(row);save()
        write_marker(folder/f'hold-{phase}.json',row);deadline=time.monotonic()+6
        path=folder/f'hold-{ack}-ack.json'
        while not path.exists():
            if time.monotonic()>=deadline:raise TimeoutError('actual original hold handshake')
            time.sleep(.002)
        response=json.loads(path.read_text())
        if response['stage']!=ack or response['request']!=row:raise ValueError('wrong original hold acknowledgment')
        r['hold_acknowledgements'].append(response);save()
    process=None;handles=[];buffer=bytearray()
    def event(expected):
        deadline=time.monotonic()+7
        while b'\n'not in buffer:
            if time.monotonic()>=deadline:raise TimeoutError('bounded actual probe output')
            if select.select([process.stdout],[],[],.02)[0]:
                chunk=os.read(process.stdout.fileno(),4096)
                if not chunk:raise ValueError('actual probe exited before '+expected)
                buffer.extend(chunk)
                if len(buffer)>32768:raise ValueError('probe output budget exceeded')
        line,_,tail=buffer.partition(b'\n');buffer[:]=tail
        row=json.loads(line);r['events'].append(row);save()
        if row.get('stage')!=expected:raise ValueError('expected original probe stage '+expected)
        return row
    def send(value):process.stdin.write((value+'\n').encode());process.stdin.flush()
    try:
        for slot in range(2):
            deadline=time.monotonic()+90
            while True:
                try:owner=observe_guest_hcc(registration(f'1-{slot+1}'),'E');break
                except (OSError,ValueError):
                    if time.monotonic()>=deadline:raise
                    time.sleep(.1)
            r['owners'].append(owner);save();print(f'WS73_ADDRESS_LIFECYCLE_SETUP: slot={slot}',flush=True)
        for owner in r['owners']:
            command=['/bin/slkconfig','--adapter',str(owner['index']),'--generation',str(owner['generation']),'query','mac']
            row=dict(args=command,start_wall_ns=time.time_ns());r['original_queries'].append(row);save()
            result=subprocess.run(command,text=True,capture_output=True,timeout=7)
            row.update(exit=result.returncode,stdout=result.stdout,stderr=result.stderr,end_wall_ns=time.time_ns())
            row['value']=decode_query(row,owner);save()
        if r['original_queries'][0]['value']==args.address.replace(':','').lower():raise ValueError('already configured;not a new mutation')
        observers=[NativeAdapter(i,r['owners'][i]['generation'])for i in range(2)];handles.extend(observers)
        r['initial_snapshots']=[bytes(x.snapshot()).hex()for x in observers];save()
        peer=NativeAdapter(1,r['owners'][1]['generation']);handles.append(peer);peer_lease=peer.acquire_management(1)
        ready=ReadyPeer(peer,observers[1],observers[1].snapshot(),r,save)
        ready.phase(1);r['peer_management_before']=bytes(observers[1].management_status()).hex();save()
        timeout=500 if args.case=='deadline' else 5000
        cmd=[str(args.probe),'0',str(r['owners'][0]['generation']),args.case,args.address.replace(':','').lower(),str(timeout)]
        r['probe_command']=cmd;r['timeout_ms']=timeout;r['child_start_wall_ns']=time.time_ns();save()
        with (folder/'probe-stderr.log').open('wb')as errors:
            process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors)
            event('owner');event('initialized')
            trace=NativeAdapter(0,r['owners'][0]['generation']);handles.append(trace)
            r['trace_prefix']=[];r['snoop_base_seq']=0
            while True:
                observed=trace.poll_snoop()
                if observed is None:break
                r['trace_prefix'].append(bytes(observed).hex());r['snoop_base_seq']=observed.seq
                if len(r['trace_prefix'])>64:raise ValueError('trace prefix budget exceeded')
            save();stage('arm_ready','armed');send('submit');event('admitted')
            stage('wait_held','held');send('held');event('pending-result');event('held')
            ready.phase(2);r['withdraw_before_wall_ns']=time.time_ns();save();send('withdraw')
            if args.case=='dup':event('dup-first-close-result');event('dup-first-close')
            if args.case=='deadline':event('expired-result')
            event('before-fault-assert')
            event('withdrawn');r['withdraw_after_wall_ns']=time.time_ns();save()
            stage('release_ready','released')
            # An acknowledgement that QEMU released a frame does not prove the
            # guest has received it. Wait on the existing independent native
            # seam trace before requesting the final snapshot. This is neither
            # a fixed sleep nor proof of callback/worker/reference drain.
            r['late_trace']=[];deadline=time.monotonic()+2
            while True:
                observed=trace.poll_snoop()
                if observed is None:
                    if time.monotonic()>=deadline:raise TimeoutError('original late Native RX ingress')
                    time.sleep(.001);continue
                raw=bytes(observed).hex();r['late_trace'].append(raw);save()
                if len(r['late_trace'])>64:raise ValueError('late trace budget exceeded')
                data=bytes(observed.payload[:observed.captured_length])
                if observed.direction==1 and setter_complete(data):
                    r['late_reply_trace']=raw;r['late_trace_observed_wall_ns']=time.time_ns();save();break
            late_ingress(r);send('released')
            if args.case=='deadline':event('late-result')
            event('after-late-reply');r['probe_exit']=process.wait(timeout=3)
            if buffer or process.stdout.read(1)or r['probe_exit']:raise ValueError('unexpected original probe output/exit')
        if (folder/'probe-stderr.log').read_bytes():raise ValueError('probe stderr is not empty')
        r['after_reply_wall_ns']=time.time_ns();ready.observe_on('on_after_quarantine')
        for identifier,operation in [(204,4),(205,3),(206,4)]:ready.perform('after',identifier,operation)
        r['peer_after']=bytes(observers[1].snapshot()).hex();r['peer_management_after']=bytes(observers[1].management_status()).hex()
        peer.release_management(peer_lease,1);r['ready_peer']['released_management']=bytes(observers[1].management_status()).hex()
        r['status']='RUNTIME_ADDRESS_FILE_PENDING_RAW_CORROBORATION';save()
        print('WS73_ADDRESS_LIFECYCLE_PROBE_DONE',flush=True)
    except BaseException as error:
        r.update(status='FAIL',error=type(error).__name__+': '+str(error));save();raise
    finally:
        if process is not None and process.poll()is None:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for handle in handles:handle.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=CASES,required=True)
    parser.add_argument('--address',required=True)
    parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args())
