#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Ordinary D-Bus callers supersede an actual held reply while slkd stays live."""
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

from ws73_diagnostic_hold import HoldCoordinator, write_marker, corroborate_host_hold
from ws73_north_star import daemon_identity, ordinary_identity, parse_result, stable


class DaemonHoldCoordinator(HoldCoordinator):
    def __init__(self, share, record):
        super().__init__(share,record)
        self.folder=Path(share)/'application/recovery-control/daemon-hold'


class Invocation:
    """Read live pipes, never a redirected producer file; reap before sealing."""
    def __init__(self, args, toggle):
        self.row=dict(args=args,toggle=toggle,start_wall_ns=time.time_ns())
        self.process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.row['pid']=self.process.pid
        self.prefix=b''

    def identifier(self):
        deadline=time.monotonic()+2
        with selectors.DefaultSelector() as watch:
            watch.register(self.process.stdout,selectors.EVENT_READ)
            while time.monotonic()<deadline:
                for key,_ in watch.select(.005):
                    data=os.read(key.fileobj.fileno(),4096)
                    if not data:raise ValueError('caller ended before actual scan request marker')
                    self.prefix+=data
                    pattern = (rb'^NativePoliciesCancelRequest: generation=(\d+)\n' if self.row['toggle']=='cancel' else rb'^NativeScanRequest: request=(\d+) enable='+self.row['toggle'].encode()+rb'\n')
                    matches=re.findall(pattern,self.prefix,re.M)
                    if len(matches)==1:
                        identifier=int(matches[0])
                        if not identifier:raise ValueError('nonzero actual caller request required')
                        self.row['generation' if self.row['toggle']=='cancel' else 'request_id']=identifier
                        self.row['marker_wall_ns']=time.time_ns()
                        return identifier
                    if len(matches)>1:raise ValueError('duplicate actual scan request marker')
                if self.process.poll() is not None:raise ValueError('caller failed before actual request marker')
        raise TimeoutError('bounded actual scan request marker')

    def finish(self, kill=False):
        if kill:
            self.row['kill_wall_ns']=time.time_ns()
            self.process.kill()
        try:
            out,err=self.process.communicate(timeout=3)
        except BaseException:
            if self.process.poll() is None:self.process.kill()
            out,err=self.process.communicate()
            self.row.update(stdout=(self.prefix+out).decode(),stderr=err.decode(),exit=self.process.returncode,end_wall_ns=time.time_ns())
            raise
        self.row.update(stdout=(self.prefix+out).decode(),stderr=err.decode(),exit=self.process.returncode,end_wall_ns=time.time_ns())
        return self.row


PATTERN=(r'^NativeOperationResult: generation=(\d+) request=(\d+) operation=(\d+) state=(\d+) errno=(-?\d+) status=0x([0-9a-f]{2}) '
         r'opcode=0x([0-9a-f]{4}) step=(\d+)/(\d+) power=(-?\d+) power_valid=(\d+) adv=(\d+) scan=(\d+) profile=(\d+)$')


def observed(row,owner,identifier,operation,state,opcode,step,count,scan=1):
    matches=re.findall(PATTERN,row['stdout'],re.M)
    error=-125 if state==5 else 0
    expected=[owner['generation'],identifier,operation,state,error,0,opcode,step,count,0,0,1,scan,1]
    if len(matches)!=1 or row['stdout'].count('NativeOperationResult:')!=1:
        raise ValueError('one complete original operation observation required')
    values=[int(v,16 if i in [5,6] else 10) for i,v in enumerate(matches[0])]
    if values!=expected or type(row['exit']) is not int or (row['exit']==0)!=(state!=5):
        raise ValueError('actual generation/result state/errno/opcode must remain exact')


