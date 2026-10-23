# SPDX-License-Identifier: GPL-2.0-only
"""One finite real CPCD/update/application-reply gate in the existing VM runner.

Actual SDK apps perform the receive/check/reply. This supervisor does not send
SSAP,acknowledge a fake peer or implement a Host. Paired raw USB legs remain
necessary and are checked independently against fixed packet bytes below.
"""
from pathlib import Path
import json
import os
import re
import secrets
import subprocess
import time
import hashlib
from ws73_capture import CaptureError
from ws73_channel_socket import credentials
from ws73_ssap_owned import publisher, wait_text, value_snapshot, await_removed, observed_process, output_text, verify_output
from ws73_application_client import application_environment, owned_arguments, authorization_context

LENGTHS=(32,2036,2037,2042)

STATUS='REAL_CPCD_UPDATE_APPLICATION_REPLY_PENDING_PAIRED_CAPTURE'
TOOLS=['/bin/ws73-application-client-c','/usr/share/sparklink/tools/ws73-application-client.py',
    '/usr/lib/libsparklink.so.0','/usr/share/sparklink/python/sparklink/client.py',
    '/usr/share/sparklink/python/sparklink/local_services.py','/usr/share/sparklink/python/sparklink/service_authorization.py']

def contract_version(package):
    value=package.get('ssap_update_delivery_contract_version',1)
    if type(value)is not int or value not in (1,2):raise ValueError('unknown update delivery contract')
    return value

def matrix(row):
    value=row.get('ssap_update_delivery_version',1)
    if type(value)is not int or value not in (1,2):raise CaptureError('explicit supported update delivery version required')
    return (32,) if value==1 else LENGTHS

def requested(args,*,passthrough):
    value=getattr(args,'ssap_update_delivery_verify',False)
    if type(value)is not bool:raise ValueError('explicit update delivery boolean required')
    if value and (not passthrough or not getattr(args,'channel_socket_verify',False)
            or getattr(args,'security_agent',None)!='numeric-approve'
            or any(getattr(args,k,False)for k in ['ssap_owned_verify','ssap_owned_update_verify','ssap_owner_lifecycle_verify',
                'ssap_requester_lifecycle_verify','channel_socket_close_prefix','channel_socket_burst','channel_socket_boundaries',
                'dynamic_channel_verify','channel_fairness_verify'])):
        raise ValueError('CPCD update delivery requires dedicated numeric-approve protected socket gate')
    return value

def tool_records(root=Path('/')):
    return {name:dict(sha256=hashlib.sha256((root/name.lstrip('/')).read_bytes()).hexdigest(),
        bytes=(root/name.lstrip('/')).stat().st_size)for name in TOOLS}

def validate_tools(records,root,manifest):
    if records!=tool_records(root):raise CaptureError('executed update apps/SDK differ from sealed root')
    for name,receipt in records.items():
        actual=(root/name.lstrip('/')).resolve(strict=True)
        matches=[p for p in manifest if Path(p['path']).resolve()==actual]
        if len(matches)!=1 or matches[0]['sha256']!=receipt['sha256']:
            raise CaptureError('update app/SDK missing from build manifest')

def command_receipt(process,item,command,prefix,*,limit=32,before_receipt=None):
    path=Path(item['output_files'][0]);pattern='^'+re.escape(prefix)+r': (.+)$'
    count=len(re.findall(pattern,output_text(process,path),re.M))
    start=time.monotonic_ns();wall=time.time_ns()
    deadline=time.monotonic()+5
    process.stdin.write(command+'\n');process.stdin.flush()
    if before_receipt is not None:before_receipt()
    rows,_=wait_text(process,path,pattern,deadline,min_count=count+1,max_count=limit)
    if time.monotonic()>=deadline:raise CaptureError('original SDK receipt observation deadline')
    if len(rows)!=count+1:raise CaptureError('one actual SDK receipt per command required')
    return dict(start_wall_ns=wall,end_wall_ns=time.time_ns(),start_monotonic_ns=start,
        end_monotonic_ns=time.monotonic_ns(),receipt=json.loads(rows[-1]))

