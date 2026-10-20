# SPDX-License-Identifier: GPL-2.0-only
"""Finite VM-only continuous-lease gate,using the existing SDK and supervisor.

No protocol sender,ACK generator,Host or Engine. The actual C/Python reader
checks each payload and sends a distinct verified write using its original view.
Literal packet expectations below are independent evidence checks,not a codec.
"""
from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
import os
import secrets
import subprocess
import time

from ws73_capture import CaptureError
from ws73_north_star import file_record
from ws73_application_client import application_environment,process_identity,owned_arguments,authorization_context
from ws73_ssap_owned import publisher,wait_text,value_snapshot,await_removed
from ws73_ssap_update_delivery import configuration,command_receipt,discover,discovery_wire,sdk_receipt

ROOT=Path('/evidence/subscription-role')
INPUT=Path('/evidence/application/passthrough-control')
STATUS='CONTINUOUS_SUBSCRIPTION_APPLICATION_REPLIES_PENDING_PAIRED_USB'
COUNT=3
PRESSURE_CAPACITY=16
LEASE_MS=30000
INITIAL_RENEWAL_LEASE_MS=1000
TOOLS=('/bin/ws73-application-client-c','/usr/share/sparklink/tools/ws73-application-client.py',
       '/usr/lib/libsparklink.so.0','/usr/share/sparklink/python/sparklink/client.py',
       '/usr/share/sparklink/python/sparklink/ssap_subscription.py',
       '/usr/share/sparklink/python/sparklink/local_services.py',
       '/usr/share/sparklink/python/sparklink/service_authorization.py','/bin/bus-policy-probe')


def requested(args,*,passthrough):
    value=getattr(args,'ssap_subscription_verify',False)
    if type(value)is not bool:raise ValueError('explicit subscription selector required')
    renewal=getattr(args,'ssap_subscription_renewal_verify',False)
    if type(renewal)is not bool or renewal and not value:raise ValueError('renewal requires the explicit subscription gate')
    pressure=getattr(args,'ssap_subscription_pressure_verify',False)
    if type(pressure)is not bool or pressure and(not value or renewal):raise ValueError('pressure requires dedicated subscription gate;renewal is separate')
    if value and any(v for k,v in vars(args).items()if type(v)is bool and k not in {'passthrough','qmp_hotplug','connection_verify','channel_socket_verify','ssap_subscription_verify','ssap_subscription_renewal_verify','ssap_subscription_pressure_verify'}):raise ValueError('subscription excludes other test selectors')
    if value and (not passthrough or not getattr(args,'channel_socket_verify',False)
            or getattr(args,'security_agent',None)!='numeric-approve'
            or any(getattr(args,key,False)for key in ('ssap_update_delivery_verify','ssap_update_lifecycle_verify',
                'ssap_sender_deadline_verify','ssap_value_lengths_verify','ssap_owned_verify',
                'ssap_owned_update_verify','ssap_owner_lifecycle_verify','ssap_requester_lifecycle_verify',
                'application_client_verify','channel_socket_close_prefix','channel_socket_burst',
                'channel_socket_boundaries','dynamic_channel_verify','channel_fairness_verify'))):
        raise ValueError('subscription requires dedicated protected numeric-approve socket gate')
    return value


def renewal_required(row):
    value=row.get('ssap_subscription_renewal_required',False)
    if type(value)is not bool:raise CaptureError('typed renewal selector required')
    version=row.get('ssap_subscription_renewal_contract_version')
    if value and(type(version)is not int or version!=1)or not value and version is not None:
        raise CaptureError('explicit renewal contract1 required;no relabelled continuous evidence')
    return value


def pressure_required(row):
    value=row.get('ssap_subscription_pressure_required',False)
    version=row.get('ssap_subscription_pressure_contract_version')
    if(type(value)is not bool or value and(type(version)is not int or version!=1)
            or not value and version is not None or value and renewal_required(row)):
        raise CaptureError('explicit separate pressure contract1 required;no relabelled old evidence')
    return value


def tool_records(root=Path('/')):
    return {name:dict(sha256=hashlib.sha256((root/name.lstrip('/')).read_bytes()).hexdigest(),
                     bytes=(root/name.lstrip('/')).stat().st_size)for name in TOOLS}


def validate_tools(records,root,manifest):
    if records!=tool_records(root):raise CaptureError('subscription tools differ from sealed root')
    for name,receipt in records.items():
        actual=(root/name.lstrip('/')).resolve(strict=True)
        matches=[p for p in manifest if Path(p['path']).resolve()==actual]
        if len(matches)!=1 or matches[0]['sha256']!=receipt['sha256']:
            raise CaptureError('subscription actual tool missing from original build manifest')