def execute(run,a,b,case):
    if case not in ['supersede','caller-exit']:raise ValueError('explicit daemon caller case required')
    folder=run.output/'daemon-hold';folder.mkdir(exist_ok=False)
    r=dict(format_version=2,status='RUNNING',case=case,target=a,peer=b,markers=[],hold_acknowledgements=[],
        application_identity=ordinary_identity(),daemon_before=daemon_identity(run.args.slkd_pid),
        bus_before=run.bus_identity(),cancel_polls=[],physical_acceptance=False,automatic_fault_recovery_acceptance=False)
    run.data['daemon_hold']=r;run.save()
    def stage(phase,ack):
        marker=dict(hold_phase=phase,wall_ns=time.time_ns());r['markers'].append(marker);run.save()
        write_marker(folder/f'hold-{phase}.json',marker)
        deadline=time.monotonic()+6
        while not (folder/f'hold-{ack}-ack.json').exists():
            run.alive()
            if time.monotonic()>deadline:raise TimeoutError('actual daemon host hold acknowledgement')
            time.sleep(.002)
        value=__import__('json').loads((folder/f'hold-{ack}-ack.json').read_text())
        if value['stage']!=ack or value['request']!=marker:raise ValueError('wrong actual host acknowledgement')
        r['hold_acknowledgements'].append(value);run.save()
    def query(identifier,key):
        value=run.command([str(run.args.slctl),'--adapter',a['path'],'result',str(identifier)],3,field='daemon_hold_query')
        r[key]=value;run.save();return value
    callers=[]
    try:
        stage('arm_ready','armed')
        original=Invocation([str(run.args.slctl),'--adapter',a['path'],'scan','on'],'on');callers.append(original)
        r['original_caller']=original.row;old=original.identifier();run.save()
        stage('wait_held','held')
        observed(query(old,'pending'),a,old,3,2,0x1001,0,2)
        if case=='caller-exit':
            original.finish(kill=True);run.save()
            observed(query(old,'after_caller_exit'),a,old,3,2,0x1001,0,2)
        peer=run.command([str(run.args.slctl),'--adapter',b['path'],'scan','on'],3,field='daemon_hold_peer_start')
        parse_result(peer['stdout'],b,3);r['peer_start']=peer;run.save()
        replacement=Invocation([str(run.args.slctl),'--adapter',a['path'],'cancel-discovery'],'cancel');callers.append(replacement)
        r['cancel_caller']=replacement.row
        if replacement.identifier()!=a['generation']:raise ValueError('cancel caller selected wrong generation')
        run.save()
        deadline=time.monotonic()+.1
        while True:
            value=query(old,'cancelled');r['cancel_polls'].append(value);run.save()
            try:observed(value,a,old,3,5,0x1001,0,2);break
            except ValueError:
                if time.monotonic()>deadline:raise
                time.sleep(.001)
        if case=='supersede':original.finish();run.save()
        r['replacement_pending_before_release']=replacement.process.poll() is None
        if r['replacement_pending_before_release'] is not True:raise ValueError('replacement CLI completed before original reply drain')
        r['cancel_observed_wall_ns']=time.time_ns();run.save()
        stage('release_ready','released')
        replacement.finish();run.save()
        if replacement.row['exit']:raise ValueError('actual Managed policy cancellation/reacquisition failed')
        observed(query(old,'after_drain'),a,old,3,5,0x1001,0,2)
        r['peer_on_after_drain']=run.command([str(run.args.slctl),'--adapter',b['path'],'result',str(parse_result(peer['stdout'],b,3)['request'])],3,field='daemon_hold_peer_on')
        parse_result(r['peer_on_after_drain']['stdout'],b,3)
        peer_stop=run.command([str(run.args.slctl),'--adapter',b['path'],'scan','off'],3,field='daemon_hold_peer_stop')
        parse_result(peer_stop['stdout'],b,4);r['peer_stop']=peer_stop
        r['target_after']=run.ready(a['port']);r['peer_after']=run.ready(b['port'])
        if not stable(a,r['target_after']) or not stable(b,r['peer_after']):raise ValueError('held cancellation changed registration')
        r['daemon_after']=daemon_identity(run.args.slkd_pid);r['bus_after']=run.bus_identity()
        r['status']='DAEMON_HELD_REPLY_CANCEL_EVIDENCE_PENDING';verify_records(r);run.save()
    except BaseException as error:
        r.update(status='FAIL',error=str(error),error_type=type(error).__name__);run.save();raise
    finally:
        for caller in callers:
            if caller.process.poll() is None:
                caller.finish(kill=True)
        run.save()


