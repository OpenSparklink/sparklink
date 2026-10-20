# SPDX-License-Identifier: GPL-2.0-only
"""Real late-ACK/original-author-deadline gate in the existing VM runner.

Not an Engine or a delivery shortcut. Existing C/Python SDK applications own
both ends; the existing bounded QEMU hold keeps original IN81 bytes unchanged.
The first held aggregate may contain NOCP. It is NOT automatically the ACK or
proof that NOCP belongs to this send. The ACK has its own two-ended witnesses.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import time

from ws73_capture import CaptureError, read_live_prefix, reassemble_acb
from ws73_channel_prefix_hold import PrefixBarrier
from ws73_diagnostic_hold import HoldCoordinator, PROPERTIES, corroborate_host_hold
from ws73_ssap_initialization import SEQUENCE_QEMU_SHA256
from ws73_ssap_owned import publisher, wait_text, value_snapshot, await_removed
from ws73_ssap_update_delivery import configuration, command_receipt, discover, discovery_wire
from ws73_ssap_receive_lifecycle import receiver, ordinary
from ws73_application_client import application_environment, owned_arguments, authorization_context, process_identity

STATUS = 'REAL_AUTHOR_DEADLINE_LATE_ACK_PENDING_PAIRED_CAPTURE'
METHOD = 'BOUNDED2S_REAL_IN81_ORIGINAL1S_AUTHOR_DEADLINE'
RELEASE_METHOD = 'BOUNDED2S_REAL_IN81_SUBSCRIPTION_RELEASE'
EXPIRY_METHOD = 'BOUNDED2S_REAL_IN81_SUBSCRIPTION_ORIGINAL_EXPIRY'
HOLD_METHODS={'deadline':METHOD,'subscription-release':RELEASE_METHOD,'subscription-expiry':EXPIRY_METHOD}


def hold_status(purpose):
    return 'TWO_ORIGINAL_SUBSCRIPTION_EXPIRY_HOLDS_CORROBORATED'if purpose=='subscription-expiry'else'TWO_ORIGINAL_SUBSCRIPTION_RELEASE_HOLDS_CORROBORATED'if purpose=='subscription-release'else'TWO_ORIGINAL_AUTHOR_DEADLINE_LATE_ACK_HOLDS_CORROBORATED'
FIELD = 'ssap_sender_deadline'
CASES = ('deadline', 'owner-after-deadline')


def lifecycle_case(args):
    value=getattr(args,'ssap_sender_lifecycle_case','deadline')
    if value not in CASES or (value!='deadline' and not getattr(args,'ssap_sender_deadline_verify',False)):
        raise ValueError('explicit sender lifecycle case requires its dedicated real gate')
    return value


def boot_case(tokens, enabled):
    values=[t.split('=',1)[1]for t in tokens if t.startswith('ws73.ssap_sender_case=')]
    if not values:return 'deadline'
    if len(values)!=1 or not enabled or values[0]not in CASES:
        raise CaptureError('one original requested sender lifecycle boot case required')
    return values[0]


def validate_inputs(package,*,subscription=False):
    """Do not execute an old prepared guest under a new lifecycle selector."""
    here=Path(__file__).resolve().parent
    names=['ws73_ssap_sender_deadline.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh',
           'testing/application_client/client.c','testing/application_client/client.py']
    if subscription:names+=['ws73_ssap_subscription.py','ws73_application_role.py']
    for name in names:
        path=here/name
        records=package.get('application_client_tools',{}).get('sources',[])if name.startswith('testing/')else package.get('inputs',[])
        matches=[v for v in records if Path(v['path']).resolve()==path.resolve()]
        if len(matches)!=1 or matches[0]['sha256']!=hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('fresh exact sender lifecycle guest input required: '+name)


def requested(args, *, passthrough):
    lifecycle_case(args)
    value = getattr(args, 'ssap_sender_deadline_verify', False)
    if type(value) is not bool:raise ValueError('explicit sender deadline boolean required')
    if value and (not passthrough or not getattr(args, 'ssap_update_delivery_verify', False)
            or getattr(args, 'channel_socket_rounds', 4) != 4 or getattr(args, 'channel_socket_bytes', 61) != 61
            or any(getattr(args, k, False) for k in ['ssap_update_lifecycle_verify',
                'ssap_owner_lifecycle_verify', 'ssap_requester_lifecycle_verify', 'ssap_initialization_verify'])):
        raise ValueError('sender deadline requires separate protected update delivery and ordinary61 baseline')
    return value


def validate_qemu(path):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != SEQUENCE_QEMU_SHA256:
        raise ValueError('exact existing bounded2s real-IN81 QEMU required')


def selection(row, item, start):
    controllers = [dict(bus=v['owner']['bus'], device=v['owner']['device'],
        index=v['owner']['index'], generation=v['owner']['generation'],
        lifetime=v['object']['lifetime'], handle=v['object']['handle'], port=v['owner']['port'])
        for v in row['owners']]
    before=time.monotonic_ns();wall=time.time_ns();after=time.monotonic_ns()
    value = dict(version=1, phase=row['phase'], controllers=controllers,
                 property=item['handle'], value=item['secret'], start_wall_ns=start,
                 clock=dict(before_ns=before,wall_ns=wall,after_ns=after))
    check_selection(value, row['phase'])
    return value


def check_selection(value, phase):
    if (set(value) != {'version','phase','controllers','property','value','start_wall_ns','clock'}
            or type(value['version']) is not int or value['version'] != 1
            or type(value['phase']) is not int or type(phase)is not int or value['phase'] != phase or phase not in (0,1)
            or type(value['property']) is not int or not 1 <= value['property'] <= 65535
            or type(value['start_wall_ns']) is not int or value['start_wall_ns'] <= 0
            or not isinstance(value['value'], str) or not re.fullmatch('[0-9a-f]{64}', value['value'])):
        raise CaptureError('bounded original sender selection required')
    clock=value['clock']
    if (not isinstance(clock,dict)or set(clock)!={'before_ns','wall_ns','after_ns'}
            or any(type(v)is not int or v<=0 for v in clock.values())
            or not 0<=clock['after_ns']-clock['before_ns']<=1_000_000):
        raise CaptureError('bounded guest-only realtime/monotonic bracket required')
    owners = value['controllers']
    if not isinstance(owners, list) or len(owners) != 2:raise CaptureError('two original endpoints required')
    for v in owners:
        if (not isinstance(v, dict) or set(v) != {'bus','device','index','generation','lifetime','handle','port'}
                or any(type(v[k]) is not int for k in v if k != 'port')
                or not 0 < v['bus'] <= 255 or not 0 < v['device'] <= 127
                or not 0 <= v['index'] <= 65535 or not 0 < v['generation'] < 2**64
                or not 0 < v['lifetime'] < 2**64 or not 0 <= v['handle'] <= 4095):
            raise CaptureError('full original endpoint identity required')
    if (set(v['port'] for v in owners) != {'1-1','1-2'}
            or owners[0]['index'] == owners[1]['index']
            or (owners[0]['bus'],owners[0]['device']) == (owners[1]['bus'],owners[1]['device'])):
        raise CaptureError('distinct original guest endpoints;never infer USB slot from Native index')
    return int(owners[1]['port'][-1])-1


def update_frame(value):
    raw = b'\x10\x03' + value['property'].to_bytes(2,'little') + b'\x20\0' + bytes.fromhex(value['value'])
    return b'\x0a\0' + len(raw).to_bytes(2,'little') + raw


def live_witness(output, capture, value, observations):
    owners=value['controllers']
    data=read_live_prefix(output,capture,[(v['bus'],v['device'])for v in owners],observations)
    if data is None:return None
    try:sdus=reassemble_acb(data)
    except CaptureError as error:
        if str(error)!='incomplete A3 at sealed capture end':raise
        observations[-1]['partial']=str(error);return None
    legs=[]
    for index,direction,frame in [(1,'out',update_frame(value)),(0,'in',update_frame(value)),
                                   (0,'out',b'\x0a\0\x03\0\x11\x03\x01')]:
        v=owners[index]
        found=[p for p in sdus if
            (p['bus'],p['device'],p['handle'],p['direction'],p['data']) ==
            (v['bus'],v['device'],v['handle'],direction,frame.hex()) and p['wall_ns']>=value['start_wall_ns']]
        if len(found)>1:raise CaptureError('duplicate original indication/ACK at live barrier')
        if not found:return None
        legs.append(found[0])
    v=owners[1]
    if any((p['bus'],p['device'],p['handle'],p['direction'],p['data']) ==
           (v['bus'],v['device'],v['handle'],'in','0a000300110301') and p['wall_ns']>=value['start_wall_ns']
           for p in sdus):raise CaptureError('ACK reached provider before controlled release')
    if not legs[0]['wall_ns']<=legs[1]['wall_ns']<=legs[2]['wall_ns']:
        raise CaptureError('original indication TX/peer RX/ACK TX order required')
    return dict(indication_tx=legs[0],indication_rx=legs[1],ack_tx=legs[2],observations=observations)


def selection_bytes(path,share):
    if path.is_symlink() or not path.resolve().is_relative_to(share.resolve()):raise CaptureError('sender selection path escaped evidence root')
    with path.open('rb')as source:raw=source.read(2049)
    if len(raw)>2048:raise CaptureError('sender selection byte budget')
    return raw


class Coordinator:
    def __init__(self, share, output, record, qemu,*,purpose='deadline'):
        if purpose not in HOLD_METHODS:raise CaptureError('fixed hold purpose required')
        validate_qemu(qemu)
        self.method=HOLD_METHODS[purpose]
        self.share=Path(share);self.root=self.share/'application/passthrough-control/sender-deadline-hold'
        self.output=Path(output);self.record=record;self.child=None;self.used=[]
        record.update(method=self.method,qemu_sha256=SEQUENCE_QEMU_SHA256,phases=[],complete=False,
                      physical_acceptance=False,automatic_fault_recovery_acceptance=False)

    def poll(self, monitor, owner):
        if self.record['complete']:return
        phase=len(self.used);folder=self.root/f'phase-{phase}';path=folder/'selection.json'
        if self.child is None:
            if not path.exists() or not (folder/'hold-arm_ready.json').exists():return
            raw=selection_bytes(path,self.share)
            value=json.loads(raw);slot=check_selection(value,phase)
            if raw!=(json.dumps(value)+'\n').encode():raise CaptureError('canonical original sender selection required')
            if slot in self.used:raise CaptureError('fresh hold target in each role required')
            child=HoldCoordinator(folder,{})
            child.folder=folder;child.path=f'/machine/peripheral/ws73_{slot}'
            child.record.update(selection=value,slot=slot,method=self.method,selection_sha256=hashlib.sha256(raw).hexdigest(),
                host_identity_at_arm=owner(slot),live_observations=[])
            self.child=child;self.record['phases'].append(child.record)
        child=self.child
        if hashlib.sha256(selection_bytes(path,self.share)).hexdigest()!=child.record['selection_sha256']:raise CaptureError('sender selection changed while pending')
        if child.phase=='wait_held' and (folder/'hold-wait_held.json').exists():
            witness=live_witness(self.output,self.share/'ws73.pcap',child.record['selection'],child.record['live_observations'])
            if witness is None:return
            child.record['live_witness']=witness
        if(self.method in (RELEASE_METHOD,EXPIRY_METHOD) and child.phase=='release_ready'
                and (folder/'hold-release_ready.json').exists()):
            witness=release_witness(self.output,self.share/'ws73.pcap',child.record['selection'],
                child.record.setdefault('release_observations',[]))
            if witness is None:return
            child.record['release_witness']=witness
        child.poll(monitor)
        if child.phase=='done':
            self.used.append(child.record['slot']);self.child=None
            self.record['complete']=len(self.used)==2


def release_witness(output,capture,value,observations):
    """Causal raw disable TX while original provider ACK RX is still absent."""
    owners=value['controllers'];data=read_live_prefix(output,capture,[(v['bus'],v['device'])for v in owners],observations)
    if data is None:return None
    try:sdus=reassemble_acb(data)
    except CaptureError as error:
        if str(error)!='incomplete A3 at sealed capture end':raise
        observations[-1]['partial']=str(error);return None
    peer,server=owners;h=value['property']
    frame=(b'\x0a\0\x07\0\x0d\x23'+h.to_bytes(2,'little')+b'\x02\0\0').hex()
    found=[p for p in sdus if(p['bus'],p['device'],p['handle'],p['direction'],p['data'])==
        (peer['bus'],peer['device'],peer['handle'],'out',frame)and p['wall_ns']>=value['start_wall_ns']]
    if len(found)>1:raise CaptureError('one original in-flight disable TX required')
    if any((p['bus'],p['device'],p['handle'],p['direction'],p['data'])==
            (server['bus'],server['device'],server['handle'],'in','0a000300110301')
            and p['wall_ns']>=value['start_wall_ns']for p in sdus):
        raise CaptureError('provider ACK RX preceded in-flight disable barrier')
    if not found:return None
    return dict(disable_tx=found[0],observations=observations)


def execute(run,row):
    if row.get('security_requirement')!=2:raise CaptureError('actual mechanism2 required')
    selected=lifecycle_case(run.args);retired=selected=='owner-after-deadline'
    row.update(ssap_sender_deadline_required=True,ssap_sender_deadline=[],ssap_sender_lifecycle_case=selected);run.save()
    peer,server=row['owners'];api='c'if row['phase']==0 else'python';other='python'if api=='c'else'c'
    with publisher(run,row,0,'allow',collection=FIELD,label='sender-deadline',sdk_api=api,updates=True)as(owner,item):
        item['credentials'],item['process_status']=process_identity(owner.pid)
        discover(run,peer,item)
        case=dict(start_wall_ns=time.time_ns(),mode=2,value=item['secret'],reply=os.urandom(32).hex())
        item['case']=case
        if case['value']==case['reply']:raise CaptureError('distinct random application reply required')
        prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
        args=prefix+['update-retired'if retired else'update-peer',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(item['handle']),'2']+(['5','5000']if retired else[case['value'],case['reply']])
        with receiver(run,args,f'sender-deadline-{row["phase"]}')as invocation:
            app=invocation.row;case['application']=app;app['api']=other
            app['credentials'],app['process_status']=process_identity(invocation.process.pid);run.save()
            invocation.until(rb'^(\{[^\n]*"stage"\s*:\s*"ssap_update_wait"[^\n]*\})\n',timeout=3,limit=4096,label='actual receiver call')
            case['enabled']=configuration(owner,item,2,invocation.process);run.save()
            # The original independent2s fixture never extends the production
            #5s physical drain. This API request chooses1s before submission.
            time.sleep(.15)
            folder=run.output/'sender-deadline-hold'/f'phase-{row["phase"]}'
            folder.parent.mkdir(exist_ok=True)
            barrier=PrefixBarrier(case,run.save,folder,field='hold')
            value=selection(row,item,time.time_ns());case['selection']=value
            from ws73_diagnostic_hold import write_marker
            write_marker(folder/'selection.json',value);run.save()
            barrier.stage('arm_ready','armed')
            case['send']=command_receipt(owner,item,'indicate-deadline','SdkOwnedUpdateDeadline');run.save()
            check_deadline(case['send'],api,item['handle'])
            barrier.stage('wait_held','held')
            case['owner_while_held']=configuration(owner,item,2);run.save()
            if retired:
                owner.kill();case['owner_exit']=owner.wait(timeout=2);case['owner_exit_wall_ns']=time.time_ns()
                case['owner_removal']=await_removed(run,server,item['start']);run.save()
            barrier.release()
            invocation.process.wait(timeout=3)
            if invocation.process.returncode:raise CaptureError('real peer failed required receive outcome after original author deadline')
        if retired:
            def credentials(process,record):record['credentials'],record['process_status']=process_identity(process.pid)
            case['retired_write']=run.command(prefix+['ssap-error',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],'ssap-write',str(item['handle']),'5',case['reply']],7,
                collection='ssap_sender_retired_write',on_started=credentials,environment=application_environment())
            if case['retired_write']['exit']:raise CaptureError('actual SDK retired write must fail with its required negative result')
            item['cleanup']=case['owner_removal']
        else:
            case['disabled']=configuration(owner,item,0)
            case['after']=value_snapshot(owner,item,case['reply'])
        case['end_wall_ns']=time.time_ns();run.save()
        if not retired:
            owner.stdin.write('quit\n');owner.stdin.flush();owner.wait(timeout=2)
            if owner.returncode:raise CaptureError('original owner unregister failed')
            item['cleanup']=await_removed(run,server,item['start'])
    row['ssap_sender_deadline_status']=STATUS;run.save()


def check_deadline(observation,api,handle):
    r=observation['receipt']
    if (set(r)!={'api','handle','result','started_ns','deadline_ns','returned_ns'}
            or r['api']!=api or type(r['handle'])is not int or r['handle']!=handle
            or type(r['result'])is not int or r['result']!=-errno.ETIMEDOUT
            or any(type(r[k])is not int for k in ['started_ns','deadline_ns','returned_ns'])
            or not observation['start_monotonic_ns']<=r['started_ns']<r['deadline_ns']<=r['returned_ns']<=observation['end_monotonic_ns']
            or r['deadline_ns']-r['started_ns']!=1_000_000_000
            or r['returned_ns']-r['deadline_ns']>500_000_000):
        raise CaptureError('actual ETIMEDOUT at original1s SDK deadline required;never renew or accept arbitrary failure')
    return r


def corroborate(row,matched):
    if not row.get('ssap_sender_deadline_required',False):return [],{0:0,1:0}
    items=row.get(FIELD,[]);phase=row['phase'];owners=row['owners'];peer,server=owners
    api='c'if phase==0 else'python';other='python'if api=='c'else'c'
    selected=row.get('ssap_sender_lifecycle_case','deadline')
    if selected not in CASES:raise CaptureError('known original sender lifecycle case required')
    retired=selected=='owner-after-deadline'
    if row.get('ssap_sender_deadline_status')!=STATUS or len(items)!=1 or row.get('security_requirement')!=2:
        raise CaptureError('complete same-actor sender deadline gate required')
    item=items[0];case=item['case'];h=item['handle'];value=bytes.fromhex(case['value']);reply=bytes.fromhex(case['reply'])
    ordinary(item)
    if (item['sender']!=0 or item['target']!=1 or item['publisher_api']!=api or item['policy']!='allow'
            or item['args']!=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'allow',update_connection=server['object']['path'])
            or item.get('environment')!=application_environment() or item['exit']!=(-9 if retired else 0) or item['stderr']
            or item['credentials']['uids']!=[1000]*4 or any(int(v,16)for v in item['credentials']['capabilities'].values())
            or len(value)!=32 or len(reply)!=32 or value==reply or case['value']!=item['secret']or case['mode']!=2):
        raise CaptureError('actual ordinary retained owner and distinct random peer values required')
    selection_value=case['selection'];slot=check_selection(selection_value,phase)
    expected=[dict(bus=v['owner']['bus'],device=v['owner']['device'],index=v['owner']['index'],
        generation=v['owner']['generation'],lifetime=v['object']['lifetime'],handle=v['object']['handle'],port=v['owner']['port'])for v in owners]
    if selection_value['controllers']!=expected or selection_value['property']!=h or selection_value['value']!=case['value']:
        raise CaptureError('original full identity and value must bind selected slot')
    r=check_deadline(case['send'],api,h)
    hold=case['hold'];markers=hold['markers'];acks=hold['acks'];receipts=hold['ack_receipts']
    states=[[True,False,0,0,0,0,False,0],[False,True,1,0,0,0,False,0],[False,False,1,1,0,0,False,0]]
    if len(markers)!=3 or len(acks)!=3 or len(receipts)!=3:raise CaptureError('one complete explicit hold handshake required')
    for i,(m,a,receipt) in enumerate(zip(markers,acks,receipts,strict=True)):
        if (m['hold_phase']!=['arm_ready','wait_held','release_ready'][i]or a['stage']!=['armed','held','released'][i]
                or a['request']!=m or a['state']!=dict(zip(PROPERTIES,states[i]))
                or any(type(a['state'][k])is not type(v)for k,v in zip(PROPERTIES,states[i]))
                or receipt['stage']!=a['stage']or receipt['wall_ns']<m['wall_ns']
                or (i and receipts[i-1]['wall_ns']>=m['wall_ns'])):raise CaptureError('ordered explicit hold without automatic release/drop/error required')
    if not (receipts[0]['wall_ns']<case['send']['start_wall_ns']<=case['send']['end_wall_ns']
            <markers[1]['wall_ns']<receipts[1]['wall_ns']<=case['owner_while_held'][0]['start_wall_ns']
            <=case['owner_while_held'][-1]['end_wall_ns']<markers[2]['wall_ns']<receipts[2]['wall_ns']):
        raise CaptureError('author terminal and retained owner must precede explicit release')
    for key,wanted in [('enabled',2),('owner_while_held',2)]+([]if retired else[('disabled',0)]):
        values=case[key]
        if not 1<=len(values)<=12 or any(v['receipt']['api']!=api or v['receipt']['handle']!=h for v in values)or values[-1]['receipt']['modes']!=wanted:
            raise CaptureError('original owner configuration before/during/after hold required')
    app=case['application'];prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    ordinary(app)
    expected_args=prefix+['update-retired'if retired else'update-peer',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(h),'2']+(['5','5000']if retired else[case['value'],case['reply']])
    if (app['args']!=expected_args
            or app['exit']!=0 or app['stderr']or app.get('environment')!=application_environment()
            or app['credentials']['uids']!=[1000]*4 or any(int(v,16)for v in app['credentials']['capabilities'].values())):
        raise CaptureError('actual opposite SDK process required')
    output=[json.loads(v)for v in app['stdout'].splitlines()]
    if (len(output)!=2 or output[0].get('stage')!='ssap_update_wait'or output[0].get('client_closed')is not True
            or output[0].get('api')!=other or output[0].get('handle')!=h or output[0].get('mode')!=2
            or not receipts[2]['wall_ns']<app['end_wall_ns']<=case['end_wall_ns']):
        raise CaptureError('actual opposite SDK original receive interval required')
    if retired:
        check_retired(case,item,app,output,prefix,peer,other,h,markers,receipts)
    elif (output[1]!={'stage':'ssap_update_checked_reply','api':other,'handle':h,'mode':2,
            'pdu':update_frame(selection_value)[4:].hex(),'value':case['value'],'reply':case['reply']}
            or case['after']['value']!=case['reply']):
        raise CaptureError('real post-deadline peer application check and distinct reply required')
    lines=item['stdout'].splitlines()
    if (lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only']
            or (not retired and lines[-1:]!=[f'SdkOwnedRemoved: api={api} start={item["start"]}'])
            or (retired and re.search(r'^SdkOwnedRemoved:',item['stdout'],re.M))
            or [json.loads(v)for v in re.findall(r'^SdkOwnedUpdateDeadline: (.+)$',item['stdout'],re.M)]!=[r]
            or re.findall(r'^SdkOwnedUpdate: (.+)$',item['stdout'],re.M)
            or re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]+)$',item['stdout'],re.M)!=([]if retired else[(str(h),case['reply'])])):
        raise CaptureError('one immutable author timeout,no late success,owner actually observes reply')
    decisions=[json.loads(v)for v in re.findall(r'^SdkAuthorizationDecision: (.+)$',item['stdout'],re.M)]
    if len(decisions)!=(1 if retired else 2):raise CaptureError('actual owned approvals required;no decision after owner death')
    for decision,wanted in zip(decisions,['0200']if retired else['0200','0000'],strict=True):
        context={k:v for k,v in decision.items()if k not in {'allow','decision_ns','decision_wall_ns'}}
        authorization_context(context,api,level=2,data_type=2)
        if ([decision[k]for k in ['index','generation','lifetime','handle','property']]!=
                [server['owner']['index'],server['owner']['generation'],server['object']['lifetime'],server['object']['handle'],h]
                or decision['value']!=wanted or decision['allow']is not True or decision['decision_ns']>=decision['deadline_ns']):
            raise CaptureError('original typed owner decision required')
    legs=[];credit={0:0,1:0}
    def exchange(a,b,pdu,window):
        from ws73_ssap_value import pair_wire,physical_sends
        leg=pair_wire(row,matched,owners[a],owners[b],pdu,window);legs.append(leg);credit[a]+=physical_sends(leg['tx'])
        return leg
    discovery_wire(item,peer,exchange)
    hb=h.to_bytes(2,'little')
    for request,response in [(b'\x08\x03'+hb+b'\x02',b'\x09\x03\0\0'),
                             (b'\x0d\x23'+hb+b'\x02\x02\0',b'\x0e\x03'+hb+b'\x02\x02\0')]:
        exchange(0,1,request,case);exchange(1,0,response,case)
    sent=exchange(1,0,update_frame(selection_value)[4:],case)
    ack=exchange(0,1,b'\x11\x03\x01',case)
    clock=selection_value['clock']
    earliest=clock['wall_ns']+r['deadline_ns']-clock['after_ns']
    latest=clock['wall_ns']+r['deadline_ns']-clock['before_ns']
    if not (case['send']['start_wall_ns']<=sent['tx']['wall_ns']<=sent['rx']['wall_ns']<=ack['tx']['wall_ns']<earliest
            and ack['rx']['wall_ns']>latest and ack['rx']['wall_ns']>=markers[2]['wall_ns']):
        raise CaptureError('actual peer ACK TX before original deadline and provider RX after deadline/release required')
    cleanup_window=dict(start_wall_ns=case['start_wall_ns'],end_wall_ns=app['end_wall_ns'])if retired else case
    # Production WriteError has count1,originalhandle,error8,not ReadError's
    # error16. Reference bodies agree;libws73's control flags differ. This
    # fixed local-host oracle is not a reference interoperability certificate.
    write_refusal=b'\x0e\x07\x01'+hb+b'\x04'
    for request,response,window in [(b'\x0d\x23'+hb+b'\x02\0\0',write_refusal if retired else b'\x0e\x03'+hb+b'\x02\0\0',cleanup_window),
                             (b'\x0d\x23'+hb+b'\0'+reply,write_refusal if retired else b'\x0e\x03'+hb+b'\0'+reply,case['retired_write']if retired else case)]:
        tx=exchange(0,1,request,window);rx=exchange(1,0,response,window)
        if retired and (rx['tx']['wall_ns']<case['owner_exit_wall_ns']or rx['tx']['wall_ns']<markers[2]['wall_ns']):
            raise CaptureError('actual oldservice rejection only after owner removal and explicit release required')
    if len(legs)!=20:raise CaptureError('all hierarchy,configuration,update,ACK,cleanup and business wire required')
    cleanup=item['cleanup'];matches=re.findall(r'^SsapLocalServices: (.+)$',cleanup['stdout'],re.M)
    if cleanup['exit']or len(matches)!=1 or any(v[0]==item['start']for v in json.loads(matches[0])):raise CaptureError('original local owner unregister required')
    return [dict(phase=phase,publisher=api,peer=other,slot=slot,author_result=-errno.ETIMEDOUT,
                 application_replies=0 if retired else 1,original_author_ms=1000,physical_drain_expiry_verified=False,
                 **(dict(lifecycle_case=selected,retired_receive_refusals=1,retired_write_refusals=1)if retired else{}),wire=legs)],credit


def check_retired(case,item,app,output,prefix,peer,api,h,markers,receipts):
    """Actual SDK error receipts plus separate mandatory wire Error4 below.

    Failed remote CPCD cleanup does not expose a successfully delivered update
    to this SDK application. EIO is not by itself proof of remote rejection.
    """
    first,last=output
    if (set(first)!={'stage','api','handle','mode','deadline_ns','client_closed','started_ns','budget_ms'}
            or set(last)!={'stage','api','handle','mode','errno','deadline_ns','returned_ns'}
            or any(type(first[k])is not int for k in ['started_ns','deadline_ns','budget_ms'])
            or first['budget_ms']!=5000 or first['deadline_ns']-first['started_ns']!=5_000_000_000
            or last!={'stage':'ssap_update_error','api':api,'handle':h,'mode':2,'errno':errno.EIO,
                'deadline_ns':first['deadline_ns'],'returned_ns':last.get('returned_ns')}
            or type(last['returned_ns'])is not int or not app['start_monotonic_ns']<=first['started_ns']<last['returned_ns']<=app['end_monotonic_ns']
            or last['returned_ns']>=first['deadline_ns']
            or case['owner_exit']!=-9 or any(k in case for k in ['disabled','after'])
            or not case['owner_while_held'][-1]['end_wall_ns']<case['owner_exit_wall_ns']<markers[2]['wall_ns']):
        raise CaptureError('actual owner death after author timeout and actual failed receive cleanup required')
    removed=case['owner_removal']
    if (removed!=item['cleanup'] or not case['owner_exit_wall_ns']<=removed['start_wall_ns']<=removed['end_wall_ns']<markers[2]['wall_ns']):
        raise CaptureError('original local Owner removal before controlled release required')
    probe=case['retired_write'];ordinary(probe)
    if (probe['args']!=prefix+['ssap-error',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],'ssap-write',str(h),'5',case['reply']]
            or probe['exit'] or probe['stderr']or probe.get('environment')!=application_environment()
            or not receipts[2]['wall_ns']<app['end_wall_ns']<=probe['start_wall_ns']<probe['end_wall_ns']<=case['end_wall_ns']):
        raise CaptureError('actual ordinary SDK old-service write rejection after release required')
    lines=[json.loads(v)for v in probe['stdout'].splitlines()]
    if len(lines)!=2:raise CaptureError('actual SDK call/error pair required')
    call,result=lines
    if (set(call)!={'stage','api','deadline_ns','call_ns','client_closed'}
            or set(result)!={'stage','api','errno','operation_success','deadline_ns','returned_ns'}
            or call['stage']!='ssap_call'or call['api']!=api or call['client_closed']is not True
            or result.get('operation_success')is not False
            or result!={'stage':'ssap_error','api':api,'errno':errno.EIO,'operation_success':False,
                'deadline_ns':call['deadline_ns'],'returned_ns':result.get('returned_ns')}
            or any(type(v)is not int for v in [call['call_ns'],call['deadline_ns'],result['returned_ns']])
            or not probe['start_monotonic_ns']<=call['call_ns']<result['returned_ns']<call['deadline_ns']
            or not result['returned_ns']<=probe['end_monotonic_ns'] or not 0<call['deadline_ns']-call['call_ns']<=5_000_000_000):
        raise CaptureError('actual failed SDK write under original deadline required;errno alone not wire proof')


def valid_summary(proof):
    from ws73_ssap_value import valid_wire
    try:
        rows=proof['proofs']
        if proof.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED' or len(rows)!=2:return False
        slots=set();cases=set()
        for phase,row in enumerate(rows):
            values=row[FIELD]
            if row['phase']!=phase or len(values)!=1:return False
            v=values[0];slots.add(v['slot'])
            selected=v.get('lifecycle_case','deadline');retired=selected=='owner-after-deadline'
            cases.add(selected)
            if (selected not in CASES or type(v['slot'])is not int or v['slot']not in (0,1) or v['peer']!=('python'if phase==0 else'c') or v['phase']!=phase or v['publisher']!=('c'if phase==0 else'python')
                    or v['author_result']!=-errno.ETIMEDOUT or type(v['application_replies'])is not int or v['application_replies']!=(0 if retired else 1)
                    or (retired and any(type(v.get(k))is not int or v[k]!=1 for k in ['retired_receive_refusals','retired_write_refusals']))
                    or v['original_author_ms']!=1000 or v['physical_drain_expiry_verified']is not False
                    or len(v['wire'])!=20 or not all(valid_wire(leg)for leg in v['wire'])):return False
    except (KeyError,ValueError,TypeError,IndexError):return False
    return slots=={0,1} and len(cases)==1


def corroborate_holds(record,control,capture,stderr,*,cases=None,purpose='deadline'):
    if purpose not in HOLD_METHODS:raise CaptureError('fixed hold proof purpose required')
    method=HOLD_METHODS[purpose]
    if (record.get('method')!=method or record.get('complete')is not True
            or record.get('qemu_sha256')!=SEQUENCE_QEMU_SHA256 or len(record.get('phases',[]))!=2):
        raise CaptureError('two original bounded hold phases required')
    rows=[];sdus=reassemble_acb(capture)
    if cases is None:cases=[row[FIELD][0]['case']for row in control['channel_socket']]
    for phase,(case,host) in enumerate(zip(cases,record['phases'],strict=True)):
        hold=case['hold'];value=case['selection'];slot=check_selection(value,phase)
        if host['selection']!=value or host['slot']!=slot or host['observations']!=hold['acks']or not host.get('live_witness'):
            raise CaptureError('original host/guest hold selection and observations required')
        for key in ['indication_tx','indication_rx','ack_tx']:
            observed=host['live_witness'][key]
            originals=[p for p in sdus if (p['record'],p.get('hcc_offset'),p.get('direction'))==
                (observed['record'],observed.get('hcc_offset'),observed.get('direction'))]
            if originals!=[observed]:raise CaptureError('live sender witness differs from original sealed capture')
        if purpose in ('subscription-release','subscription-expiry'):
            observed=host['release_witness']['disable_tx']
            originals=[p for p in sdus if(p['record'],p.get('hcc_offset'),p.get('direction'))==
                (observed['record'],observed.get('hcc_offset'),observed.get('direction'))]
            trigger=case['expiry']['start_wall_ns']if purpose=='subscription-expiry'else case['release_request_wall_ns']
            if originals!=[observed]or not trigger<=observed['wall_ns']<=hold['ack_receipts'][2]['wall_ns']:
                raise CaptureError('original in-flight disable TX before unhold confirmation required')
        # The held transfer is independently identified. A NOCP inside it is
        # an observation,not a proved old/new lifetime completion attribution.
        candidates=[v for v in capture['native_events']if v['event']==9]+capture['acb_packets']
        target=value['controllers'][1];selected={}
        received=[p for p in capture['rx_urbs']if (p['bus'],p['device'],p['kind'],p['status'])==
            (target['bus'],target['device'],'C',0)and p['length']>0 and hold['markers'][2]['wall_ns']<=p['wall_ns']<=case['end_wall_ns']]
        if not received:raise CaptureError('first original nonempty successful RX after explicit release required')
        first=min(received,key=lambda p:p['record'])
        for p in candidates:
            if (p['bus'],p['device'],p.get('direction','in'),p['record'])==(target['bus'],target['device'],'in',first['record']):
                selected.setdefault((p['record'],p['usb_sha256'],p['usb_length']),p)
        good=[]
        relevant_stderr='\n'.join(line for line in stderr.splitlines()if
            ('WS73_TEST_RUNTIME_HOLD:'in line or 'WS73_TEST_RUNTIME_HOLD_RELEASE:'in line)
            and f"dev {host['host_identity_at_arm']['bus']}:{host['host_identity_at_arm']['address']} "in line)
        for p in selected.values():
            try:
                proof=corroborate_host_hold(host,dict(records=hold['markers'],host_hold_acknowledgements=hold['acks']),[],relevant_stderr,
                    host['host_identity_at_arm'],held_reply=p,expected_method=method)
            except ValueError:continue
            good.append((p,proof))
        if len(good)!=1:raise CaptureError('one original delivered held aggregate hash required')
        p,proof=good[0]
        if not hold['markers'][2]['wall_ns']<=p['wall_ns']<=case['end_wall_ns']:raise CaptureError('original withheld aggregate delivered after explicit release required')
        rows.append(dict(phase=phase,slot=slot,host_hold=proof,held_kind='NOCP'if p.get('event')==9 else'ACB',
            scope='Controlled delay only;held aggregate may differ from ACK. Not NOCP lifetime truth,natural recovery,partial admission or full callback/refdrain proof.'))
    return dict(status=hold_status(purpose),phases=rows)


def validate_prefixes(record,path):
    with Path(path).open('rb')as source:raw=source.read(64*1024*1024+1)
    if len(raw)>64*1024*1024:raise CaptureError('sealed sender capture byte budget')
    phases=record['phases']
    if len(phases)!=2:raise CaptureError('two original sender capture phases required')
    for phase in phases:
        observations=phase['live_observations']
        if not 1<=len(observations)<=64 or 'partial'in observations[-1]:raise CaptureError('bounded complete live witness required')
        for v in observations:
            size=v['bytes']
            if type(size)is not int or not 24<=size<=len(raw)or hashlib.sha256(raw[:size]).hexdigest()!=v['sha256']:
                raise CaptureError('original sender live capture prefix changed or missing')
        witness=phase['live_witness']
        if witness['observations']!=observations:raise CaptureError('live witness observation identity differs')
        if record.get('method')==RELEASE_METHOD:
            observations=phase['release_observations']
            if not 1<=len(observations)<=64 or 'partial'in observations[-1]or phase['release_witness']['observations']!=observations:
                raise CaptureError('bounded actual release observations required')
            for v in observations:
                size=v['bytes']
                if type(size)is not int or not 24<=size<=len(raw)or hashlib.sha256(raw[:size]).hexdigest()!=v['sha256']:
                    raise CaptureError('original release capture prefix changed or missing')


def valid_hold_summary(record,proof,*,purpose='deadline'):
    """Terminal schema checks,not a substitute for original-byte corroboration."""
    try:
        if purpose not in HOLD_METHODS:return False
        method=HOLD_METHODS[purpose]
        if (record['method']!=method or record['qemu_sha256']!=SEQUENCE_QEMU_SHA256
                or record['complete']is not True or record['physical_acceptance']is not False
                or record['automatic_fault_recovery_acceptance']is not False
                or len(record['phases'])!=2 or len(proof['phases'])!=2
                or proof['status']!=hold_status(purpose)):return False
        slots=set()
        for phase,(r,p)in enumerate(zip(record['phases'],proof['phases'],strict=True)):
            slot=check_selection(r['selection'],phase);slots.add(slot)
            if (r['method']!=method or r['slot']!=slot or r['complete']is not True
                    or r['physical_acceptance']is not False or r['automatic_fault_recovery_acceptance']is not False
                    or r['selection_sha256']!=hashlib.sha256((json.dumps(r['selection'])+'\n').encode()).hexdigest()
                    or p['phase']!=phase or p['slot']!=slot or p['held_kind']not in ('NOCP','ACB')):return False
            rows=r['observations']
            if len(rows)!=3 or [v['stage']for v in rows]!=['armed','held','released']:return False
            states=[[True,False,0,0,0,0,False,0],[False,True,1,0,0,0,False,0],[False,False,1,1,0,0,False,0]]
            for v,state in zip(rows,states,strict=True):
                if v['state']!=dict(zip(PROPERTIES,state))or any(type(v['state'][k])is not type(w)for k,w in zip(PROPERTIES,state)):return False
            observations=r['live_observations']
            if not 1<=len(observations)<=64 or 'partial'in observations[-1] or r['live_witness']['observations']!=observations:return False
            for v in observations:
                if (not isinstance(v,dict)or not {'bytes','sha256'}<=set(v)<= {'bytes','sha256','partial'}
                        or type(v['bytes'])is not int or not 24<=v['bytes']<=16*1024*1024
                        or not re.fullmatch('[0-9a-f]{64}',v['sha256'])):return False
            for key in ['indication_tx','indication_rx','ack_tx']:
                if not isinstance(r['live_witness'][key],dict)or not r['live_witness'][key]:return False
            if purpose in ('subscription-release','subscription-expiry'):
                observations=r.get('release_observations',[])
                if not r.get('release_witness',{}).get('disable_tx')or not 1<=len(observations)<=64 or 'partial'in observations[-1]or r['release_witness']['observations']!=observations:return False
                for v in observations:
                    if(not isinstance(v,dict)or not {'bytes','sha256'}<=set(v)<= {'bytes','sha256','partial'}
                            or type(v['bytes'])is not int or not 24<=v['bytes']<=16*1024*1024
                            or not re.fullmatch('[0-9a-f]{64}',v['sha256'])):return False
            h=p['host_hold']
            if (h['status']!='ACTUAL_HOST_HOLD_CORROBORATED' or h['physical_acceptance']is not False
                    or h['automatic_fault_recovery_acceptance']is not False
                    or not re.fullmatch('[0-9a-f]{64}',h['host_transfer_sha256'])
                    or type(h['host_transfer_bytes'])is not int or not 0<h['host_transfer_bytes']<=65536
                    or type(h['delivered_usb_record'])is not int or h['delivered_usb_record']<=0):return False
    except (KeyError,ValueError,TypeError,IndexError):return False
    return slots=={0,1}