def validate_request(row,phase):
    renewal=renewal_required(row)
    pressure=pressure_required(row)
    fields={'phase','owners','tools','security_requirement','message_security_required','status','start_wall_ns'}
    if renewal:fields|={'ssap_subscription_renewal_required','ssap_subscription_renewal_contract_version'}
    if pressure:fields|={'ssap_subscription_pressure_required','ssap_subscription_pressure_contract_version'}
    if (set(row)!=fields
            or row['status']!='RUNNING' or type(phase)is not int or phase not in (0,1)
            or type(row['phase'])is not int or row['phase']!=phase
            or type(row['security_requirement'])is not int or row['security_requirement']!=2
            or row['message_security_required']is not True):
        raise CaptureError('fixed protected subscription role request required')
    # Reuse the existing canonical-path/identity input guard;payloads are made
    # by the root test supervisor,not supplied as privileged work instructions.
    from ws73_application_role import validate_request as pair_request
    pair_request(dict(phase=phase,owners=row['owners'],tools=row['tools'],applications=[],
        request=(phase.to_bytes(4,'little')+b'a'*57).hex(),
        reply=(phase.to_bytes(4,'little')+b'b'*57).hex(),
        status='RUNNING',start_wall_ns=row['start_wall_ns']),phase)


def request(run,row):
    phase=row['phase']
    value=dict(phase=phase,owners=row['owners'],tools=tool_records(),security_requirement=row['security_requirement'],
               message_security_required=row['message_security_required'],status='RUNNING',start_wall_ns=time.time_ns())
    if getattr(run.args,'ssap_subscription_renewal_verify',False):
        value.update(ssap_subscription_renewal_required=True,ssap_subscription_renewal_contract_version=1)
    if getattr(run.args,'ssap_subscription_pressure_verify',False):
        value.update(ssap_subscription_pressure_required=True,ssap_subscription_pressure_contract_version=1)
    validate_request(value,phase)
    path=run.output/f'subscription-role-{phase}.request.json';temporary=path.with_suffix('.tmp')
    with temporary.open('x')as stream:json.dump(value,stream)
    temporary.chmod(0o600);os.link(temporary,path);temporary.unlink()
    response=ROOT/f'phase-{phase}'/'run.json';deadline=time.monotonic()+90
    while not response.is_file():
        if time.monotonic()>=deadline:raise CaptureError('subscription role supervisor deadline')
        time.sleep(.01)
    from ws73_application_role import read_json,verify_probe
    result=read_json(response,0,limit=(1024 if pressure_required(value)else 512)*1024)
    for key in value:
        if result.get(key)!=value[key]:raise CaptureError('root subscription supervisor changed original request')
    verify_probe(result)
    if result.get('ssap_subscription_status')!=STATUS:raise CaptureError('actual subscription phase failed: '+str(result.get('error')))
    for key in ('ssap_subscription','ssap_subscription_status','role_probe','role_supervisor','channel_role','application_role_contract_version'):
        row[key]=result[key]
    row.update(ssap_subscription_required=True,ssap_subscription_contract_version=1,
               ssap_subscription_tools=value['tools'],ssap_subscription_request=value)
    if renewal_required(value):row.update(ssap_subscription_renewal_required=True,ssap_subscription_renewal_contract_version=1)
    if pressure_required(value):row.update(ssap_subscription_pressure_required=True,ssap_subscription_pressure_contract_version=1)
    run.save()


def app_rows(process,app):
    text=Path(app['output_files'][0]).read_text()
    # A live regular file can end in the middle of one stdio write. Only the
    # current incomplete tail is pending;terminal raw output is checked exactly.
    raw=[line for line in text.splitlines(keepends=True)if line.endswith('\n')]
    if len(raw)>24:raise CaptureError('bounded subscription application transcript required')
    try:return [json.loads(line)for line in raw]
    except json.JSONDecodeError as error:raise CaptureError('complete actual SDK JSON output required')from error


def wait_stage(process,app,stage,count,deadline):
    while True:
        rows=app_rows(process,app);found=[v for v in rows if v.get('stage')==stage]
        if len(found)>count:raise CaptureError('duplicate or unexpected SDK stage')
        if len(found)==count:return found[-1]
        if process.poll()is not None or time.monotonic()>=deadline:raise CaptureError('actual SDK stage/original supervisor budget missing: '+stage)
        time.sleep(.01)


