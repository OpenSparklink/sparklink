# SPDX-License-Identifier: GPL-2.0-only
"""Finite real WRITE Provider gate on existing Owned/SDK/paired-USB facilities.

No protocol Engine. Expected wire bytes are the independent existing oracle.
Local acceptance, app memory and peer reply are all required, none substitutes
for the other. This first gate is type0 verified short WriteReq only.
"""
import copy
import errno
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from ws73_capture import CaptureError, packet_interval
from ws73_ssap_read_provider import _cleanup, _wire
import ws73_ssap_sdk_read_provider as shared
from ws73_ssap_provider_owner_exit import CLOCK_CONTRACT, _clock_sample

PREFIX='ssap_sdk_write_provider'
TOKEN='ws73.'+PREFIX+'=1'
VERSION=1
STATUS='SDK_WRITE_PROVIDER_APPLICATION_PAIRED_USB'
PENDING='SDK_WRITE_PROVIDER_PENDING_PAIRED_USB'
COLLECTION=PREFIX+'_cases'
SUMMARY_KEY=PREFIX+'s'
MODES=('application-error-ff','value31','value32')
EXTRA_TOOLS=shared.EXTRA_TOOLS+('/usr/share/sparklink/tools/ws73_ssap_sdk_write_provider.py',)
REQUEST=shared.REQUEST-{'maximum_bytes'}|{'operation','data_type','offset','value_length','verify','value'}
REPLY=shared.REPLY|{'matched_value','accepted_value'}
VALUE={'api','property','value','application_memory_only'}
need,integer,json_rows=shared.need,shared.integer,shared.json_rows


def requested(args, *, passthrough=None, selector=PREFIX):
    selected=getattr(args,selector+'_verify',False)
    need(type(selected)is bool,'explicit WRITE Provider selector required')
    if not selected:return False
    need(not any(getattr(args, name+'_verify',False) for name in
        ('ssap_sdk_write_provider','ssap_write_provider_unregister','ssap_write_provider_deadline') if name != selector),
        'one dedicated WRITE scenario required')
    if passthrough is None:passthrough=getattr(args,'passthrough',False)
    incompatible=('ssap_read_provider_verify','ssap_sdk_read_provider_verify','ssap_provider_owner_exit_verify',
        'ssap_provider_unregister_verify','ssap_provider_deadline_verify','ssap_description_verify','parallel','parallel_business',
        'application_client_verify','ssap_write_command_verify','ssap_owned_update_verify','ssap_update_delivery_verify',
        'ssap_value_lengths_verify','ssap_requester_lifecycle_verify','ssap_owner_lifecycle_verify','ssap_initialization_verify',
        'ssap_subscription_verify','ssap_sender_deadline_verify','channel_benchmark','dynamic_channel_verify',
        'channel_fairness_verify','channel_socket_boundaries','channel_socket_close_prefix','channel_socket_burst')
    need(passthrough and getattr(args,'ssap_owned_verify',False) and getattr(args,'channel_socket_verify',False)
         and getattr(args,'channel_socket_rounds',4)==4 and getattr(args,'channel_socket_bytes',61)==61
         and getattr(args,'security_agent',None)is None and not any(getattr(args,k,False)for k in incompatible),
         'WRITE Provider requires dedicated ordinary61/4 Owned gate')
    return True


def boot_requested(tokens, *, selector=PREFIX):
    need(type(tokens)in(list,tuple)and all(type(t)is str for t in tokens),'tokenized boot arguments required')
    token='ws73.'+selector+'=1'
    found=[t for t in tokens if t=='ws73.'+selector or t.startswith('ws73.'+selector+'=')]
    need(found in ([],[token]),'one exact WRITE Provider boot token required')
    if found:
        need(not any(t == 'ws73.'+name or t.startswith('ws73.'+name+'=') for name in
            ('ssap_sdk_write_provider','ssap_write_provider_unregister','ssap_write_provider_deadline')
            if name != selector for t in tokens), 'one dedicated WRITE boot scenario required')
        need(tokens.count('ws73.ssap_owned=1')==1 and not any(t.startswith(('ws73.ssap_read_provider','ws73.ssap_sdk_read_provider','ws73.ssap_provider_'))for t in tokens),
             'WRITE Provider boot dependencies/conflicts differ')
    return bool(found)


