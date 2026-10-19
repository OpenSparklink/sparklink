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
    def __init__(self, args, toggle, *, credentials=None, stdin=None, env=None):
        self.row=dict(args=args,toggle=toggle,start_wall_ns=time.time_ns())
        options={} if credentials is None else dict(user=credentials[0],group=credentials[1],extra_groups=[])
        if stdin is not None:options['stdin']=stdin
        if env is not None:options['env']=env
        self.process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**options)
        self.row['pid']=self.process.pid
        self.prefix=b''

    def until(self, pattern, *, timeout=2, limit=None, label='actual scan request marker'):
        deadline=time.monotonic()+timeout
        with selectors.DefaultSelector() as watch:
            watch.register(self.process.stdout,selectors.EVENT_READ)
            while time.monotonic()<deadline:
                for key,_ in watch.select(.005):
                    data=os.read(key.fileobj.fileno(),4096)
                    if not data:raise ValueError('caller ended before '+label)
                    self.prefix+=data
                    if limit is not None and len(self.prefix)>limit:raise ValueError('bounded '+label+' output exceeded')
                    matches=re.findall(pattern,self.prefix,re.M)
                    if len(matches)==1:return matches[0]
                    if len(matches)>1:raise ValueError('duplicate '+label)
                if self.process.poll() is not None:raise ValueError('caller failed before '+label)
        raise TimeoutError('bounded '+label)

    def identifier(self):
        pattern = (rb'^NativePoliciesCancelRequest: generation=(\d+)\n' if self.row['toggle']=='cancel' else rb'^NativeScanRequest: request=(\d+) enable='+self.row['toggle'].encode()+rb'\n')
        identifier=int(self.until(pattern))
        if not identifier:raise ValueError('nonzero actual caller request required')
        self.row['generation' if self.row['toggle']=='cancel' else 'request_id']=identifier
        self.row['marker_wall_ns']=time.time_ns()
        return identifier

    def finish(self, kill=False, *, timeout=3):
        if kill:
            self.row['kill_wall_ns']=time.time_ns()
            self.process.kill()
        try:
            out,err=self.process.communicate(timeout=timeout)
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


MANAGEMENT_PATTERN=(r'^NativeManagementStatus: generation=(\d+) mode=(\d+) state=(\d+) flags=(\d+) errno=(-?\d+) status=0x([0-9a-f]{2}) opcode=0x([0-9a-f]{4})$')

def management_observed(row,owner,state):
    matches=re.findall(MANAGEMENT_PATTERN,row['stdout'],re.M)
    if row['exit'] or len(matches)!=1 or row['stdout'].count('NativeManagementStatus:')!=1 or 'lease=' in row['stdout']:
        raise ValueError('one actual token-free kernel management query required')
    values=[int(v,16 if i in [5,6] else 10) for i,v in enumerate(matches[0])]
    st=values[2]
    if (state is not None and state!=st) or values!=[owner['generation'],1 if st==1 else 0,st,1 if st==1 else 0,0,0,0]:
        raise ValueError('actual per-file Revoking or reacquired owned Held required')
    return st