def execute_supervised(run,row):
    """Only the existing root VM role supervisor calls this finite workload."""
    from ws73_application_role import require_vm
    require_vm('ws73.ssap_subscription=1')
    renewal=renewal_required(row)
    pressure=pressure_required(row)
    if ('ws73.ssap_subscription_renewal=1'in Path('/proc/cmdline').read_text().split())!=renewal:
        raise CaptureError('renewal boot/request mismatch')
    if ('ws73.ssap_subscription_pressure=1'in Path('/proc/cmdline').read_text().split())!=pressure:
        raise CaptureError('pressure boot/request mismatch')
    duration=INITIAL_RENEWAL_LEASE_MS if renewal else LEASE_MS
    row.update(ssap_subscription=[],ssap_subscription_required=True,ssap_subscription_contract_version=1);run.save()
    for sender in (0,1):
        peer,server=row['owners'][sender],row['owners'][1-sender]
        api='c'if (row['phase']+sender)%2==0 else'python';reader='python'if api=='c'else'c'
        with publisher(run,row,sender,'allow',collection='ssap_subscription',label='subscription',
                       sdk_api=api,updates=True,application_uid=1005)as(owner,item):
            discover(run,peer,item);item['leases']=[];run.save()
            for mode in (1,2):
                prefix=['/bin/ws73-application-client-c']if reader=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
                args=prefix+['subscription',str(peer['owner']['index']),str(peer['owner']['generation']),
                             peer['object']['path'],str(item['handle']),str(mode),str(duration)]
                label=f'subscription-{row["phase"]}-{sender}-{mode}'
                out=run.output/(label+'.stdout');err=run.output/(label+'.stderr')
                lease=dict(mode=mode,start_wall_ns=time.time_ns(),messages=[]);item['leases'].append(lease)
                app=dict(api=reader,args=args,environment=application_environment(),start_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
                lease['application']=app;run.save();process=None
                try:
                    with ExitStack()as files:
                        process=subprocess.Popen(args,user=1004,group=1004,extra_groups=[],env=dict(os.environ,**application_environment()),
                            stdin=subprocess.PIPE,stdout=files.enter_context(out.open('x')),stderr=files.enter_context(err.open('x')),text=True)
                        app.update(pid=process.pid);app['credentials'],app['process_status']=process_identity(process.pid,1004);run.save()
                        lease['active']=wait_stage(process,app,'ssap_subscription_active',1,time.monotonic()+6)
                        lease['enabled']=configuration(owner,item,mode,process);run.save()
                        for number in range(PRESSURE_CAPACITY+2 if pressure else COUNT):
                            sequence=(row['phase']<<24)|(sender<<20)|(mode<<16)|number
                            value=sequence.to_bytes(4,'little')+secrets.token_bytes(28)
                            reply=(sequence|0x80000000).to_bytes(4,'little')+secrets.token_bytes(28)
                            case=dict(number=number,value=value.hex(),reply=reply.hex(),start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns());lease['messages'].append(case)
                            case['replacement']=command_receipt(owner,item,'replace '+value.hex(),'SdkOwnedReplaced',limit=40 if pressure else 32)
                            case['before']=value_snapshot(owner,item,value.hex(),limit=80 if pressure else 16);run.save()
                            if pressure and number<=PRESSURE_CAPACITY:
                                overflow=number==PRESSURE_CAPACITY
                                case['send']=command_receipt(owner,item,'indicate-observe'if overflow and mode==2 else'indicate'if mode==2 else'notify',
                                    'SdkOwnedUpdateObserved'if overflow and mode==2 else'SdkOwnedUpdate',limit=40)
                                case['sent_wall_ns']=time.time_ns();run.save()
                                if not overflow:continue
                                process.stdin.write('drain\n');process.stdin.flush()
                                lease['drained']=wait_stage(process,app,'ssap_subscription_batch',1,time.monotonic()+6);run.save()
                                for position,filled in enumerate(lease['messages'][:PRESSURE_CAPACITY]):
                                    process.stdin.write('check-cached '+filled['value']+' '+filled['reply']+'\n');process.stdin.flush()
                                    filled['checked']=wait_stage(process,app,'ssap_subscription_checked_reply',position+1,time.monotonic()+6)
                                    filled['after']=value_snapshot(owner,item,filled['reply'],limit=80)
                                    filled['end_wall_ns']=time.time_ns();filled['end_monotonic_ns']=time.monotonic_ns();run.save()
                                case['end_wall_ns']=time.time_ns();case['end_monotonic_ns']=time.monotonic_ns();run.save();continue
                            process.stdin.write('check '+value.hex()+' '+reply.hex()+'\n');process.stdin.flush()
                            case['send']=command_receipt(owner,item,'indicate'if mode==2 else'notify','SdkOwnedUpdate',limit=40 if pressure else 32);run.save()
                            case['checked']=wait_stage(process,app,'ssap_subscription_checked_reply',number if pressure else number+1,time.monotonic()+6)
                            case['batch']=wait_stage(process,app,'ssap_subscription_batch',2 if pressure else number+1,time.monotonic()+1)
                            case['after']=value_snapshot(owner,item,reply.hex(),limit=80 if pressure else 16);case['end_wall_ns']=time.time_ns();case['end_monotonic_ns']=time.monotonic_ns();run.save()
                            if renewal and number==0:
                                process.stdin.write('renew '+str(LEASE_MS)+'\n');process.stdin.flush()
                                lease['renewal']=wait_stage(process,app,'ssap_subscription_renewed',1,time.monotonic()+6);run.save()
                                # Ready returned after the original daemon expiry was
                                # computed. Returned+initial TTL is an upper bound;
                                # do not rely on a conservatively rounded timestamp.
                                upper=lease['active']['returned_ns']+duration*1_000_000
                                threshold=upper+50_000_000
                                barrier=dict(original_expiry_upper_ns=upper,threshold_ns=threshold,start_ns=time.monotonic_ns())
                                if threshold>barrier['start_ns']+2_000_000_000:raise CaptureError('bounded old-expiry barrier required')
                                while time.monotonic_ns()<threshold:
                                    if process.poll()is not None:raise CaptureError('reader exited before old-expiry barrier')
                                    time.sleep(min(.05,max(0,(threshold-time.monotonic_ns())/1e9)))
                                barrier['end_ns']=time.monotonic_ns();lease['old_expiry_barrier']=barrier;run.save()
                        process.stdin.write('release\n');process.stdin.flush()
                        lease['release']=wait_stage(process,app,'ssap_subscription_released',1,time.monotonic()+6);run.save()
                        process.stdin.write('quit\n');process.stdin.flush();process.wait(timeout=2)
                        if process.returncode:raise CaptureError('actual subscription reader failed')
                finally:
                    if process is not None:
                        if process.poll()is None:process.kill();process.wait(timeout=2)
                        if process.stdin:process.stdin.close()
                        app.update(exit=process.returncode,end_wall_ns=time.time_ns(),stdout=out.read_text(),stderr=err.read_text())
                    run.save()
                lease['disabled']=configuration(owner,item,0);lease['end_wall_ns']=time.time_ns();run.save()
            owner.stdin.write('quit\n');owner.stdin.flush();owner.wait(timeout=2)
            if owner.returncode:raise CaptureError('original service owner cleanup failed')
            item['cleanup']=await_removed(run,server,item['start']);run.save()
    row['ssap_subscription_status']=STATUS;run.save()


def role(identity,uid):
    if (identity['uids']!=[uid]*4 or identity['gids']!=[uid]*4 or identity['groups']!=[]
            or set(identity['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'}
            or any(int(v,16)for v in identity['capabilities'].values())):
        raise CaptureError('exact independent cap-zero application/service-only credentials required')


def verify_supervisor_artifacts(control,evidence):
    """Actual root outputs,not a caller-supplied completed summary."""
    from ws73_application_role import verify_probe
    evidence=Path(evidence);root=evidence/'subscription-role'
    finished=json.loads((root/'finished.json').read_text())
    if (finished['status']!='TWO_FINITE_SUBSCRIPTION_PHASES_COMPLETED'
            or finished['daemon']!=control['daemon_before']or control['daemon_before']!=control['daemon_after']
            or len(control['channel_socket'])!=2):raise CaptureError('two actual root subscription phases and unchanged daemon required')
    for phase,row in enumerate(control['channel_socket']):
        original=json.loads((root/f'phase-{phase}'/'run.json').read_text())
        verify_probe(original)
        for key,value in row['ssap_subscription_request'].items():
            if original[key]!=value:raise CaptureError('original root request identity changed')
        for key in ('ssap_subscription','ssap_subscription_status','role_probe','role_supervisor','channel_role','application_role_contract_version'):
            if row[key]!=original[key]:raise CaptureError('root subscription record differs from control')
        if (original['ssap_subscription_status']!=STATUS or original['ssap_subscription_contract_version']!=1
                or original['role_supervisor']!=finished['supervisor']):raise CaptureError('completed original root subscription phase required')
        apps=[original['role_probe']]
        for item in original['ssap_subscription']:
            apps.append(item);apps.extend(l['application']for l in item['leases'])
        for app in apps:
            for filename in app['output_files']:
                relative=Path(filename).relative_to('/evidence')
                if not relative.is_relative_to(Path('subscription-role')/f'phase-{phase}'):
                    raise CaptureError('fixed phase output paths required')
                if (evidence/relative).read_text()!=app['stdout'if filename.endswith('.stdout')else'stderr']:
                    raise CaptureError('raw process stream differs from original subscription record')
    renewals=[renewal_required(row)for row in control['channel_socket']]
    if any(renewals)and not all(renewals):raise CaptureError('both real renewal phases required')
    pressures=[pressure_required(row)for row in control['channel_socket']]
    if any(pressures)and not all(pressures):raise CaptureError('both real pressure phases required')
    result=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,
                phases=2,reader_UID=1004,provider_UID=1005,readers=8,providers=4,updates=144 if all(pressures)else 24,
                daemon=finished['daemon'],supervisor=finished['supervisor'],
                scope='Fixed actual role supervision only;not raw RF replay or full lifecycle/recovery qualification')
    if all(renewals):result.update(renewal_contract_version=1,renewals=8,post_original_expiry_updates=16)
    if all(pressures):result.update(pressure_contract_version=1,checked_replies=136,notification_drops=4,indication_refusals=4,resumed=8)
    return result


def valid_supervision(proof):
    try:
        expected=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,
                      phases=2,reader_UID=1004,provider_UID=1005,readers=8,providers=4,
                      updates=144 if proof.get('pressure_contract_version')==1 else 24)
        if any(proof[k]!=v or type(proof[k])is not type(v)for k,v in expected.items()):return False
        return all(type(proof[k][f])is int and proof[k][f]>0
                   for k in ('daemon','supervisor')for f in ('pid','start_ticks'))
    except (KeyError,TypeError):return False