def configuration(process,item,wanted,peer=None):
    observations=[];deadline=time.monotonic()+3
    while True:
        if peer is not None and peer.poll()is not None:raise CaptureError('peer exited before actual CPCD state barrier')
        observed=command_receipt(process,item,'configuration','SdkOwnedConfiguration');observations.append(observed)
        if observed['receipt'].get('modes')==wanted:return observations
        if time.monotonic()>=deadline or len(observations)>=12:raise CaptureError('actual CPCD state barrier not reached')
        time.sleep(.1)

def discover(run,peer,item):
    # The one advisory cache is published only by complete hierarchy
    # discovery. A filtered result does not replace it or grant access.
    item['full_discovery']=run.command([str(run.args.slctl),'--adapter',peer['owner']['path'],
        'ssap-discover',peer['object']['path']],10,collection='ssap_update_delivery_discovery')
    if item['full_discovery']['exit']:raise CaptureError('actual complete peer hierarchy refresh failed')
    item['discovery']=run.command([str(run.args.slctl),'--adapter',peer['owner']['path'],
        'ssap-discover',peer['object']['path'],'property',item['uuid']],10,collection='ssap_update_delivery_discovery')
    if item['discovery']['exit']:raise CaptureError('actual owned CPCD property discovery failed')

def execute(run,row):
    if row.get('security_requirement')!=2 or not row.get('message_security_required'):
        raise CaptureError('update delivery requires actual protected2 baseline,not local approval')
    row.update(ssap_update_delivery_required=True,ssap_update_delivery_version=2,ssap_update_delivery_output_contract_version=1,ssap_update_delivery_lengths=list(LENGTHS),ssap_update_delivery=[],ssap_update_delivery_tools=tool_records());run.save()
    for sender in (0,1):
        peer,server=row['owners'][sender],row['owners'][1-sender]
        api='c'if(row['phase']+sender)%2==0 else'python';peer_api='python'if api=='c'else'c'
        with publisher(run,row,sender,'allow',collection='ssap_update_delivery',label='delivery',sdk_api=api,updates=True) as (owner,item):
            discover(run,peer,item)
            item['cases']=[];run.save()
            for sequence,(size,mode) in enumerate((size,mode)for size in LENGTHS for mode in(1,2)):
                value=(sequence.to_bytes(4,'little')+secrets.token_bytes(size-4)).hex()
                reply=((sequence|0x80000000).to_bytes(4,'little')+secrets.token_bytes(size-4)).hex()
                if value==reply or value==item['secret']:raise CaptureError('independent random business values required')
                case=dict(mode=mode,sequence=sequence,application_bytes=size,value=value,reply=reply,start_wall_ns=time.time_ns());item['cases'].append(case);run.save()
                case['replacement']=command_receipt(owner,item,'replace '+value,'SdkOwnedReplaced')
                case['before']=value_snapshot(owner,item,value)
                prefix=['/bin/ws73-application-client-c']if peer_api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
                args=prefix+['update-peer',str(peer['owner']['index']),str(peer['owner']['generation']),
                    peer['object']['path'],str(item['handle']),str(mode),value,reply]
                out=run.output/f'update-peer-{row["phase"]}-{sender}-{mode}-{size}.stdout';err=out.with_suffix('.stderr')
                app=dict(api=peer_api,args=args,start_wall_ns=time.time_ns(),environment=application_environment(),output_files=[str(out),str(err)])
                case['application']=app;run.save();process=None
                try:
                    with observed_process(args,app,out,err,env=dict(os.environ,**application_environment()),text=True)as process:
                        app.update(pid=process.pid,credentials=credentials(process.pid));run.save()
                        wait_text(process,out,r'^\{.*"stage"\s*:\s*"ssap_update_wait".*\}$',time.monotonic()+5)
                        case['enabled']=configuration(owner,item,mode,process);run.save()
                        case['send']=command_receipt(owner,item,'indicate'if mode==2 else'notify','SdkOwnedUpdate');run.save()
                        process.wait(timeout=10)
                        if process.returncode:raise CaptureError('ordinary peer application did not validate/reply')
                finally:
                    run.save()
                case['disabled']=configuration(owner,item,0)
                case['after']=value_snapshot(owner,item,reply)
                case['end_wall_ns']=time.time_ns();run.save()
            owner.stdin.write('quit\n');owner.stdin.flush();owner.wait(timeout=2)
            if owner.returncode:raise CaptureError('original provider unregister failed')
            item['cleanup']=await_removed(run,server,item['start']);run.save()
    row['ssap_update_delivery_status']=STATUS;run.save()