def verify_records(r):
    if (type(r.get('format_version')) is not int or r['format_version']!=2 or r.get('status')!='DAEMON_HELD_REPLY_CANCEL_EVIDENCE_PENDING'
            or r.get('case') not in ['supersede','caller-exit'] or r.get('physical_acceptance') is not False or r.get('automatic_fault_recovery_acceptance') is not False):
        raise ValueError('explicit limited daemon original held reply case required')
    a,b=r['target'],r['peer']
    if a['generation']==b['generation'] or a['path']==b['path'] or a['address']==b['address'] or a['port']==b['port']:
        raise ValueError('two independent daemon registrations required')
    app=r['application_identity']
    if len(app['uids'])!=4 or app['uids'][0]!=1000 or len(set(app['uids']))!=1 or any(int(app[k],16) for k in ['cap_eff','cap_prm','cap_amb']):
        raise ValueError('ordinary UID1000 and zero capabilities required')
    if r['daemon_before']!=r['daemon_after'] or r['bus_before']!=r['bus_after'] or r['bus_before']['pid']!=r['daemon_before']['pid']:
        raise ValueError('same running daemon and authenticated bus required')
    if not stable(a,r['target_after']) or not stable(b,r['peer_after']):raise ValueError('same Ready registrations required')
    original,cancel=r['original_caller'],r['cancel_caller'];old=original['request_id']
    if type(old) is not int or not old or original['pid']==cancel['pid'] or cancel['generation']!=a['generation']:
        raise ValueError('distinct actual CLI processes and selected generation required')
    prefix=[original['args'][0],'--adapter',a['path']]
    if original['args']!=prefix+['scan','on'] or cancel['args']!=prefix+['cancel-discovery'] or original['toggle']!='on' or cancel['toggle']!='cancel':
        raise ValueError('actual original CLI and explicit policy cancellation required')
    if len(re.findall(r'^NativeScanRequest: request='+str(old)+' enable=on$',original['stdout'],re.M))!=1:
        raise ValueError('actual original request marker required')
    if (cancel['exit'] or cancel['stdout'].count('NativePoliciesCancelRequest:')!=1 or cancel['stdout'].count('NativePoliciesCancelled:')!=1
            or re.findall(r'^NativePoliciesCancelRequest: generation=(\d+)$',cancel['stdout'],re.M)!=[str(a['generation'])]
            or re.findall(r'^NativePoliciesCancelled: generation=(\d+)$',cancel['stdout'],re.M)!=[str(a['generation'])]
            or 'NativeOperationResult:' in cancel['stdout']):
        raise ValueError('actual bounded handoff confirmation, no invented successful operation required')
    for key,st in [('pending',2),('cancelled',5),('after_drain',5)]:
        row=r[key]
        if row['args']!=prefix+['result',str(old)]:raise ValueError('exact result query affinity required')
        observed(row,a,old,3,st,0x1001,0,2)
    markers=r['markers'];acks=r['hold_acknowledgements']
    if len(markers)!=3 or [v['hold_phase'] for v in markers]!=['arm_ready','wait_held','release_ready'] or len(acks)!=3 or [v['stage'] for v in acks]!=['armed','held','released'] or [v['request'] for v in acks]!=markers:
        raise ValueError('one original host arm/hold/release required')
    times=[markers[0]['wall_ns'],original['start_wall_ns'],original['marker_wall_ns'],markers[1]['wall_ns'],r['pending']['start_wall_ns'],r['pending']['end_wall_ns'],r['peer_start']['start_wall_ns'],r['peer_start']['end_wall_ns'],cancel['start_wall_ns'],cancel['marker_wall_ns'],r['cancelled']['start_wall_ns'],r['cancelled']['end_wall_ns'],r['cancel_observed_wall_ns'],markers[2]['wall_ns'],cancel['end_wall_ns'],r['after_drain']['start_wall_ns'],r['after_drain']['end_wall_ns'],r['peer_on_after_drain']['start_wall_ns'],r['peer_on_after_drain']['end_wall_ns'],r['peer_stop']['start_wall_ns'],r['peer_stop']['end_wall_ns']]
    if any(type(t) is not int or t<=0 for t in times) or times!=sorted(times) or markers[2]['wall_ns']-original['start_wall_ns']>=400_000_000:
        raise ValueError('actual causal sequence and unchanged original500ms deadline required')
    if r['case']=='caller-exit':
        row=r['after_caller_exit'];observed(row,a,old,3,2,0x1001,0,2)
        if original['exit']!=-signal.SIGKILL or not r['pending']['end_wall_ns']<original['kill_wall_ns']<=original['end_wall_ns']<row['start_wall_ns']<=row['end_wall_ns']<r['peer_start']['start_wall_ns']:
            raise ValueError('caller actually exits; admitted operation remains pending before explicit policy cancellation')
    else:
        if 'after_caller_exit' in r or 'kill_wall_ns' in original or not r['cancelled']['end_wall_ns']<=original['end_wall_ns']<markers[2]['wall_ns']:
            raise ValueError('connected original caller must return cancellation while original frame is held')
        observed(original,a,old,3,5,0x1001,0,2)
    if r.get('replacement_pending_before_release') is not True:raise ValueError('replacement caller must remain waiting on original reserved slot')
    polls=r['cancel_polls']
    if not polls or polls[-1]!=r['cancelled']:raise ValueError('complete cancellation observation history required')
    previous=cancel['marker_wall_ns']
    for n,row in enumerate(polls):
        observed(row,a,old,3,5 if n==len(polls)-1 else 2,0x1001,0,2)
        if not previous<=row['start_wall_ns']<=row['end_wall_ns']<=r['cancel_observed_wall_ns']:raise ValueError('ordered original Pending-to-Cancelled observation interval required')
        previous=row['end_wall_ns']
    peer_id=parse_result(r['peer_start']['stdout'],b,3)['request']
    if (r['peer_start']['exit'] or r['peer_on_after_drain']['exit'] or r['peer_stop']['exit']
            or r['peer_on_after_drain']['args']!=[prefix[0],'--adapter',b['path'],'result',str(peer_id)]
            or parse_result(r['peer_on_after_drain']['stdout'],b,3)['request']!=peer_id):
        raise ValueError('independent peer remains On across target cancellation/drain')
    parse_result(r['peer_stop']['stdout'],b,4)