def valid_renewal_supervision(proof):
    return (valid_supervision(proof)and all(type(proof.get(k))is int and proof[k]==v
        for k,v in dict(renewal_contract_version=1,renewals=8,post_original_expiry_updates=16).items()))


def valid_pressure_supervision(proof):
    return(valid_supervision(proof)and all(type(proof.get(k))is int and proof[k]==v
        for k,v in dict(pressure_contract_version=1,checked_replies=136,notification_drops=4,indication_refusals=4,resumed=8).items()))


def pressure_batch(lease,api,handle,*,resumed=False):
    mode=lease['mode'];cases=lease['messages'][-1:]if resumed else lease['messages'][:PRESSURE_CAPACITY]
    packets=[dict(sequence=c['number']+1,epoch=lease['active']['epoch'],level=2,indication=mode==2,
        pdu=(bytes([16 if mode==2 else 15,3])+handle.to_bytes(2,'little')+b'\x20\0'+bytes.fromhex(c['value'])).hex())for c in cases]
    return dict(stage='ssap_subscription_batch',api=api,last=18 if resumed else 17,
        dropped=1 if mode==1 else 0,refused=1 if mode==2 else 0,state=1,flags=0,reason=0,discarded=0,packets=packets)


def verify_renewal(lease,api):
    active=lease['active'];r=lease['renewal'];b=lease['old_expiry_barrier']
    fields={'stage','api','token','epoch','expires_ns','started_ns','deadline_ns','returned_ns'}
    if (set(r)!=fields or r['stage']!='ssap_subscription_renewed'or r['api']!=api
            or any(type(r[k])is not int or r[k]<=0 for k in fields-{'stage','api'})
            or r['token']!=active['token']or r['epoch']!=active['epoch']
            or r['deadline_ns']-r['started_ns']!=5_000_000_000
            or not lease['messages'][0]['end_monotonic_ns']<=r['started_ns']<=r['returned_ns']<r['deadline_ns']
            or r['returned_ns']>=active['expires_ns']or r['expires_ns']<=active['expires_ns']
            or r['expires_ns']>r['deadline_ns']+LEASE_MS*1_000_000):
        raise CaptureError('actual same-token/epoch long renewal and original operation deadline required')
    if (set(b)!={'original_expiry_upper_ns','threshold_ns','start_ns','end_ns'}
            or any(type(v)is not int or v<=0 for v in b.values())
            or b['original_expiry_upper_ns']!=active['returned_ns']+INITIAL_RENEWAL_LEASE_MS*1_000_000
            or b['threshold_ns']!=b['original_expiry_upper_ns']+50_000_000
            or not r['returned_ns']<=b['start_ns']<=b['end_ns']
            or not b['threshold_ns']<=b['end_ns']<r['expires_ns']
            or any(c['start_monotonic_ns']<b['end_ns']for c in lease['messages'][1:])):
        raise CaptureError('two real updates after conservative original-expiry upper bound required')
    return r