def execute(run,a,b,case):
    if case not in ['supersede','caller-exit','cancel-caller-exit','cancel-busy','cancel-admission']:raise ValueError('explicit daemon caller case required')
    folder=run.output/'daemon-hold';folder.mkdir(exist_ok=False)
    r=dict(format_version=4 if case=='cancel-admission' else 3,status='RUNNING',case=case,target=a,peer=b,markers=[],hold_acknowledgements=[],
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
        if case!='caller-exit':original.finish();run.save()
        r['replacement_pending_before_release']=replacement.process.poll() is None
        if r['replacement_pending_before_release'] is not True:raise ValueError('replacement CLI completed before original reply drain')
        new_case=case in ['cancel-caller-exit','cancel-busy','cancel-admission']
        if new_case:
            r['management_revoking']=run.command([str(run.args.slctl),'--adapter',a['path'],'management'],3,field='daemon_hold_management')
            management_observed(r['management_revoking'],a,2)
            if case=='cancel-caller-exit':
                replacement.finish(kill=True);run.save()
                observed(query(old,'after_cancel_caller_exit'),a,old,3,5,0x1001,0,2)
                r['management_after_cancel_exit']=run.command([str(run.args.slctl),'--adapter',a['path'],'management'],3,field='daemon_hold_management')
                management_observed(r['management_after_cancel_exit'],a,2)
            else:
                r['busy_cancel']=run.command([str(run.args.slctl),'--adapter',a['path'],'cancel-discovery'],3,field='daemon_hold_busy_cancel')
                if not r['busy_cancel']['exit'] or 'device management admission or handoff busy' not in r['busy_cancel']['stderr']:
                    raise ValueError('second cancel must fail busy without starting another handoff')
                r['first_cancel_pending_after_busy']=replacement.process.poll() is None
                if not r['first_cancel_pending_after_busy']:raise ValueError('original handoff completed before release')
        if case=='cancel-admission':
            r['admission_refusals']=[]
            for words in [('advertise','on'),('advertise','off'),('scan','on'),('scan','off'),('advertise','initialized-off'),('scan','initialized-off')]:
                row=run.command([str(run.args.slctl),'--adapter',a['path'],*words],3,field='daemon_hold_admission')
                r['admission_refusals'].append(row);run.save()
                if (row['exit']!=1 or 'device management admission or handoff busy' not in row['stderr']
                        or 'NativeOperationResult:' in row['stdout'] or 'NativeAdvertisementAccepted:' in row['stdout']
                        or row['end_wall_ns']-row['start_wall_ns']>=100_000_000):
                    raise ValueError('held handoff must reject business/initializer admission promptly')
            r['still_cancelled']=query(old,'still_cancelled')
            observed(r['still_cancelled'],a,old,3,5,0x1001,0,2)
            peer_id=parse_result(peer['stdout'],b,3)['request']
            r['peer_on_during_handoff']=run.command([str(run.args.slctl),'--adapter',b['path'],'result',str(peer_id)],3,field='daemon_hold_peer_during')
            parse_result(r['peer_on_during_handoff']['stdout'],b,3)
            r['first_cancel_pending_after_admission']=replacement.process.poll() is None
            if not r['first_cancel_pending_after_admission']:raise ValueError('original handoff ended before held admission checks')
        r['cancel_observed_wall_ns']=time.time_ns();run.save()
        stage('release_ready','released')
        if case!='cancel-caller-exit':
            replacement.finish();run.save()
            if replacement.row['exit']:raise ValueError('actual Managed policy cancellation/reacquisition failed')
        if new_case:
            r['management_polls']=[];deadline=time.monotonic()+1
            while True:
                value=run.command([str(run.args.slctl),'--adapter',a['path'],'management'],3,field='daemon_hold_management')
                r['management_polls'].append(value);run.save()
                try:management_observed(value,a,1);r['management_held']=value;break
                except ValueError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.002)
        observed(query(old,'after_drain'),a,old,3,5,0x1001,0,2)
        if new_case:
            r['target_resume']=[]
            for toggle,op in [('on',3),('off',4)]:
                value=run.command([str(run.args.slctl),'--adapter',a['path'],'scan',toggle],3,field='daemon_hold_resume')
                parse_result(value['stdout'],a,op);r['target_resume'].append(value);run.save()
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
    if (type(r.get('format_version')) is not int or r['format_version'] not in [2,3,4] or r.get('status')!='DAEMON_HELD_REPLY_CANCEL_EVIDENCE_PENDING'
            or r.get('case') not in ['supersede','caller-exit','cancel-caller-exit','cancel-busy','cancel-admission'] or r.get('physical_acceptance') is not False or r.get('automatic_fault_recovery_acceptance') is not False):
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
    abandoned=r['case']=='cancel-caller-exit'
    if (cancel['stdout'].count('NativePoliciesCancelRequest:')!=1
            or re.findall(r'^NativePoliciesCancelRequest: generation=(\d+)$',cancel['stdout'],re.M)!=[str(a['generation'])]
            or 'NativeOperationResult:' in cancel['stdout']):
        raise ValueError('actual cancellation invocation, no invented operation required')
    if abandoned:
        if cancel['exit']!=-signal.SIGKILL or 'NativePoliciesCancelled:' in cancel['stdout']:
            raise ValueError('cancel CLI must actually exit before handoff confirmation')
    elif (cancel['exit'] or cancel['stdout'].count('NativePoliciesCancelled:')!=1
            or re.findall(r'^NativePoliciesCancelled: generation=(\d+)$',cancel['stdout'],re.M)!=[str(a['generation'])]):
        raise ValueError('actual bounded handoff confirmation required')
    for key,st in [('pending',2),('cancelled',5),('after_drain',5)]:
        row=r[key]
        if row['args']!=prefix+['result',str(old)]:raise ValueError('exact result query affinity required')
        observed(row,a,old,3,st,0x1001,0,2)
    markers=r['markers'];acks=r['hold_acknowledgements']
    if len(markers)!=3 or [v['hold_phase'] for v in markers]!=['arm_ready','wait_held','release_ready'] or len(acks)!=3 or [v['stage'] for v in acks]!=['armed','held','released'] or [v['request'] for v in acks]!=markers:
        raise ValueError('one original host arm/hold/release required')
    times=[markers[0]['wall_ns'],original['start_wall_ns'],original['marker_wall_ns'],markers[1]['wall_ns'],r['pending']['start_wall_ns'],r['pending']['end_wall_ns'],r['peer_start']['start_wall_ns'],r['peer_start']['end_wall_ns'],cancel['start_wall_ns'],cancel['marker_wall_ns'],r['cancelled']['start_wall_ns'],r['cancelled']['end_wall_ns'],r['cancel_observed_wall_ns'],markers[2]['wall_ns'],*([] if abandoned else [cancel['end_wall_ns']]),r['after_drain']['start_wall_ns'],r['after_drain']['end_wall_ns'],r['peer_on_after_drain']['start_wall_ns'],r['peer_on_after_drain']['end_wall_ns'],r['peer_stop']['start_wall_ns'],r['peer_stop']['end_wall_ns']]
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
    new_case=r['case'] in ['cancel-caller-exit','cancel-busy','cancel-admission']
    if new_case:
        if r['format_version']!=(4 if r['case']=='cancel-admission' else 3):raise ValueError('new handoff lifecycle schema required')
        for key,st in [('management_revoking',2),('management_held',1)]:
            management_observed(r[key],a,st)
            if r[key]['args']!=prefix+['management']:raise ValueError('management query affinity required')
        if not r['cancelled']['end_wall_ns']<=original['end_wall_ns']<=r['management_revoking']['start_wall_ns']<r['management_revoking']['end_wall_ns']<markers[2]['wall_ns']:
            raise ValueError('original caller cancellation and actual held Revoking required')
        polls=r['management_polls']
        if not polls or polls[-1]!=r['management_held']:raise ValueError('actual reacquisition observation history required')
        previous=markers[2]['wall_ns']
        for i,row in enumerate(polls):
            st=management_observed(row,a,None)
            if st not in ([1] if i==len(polls)-1 else [0,2]) or row['args']!=prefix+['management'] or not previous<=row['start_wall_ns']<=row['end_wall_ns']<=r['after_drain']['start_wall_ns']:
                raise ValueError('ordered actual Revoking/Free to owned Held observation required')
            previous=row['end_wall_ns']
        if abandoned:
            observed(r['after_cancel_caller_exit'],a,old,3,5,0x1001,0,2)
            management_observed(r['management_after_cancel_exit'],a,2)
            if r['after_cancel_caller_exit']['args']!=prefix+['result',str(old)] or r['management_after_cancel_exit']['args']!=prefix+['management']:
                raise ValueError('post-exit observation affinity required')
            if not r['management_revoking']['end_wall_ns']<cancel['kill_wall_ns']<=cancel['end_wall_ns']<r['after_cancel_caller_exit']['start_wall_ns']<=r['after_cancel_caller_exit']['end_wall_ns']<r['management_after_cancel_exit']['start_wall_ns']<=r['management_after_cancel_exit']['end_wall_ns']<=r['cancel_observed_wall_ns']:
                raise ValueError('actual cancel CLI exit while original frame remains held required')
        else:
            busy=r['busy_cancel']
            if (busy['args']!=prefix+['cancel-discovery'] or busy['exit']!=1 or 'device management admission or handoff busy' not in busy['stderr']
                    or re.findall(r'^NativePoliciesCancelRequest: generation=(\d+)$',busy['stdout'],re.M)!=[str(a['generation'])]
                    or 'NativePoliciesCancelled:' in busy['stdout'] or 'NativeOperationResult:' in busy['stdout'] or r['first_cancel_pending_after_busy'] is not True
                    or not r['management_revoking']['end_wall_ns']<=busy['start_wall_ns']<=busy['end_wall_ns']<=r['cancel_observed_wall_ns']):
                raise ValueError('second actual cancellation must fail busy while first retains reserved slot')
        if r['case']=='cancel-admission':
            rows=r['admission_refusals'];words=[('advertise','on'),('advertise','off'),('scan','on'),('scan','off'),('advertise','initialized-off'),('scan','initialized-off')]
            if len(rows)!=len(words) or r['first_cancel_pending_after_admission'] is not True:
                raise ValueError('all business and initializer refusals while handoff pending required')
            previous=r['busy_cancel']['end_wall_ns'];ids=[]
            for number,(row,arguments) in enumerate(zip(rows,words)):
                if (row['args']!=prefix+list(arguments) or row['exit']!=1 or 'device management admission or handoff busy' not in row['stderr']
                        or 'NativeOperationResult:' in row['stdout'] or 'NativeAdvertisementAccepted:' in row['stdout']
                        or not previous<=row['start_wall_ns']<=row['end_wall_ns']<=r['cancel_observed_wall_ns']
                        or row['end_wall_ns']-row['start_wall_ns']>=100_000_000):
                    raise ValueError('bounded selected RPC busy refusal without successful admission required')
                if number<4:
                    pattern=(r'^NativeAdvertisementRequest: request=(\d+) marker=[0-9a-f]{32}$' if number==0 else
                             r'^NativeStopAdvertisingRequest: request=(\d+)$' if number==1 else
                             r'^NativeScanRequest: request=(\d+) enable='+arguments[1]+r'$')
                    found=re.findall(pattern,row['stdout'],re.M)
                    if len(found)!=1 or not int(found[0]):raise ValueError('one actual business caller request marker required')
                    ids.append(int(found[0]))
                previous=row['end_wall_ns']
            if len(set(ids+[old]))!=5:raise ValueError('distinct business request IDs without old result alias required')
            row=r['still_cancelled'];observed(row,a,old,3,5,0x1001,0,2)
            if row['args']!=prefix+['result',str(old)] or not previous<=row['start_wall_ns']<=row['end_wall_ns']<=r['cancel_observed_wall_ns']:
                raise ValueError('original cancelled result remains independently observable during handoff')
            peer_id=parse_result(r['peer_start']['stdout'],b,3)['request'];peer_row=r['peer_on_during_handoff']
            if (peer_row['args']!=[prefix[0],'--adapter',b['path'],'result',str(peer_id)] or peer_row['exit']
                    or parse_result(peer_row['stdout'],b,3)['request']!=peer_id
                    or not row['end_wall_ns']<=peer_row['start_wall_ns']<=peer_row['end_wall_ns']<=r['cancel_observed_wall_ns']):
                raise ValueError('same peer remains actually On during target RPC refusals')
        previous=r['after_drain']['end_wall_ns']
        if len(r['target_resume'])!=2:raise ValueError('actual business scan restart/stop required')
        for row,(toggle,op) in zip(r['target_resume'],[('on',3),('off',4)]):
            parse_result(row['stdout'],a,op)
            if row['exit'] or row['args']!=prefix+['scan',toggle] or not previous<=row['start_wall_ns']<=row['end_wall_ns']<=r['peer_on_after_drain']['start_wall_ns']:
                raise ValueError('actual post-handoff business authority and ordering required')
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
    target=command_reply(capture,a,0x1001,start,r['after_drain']['end_wall_ns'],bytes.fromhex('0000010040062003'),'')
    if not target['command']['wall_ns']<r['pending']['end_wall_ns']<r['cancelled']['end_wall_ns']<r['markers'][2]['wall_ns']<=target['reply']['wall_ns']<=(r['management_held']['end_wall_ns'] if r['case'] in ['cancel-caller-exit','cancel-busy','cancel-admission'] else r['cancel_caller']['end_wall_ns']):
        raise ValueError('original successful reply must drain before actual Managed handoff confirmation')
    peer=[]
    for opcode,params in [(0x1001,bytes.fromhex('0000010040062003')),(0x1002,b'\1\0')]:
        peer.append(command_reply(capture,b,opcode,r['peer_start']['start_wall_ns'],r['peer_start']['end_wall_ns'],params,''))
    peer.append(command_reply(capture,b,0x1002,r['peer_stop']['start_wall_ns'],r['peer_stop']['end_wall_ns'],b'\0\0',''))
    if peer[0]['reply']['wall_ns']>peer[1]['command']['wall_ns']:raise ValueError('peer scan step requires original parameter Complete')
    target_proofs=[target]
    if r['case'] in ['cancel-caller-exit','cancel-busy','cancel-admission']:
        on,off=r['target_resume']
        for opcode,params in [(0x1001,bytes.fromhex('0000010040062003')),(0x1002,b'\1\0')]:
            target_proofs.append(command_reply(capture,a,opcode,on['start_wall_ns'],on['end_wall_ns'],params,''))
        target_proofs.append(command_reply(capture,a,0x1002,off['start_wall_ns'],off['end_wall_ns'],b'\0\0',''))
        if not target['reply']['wall_ns']<=r['management_held']['end_wall_ns']<=target_proofs[1]['command']['wall_ns']<target_proofs[1]['reply']['wall_ns']<=target_proofs[2]['command']['wall_ns']<target_proofs[2]['reply']['wall_ns']<=target_proofs[3]['command']['wall_ns']<target_proofs[3]['reply']['wall_ns']:
            raise ValueError('original drain and actual ordered post-handoff business scan/STOP required')
    for owner,proofs in [(a,target_proofs),(b,peer)]:
        for key,item in [('commands','command'),('complete','reply')]:
            rows=[v for v in capture[key] if (v['bus'],v['device'])==(owner['bus'],owner['device']) and start<=v['wall_ns']<=end]
            if rows!=[v[item] for v in proofs]:raise ValueError('extra command/START/STOP/reply or wrong device in complete daemon hold interval')
    return dict(target=target_proofs,peer=peer)


def corroborate(r,host,capture,stderr,identity):
    wire=corroborate_wire(r,capture)
    hold=corroborate_host_hold(host,dict(records=r['markers'],host_hold_acknowledgements=r['hold_acknowledgements']),[],stderr,identity,held_reply=wire['target'][0]['reply'])
    return dict(status='DAEMON_ACTUAL_HELD_REPLY_CANCEL_CORROBORATED',case=r['case'],**wire,host_hold=hold,
        ordinary_user_daemon_held_cancel_case_acceptance=True,**({'busy_business_initializer_admission_acceptance':True} if r['case']=='cancel-admission' else {}),whole_managed_acceptance=False,automatic_fault_recovery_acceptance=False,natural_fault_root_cause_closed=False)