def sdk_receipt(observation,api,handle,kind):
    receipt=observation['receipt'];required={'api','handle','started_ns','deadline_ns','returned_ns'}|kind
    if set(receipt)!=required or receipt['api']!=api or receipt['handle']!=handle:
        raise CaptureError('typed original SDK command receipt required')
    if (not all(type(receipt[k])is int for k in ['handle','started_ns','deadline_ns','returned_ns'])
            or not observation['start_monotonic_ns']<=receipt['started_ns']<=receipt['returned_ns']<=observation['end_monotonic_ns']
            or receipt['deadline_ns']-receipt['started_ns']!=5_000_000_000 or receipt['returned_ns']>=receipt['deadline_ns']):
        raise CaptureError('original bounded SDK operation interval required')
    return receipt

def discovery_wire(item,peer,exchange):
    s,t,h=item['sender'],item['target'],item['handle']
    discovery=item['discovery'];uuid=bytes.fromhex(item['uuid']);end=(h+1).to_bytes(2,'little')
    full=item['full_discovery'];start=item['start'].to_bytes(2,'little');handle=h.to_bytes(2,'little')
    fq=[b'\x04\x11\x01\0\xff\xff',b'\x04\x11'+end+b'\xff\xff',b'\x04\x13'+start+handle]
    fr=[b'\x05\x0b\x81'+start+handle+bytes.fromhex(item['service'])+b'\x02',
        b'\x01\0\x04'+end+b'\x0b',b'\x05\x0b\x81'+handle+uuid+(541).to_bytes(4,'little')+b'\x01\x02']
    full_summary=re.findall(r'^SsapRemoteDiscovery: path=(\S+) kind=(\d+) entries=(\d+) requests=([0-9a-f|]+) responses=([0-9a-f|]+)$',full['stdout'],re.M)
    if (type(full.get('exit'))is not int or full['exit']!=0 or full['stderr']
            or full['args']!=[discovery['args'][0],'--adapter',peer['owner']['path'],'ssap-discover',peer['object']['path']]
            or full_summary!=[(peer['object']['path'],'1','2','|'.join(v.hex()for v in fq),'|'.join(v.hex()for v in fr))]
            or not item['start_wall_ns']<=full['start_wall_ns']<=full['end_wall_ns']<=discovery['start_wall_ns']<=discovery['end_wall_ns']<=item['end_wall_ns']):
        raise CaptureError('original complete hierarchy must refresh this lifetime before filtered discovery')
    for req,rsp in zip(fq,fr,strict=True):exchange(s,t,req,full);exchange(t,s,rsp,full)
    queries=[b'\x06\x13\x01\0\xff\xff'+uuid,b'\x06\x13'+end+b'\xff\xff'+uuid]
    responses=[b'\x07\x0b\x81'+h.to_bytes(2,'little')+uuid+(541).to_bytes(4,'little')+b'\x01\x02',b'\x01\0\x06'+end+b'\x0b']
    if discovery['exit']or discovery['stderr']or discovery['args']!=[item['discovery']['args'][0],'--adapter',peer['owner']['path'],'ssap-discover',peer['object']['path'],'property',item['uuid']]:raise CaptureError('original filtered discovery required')
    summary=re.findall(r'^SsapRemoteDiscovery: path=(\S+) kind=(\d+) entries=(\d+) requests=([0-9a-f|]+) responses=([0-9a-f|]+)$',discovery['stdout'],re.M)
    if summary!=[(peer['object']['path'],'3','1','|'.join(v.hex()for v in queries),'|'.join(v.hex()for v in responses))]:raise CaptureError('actual discovered CPCD operations/schema mismatch')
    for req,rsp in zip(queries,responses,strict=True):exchange(s,t,req,discovery);exchange(t,s,rsp,discovery)