def corroborate(row,matched):
    if not row.get('ssap_subscription_required',False):return [],{0:0,1:0}
    from ws73_application_role import verify_probe
    verify_probe(row)
    if (type(row.get('ssap_subscription_contract_version'))is not int or row['ssap_subscription_contract_version']!=1 or row.get('ssap_subscription_status')!=STATUS
            or row.get('security_requirement')!=2 or row.get('message_security_required')is not True
            or len(row.get('ssap_subscription',[]))!=2):raise CaptureError('completed protected continuous subscription phase required')
    renewal=renewal_required(row);pressure=pressure_required(row);duration=INITIAL_RENEWAL_LEASE_MS if renewal else LEASE_MS
    owners=row['owners'];proof=[];credit={0:0,1:0};fresh=set()
    for sender,item in enumerate(row['ssap_subscription']):
        s,t=sender,1-sender;peer,server=owners[s],owners[t];api='c'if (row['phase']+s)%2==0 else'python';reader='python'if api=='c'else'c';h=item['handle']
        if (item['sender']!=s or item['target']!=t or item.get('publisher_api')!=api or item['policy']!='allow'
                or item['args']!=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'allow',update_connection=server['object']['path'])
                or item['environment']!=application_environment()or type(item['exit'])is not int or item['exit']!=0 or item['stderr']):raise CaptureError('actual original service-only SDK provider required')
        role(item['credentials'],1005)
        if not 16<=item['start']<h<=item['end']<=65535 or len(item.get('leases',[]))!=2:raise CaptureError('actual property and two distinct leases required')
        lines=item['stdout'].splitlines()
        if lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only']or lines[-1:]!=[f'SdkOwnedRemoved: api={api} start={item["start"]}']:raise CaptureError('complete original owner stream required')
        legs=[]
        def exchange(a,b,pdu,window):
            from ws73_ssap_value import pair_wire,physical_sends
            leg=pair_wire(row,matched,owners[a],owners[b],pdu,window);legs.append(leg);credit[a]+=physical_sends(leg['tx'])
        discovery_wire(item,peer,exchange)
        for mode,lease in zip((1,2),item['leases'],strict=True):
            app=lease['application'];role(app['credentials'],1004)
            prefix=['/bin/ws73-application-client-c']if reader=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
            if (type(lease['mode'])is not int or lease['mode']!=mode or app['api']!=reader or app['environment']!=application_environment()
                    or app['args']!=prefix+['subscription',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(h),str(mode),str(duration)]
                    or type(app['exit'])is not int or app['exit']!=0 or app['stderr']or len(lease['messages'])!=(18 if pressure else COUNT)):raise CaptureError('actual continuous SDK reader process and finite workload required')
            active=lease['active'];raw=[json.loads(v)for v in app['stdout'].splitlines()]
            expected=[active]
            if (set(active)!={'stage','api','token','epoch','expires_ns','started_ns','deadline_ns','returned_ns','client_closed'}
                    or active['stage']!='ssap_subscription_active'or active['api']!=reader or active['client_closed']is not True
                    or any(type(active[k])is not int or active[k]<=0 for k in ('token','epoch','expires_ns','started_ns','deadline_ns','returned_ns'))
                    or active['deadline_ns']-active['started_ns']!=5_000_000_000
                    or not active['started_ns']<=active['returned_ns']<active['deadline_ns']
                    or not active['started_ns']+duration*1_000_000<=active['expires_ns']<=active['deadline_ns']+duration*1_000_000):raise CaptureError('original actual acquisition/expiry/epoch required')
            if renewal:renewed=verify_renewal(lease,reader)
            elif 'renewal'in lease or'old_expiry_barrier'in lease:raise CaptureError('unrequested renewal evidence')
            if pressure:
                drained=pressure_batch(lease,reader,h)
                if lease.get('drained')!=drained:raise CaptureError('actual full16 original ordered batch and one overflow counter required')
                expected.append(drained)
            elif 'drained'in lease:raise CaptureError('unrequested pressure batch')
            for number,case in enumerate(lease['messages']):
                sequence=(row['phase']<<24)|(s<<20)|(mode<<16)|number;value=bytes.fromhex(case['value']);reply=bytes.fromhex(case['reply'])
                if (type(case['number'])is not int or case['number']!=number or len(value)!=32 or len(reply)!=32 or value in fresh or reply in fresh
                        or value[:4]!=sequence.to_bytes(4,'little')or reply[:4]!=(sequence|0x80000000).to_bytes(4,'little')):raise CaptureError('fresh sequence-bearing distinct application payloads required')
                fresh.update((value,reply));pdu=bytes([16 if mode==2 else 15,3])+h.to_bytes(2,'little')+b'\x20\0'+value
                overflow=pressure and number==PRESSURE_CAPACITY
                checked={'stage':'ssap_subscription_checked_reply','api':reader,'sequence':number+1,'value':case['value'],'reply':case['reply']}
                batch={'stage':'ssap_subscription_batch','api':reader,'last':number+1,'dropped':0,'refused':0,'state':1,'flags':0,'reason':0,'discarded':0,
                       'packets':[dict(sequence=number+1,epoch=active['epoch'],level=2,indication=mode==2,pdu=pdu.hex())]}
                if pressure:batch=pressure_batch(lease,reader,h,resumed=True)
                if overflow:
                    if any(k in case for k in ('checked','batch','after')):raise CaptureError('overflow must not manufacture app delivery or reply')
                else:
                    if case['checked']!=checked:raise CaptureError('actual application comparison/writeback required')
                    expected.append(checked)
                    if not pressure or number==17:
                        if case['batch']!=batch:raise CaptureError('actual complete original batch required')
                        expected.append(batch)
                    elif 'batch'in case:raise CaptureError('cached packet must come only from the original drained batch')
                if renewal and number==0:expected.append(renewed)
                sent=sdk_receipt(case['send'],api,h,{'result'}if overflow and mode==2 else{'stage','pdu','ack'});replacement=sdk_receipt(case['replacement'],api,h,{'value'})
                if overflow and mode==2:
                    if type(sent['result'])is not int or sent['result']!=-5:raise CaptureError('actual peer-refusal API error required;timeout/success is not overflow')
                elif sent['pdu']!=pdu.hex()or sent['stage']!=(2 if mode==2 else 1)or sent['ack']!=('110301'if mode==2 else''):
                    raise CaptureError('actual SDK update receipt required')
                if (replacement['value']!=case['value']or case['before']['value']!=case['value']or(not overflow and case['after']['value']!=case['reply'])
                        or not lease['start_wall_ns']<=app['start_wall_ns']<=case['start_wall_ns']<=case['send']['start_wall_ns']<=case['end_wall_ns']<=app['end_wall_ns']<=lease['end_wall_ns']<=item['end_wall_ns']):raise CaptureError('original send/owner-store/application intervals required')
                exchange(t,s,pdu,case)
                if mode==2:exchange(s,t,b'\x11\x03'+bytes([0 if overflow else 1]),case)
                if overflow:continue
                exchange(s,t,b'\x0d\x23'+h.to_bytes(2,'little')+b'\0'+reply,case)
                exchange(t,s,b'\x0e\x03'+h.to_bytes(2,'little')+b'\0'+reply,case)
            release={'stage':'ssap_subscription_released','api':reader,'flags':1,'discarded':0}
            if lease['release']!=release:raise CaptureError('actual confirmed lease cleanup required')
            expected.append(release)
            if raw!=expected:raise CaptureError('complete exact original application transcript required')
            for key,wanted in [('enabled',mode),('disabled',0)]:
                observations=lease[key]
                if not 1<=len(observations)<=12:raise CaptureError('finite actual configuration barrier required')
                values=[sdk_receipt(o,api,h,{'modes'})for o in observations]
                if values[-1]['modes']!=wanted or any(type(v['modes'])is not int or not 0<=v['modes']<=3 for v in values):raise CaptureError('actual remote enable/disable observation required')
            read=b'\x08\x03'+h.to_bytes(2,'little')+b'\x02';enable=b'\x0d\x23'+h.to_bytes(2,'little')+bytes([2,mode,0]);disable=b'\x0d\x23'+h.to_bytes(2,'little')+b'\x02\0\0'
            for req,rsp in [(read,b'\x09\x03\0\0'),(enable,b'\x0e\x03'+h.to_bytes(2,'little')+bytes([2,mode,0])),(disable,b'\x0e\x03'+h.to_bytes(2,'little')+b'\x02\0\0')]:
                exchange(s,t,req,lease);exchange(t,s,rsp,lease)
        decisions=[json.loads(v.removeprefix('SdkAuthorizationDecision: '))for v in lines if v.startswith('SdkAuthorizationDecision: ')]
        if len(decisions)!=4:raise CaptureError('exact enable/disable approvals required')
        for d,value in zip(decisions,('0100','0000','0200','0000'),strict=True):
            authorization_context({k:v for k,v in d.items()if k not in {'allow','decision_ns','decision_wall_ns'}},api,level=2,data_type=2)
            if ((d['index'],d['generation'],d['lifetime'],d['handle'],d['property'])!=(server['owner']['index'],server['owner']['generation'],server['object']['lifetime'],server['object']['handle'],h)
                    or d['value']!=value or d['allow']is not True or d['decision_ns']>=d['deadline_ns']
                    or not item['start_wall_ns']<=d['decision_wall_ns']<=item['end_wall_ns']):raise CaptureError('original authenticated typed owner decision required')
        snapshots=[]
        for lease in item['leases']:
            cases=lease['messages']
            snapshots.extend((str(h),v)for v in ([c['value']for c in cases[:17]]+[c['reply']for c in cases[:16]]+[cases[-1]['value'],cases[-1]['reply']]if pressure else[c[k]for c in cases for k in ('value','reply')]))
        import re
        if re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]+)$',item['stdout'],re.M)!=snapshots:raise CaptureError('actual original owner store snapshots required')
        for prefix,observations in [('SdkOwnedReplaced',[c['replacement']for l in item['leases']for c in l['messages']]),
                ('SdkOwnedUpdate',[c['send']for l in item['leases']for c in l['messages']if not(pressure and l['mode']==2 and c['number']==16)]),
                ('SdkOwnedUpdateObserved',[c['send']for l in item['leases']for c in l['messages']if pressure and l['mode']==2 and c['number']==16]),
                ('SdkOwnedConfiguration',[o for l in item['leases']for key in ('enabled','disabled')for o in l[key]])]:
            raw=[json.loads(v)for v in re.findall('^'+prefix+r': (.+)$',item['stdout'],re.M)]
            if raw!=[o['receipt']for o in observations]:raise CaptureError('actual provider SDK output differs from original receipts')
        result=dict(sender=s,target=t,publisher=api,peer=reader,leases=2,updates=36 if pressure else 6,application_replies=34 if pressure else 6,decisions=4,wire=legs)
        if renewal:result.update(renewal_contract_version=1,renewals=2,post_original_expiry_updates=4)
        if pressure:result.update(pressure_contract_version=1,notification_drops=1,indication_refusals=1,resumed=2)
        proof.append(result)
    return proof,credit