def corroborate_wire(r,capture):
    verify_records(r)
    from ws73_capture import command_reply
    a,b=r['target'],r['peer'];start=r['original_caller']['start_wall_ns'];end=r['peer_stop']['end_wall_ns']
    target=command_reply(capture,a,0x1001,start,end,bytes.fromhex('0000010040062003'),'')
    if not target['command']['wall_ns']<r['pending']['end_wall_ns']<r['cancelled']['end_wall_ns']<r['markers'][2]['wall_ns']<=target['reply']['wall_ns']<=r['cancel_caller']['end_wall_ns']:
        raise ValueError('original successful reply must drain before actual Managed handoff confirmation')
    peer=[]
    for opcode,params in [(0x1001,bytes.fromhex('0000010040062003')),(0x1002,b'\1\0')]:
        peer.append(command_reply(capture,b,opcode,r['peer_start']['start_wall_ns'],r['peer_start']['end_wall_ns'],params,''))
    peer.append(command_reply(capture,b,0x1002,r['peer_stop']['start_wall_ns'],r['peer_stop']['end_wall_ns'],b'\0\0',''))
    if peer[0]['reply']['wall_ns']>peer[1]['command']['wall_ns']:raise ValueError('peer scan step requires original parameter Complete')
    for owner,proofs in [(a,[target]),(b,peer)]:
        for key,item in [('commands','command'),('complete','reply')]:
            rows=[v for v in capture[key] if (v['bus'],v['device'])==(owner['bus'],owner['device']) and start<=v['wall_ns']<=end]
            if rows!=[v[item] for v in proofs]:raise ValueError('extra command/START/STOP/reply or wrong device in complete daemon hold interval')
    return dict(target=[target],peer=peer)


def corroborate(r,host,capture,stderr,identity):
    wire=corroborate_wire(r,capture)
    hold=corroborate_host_hold(host,dict(records=r['markers'],host_hold_acknowledgements=r['hold_acknowledgements']),[],stderr,identity,held_reply=wire['target'][0]['reply'])
    return dict(status='DAEMON_ACTUAL_HELD_REPLY_CANCEL_CORROBORATED',case=r['case'],**wire,host_hold=hold,
        ordinary_user_daemon_held_cancel_case_acceptance=True,whole_managed_acceptance=False,automatic_fault_recovery_acceptance=False,natural_fault_root_cause_closed=False)