def tool_records(root=Path('/')):
    records=shared.tool_records(root);p=root/EXTRA_TOOLS[-1].lstrip('/')
    records[EXTRA_TOOLS[-1]]=dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
    return records


def validate_tools(records,root,manifest):
    need(records==tool_records(root),'fresh exact WRITE consumer/tool identities required')
    shared.validate_tools({k:v for k,v in records.items()if k!=EXTRA_TOOLS[-1]},root,manifest)
    path=(root/EXTRA_TOOLS[-1].lstrip('/')).resolve(strict=True)
    found=[p for p in manifest if Path(p['path']).resolve()==path]
    need(len(found)==1 and found[0]['sha256']==records[EXTRA_TOOLS[-1]]['sha256'],'WRITE verifier absent from build manifest')


def validate_inputs(package):
    shared.validate_inputs(package)
    path=Path(__file__).resolve();found=[p for p in package.get('inputs',[])if Path(p['path']).resolve()==path]
    need(len(found)==1 and found[0]['sha256']==hashlib.sha256(path.read_bytes()).hexdigest(),'fresh WRITE verifier input required')


def validate_rows(rows,selected):
    need(type(rows)is list and type(selected)is bool,'explicit WRITE rows required')
    for phase,row in enumerate(rows):
        need(type(row.get(PREFIX+'_required',False))is bool and row.get(PREFIX+'_required',False)==selected,'WRITE selector/row mismatch')
        if not selected:
            need(not any(k.startswith(PREFIX)and k!=PREFIX+'_required'for k in row),'unrequested WRITE evidence');continue
        need(type(row['phase'])is int and row['phase']==phase and row.get('ssap_owned_required')is True
             and len(row.get('ssap_owned',[]))==4 and type(row.get(PREFIX+'_version'))is int
             and row[PREFIX+'_version']==VERSION and len(row.get(COLLECTION,[]))==1,'complete original Owned and one WRITE owner per role required')
    if selected:need(len(rows)==2 and len({(r['owners'][1]['owner']['index'],r['owners'][1]['owner']['generation'])for r in rows})==2,'two physical WRITE receivers required')


def execute(run,row):
    from ws73_application_client import ssap_commands,ssap_error_command
    from ws73_ssap_owned import publisher,wait_output,await_removed
    need(row.get('ssap_owned_required')is True and len(row.get('ssap_owned',[]))==4,'original Owned baseline must finish first')
    row.update({PREFIX+'_required':True,PREFIX+'_version':VERSION,PREFIX+'_tools':tool_records(),COLLECTION:[]})
    source,target=row['owners'];api='c'if row['phase']==0 else'python';peer_api='python'if api=='c'else'c'
    with publisher(run,row,0,'allow',collection=COLLECTION,label='sdk-write-provider',sdk_api=api,operations=6,write_provider=True)as(process,item):
        item.update(steps=[],prepared_wall_ns=time.time_ns())
        item['bind_before_monotonic_ns']=time.monotonic_ns();item['bind_before_wall_ns']=time.time_ns()
        process.stdin.write('provider\n');process.stdin.flush()
        item['bound']=shared._wait_json(process,item,'SdkWriteProviderBound',shared.BOUND,1,item['bind_before_monotonic_ns']+5_000_000_000)
        item['bound_wall_ns']=time.time_ns();run.save()
        for ordinal,mode in enumerate(MODES,1):
            value=secrets.token_bytes(31 if ordinal==2 else 32)
            need(value.hex()!=item['secret'],'fresh proposed WRITE value required')
            step=dict(mode=mode,value=value.hex(),clock_contract=copy.deepcopy(CLOCK_CONTRACT),clock_before=_clock_sample())
            item['steps'].append(step);run.save()
            def answer(app,supervisor):
                step['call']=app
                d=shared._wait_json(process,item,'SdkWriteProviderRequest',REQUEST,ordinal,supervisor)
                observed=time.monotonic_ns();need(integer(d['deadline_ns'])and observed<d['deadline_ns']and process.poll()is None,'live original WRITE request required')
                # The real application also compares this expected value itself.
                need(d['value']==value.hex(),'actual WRITE request differs from prepared peer payload')
                c=dict(prompt=d,observed_monotonic_ns=observed,observed_wall_ns=time.time_ns(),publisher_pid=process.pid,supervisor_deadline_ns=supervisor)
                step['callback']=c;step['reply_command']=f'provider-error p{d["token"]} FF'if ordinal==1 else f'provide p{d["token"]} {value.hex()}'
                c.update(reply_before_monotonic_ns=time.monotonic_ns(),reply_before_wall_ns=time.time_ns())
                need(c['reply_before_monotonic_ns']<min(d['deadline_ns'],supervisor),'original WRITE reply deadline expired')
                process.stdin.write(step['reply_command']+'\n');process.stdin.flush()
                c.update(replied_monotonic_ns=time.monotonic_ns(),replied_wall_ns=time.time_ns())
                step['reply']=shared._wait_json(process,item,'SdkWriteProviderReply',REPLY,ordinal,min(d['deadline_ns'],supervisor));run.save()
            args=['ssap-write',source['object']['path'],str(item['handle']),value.hex()]
            step['call']=(ssap_error_command(run,row,source,args,errno.EIO,api=peer_api,after_start=answer)if ordinal==1 else
                          ssap_commands(run,row,[(source,args,value)],api=peer_api,expected_size=len(value),after_start=answer)[0])
            step['clock_after']=_clock_sample()
            step['value_before_ns']=time.monotonic_ns();step['value_before_wall_ns']=time.time_ns()
            process.stdin.write('value\n');process.stdin.flush()
            step['application_value']=shared._wait_json(process,item,'SdkWriteProviderValue',VALUE,ordinal,step['value_before_ns']+2_000_000_000)
            step['value_after_ns']=time.monotonic_ns();step['value_after_wall_ns']=time.time_ns();run.save()
        item['quit_wall_ns']=time.time_ns();process.stdin.write('quit\n');process.stdin.flush();wait_output(process,2)
        need(process.returncode==0,'WRITE publisher cleanup failed');item['owner_exit_wall_ns']=time.time_ns()
        item['cleanup']=await_removed(run,target,item['start'])
        item['retired_read']=run.command([str(run.args.slctl),'--adapter',source['owner']['path'],'ssap-read',source['object']['path'],str(item['handle']),'0'],10,collection=PREFIX+'_retired');run.save()
    row[PREFIX+'_status']=PENDING;run.save()


