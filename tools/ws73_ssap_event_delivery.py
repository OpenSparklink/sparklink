# SPDX-License-Identifier: GPL-2.0-only
"""Finite event/app-reply scenario using the existing SDK/VM/output/capture path.

No Host or protocol sender. Readiness is the actual installed event lease;
ACK and verified writes remain separate from application/publisher checks.
This version qualifies only 32-byte notification/indication,not full SSAP.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from ws73_capture import CaptureError,packet_interval
from ws73_application_client import application_environment,owned_arguments,_ssap_process_receipt
from ws73_ssap_owned import publisher,observed_process,wait_text,wait_output,value_snapshot,await_removed,verify_output
from ws73_ssap_update_delivery import command_receipt

VERSION=1
TOKEN='ws73.ssap_event_delivery=1'
PENDING='EVENT_APPLICATION_REPLY_PENDING_PAIRED_USB'
STATUS='EVENT_APPLICATION_REPLY_PAIRED_USB'
LEASE_MS=10000
EXTRA_TOOLS=('/usr/share/sparklink/python/sparklink/ssap_subscription.py',)


def requested(args,*,passthrough=None):
    selected=getattr(args,'ssap_event_delivery_verify',False)
    if type(selected)is not bool:raise ValueError('explicit event selector boolean required')
    if not selected:return False
    if any(v for k,v in vars(args).items()if k.startswith('ssap_') and k.endswith('_verify') and k not in ('ssap_event_delivery_verify','ssap_owned_verify')):
        raise ValueError('event delivery requires its separate original Owned baseline')
    from ws73_ssap_read_provider import requested as baseline
    shadow=copy.copy(args);shadow.ssap_read_provider_verify=True
    baseline(shadow,passthrough=passthrough)
    return True


def boot_requested(tokens):
    if type(tokens)not in (list,tuple)or any(type(t)is not str for t in tokens):raise ValueError('original boot tokens required')
    selected=[t for t in tokens if t=='ws73.ssap_event_delivery'or t.startswith('ws73.ssap_event_delivery=')]
    if selected not in ([],[TOKEN])or selected and tokens.count('ws73.ssap_owned=1')!=1:raise ValueError('one event selector and Owned dependency required')
    return bool(selected)


def validate_inputs(package):
    from ws73_ssap_read_provider import validate_inputs as baseline
    baseline(package);p=Path(__file__).resolve()
    found=[r for r in package.get('inputs',[])if Path(r['path']).resolve()==p]
    if len(found)!=1 or found[0]['sha256']!=hashlib.sha256(p.read_bytes()).hexdigest():raise CaptureError('fresh exact event scenario/verifier required')


def tool_records(root=Path('/')):
    from ws73_ssap_update_delivery import tool_records as base
    records=base(root)
    for name in EXTRA_TOOLS:
        data=(root/name.lstrip('/')).read_bytes();records[name]=dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
    return records


def validate_tools(records,root,manifest):
    if records!=tool_records(root):raise CaptureError('event apps/SDK differ from sealed root')
    for name,value in records.items():
        p=(root/name.lstrip('/')).resolve(strict=True);found=[m for m in manifest if Path(m['path']).resolve()==p]
        if len(found)!=1 or found[0]['sha256']!=value['sha256']:raise CaptureError('event tool absent from build manifest')


def validate_rows(rows,selected):
    if type(selected)is not bool or type(rows)is not list or selected and len(rows)!=2:raise CaptureError('two event phases and explicit selection required')
    for phase,row in enumerate(rows):
        actual=row.get('ssap_event_delivery_required',False)
        if type(actual)is not bool or actual!=selected:raise CaptureError('event selector/evidence mismatch')
        if not selected:
            if any(k.startswith('ssap_event_delivery_')for k in row if k!='ssap_event_delivery_required'):raise CaptureError('unrequested event evidence')
        elif (type(row.get('phase'))is not int or row['phase']!=phase
                or type(row.get('ssap_event_delivery_version'))is not int or row['ssap_event_delivery_version']!=VERSION
                or row.get('ssap_owned_required')is not True or len(row.get('ssap_owned',[]))!=4
                or {(v['sender'],v['policy'])for v in row['ssap_owned']}!={(s,p)for s in (0,1)for p in ('allow','deny')}
                or type(row.get('ssap_event_delivery_tools'))is not dict
                or [i['sender']for i in row.get('ssap_event_delivery_cases',[])]!=[0,1]):raise CaptureError('original baseline and complete event directions required')


def peer_arguments(api,peer,event,reply):
    if api not in ('c','python')or any(type(v)is not int or not 0<v<65536 for v in (event,reply))or event==reply:raise CaptureError('explicit event and independent reply property required')
    prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    return prefix+['event-subscription',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(event),'3',str(LEASE_MS),'0',str(reply)]


def execute(run,row):
    if row.get('ssap_owned_required')is not True or len(row.get('ssap_owned',[]))!=4:raise CaptureError('original Owned baseline must precede event gate')
    row.update(ssap_event_delivery_required=True,ssap_event_delivery_version=VERSION,ssap_event_delivery_tools=tool_records(),ssap_event_delivery_cases=[]);run.save()
    for sender in (0,1):
        peer,server=row['owners'][sender],row['owners'][1-sender]
        api='c'if(row['phase']+sender)%2==0 else'python';other='python'if api=='c'else'c'
        with publisher(run,row,sender,'none',collection='ssap_event_delivery_cases',label='event',sdk_api=api,event_minimum=0)as(owner,item):
            item['cases']=[];run.save()
            for ordinal,mode in enumerate((1,2)):
                sequence=row['phase']*4+sender*2+ordinal
                value=(sequence.to_bytes(4,'little')+secrets.token_bytes(28)).hex()
                reply=((sequence|0x80000000).to_bytes(4,'little')+secrets.token_bytes(28)).hex()
                case=dict(mode=mode,sequence=sequence,value=value,reply=reply,start_wall_ns=time.time_ns());item['cases'].append(case);run.save()
                args=peer_arguments(other,peer,item['event_handle'],item['handle'])
                out=run.output/f'event-peer-{row["phase"]}-{sender}-{mode}.stdout';err=out.with_suffix('.stderr')
                app=dict(api=other,args=args,environment=application_environment(),start_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
                case['application']=app;run.save()
                try:
                    with observed_process(args,app,out,err,env=dict(os.environ,**app['environment']),text=True,stdin=subprocess.PIPE)as child:
                        from ws73_channel_socket import credentials
                        app.update(pid=child.pid,credentials=credentials(child.pid));run.save()
                        values,_=wait_text(child,out,r'^(\{.*"stage"\s*:\s*"ssap_event_listener_ready".*\})$',time.monotonic()+5,max_count=1)
                        if len(values)!=1:raise CaptureError('one actual event Ready required')
                        ready=json.loads(values[0]);validate_ready(ready,other,item['event_handle'],item['handle'])
                        case.update(ready=ready,ready_observed_wall_ns=time.time_ns())
                        case['check_command']=f'check {value} {reply}'
                        case['check_sent_wall_ns']=time.time_ns();child.stdin.write(case['check_command']+'\n');child.stdin.flush();run.save()
                        case['send']=command_receipt(owner,item,('event-indicate 'if mode==2 else'event-notify ')+value,'SdkOwnedEvent');run.save()
                        checked,_=wait_text(child,out,r'^(\{.*"stage"\s*:\s*"ssap_event_checked_reply".*\})$',case['send']['start_monotonic_ns']/1e9+5,max_count=1)
                        if len(checked)!=1:raise CaptureError('one independently checked application reply required')
                        case.update(checked=json.loads(checked[0]),checked_observed_wall_ns=time.time_ns());run.save()
                        child.stdin.write('quit\n');child.stdin.flush();wait_output(child,2)
                        if child.returncode:raise CaptureError('event peer did not cleanly release its lease')
                finally:run.save()
                case['after']=value_snapshot(owner,item,reply);case['end_wall_ns']=time.time_ns();run.save()
            owner.stdin.write('quit\n');owner.stdin.flush();wait_output(owner,2)
            if owner.returncode:raise CaptureError('event owner unregister failed')
            item['cleanup']=await_removed(run,server,item['start']);run.save()
    row['ssap_event_delivery_status']=PENDING;run.save()


def _deadline(receipt):
    vals=[receipt[k]for k in ('started_ns','returned_ns','deadline_ns')]
    if any(type(v)is not int or v<=0 for v in vals)or not vals[0]<=vals[1]<vals[2]or vals[2]-vals[0]!=5_000_000_000:raise CaptureError('one actual original5s operation deadline required')



def validate_ready(ready,api,event,reply):
    _deadline(ready)
    expected=dict(stage='ssap_event_listener_ready',version=1,api=api,event=event,reply_property=reply,minimum=0,client_closed=True)
    if (any(type(ready.get(k))is not type(v)or ready[k]!=v for k,v in expected.items())
            or set(ready)!=set(expected)|{'token','epoch','expires_ns','started_ns','returned_ns','deadline_ns'}
            or any(type(ready[k])is not int or ready[k]<=0 for k in ('token','epoch','expires_ns'))
            or not ready['returned_ns']<ready['expires_ns']<=ready['returned_ns']+LEASE_MS*1_000_000):
        raise CaptureError('actual original event lease Ready required before send')


def _case(row,item,matched,inventory):
    from ws73_ssap_command import _identity
    from ws73_ssap_value import pair_wire,physical_sends,valid_wire
    owners=row['owners'];identities=[_identity(o)for o in owners]
    if len(identities)!=2 or len({(v['index'],v['generation'])for v in identities})!=2 or len({(v['bus'],v['device'])for v in identities})!=2:raise CaptureError('two independent controller identities required')
    s,t=item['sender'],item['target'];h,e=item['handle'],item['event_handle']
    if (any(type(item[k])is not int for k in ('sender','target','start','end','handle','event_handle','pid','event_minimum'))
            or s not in (0,1)or t!=1-s or not 0<item['start']<h<e==item['end']<65536 or item['pid']<=0
            or item['event_minimum']!=0 or item['policy']!='none' or item['entry_kind']!='event'
            or [c['mode']for c in item['cases']]!=[1,2]):raise CaptureError('original event/reply identity and two modes required')
    api='c'if(row['phase']+s)%2==0 else'python';other='python'if api=='c'else'c';peer,server=owners[s],owners[t]
    if item['publisher_api']!=api or any(type(item[k])is not str or not re.fullmatch('[0-9a-f]{'+str(n)+'}',item[k])for k,n in [('service',32),('uuid',32),('event_uuid',32),('secret',64)]):raise CaptureError('original random SDK registration required')
    verify_output(item);_ssap_process_receipt(item,1000)
    if item['args']!=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'none',event_uuid=item['event_uuid'],event_minimum=0):raise CaptureError('exact event publisher invocation required')
    binding=dict(version=1,api=api,event=e,reply_property=h,minimum=0)
    lines=item['stdout'].splitlines()
    if (item['event_binding']!=binding or lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only']
            or len(lines)!=8 or json.loads(lines[2].removeprefix('SdkOwnedEventBinding: '))!=binding
            or lines[-1]!=f'SdkOwnedRemoved: api={api} start={item["start"]}'):
        raise CaptureError('complete exact event owner transcript required')
    legs=[];credit={0:0,1:0};observed=[];fresh={item['secret']}
    def exchange(a,b,pdu,window):
        leg=pair_wire(row,matched,owners[a],owners[b],pdu,window)
        from ws73_ssap_read_provider import validate_paired_leg
        validate_paired_leg(row,a,b,b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu,window,leg)
        if not valid_wire(leg)or packet_interval(leg['tx'])[1]>packet_interval(leg['rx'])[0]:raise CaptureError('valid causal paired event USB legs required')
        legs.append(leg);credit[a]+=physical_sends(leg['tx']);return leg
    for ordinal,case in enumerate(item['cases']):
        mode=ordinal+1;seq=row['phase']*4+s*2+ordinal
        if type(case['mode'])is not int or type(case['sequence'])is not int or (case['mode'],case['sequence'])!=(mode,seq):raise CaptureError('exact event sequence required')
        for k,n in [('value',seq),('reply',seq|0x80000000)]:
            v=case[k]
            if type(v)is not str or not re.fullmatch('[0-9a-f]{64}',v)or bytes.fromhex(v)[:4]!=n.to_bytes(4,'little')or v in fresh:raise CaptureError('fresh independent sequence/payload required')
            fresh.add(v)
        pdu=bytes([14+mode,7])+e.to_bytes(2,'little')+b'\x20\0'+bytes.fromhex(case['value']);app=case['application']
        verify_output(app);_ssap_process_receipt(app,1000)
        if app['api']!=other or app['args']!=peer_arguments(other,peer,e,h)or type(app['pid'])is not int or app['pid']<=0:raise CaptureError('actual original receiving SDK process required')
        output=[json.loads(l)for l in app['stdout'].splitlines()]
        if len(output)!=4:raise CaptureError('ready/check/batch/release output required')
        ready,checked,batch,closed=output
        validate_ready(ready,other,e,h);_deadline(checked)
        expected_ready=dict(stage='ssap_event_listener_ready',version=1,api=other,event=e,reply_property=h,minimum=0,client_closed=True)
        if (case['ready']!=ready or any(type(ready.get(k))is not type(v)or ready[k]!=v for k,v in expected_ready.items())
                or any(type(ready.get(k))is not int or ready[k]<=0 for k in ('token','epoch','expires_ns'))
                or not ready['returned_ns']<ready['expires_ns']<=ready['returned_ns']+LEASE_MS*1_000_000):raise CaptureError('actual original event lease Ready required')
        if ordinal and (ready['token']==item['cases'][ordinal-1]['ready']['token']or ready['epoch']!=item['cases'][0]['ready']['epoch']or case['start_wall_ns']<item['cases'][ordinal-1]['end_wall_ns']):raise CaptureError('new lease token, same original epoch and serial case windows required')
        expected_checked=dict(stage='ssap_event_checked_reply',version=1,api=other,event=e,reply_property=h,minimum=0,value=case['value'],reply=case['reply'])
        if case['checked']!=checked or any(type(checked.get(k))is not type(v)or checked[k]!=v for k,v in expected_checked.items()):raise CaptureError('actual complete application comparison and distinct reply required')
        if (type(checked.get('sequence'))is not int or checked['sequence']<=0 or not ready['returned_ns']<=checked['started_ns']<=checked['returned_ns']<ready['expires_ns']
                or case['check_command']!=f'check {case["value"]} {case["reply"]}'):
            raise CaptureError('check uses original active lease and command')
        expected_packet=dict(sequence=checked['sequence'],epoch=ready['epoch'],level=0,indication=mode==2,pdu=pdu.hex())
        if (batch!=dict(stage='ssap_subscription_batch',api=other,last=checked['sequence'],dropped=0,refused=0,state=1,flags=0,reason=0,discarded=0,packets=[expected_packet])
                or closed!=dict(stage='ssap_subscription_released',api=other,flags=1,discarded=0)):raise CaptureError('lossless original single event batch and local-only close required')
        sent=case['send']['receipt'];_deadline(sent)
        expected_sent=dict(version=1,api=api,handle=e,minimum=0,stage=mode,pdu=pdu.hex(),ack='110701'if mode==2 else'')
        if any(type(sent.get(k))is not type(v)or sent[k]!=v for k,v in expected_sent.items()):raise CaptureError('actual event admission/ACK receipt required')
        if not case['send']['start_monotonic_ns']<=sent['started_ns']<=sent['returned_ns']<=case['send']['end_monotonic_ns']:raise CaptureError('original observed send deadline required')
        if json.loads(lines[3+2*ordinal].removeprefix('SdkOwnedEvent: '))!=sent or lines[4+2*ordinal]!=f'SsapOwnedValue: handle={h} value={case["reply"]}':raise CaptureError('original sender receipt and independent readback required')
        if case['after']['value']!=case['reply']or case['after']['handle']!=h or case['after']['ordinal']!=ordinal+1:raise CaptureError('original reply property readback required')
        stamps=[item['start_wall_ns'],item['bound_wall_ns'],case['start_wall_ns'],app['start_wall_ns'],case['ready_observed_wall_ns'],case['check_sent_wall_ns'],case['send']['start_wall_ns'],case['checked_observed_wall_ns'],app['end_wall_ns'],case['after']['start_wall_ns'],case['after']['end_wall_ns'],case['end_wall_ns'],item['end_wall_ns']]
        if any(type(v)is not int or v<=0 for v in stamps)or stamps!=sorted(stamps)or not case['send']['start_wall_ns']<=case['send']['end_wall_ns']<=case['checked_observed_wall_ns']:raise CaptureError('actual Ready-before-send and independent reply chronology required')
        start=len(legs);event=exchange(t,s,pdu,case)
        if mode==2:
            ack=exchange(s,t,b'\x11\x07\x01',case)
            if packet_interval(event['rx'])[1]>packet_interval(ack['tx'])[0]:raise CaptureError('event ACK before receive')
        request=exchange(s,t,b'\x0d\x23'+h.to_bytes(2,'little')+b'\0'+bytes.fromhex(case['reply']),case)
        response=exchange(t,s,b'\x0e\x03'+h.to_bytes(2,'little')+b'\0'+bytes.fromhex(case['reply']),case)
        if packet_interval(event['rx'])[1]>packet_interval(request['tx'])[0]or packet_interval(request['rx'])[1]>packet_interval(response['tx'])[0]:raise CaptureError('reply cannot precede complete event/request receipt')
        endpoints={(v['bus'],v['device'],v['handle'])for v in identities}
        window=[p for p in inventory if (p['bus'],p['device'],p['handle'])in endpoints and case['start_wall_ns']<=p['wall_ns']<=case['end_wall_ns']and p['data'].startswith('0a00')]
        expected=[leg[side]for leg in legs[start:]for side in ('tx','rx')]
        canonical=lambda xs:sorted(json.dumps(p,sort_keys=True)for p in xs)
        if canonical(window)!=canonical(expected):raise CaptureError('missing/extra event-window packets;no hidden CPCD or ACK')
        observed.extend(copy.deepcopy(window))
    cleanup=item['cleanup'];lists=re.findall(r'^SsapLocalServices: (.+)$',cleanup['stdout'],re.M)
    if (not item['cases'][-1]['end_wall_ns']<=cleanup['start_wall_ns']<=cleanup['end_wall_ns']<=item['end_wall_ns']
            or type(cleanup['exit'])is not int or cleanup['exit']!=0 or cleanup['stderr']or len(lists)!=1 or any(x[0]==item['start']for x in json.loads(lists[0]))
            or cleanup['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',server['owner']['path'],'ssap-list']):raise CaptureError('actual owner removal required')
    return dict(status=STATUS,version=VERSION,sender=s,target=t,wire=legs,window_packets=observed,case=copy.deepcopy(item),context=copy.deepcopy({k:row[k]for k in ('phase','owners','ssap_receipts')})),credit


def corroborate(row,matched,*,inventory=None):
    selected=row.get('ssap_event_delivery_required',False)
    if type(selected)is not bool:raise CaptureError('typed event selection required')
    if not selected:
        if any(k.startswith('ssap_event_delivery_')for k in row if k!='ssap_event_delivery_required'):raise CaptureError('unrequested event evidence')
        return [],{0:0,1:0}
    if (type(row.get('ssap_event_delivery_version'))is not int or row['ssap_event_delivery_version']!=VERSION
            or row.get('ssap_event_delivery_status')!=PENDING or type(inventory)is not list
            or [x['sender']for x in row.get('ssap_event_delivery_cases',[])]!=[0,1]):raise CaptureError('complete event evidence and raw inventory required')
    proof=[];credit={0:0,1:0}
    for item in row['ssap_event_delivery_cases']:
        value,used=_case(row,item,matched,inventory);proof.append(value)
        for k in credit:credit[k]+=used[k]
    return proof,credit


def valid_summary(proof):
    try:
        if proof.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'or len(proof['proofs'])!=2:return False
        fresh=set()
        for phase,row in enumerate(proof['proofs']):
            if type(row['phase'])is not int or row['phase']!=phase or [i['sender']for i in row['ssap_event_deliveries']]!=[0,1]:return False
            for item in row['ssap_event_deliveries']:
                if item['status']!=STATUS or type(item['version'])is not int or item['version']!=VERSION or item['context']['phase']!=phase or item['context']['owners']!=row['owners']:return False
                packets=copy.deepcopy([p for leg in item['wire']for p in (leg['tx'],leg['rx'])])
                def matched(owner,direction,payload,window):
                    key=(owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,payload.hex())
                    found=[p for p in packets if tuple(p[k]for k in ('bus','device','handle','direction','data'))==key and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
                    if len(found)!=1:raise CaptureError('one retained event packet required')
                    packets.remove(found[0]);return found[0]
                rebuilt,_=_case(item['context'],item['case'],matched,item['window_packets'])
                if packets or json.dumps(rebuilt,sort_keys=True)!=json.dumps(item,sort_keys=True):return False
                for c in item['case']['cases']:
                    for k in ('value','reply'):
                        if c[k]in fresh:return False
                        fresh.add(c[k])
        return True
    except (KeyError,AttributeError,TypeError,ValueError,IndexError):return False


def valid_manifest(record):
    try:
        selected=record.get('ssap_event_delivery_requested',False)
        if type(selected)is not bool or boot_requested([t for arg in record.get('qemu_args',[])for t in arg.split()])!=selected:return False
        proof=record.get('channel_socket_corroboration',{})
        if not selected:return record.get('ssap_event_delivery_acceptance',False)is False and 'ssap_event_delivery_version'not in record and not any('ssap_event_deliveries'in r for r in proof.get('proofs',[]))
        return(type(record.get('ssap_event_delivery_version'))is int and record['ssap_event_delivery_version']==VERSION
               and record.get('ssap_event_delivery_acceptance')is True and record.get('ssap_owned_requested')is True
               and record.get('ssap_owned_acceptance')is True and record.get('ordinary_channel_socket_acceptance')is True
               and record.get('status')=='PASSTHROUGH_SUPPORT_PASS'and type(record.get('qemu_exit'))is int and record['qemu_exit']==0 and valid_summary(proof))
    except (KeyError,AttributeError,TypeError,ValueError):return False