def valid_summary(proof):
    from ws73_ssap_value import valid_wire
    try:
        if proof['status']!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'or len(proof['proofs'])!=2:return False
        for phase,row in enumerate(proof['proofs']):
            if row['phase']!=phase or len(row['ssap_subscription'])!=2:return False
            for sender,value in enumerate(row['ssap_subscription']):
                api='c'if (phase+sender)%2==0 else'python'
                pressure=value.get('pressure_contract_version')is not None
                if pressure and(type(value['pressure_contract_version'])is not int or value['pressure_contract_version']!=1):return False
                for k,v in dict(sender=sender,target=1-sender,leases=2,updates=36 if pressure else 6,application_replies=34 if pressure else 6,decisions=4).items():
                    if type(value[k])is not int or value[k]!=v:return False
                if value['publisher']!=api or value['peer']!=('python'if api=='c'else'c')or len(value['wire'])!=(144 if pressure else 43):return False
                if not all(valid_wire(leg)for leg in value['wire']):return False
        return True
    except (KeyError,TypeError,ValueError):return False


def valid_renewal_summary(proof):
    return(valid_summary(proof)and all(type(v.get(k))is int and v[k]==n
        for row in proof['proofs']for v in row['ssap_subscription']
        for k,n in dict(renewal_contract_version=1,renewals=2,post_original_expiry_updates=4).items()))


def valid_pressure_summary(proof):
    return(valid_summary(proof)and all(type(v.get(k))is int and v[k]==n
        for row in proof['proofs']for v in row['ssap_subscription']
        for k,n in dict(pressure_contract_version=1,notification_drops=1,indication_refusals=1,resumed=2).items()))