def _case(row,item,matched):
    from ws73_application_client import (owned_arguments,application_environment,_ssap_process_receipt,
        ssap_receipt,ssap_error_receipt,authorization_context,AUTHORIZATION_CONTEXT_FIELDS)
    from ws73_ssap_owned import verify_output
    from ws73_ssap_command import _identity
    from ws73_ssap_update_delivery import TOOLS
    from ws73_ssap_access import value_operations
    verify_output(item);_ssap_process_receipt(item,1000)
    need(type(row['phase'])is int and row['phase']in(0,1),'two ordered physical WRITE roles required')
    api='c'if row['phase']==0 else'python';peer_api='python'if api=='c'else'c';source,target=row['owners'];identities=[_identity(x)for x in row['owners']]
    records=row[PREFIX+'_tools']
    need(type(records)is dict and set(records)==set(TOOLS)|set(EXTRA_TOOLS)and all(type(v)is dict and set(v)=={'sha256','bytes'}and integer(v['bytes'])and type(v['sha256'])is str and re.fullmatch('[0-9a-f]{64}',v['sha256'])for v in records.values()),'exact WRITE tool provenance required')
    need(len({(i['index'],i['generation'])for i in identities})==2 and len({(i['bus'],i['device'])for i in identities})==2,'independent controllers required')
    h=item['handle'];need(all(type(item[k])is int for k in ('sender','target','start','end','handle','pid','operations','sdk_write_provider_contract_version'))
        and(item['sender'],item['target'],item['operations'],item['sdk_write_provider_contract_version'])==(0,1,6,1)
        and 0<item['start']<h==item['end']<65536 and item['pid']>0 and item['policy']=='allow'and item['publisher_api']==api,'original write-only SDK owner required')
    need(all(type(item[k])is str and re.fullmatch('[0-9a-f]{32}',item[k])for k in ('service','uuid'))and re.fullmatch('[0-9a-f]{64}',item['secret'])
        and item['environment']==application_environment()and item['args']==owned_arguments(api,target,item['service'],item['uuid'],item['secret'],'allow',write_provider=True),'exact WRITE owner argv/environment required')
    lines=item['stdout'].splitlines();bound=json_rows(item['stdout'],'SdkWriteProviderBound',shared.BOUND,1)[0]
    requests=json_rows(item['stdout'],'SdkWriteProviderRequest',REQUEST,3);replies=json_rows(item['stdout'],'SdkWriteProviderReply',REPLY,3)
    values=json_rows(item['stdout'],'SdkWriteProviderValue',VALUE,3)
    approvals=json_rows(item['stdout'],'SdkAuthorizationDecision',AUTHORIZATION_CONTEXT_FIELDS|{'allow','decision_ns','decision_wall_ns'},3)
    need(len(lines)==16 and lines[:2]==[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={h} property={h}; local registration only']and lines[2].startswith('SdkWriteProviderBound: ')
        and lines[-1]==f'SdkOwnedRemoved: api={api} start={item["start"]}'and all([l.split(': ',1)[0]for l in lines[3+i*4:7+i*4]]==['SdkAuthorizationDecision','SdkWriteProviderRequest','SdkWriteProviderReply','SdkWriteProviderValue']for i in range(3)),'exact complete WRITE transcript required')
    need(bound==item['bound']and bound['api']==api and (bound['index'],bound['generation'],bound['property'])==(identities[1]['index'],identities[1]['generation'],h)
        and all(type(bound[k])is int for k in ('index','generation','property','result','notification_result'))and bound['result']==bound['notification_result']==0
        and bound['notification_ready']is True and bound['local_binding_only']is True and all(integer(bound[k])for k in ('started_ns','deadline_ns','returned_ns'))
        and item['bind_before_monotonic_ns']<=bound['started_ns']<=bound['returned_ns']<bound['deadline_ns']and 0<bound['deadline_ns']-bound['started_ns']<=5_000_000_000,'original successful bounded WRITE bind required')
    need(type(item['steps'])is list and [s['mode']for s in item['steps']]==list(MODES),'complete ordered WRITE scenarios required')
    need(row['ssap_language_clients']==[s['call']for s in item['steps']]and len({a['pid']for a in row['ssap_language_clients']})==3,'exact three actual peer processes required')
    stamps=[item[k]for k in ('start_wall_ns','prepared_wall_ns','bind_before_wall_ns','bound_wall_ns')];exchanges=[];pdus=[];limits=[];seen={item['secret']};outcomes=[]
    for ordinal,(s,d,r,a,v)in enumerate(zip(item['steps'],requests,replies,approvals,values,strict=True)):
        payload=s['value'];need(type(payload)is str and re.fullmatch('[0-9a-f]+',payload)and len(payload)==(62 if ordinal==1 else 64)and payload not in seen,'fresh full random WRITE payload required');seen.add(payload)
        c,app=s['callback'],s['call'];need(d['api']==api and all(integer(d[k],zero=True)for k in REQUEST-{'api','verify','value'})and d['verify']is True and d['value']==payload
            and all(d[k]for k in ('token','request_id','lifetime','epoch','deadline_ns','property','observed_ns','observed_wall_ns'))
            and tuple(d[k]for k in ('index','generation','lifetime','handle','property'))==(identities[1]['index'],identities[1]['generation'],identities[1]['lifetime'],identities[1]['handle'],h)
            and(d['level'],d['local_tcid'],d['remote_tcid'],d['pi'],d['operation'],d['data_type'],d['offset'],d['value_length'])==(0,10,10,0,13,0,0,len(payload)//2)
            and c['prompt']==d and c['publisher_pid']==item['pid'],'original WRITE context/value/operation required')
        authorization_context({k:a[k]for k in AUTHORIZATION_CONTEXT_FIELDS},api)
        need(a['allow']is True and a['write']is True and a['data_type']==0 and a['value']==payload and all(integer(a[k])for k in ('decision_ns','decision_wall_ns'))
            and all(a[k]==d[k]for k in ('index','generation','request_id','lifetime','handle','epoch','level','deadline_ns','property','local_tcid','remote_tcid','pi'))
            and a['decision_ns']<=d['observed_ns']and a['decision_wall_ns']<=d['observed_wall_ns'],'independent original WRITE policy approval required')
        if ordinal:need(all(d[k]>requests[ordinal-1][k]for k in ('token','request_id'))and all(d[k]==requests[0][k]for k in ('index','generation','lifetime','handle','epoch','level','property','local_tcid','remote_tcid','pi')),'new request/token within unchanged lifetime required')
        accepted=None if ordinal==0 else payload;response=''if ordinal==0 else payload;status=255 if ordinal==0 else 0
        command=f'provider-error p{d["token"]} FF'if ordinal==0 else f'provide p{d["token"]} {payload}'
        need(r==s['reply']and r['api']==api and r['token']==r['current_token']==d['token']and r['api_called']is True and r['matched_value']is True and r['local_acceptance_only']is True
            and type(r['result'])is int and r['result']==0 and type(r['status'])is int and r['status']==status and r['value']==response and r['accepted_value']==accepted
            and r['deadline_ns']==d['deadline_ns']and all(integer(r[k])for k in ('token','current_token','deadline_ns','started_ns','returned_ns'))and s['reply_command']==command,'actual local WRITE reply must match original request')
        need(v==s['application_value']and v==dict(api=api,property=h,value=accepted,application_memory_only=True)and type(v['property'])is int,'actual application memory must match accepted/rejected WRITE')
        need(app['api']==peer_api and app['ssap_operation']=='ssap-write'and app['ssap_handle']==h,'opposite language real WRITE requester required')
        if ordinal==0:
            call=ssap_error_receipt(app,source,expected_errno=errno.EIO);origin,upper=call['call_ns'],min(call['returned_ns'],d['deadline_ns']);need(app['ssap_proposed']==payload and c['supervisor_deadline_ns']==app['ssap_supervisor_deadline_ns'],'exact failed WRITE payload/deadline required')
        else:
            ssap_receipt(app,source,expected_size=len(payload)//2);need(app['ssap_expected']==payload,'peer must validate accepted bytes');origin,upper=app['ssap_release_monotonic_ns'],d['deadline_ns'];need(c['supervisor_deadline_ns']==origin+7_000_000_000,'original positive peer supervisor required')
        times=[origin,a['decision_ns'],d['observed_ns'],c['observed_monotonic_ns'],c['reply_before_monotonic_ns'],r['started_ns'],r['returned_ns'],d['deadline_ns']]
        need(all(integer(t)for t in times)and times==sorted(times)and r['returned_ns']<d['deadline_ns']and c['reply_before_monotonic_ns']<=c['replied_monotonic_ns']<d['deadline_ns']<=c['supervisor_deadline_ns']and 0<d['deadline_ns']-d['observed_ns']<=5_000_000_000,'original WRITE deadline and actual callback order required')
        need(all(integer(s[k])for k in ('value_before_ns','value_after_ns'))and s['clock_after']['monotonic_after_ns']<=s['value_before_ns']<=s['value_after_ns']<=s['value_before_ns']+2_000_000_000,'bounded application memory observation after actual peer result required')
        stamps += [app['start_wall_ns'],c['observed_wall_ns'],c['reply_before_wall_ns'],c['replied_wall_ns'],app['end_wall_ns'],s['value_before_wall_ns'],s['value_after_wall_ns']]
        _,request,reply=value_operations(h,b'',b'',bytes.fromhex(payload),status)[2]
        exchanges.append((app,reply,c));pdus.append(request);limits.append((shared._clocks(s,operation_key='call'),origin,upper,d['observed_ns'],r['started_ns']))
        outcomes.append(dict(mode=s['mode'],application_bytes=len(payload)//2,accepted=accepted,peer_validated=ordinal!=0,sdk_errno=errno.EIO if ordinal==0 else 0))
    _cleanup(row,item);removed=item['retired_read'];stamps += [item['quit_wall_ns'],item['owner_exit_wall_ns'],item['cleanup']['start_wall_ns'],item['cleanup']['end_wall_ns'],removed['start_wall_ns'],removed['end_wall_ns'],item['end_wall_ns']]
    need(all(integer(t)for t in stamps)and stamps==sorted(stamps),'original WRITE owner/call/cleanup chronology required')
    exchanges.append((removed,b'\x09\x0b\x04\0',None));pdus.append(b'\x08\x03'+h.to_bytes(2,'little')+b'\0')
    wire,credit=_wire(row,item,matched,exchanges,requests=pdus)
    for i in range(0,len(wire),2):
        request,response=wire[i:i+2];need(all(packet_interval(p['tx'])[1]<=packet_interval(p['rx'])[0]for p in (request,response))and packet_interval(request['rx'])[1]<=packet_interval(response['tx'])[0],'two-end WRITE causal order required')
        if i<6:
            offset,origin,upper,observed,answered=limits[i//2]
            need(all(shared._packet_mono(p,offset)[0]>=origin and shared._packet_mono(p,offset)[1]<observed for p in request.values()),'paired WRITE request must follow peer call and precede callback')
            need(all(shared._packet_mono(p,offset)[0]>=answered and shared._packet_mono(p,offset)[1]<upper for p in response.values()),'paired WRITE response must follow app answer within original completion')
    context=copy.deepcopy({k:row[k]for k in ('phase','owners','ssap_receipts','ssap_language_clients')})
    return dict(status=STATUS,version=VERSION,sender=0,target=1,provider_api=api,peer_api=peer_api,outcomes=outcomes,wire=wire,tools=copy.deepcopy(records),context=context,case=copy.deepcopy(item)),credit


def corroborate(row,matched):
    selected=row.get(PREFIX+'_required',False);need(type(selected)is bool,'explicit WRITE request required')
    if not selected:
        need(not any(k.startswith(PREFIX)and k!=PREFIX+'_required'for k in row),'unrequested WRITE evidence');return [],{0:0,1:0}
    need(type(row.get(PREFIX+'_version'))is int and row[PREFIX+'_version']==VERSION and len(row.get(COLLECTION,[]))==1,'one original WRITE case required')
    item,credit=_case(row,row[COLLECTION][0],matched);return [item],credit


def valid_summary(proof, *, version=VERSION):
    try:
        need(type(version)is int and version==VERSION and len(proof['proofs'])==2,'two WRITE phase proofs required');receivers=set();values=set()
        for phase,row in enumerate(proof['proofs']):
            items=row[SUMMARY_KEY];need(type(row['phase'])is int and row['phase']==phase and len(items)==1,'exact WRITE phase proof required');item=items[0];context=copy.deepcopy(item['context'])
            need(type(item['version'])is int and item['version']==VERSION and context['phase']==phase and context['owners']==row['owners']and len(item['wire'])==8,'WRITE proof context mismatch')
            packets=[copy.deepcopy(leg[side])for leg in item['wire']for side in ('tx','rx')]
            def matched(owner,direction,frame,window):
                key=(owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
                found=[p for p in packets if tuple(p[k]for k in ('bus','device','handle','direction','data'))==key and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
                need(len(found)==1,'one retained paired WRITE packet required');packets.remove(found[0]);return found[0]
            context[PREFIX+'_tools']=item['tools'];rebuilt,_=_case(context,item['case'],matched)
            need(not packets and rebuilt==item,'WRITE proof must replay exact receipts and both captures')
            owner=row['owners'][1]['owner'];receivers.add((owner['index'],owner['generation']));values.update(s['value']for s in item['case']['steps'])
        return len(receivers)==2 and len(values)==6
    except (KeyError,AttributeError,IndexError,TypeError,ValueError,StopIteration):return False


def valid_manifest(record):
    try:
        selected=record.get(PREFIX+'_requested',False);need(type(selected)is bool,'explicit WRITE manifest selector required')
        need(boot_requested([t for arg in record.get('qemu_args',[])for t in arg.split()])==selected,'WRITE boot/manifest mismatch');proof=record.get('channel_socket_corroboration',{})
        if not selected:return record.get(PREFIX+'_acceptance',False)is False and not any(PREFIX+s in record for s in ('_version','_verifier','_tools'))and not any(SUMMARY_KEY in r for r in proof.get('proofs',[]))
        v=record[PREFIX+'_verifier'];need(type(v)is dict and set(v)=={'path','sha256','bytes'}and type(v['path'])is str and Path(v['path']).name=='ws73_ssap_sdk_write_provider.py'and integer(v['bytes'])and re.fullmatch('[0-9a-f]{64}',v['sha256']),'exact WRITE verifier identity required')
        for row in proof.get('proofs',[]):
            for item in row.get(SUMMARY_KEY,[]):need(item['tools'][EXTRA_TOOLS[-1]]=={k:v[k]for k in ('sha256','bytes')},'WRITE verifier differs from guest tool')
        return (record.get('status')=='PASSTHROUGH_SUPPORT_PASS' and type(record.get('qemu_exit'))is int and record['qemu_exit']==0
                and record.get('ssap_owned_acceptance')is True and record.get('ordinary_channel_socket_acceptance')is True
                and type(record.get(PREFIX+'_version'))is int and record[PREFIX+'_version']==VERSION and record.get(PREFIX+'_acceptance')is True and valid_summary(proof))
    except (KeyError,AttributeError,IndexError,TypeError,ValueError):return False