def corroborate(row,matched):
    if not row.get('ssap_update_delivery_required',False):return [],{0:0,1:0}
    items=row.get('ssap_update_delivery',[]);owners=row['owners'];proof=[];credit={0:0,1:0};fresh=set()
    output_version=row.get('ssap_update_delivery_output_contract_version')
    if output_version is not None:
        if type(output_version)is not int or output_version!=1:raise CaptureError('explicit supported pipe output contract required')
        for item in items:
            verify_output(item)
            for case in item.get('cases',[]):verify_output(case['application'])
    lengths=matrix(row);version=row.get('ssap_update_delivery_version',1)
    if version==2 and row.get('ssap_update_delivery_lengths')!=list(LENGTHS):raise CaptureError('complete explicit update length matrix required')
    if (row.get('ssap_update_delivery_status')!=STATUS or len(items)!=2
            or [i.get('sender')for i in items]!=[0,1] or row.get('security_requirement')!=2
            or not row.get('message_security_required')):raise CaptureError('both protected directions and completed delivery gate required')
    for item in items:
        s,t=item['sender'],item['target'];peer,server=owners[s],owners[t];h=item['handle'];api='c'if(row['phase']+s)%2==0 else'python';peer_api='python'if api=='c'else'c'
        if (t!=1-s or item.get('publisher_api')!=api or item['policy']!='allow'
                or item['args']!=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'allow',update_connection=server['object']['path'])
                or item.get('exit')!=0 or item.get('stderr') or item.get('environment')!=application_environment()
                or item['credentials']['uids']!=[1000]*4 or any(int(v,16)for v in item['credentials']['capabilities'].values())):
            raise CaptureError('ordinary actual original SDK owned provider required')
        if (not all(type(item[k])is int for k in ['start','end','handle','sender','target','exit'])
                or not 16<=item['start']<h<=item['end']<=65535 or len(item.get('cases',[]))!=2*len(lengths)):raise CaptureError('one real property and both update kinds required')
        lines=item['stdout'].splitlines()
        if (lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only']
                or lines[-1:]!=[f'SdkOwnedRemoved: api={api} start={item["start"]}']):raise CaptureError('complete original SDK provider stream required')
        snapshots=re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]+)$',item['stdout'],re.M)
        if snapshots!=[(str(h),v)for c in item['cases']for v in [c['value'],c['reply']]]:raise CaptureError('original owner must actually observe payload and business reply')
        for prefix,observations in [
            ('SdkOwnedReplaced',[c['replacement']for c in item['cases']]),
            ('SdkOwnedUpdate',[c['send']for c in item['cases']]),
            ('SdkOwnedConfiguration',[o for c in item['cases']for o in c['enabled']+c['disabled']]),
        ]:
            raw=[json.loads(v)for v in re.findall('^'+prefix+r': (.+)$',item['stdout'],re.M)]
            if raw!=[o['receipt']for o in observations]:raise CaptureError('provider raw SDK output differs from supervised receipts')
        for key,size in [('service',16),('uuid',16),('secret',32)]:
            value=bytes.fromhex(item[key])
            if len(value)!=size or value in fresh:raise CaptureError('independent service/value identities required')
            fresh.add(value)
        legs=[]
        def exchange(a,b,pdu,window):
            from ws73_ssap_value import pair_wire,physical_sends
            leg=pair_wire(row,matched,owners[a],owners[b],pdu,window)
            legs.append(leg);credit[a]+=physical_sends(leg['tx'])
        discovery_wire(item,peer,exchange)
        modes=[]
        for sequence,case in enumerate(item['cases']):
            size=lengths[sequence//2]
            if version==2 and (type(case.get('sequence'))is not int or case.get('sequence')!=sequence or type(case.get('application_bytes'))is not int or case.get('application_bytes')!=size):raise CaptureError('exact recorded length/order required')
            mode=case['mode'];modes.append(mode);value=bytes.fromhex(case['value']);reply=bytes.fromhex(case['reply']);app=case['application']
            if type(mode)is not int or mode not in (1,2)or len(value)!=size or len(reply)!=size or value in fresh or reply in fresh or value==reply:raise CaptureError('fresh complete application values required')
            if version==2 and (value[:4]!=sequence.to_bytes(4,'little') or reply[:4]!=(sequence|0x80000000).to_bytes(4,'little')):raise CaptureError('independent sequence-bearing application payloads required')
            fresh.update([value,reply]);outgoing=bytes([16 if mode==2 else 15,3])+h.to_bytes(2,'little')+len(value).to_bytes(2,'little')+value
            replacement=sdk_receipt(case['replacement'],api,h,{'value'})
            if replacement['value']!=case['value']or case['before']['value']!=case['value']or case['after']['value']!=case['reply']:raise CaptureError('actual owner local snapshot and peer business reply required')
            for key,wanted in [('enabled',mode),('disabled',0)]:
                observations=case[key]
                if not observations or len(observations)>12:raise CaptureError('bounded actual configuration observations required')
                receipts=[sdk_receipt(o,api,h,{'modes'})for o in observations]
                if any(type(r['modes'])is not int or not 0<=r['modes']<=3 for r in receipts)or receipts[-1]['modes']!=wanted:raise CaptureError('actual configuration barrier mismatch')
            sent=sdk_receipt(case['send'],api,h,{'stage','pdu','ack'})
            if (sent['stage']!=(2 if mode==2 else 1)or sent['pdu']!=outgoing.hex()
                    or sent['ack']!=('110301'if mode==2 else'')):raise CaptureError('actual admission/ACK receipt differs')
            prefix=['/bin/ws73-application-client-c']if peer_api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
            if (app['args']!=prefix+['update-peer',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(h),str(mode),case['value'],case['reply']]
                    or app['api']!=peer_api or type(app.get('exit'))is not int or app.get('exit')!=0 or app.get('stderr')or app.get('environment')!=application_environment()
                    or app['credentials']['uids']!=[1000]*4 or any(int(v,16)for v in app['credentials']['capabilities'].values())):raise CaptureError('ordinary opposite application execution required')
            output=[json.loads(v)for v in app['stdout'].splitlines()]
            if (len(output)!=2 or output[0].get('stage')!='ssap_update_wait'or output[0].get('client_closed')is not True
                    or output[0].get('api')!=peer_api or output[0].get('handle')!=h or output[0].get('mode')!=mode
                    or output[1]!={'stage':'ssap_update_checked_reply','api':peer_api,'handle':h,'mode':mode,'pdu':outgoing.hex(),'value':case['value'],'reply':case['reply']}):raise CaptureError('peer must actually compare and reply,not a log-only send')
            if not case['start_wall_ns']<=app['start_wall_ns']<=case['send']['start_wall_ns']<=app['end_wall_ns']<=case['end_wall_ns']<=item['end_wall_ns']:raise CaptureError('original transaction intervals required')
            window=case
            read=b'\x08\x03'+h.to_bytes(2,'little')+b'\x02'
            enable=b'\x0d\x23'+h.to_bytes(2,'little')+bytes([2,mode,0]);disable=b'\x0d\x23'+h.to_bytes(2,'little')+b'\x02\0\0'
            # Repeated zero/read/disable frames use disjoint original case windows.
            for req,rsp in [(read,b'\x09\x03\0\0'),(enable,b'\x0e\x03'+h.to_bytes(2,'little')+bytes([2,mode,0]))]:exchange(s,t,req,window);exchange(t,s,rsp,window)
            exchange(t,s,outgoing,window)
            if mode==2:exchange(s,t,b'\x11\x03\x01',window)
            exchange(s,t,disable,window);exchange(t,s,b'\x0e\x03'+h.to_bytes(2,'little')+b'\x02\0\0',window)
            exchange(s,t,b'\x0d\x23'+h.to_bytes(2,'little')+b'\0'+reply,window)
            exchange(t,s,b'\x0e\x03'+h.to_bytes(2,'little')+b'\0'+reply,window)
        if modes!=[1,2]*len(lengths):raise CaptureError('both notification/indication required')
        decisions=[json.loads(v)for v in re.findall(r'^SdkAuthorizationDecision: (.+)$',item['stdout'],re.M)]
        if len(decisions)!=4*len(lengths):raise CaptureError('complete actual enable/disable approvals required')
        for d,value in zip(decisions,['0100','0000','0200','0000']*len(lengths),strict=True):
            context={k:v for k,v in d.items()if k not in {'allow','decision_ns','decision_wall_ns'}}
            authorization_context(context,api,level=2,data_type=2)
            expected=(server['owner']['index'],server['owner']['generation'],server['object']['lifetime'],server['object']['handle'],h)
            if ((d['index'],d['generation'],d['lifetime'],d['handle'],d['property'])!=expected or d['value']!=value or d.get('allow')is not True
                    or type(d.get('decision_ns'))is not int or d['decision_ns']>=d['deadline_ns']
                    or type(d.get('decision_wall_ns'))is not int or not item['start_wall_ns']<=d['decision_wall_ns']<=item['end_wall_ns']):raise CaptureError('exact original typed authenticated approval required')
        proof.append(dict(sender=s,target=t,publisher=api,peer=peer_api,updates=2*len(lengths),application_replies=2*len(lengths),wire=legs,decisions=4*len(lengths),**(dict(version=version,lengths=list(lengths))if version==2 else{})))
    return proof,credit

def valid_summary(proof,*,expected_version=None):
    from ws73_ssap_value import valid_wire
    if expected_version is not None and (type(expected_version)is not int or expected_version not in (1,2)):return False
    if not isinstance(proof,dict) or proof.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED':return False
    rows=proof.get('proofs')
    if not isinstance(rows,list) or len(rows)!=2:return False
    observed_version=None
    for phase,row in enumerate(rows):
        if not isinstance(row,dict) or type(row.get('phase'))is not int or row['phase']!=phase:return False
        directions=row.get('ssap_update_delivery')
        if not isinstance(directions,list) or len(directions)!=2:return False
        for sender,value in enumerate(directions):
            if not isinstance(value,dict):return False
            version=value.get('version',1)
            if type(version)is not int or version not in (1,2) or expected_version is not None and version!=expected_version:return False
            if observed_version is not None and observed_version!=version:return False
            observed_version=version
            lengths=(32,)if version==1 else LENGTHS
            if version==2 and value.get('lengths')!=list(LENGTHS):return False
            expected={'sender':sender,'target':1-sender,'updates':2*len(lengths),'application_replies':2*len(lengths),'decisions':4*len(lengths)}
            if any(type(value.get(k))is not int or value[k]!=v for k,v in expected.items()):return False
            publisher='c'if(phase+sender)%2==0 else'python'
            if value.get('publisher')!=publisher or value.get('peer')!=('python'if publisher=='c'else'c'):return False
            legs=value.get('wire')
            if not isinstance(legs,list) or len(legs)!=10+19*len(lengths):return False
            if version==1:
                if any(not isinstance(leg,dict) or set(leg)!={'tx','rx'}
                        or any(not isinstance(leg[k],dict) or not leg[k]for k in ['tx','rx'])for leg in legs):return False
            else:
                from collections import Counter
                if not all(valid_wire(leg)for leg in legs):return False
                actual=Counter((bytes.fromhex(leg['logical_pdu'])[0],len(bytes.fromhex(leg['logical_pdu'])))for leg in legs if 'logical_pdu'in leg)
                if actual!=Counter({(15,2043):1,(16,2043):1,(15,2048):1,(16,2048):1,(13,2047):2,(14,2047):2}):return False
    return True
