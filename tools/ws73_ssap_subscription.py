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

def role_paths(pair=None):
    from ws73_role_snapshot import profile
    bounds=profile('subscription',pair)
    return Path(bounds['artifact']),INPUT if pair is None else Path('/evidence/application/parallel-business')/('pair-'+str(pair))


def requested(args,*,passthrough):
    value=getattr(args,'ssap_subscription_verify',False)
    if type(value)is not bool:raise ValueError('explicit subscription selector required')
    renewal=getattr(args,'ssap_subscription_renewal_verify',False)
    if type(renewal)is not bool or renewal and not value:raise ValueError('renewal requires the explicit subscription gate')
    pressure=getattr(args,'ssap_subscription_pressure_verify',False)
    if type(pressure)is not bool or pressure and(not value or renewal):raise ValueError('pressure requires dedicated subscription gate;renewal is separate')
    owner_loss=getattr(args,'ssap_subscription_owner_loss_verify',False)
    if type(owner_loss)is not bool or owner_loss and(not value or renewal or pressure):raise ValueError('owner loss requires a separate subscription gate')
    inflight=getattr(args,'ssap_subscription_inflight_release_verify',False)
    if type(inflight)is not bool or inflight and(not value or renewal or pressure or owner_loss):raise ValueError('in-flight release requires a separate subscription gate')
    requested_inflight_case(args)
    shared=getattr(args,'ssap_subscription_shared_verify',False)
    if type(shared)is not bool or shared and(not value or renewal or pressure or owner_loss or inflight):raise ValueError('shared owners require their separate protected subscription gate')
    requested_shared_case(args,four_pair=getattr(args,'four_device_shared_subscription',False)is True)
    if shared and(getattr(args,'channel_socket_rounds',4)!=4 or getattr(args,'channel_socket_bytes',61)!=61):raise ValueError('shared gate retains the ordinary4x61 baseline')
    if value and any(v for k,v in vars(args).items()if type(v)is bool and k not in {'passthrough','qmp_hotplug','connection_verify','channel_socket_verify','ssap_subscription_verify','ssap_subscription_renewal_verify','ssap_subscription_pressure_verify','ssap_subscription_owner_loss_verify','ssap_subscription_inflight_release_verify','ssap_subscription_shared_verify'}):raise ValueError('subscription excludes other test selectors')
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


def owner_loss_required(row):
    value=row.get('ssap_subscription_owner_loss_required',False)
    version=row.get('ssap_subscription_owner_loss_contract_version')
    if(type(value)is not bool or value and(type(version)is not int or version!=1)
            or not value and version is not None or value and(renewal_required(row)or pressure_required(row))):
        raise CaptureError('explicit separate owner-loss contract1 required')
    return value


def inflight_required(row):
    value=row.get('ssap_subscription_inflight_release_required',False)
    version=row.get('ssap_subscription_inflight_release_contract_version')
    if(type(value)is not bool or value and(type(version)is not int or version!=1)
            or not value and version is not None or value and(renewal_required(row)or pressure_required(row)or owner_loss_required(row))):
        raise CaptureError('explicit separate in-flight release contract1 required')
    return value


def requested_inflight_case(args):
    case=getattr(args,'ssap_subscription_inflight_case','release')
    if case not in ('release','expiry','owner-exit')or case!='release'and not getattr(args,'ssap_subscription_inflight_release_verify',False):
        raise ValueError('expiry case requires the dedicated protected in-flight gate')
    return case


def inflight_case(row):
    case=row.get('ssap_subscription_inflight_case','release')
    version=row.get('ssap_subscription_inflight_expiry_contract_version')
    if (case not in ('release','expiry','owner-exit')or case=='expiry'and(not inflight_required(row)or type(version)is not int or version!=1)
            or case=='release'and version is not None):
        raise CaptureError('explicit in-flight expiry contract1 required;old release is not expiry evidence')
    return case


def boot_inflight_case(tokens,enabled):
    values=[v.split('=',1)[1]for v in tokens if v.startswith('ws73.subscription_inflight_case=')]
    if not values:return 'release'
    if len(values)!=1 or not enabled or values[0]!='expiry':raise CaptureError('one enabled original expiry boot case required')
    return values[0]


def lease_duration(row,sender,mode,attempt):
    return INITIAL_RENEWAL_LEASE_MS if renewal_required(row)or(inflight_case(row)=='expiry'and sender==0 and mode==2 and attempt==0)else LEASE_MS


def shared_required(row):
    value=row.get('ssap_subscription_shared_required',False);version=row.get('ssap_subscription_shared_contract_version')
    if(type(value)is not bool or value and(type(version)is not int or version!=1)or not value and version is not None
        or value and(renewal_required(row)or pressure_required(row)or owner_loss_required(row)or inflight_required(row))):
        raise CaptureError('explicit separate shared-owner contract1 required')
    return value


def requested_shared_case(args,*,four_pair=False):
    case=getattr(args,'ssap_subscription_shared_case','release')
    parallel=four_pair and getattr(args,'four_device_shared_subscription',False)is True
    if(type(four_pair)is not bool or type(case)is not str or case not in ('release','expiry','owner-exit','pressure')
        or case!='release'and not(getattr(args,'ssap_subscription_shared_verify',False)is True or parallel)
        or parallel and case not in ('release','expiry','owner-exit')):
        raise ValueError('lifetime case requires its dedicated supported shared-owner gate')
    return case


def shared_case(row):
    case=row.get('ssap_subscription_shared_case','release');version=row.get('ssap_subscription_shared_lifetime_contract_version')
    pressure=row.get('ssap_subscription_shared_pressure_contract_version')
    if(type(case)is not str or case not in ('release','expiry','owner-exit','pressure')
        or case!='release'and not shared_required(row)
        or case in ('expiry','owner-exit')and(type(version)is not int or version!=1)
        or case not in ('expiry','owner-exit')and version is not None
        or case=='pressure'and(type(pressure)is not int or pressure!=1)
        or case!='pressure'and pressure is not None):
        raise CaptureError('explicit shared lifetime case/contract1 required;old releases are not lifetime evidence')
    return case


def boot_shared_case(tokens,enabled):
    values=[v.split('=',1)[1]for v in tokens if v.startswith('ws73.subscription_shared_case=')]
    if not values:return 'release'
    if len(values)!=1 or not enabled or values[0]not in ('expiry','owner-exit','pressure'):
        raise CaptureError('one enabled shared lifetime boot case required')
    return values[0]


def shared_boot(tokens):
    found=[v for v in tokens if v.startswith('ws73.ssap_subscription_shared=')]
    if found not in([],['ws73.ssap_subscription_shared=1']):raise CaptureError('one exact shared-owner boot selector required')
    return bool(found)


def lease_matrix(row,sender):
    if owner_loss_required(row):return [(m,n)for m in(1,2)for n in(0,1)]
    return [(1,0),(2,0),(2,1)]if inflight_required(row)and sender==0 else[(1,0),(2,0)]


INFLIGHT_TOOLS=tuple('/usr/share/sparklink/tools/'+n for n in
    ('ws73_ssap_sender_deadline.py','ws73_diagnostic_hold.py','ws73_channel_prefix_hold.py'))


def tool_records(root=Path('/'),*,snapshot=False,inflight=False,shared=False):
    from ws73_role_snapshot import HELPER,SUPERVISOR
    names=(*TOOLS,HELPER,SUPERVISOR)if snapshot else TOOLS
    if inflight:names=(*names,*INFLIGHT_TOOLS)
    if shared:names=(*names,"/usr/share/sparklink/tools/ws73_ssap_shared.py","/usr/share/sparklink/tools/ws73_ssap_owned.py")
    return {name:dict(sha256=hashlib.sha256((root/name.lstrip('/')).read_bytes()).hexdigest(),
                     bytes=(root/name.lstrip('/')).stat().st_size)for name in names}


def validate_tools(records,root,manifest):
    from ws73_role_snapshot import HELPER
    if records!=tool_records(root,snapshot=HELPER in records,inflight=INFLIGHT_TOOLS[0]in records,shared="/usr/share/sparklink/tools/ws73_ssap_shared.py"in records):raise CaptureError('subscription tools differ from sealed root')
    for name,receipt in records.items():
        actual=(root/name.lstrip('/')).resolve(strict=True)
        matches=[p for p in manifest if Path(p['path']).resolve()==actual]
        if len(matches)!=1 or matches[0]['sha256']!=receipt['sha256']:
            raise CaptureError('subscription actual tool missing from original build manifest')


def validate_request(row,phase):
    renewal=renewal_required(row)
    pressure=pressure_required(row)
    owner_loss=owner_loss_required(row)
    inflight=inflight_required(row)
    expiry=inflight_case(row)=='expiry'
    from ws73_role_snapshot import requested as snapshot_required
    fields={'phase','owners','tools','security_requirement','message_security_required','status','start_wall_ns'}
    if 'parallel_pair'in row:
        pair=row['parallel_pair'];role_paths(pair)
        if pair is None or {x['owner'].get('port')for x in row['owners']}!={f'1-{2*pair+1}',f'1-{2*pair+2}'}:
            raise CaptureError('actual selected controller pair required')
        fields.add('parallel_pair')
    if renewal:fields|={'ssap_subscription_renewal_required','ssap_subscription_renewal_contract_version'}
    if pressure:fields|={'ssap_subscription_pressure_required','ssap_subscription_pressure_contract_version'}
    if owner_loss:fields|={'ssap_subscription_owner_loss_required','ssap_subscription_owner_loss_contract_version'}
    if inflight:fields|={'ssap_subscription_inflight_release_required','ssap_subscription_inflight_release_contract_version'}
    if expiry:fields|={'ssap_subscription_inflight_case','ssap_subscription_inflight_expiry_contract_version'}
    if shared_required(row):fields|={'ssap_subscription_shared_required','ssap_subscription_shared_contract_version'}
    case=shared_case(row)
    if case!='release':fields|={'ssap_subscription_shared_case','ssap_subscription_shared_pressure_contract_version'if case=='pressure'else'ssap_subscription_shared_lifetime_contract_version'}
    if snapshot_required(row):fields.add('ssap_subscription_snapshot_contract_version')
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
    from ws73_role_snapshot import TOKEN
    snapshot=Path('/proc/cmdline').read_text().split().count(TOKEN)==1
    value=dict(phase=phase,owners=row['owners'],tools=tool_records(snapshot=snapshot,inflight=getattr(run.args,'ssap_subscription_inflight_release_verify',False),shared=getattr(run.args,'ssap_subscription_shared_verify',False)),security_requirement=row['security_requirement'],
               message_security_required=row['message_security_required'],status='RUNNING',start_wall_ns=time.time_ns())
    if getattr(run.args,'ssap_subscription_renewal_verify',False):
        value.update(ssap_subscription_renewal_required=True,ssap_subscription_renewal_contract_version=1)
    if getattr(run.args,'ssap_subscription_pressure_verify',False):
        value.update(ssap_subscription_pressure_required=True,ssap_subscription_pressure_contract_version=1)
    if getattr(run.args,'ssap_subscription_owner_loss_verify',False):
        value.update(ssap_subscription_owner_loss_required=True,ssap_subscription_owner_loss_contract_version=1)
    if getattr(run.args,'ssap_subscription_inflight_release_verify',False):
        value.update(ssap_subscription_inflight_release_required=True,ssap_subscription_inflight_release_contract_version=1)
    if requested_inflight_case(run.args)=='expiry':value.update(ssap_subscription_inflight_case='expiry',ssap_subscription_inflight_expiry_contract_version=1)
    if getattr(run.args,'ssap_subscription_shared_verify',False):value.update(ssap_subscription_shared_required=True,ssap_subscription_shared_contract_version=1)
    case=requested_shared_case(run.args)
    if case!='release':value.update(ssap_subscription_shared_case=case,**{'ssap_subscription_shared_pressure_contract_version'if case=='pressure'else'ssap_subscription_shared_lifetime_contract_version':1})
    if snapshot:value['ssap_subscription_snapshot_contract_version']=1
    if getattr(run.args,'shared_subscription',False):value['parallel_pair']=run.args.pair
    validate_request(value,phase)
    path=run.output/f'subscription-role-{phase}.request.json';temporary=path.with_suffix('.tmp')
    with temporary.open('x')as stream:json.dump(value,stream)
    temporary.chmod(0o600);os.link(temporary,path);temporary.unlink()
    root,_=role_paths(value.get('parallel_pair'))
    response=root/f'phase-{phase}'/'run.json';deadline=time.monotonic()+90
    while not response.is_file():
        if time.monotonic()>=deadline:raise CaptureError('subscription role supervisor deadline')
        time.sleep(.01)
    from ws73_application_role import read_json,verify_probe
    result=read_json(response,0,limit=(4096 if case=='pressure'else 1024 if pressure_required(value)or shared_required(value)else 512)*1024)
    for key in value:
        if result.get(key)!=value[key]:raise CaptureError('root subscription supervisor changed original request')
    verify_probe(result)
    if result.get('ssap_subscription_status')!=STATUS:raise CaptureError('actual subscription phase failed: '+str(result.get('error')))
    for key in ('ssap_subscription','ssap_subscription_status','role_probe','role_supervisor','channel_role','application_role_contract_version'):
        row[key]=result[key]
    if owner_loss_required(value):row['role_ssap_commands']=result['role_ssap_commands']
    row.update(ssap_subscription_required=True,ssap_subscription_contract_version=1,
               ssap_subscription_tools=value['tools'],ssap_subscription_request=value)
    if renewal_required(value):row.update(ssap_subscription_renewal_required=True,ssap_subscription_renewal_contract_version=1)
    if pressure_required(value):row.update(ssap_subscription_pressure_required=True,ssap_subscription_pressure_contract_version=1)
    if owner_loss_required(value):row.update(ssap_subscription_owner_loss_required=True,ssap_subscription_owner_loss_contract_version=1)
    if inflight_required(value):row.update(ssap_subscription_inflight_release_required=True,ssap_subscription_inflight_release_contract_version=1)
    if inflight_case(value)=='expiry':row.update(ssap_subscription_inflight_case='expiry',ssap_subscription_inflight_expiry_contract_version=1)
    if shared_required(value):row.update(ssap_subscription_shared_required=True,ssap_subscription_shared_contract_version=1)
    if case!='release':row.update(ssap_subscription_shared_case=case,**{'ssap_subscription_shared_pressure_contract_version'if case=='pressure'else'ssap_subscription_shared_lifetime_contract_version':1})
    if snapshot:row['ssap_subscription_snapshot_contract_version']=1
    if 'parallel_pair'in value:row['parallel_pair']=value['parallel_pair']
    run.save()


def app_rows(process,app):
    text=Path(app['output_files'][0]).read_text()
    # A live regular file can end in the middle of one stdio write. Only the
    # current incomplete tail is pending;terminal raw output is checked exactly.
    raw=[line for line in text.splitlines(keepends=True)if line.endswith('\n')]
    version=app.get('ssap_shared_pressure_contract_version')
    if version is not None and(type(version)is not int or version!=1):raise CaptureError('explicit shared-pressure transcript contract required')
    if len(raw)>(64 if version is not None else 24):raise CaptureError('bounded subscription application transcript required')
    try:return [json.loads(line)for line in raw]
    except json.JSONDecodeError as error:raise CaptureError('complete actual SDK JSON output required')from error


def wait_stage(process,app,stage,count,deadline):
    while True:
        rows=app_rows(process,app);found=[v for v in rows if v.get('stage')==stage]
        if len(found)>count:raise CaptureError('duplicate or unexpected SDK stage')
        if len(found)==count:return found[-1]
        if process.poll()is not None or time.monotonic()>=deadline:raise CaptureError('actual SDK stage/original supervisor budget missing: '+stage)
        time.sleep(.01)


def stop_reader_process(run,lease,process):
    """Only a known disposable guest reader;no host process/hardware action."""
    from ws73_application_role import require_vm
    require_vm('ws73.ssap_subscription=1')
    if process.pid!=lease['application']['pid']:raise CaptureError('original reader child identity required')
    process_identity(process.pid,1004)
    if process.poll()is not None:raise CaptureError('reader exited before intentional owner-loss point')
    death=dict(start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns(),pid=process.pid,signal=9)
    lease['owner_loss']=death;run.save()
    process.kill();death['exit']=process.wait(timeout=2)
    death.update(exit_wall_ns=time.time_ns(),exit_monotonic_ns=time.monotonic_ns())
    if death['exit']!=-9:raise CaptureError('actual known reader SIGKILL required')
    death['observation_deadline_ns']=death['start_monotonic_ns']+5_000_000_000;run.save()
    return death


def owner_cleanup(run,row,peer,owner,item,lease,process):
    death=stop_reader_process(run,lease,process)
    lease['disabled']=configuration(owner,item,0);death['read_attempts']=[];run.save()
    for _ in range(16):
        remaining=(death['observation_deadline_ns']-time.monotonic_ns())/1e9
        if remaining<=0:raise CaptureError('original owner-loss observation budget')
        observed=run.command([str(run.args.slctl),'--adapter',peer['owner']['path'],'ssap-read',peer['object']['path'],str(item['handle']),'0'],min(2,remaining),collection='ssap_values')
        death['read_attempts'].append(observed);run.save()
        if not observed['exit']:
            expected=f'SsapPeerValue: operation=ssap-read path={peer["object"]["path"]} handle={item["handle"]} value={lease["messages"][-1]["reply"]}'
            if observed['stderr']or observed['stdout'].splitlines().count(expected)!=1:raise CaptureError('same-actor post-cleanup read changed actual value')
            break
        if 'SSAP client sequence owned by receive transaction'not in observed['stderr']:
            raise CaptureError('post-cleanup read failed for a reason other than the original live receive transaction')
        time.sleep(.01)
    else:raise CaptureError('finite owner-loss actor convergence attempts exhausted')
    death.update(end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns())
    if death['end_monotonic_ns']>=death['observation_deadline_ns']:raise CaptureError('owner-loss original observation expired')
    run.save()
    return death


def checked_update_reply(process,app,owner,item,value,reply,checked_count,batch_count,*,limit,before_wait=None,record=None,save=None):
    """One actual SDK read/check/writeback,shared by finite VM workloads."""
    process.stdin.write('check '+value+' '+reply+'\n');process.stdin.flush()
    result={}if record is None else record
    def checkpoint():
        if save is not None:save()
    if before_wait is not None:result['send']=before_wait();checkpoint()
    result['checked']=wait_stage(process,app,'ssap_subscription_checked_reply',checked_count,time.monotonic()+6);checkpoint()
    result['batch']=wait_stage(process,app,'ssap_subscription_batch',batch_count,time.monotonic()+1);checkpoint()
    result['after']=value_snapshot(owner,item,reply,limit=limit);checkpoint()
    return result


def checked_cached_reply(process,app,owner,item,value,reply,checked_count,*,limit,record,save):
    """Same real SDK cached read/check/writeback for single/shared pressure."""
    process.stdin.write('check-cached '+value+' '+reply+'\n');process.stdin.flush()
    record['checked']=wait_stage(process,app,'ssap_subscription_checked_reply',checked_count,time.monotonic()+6)
    record['after']=value_snapshot(owner,item,reply,limit=limit);save()


def execute_inflight_cleanup(run,row,owner,item,lease,process):
    from ws73_ssap_sender_deadline import selection
    from ws73_channel_prefix_hold import PrefixBarrier
    from ws73_diagnostic_hold import write_marker
    sequence=(row['phase']<<24)|(2<<16)|COUNT
    value=sequence.to_bytes(4,'little')+secrets.token_bytes(28)
    case=dict(value=value.hex(),mode=2,start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns())
    lease['inflight_release']=case;run.save()
    case['replacement']=command_receipt(owner,item,'replace '+value.hex(),'SdkOwnedReplaced')
    case['before']=value_snapshot(owner,item,value.hex(),limit=32);run.save()
    # Existing fixture prep only;actual update/ACK/disable witnesses below
    # decide correctness,not this quiet interval or a configuration value.
    time.sleep(.15)
    folder=INPUT/'sender-deadline-hold'/f'phase-{row["phase"]}';folder.parent.mkdir(exist_ok=True)
    barrier=PrefixBarrier(case,run.save,folder,field='hold')
    case['selection']=selection(row,dict(item,secret=value.hex()),time.time_ns())
    write_marker(folder/'selection.json',case['selection']);run.save()
    barrier.stage('arm_ready','armed')
    app=lease['application'];expiry=inflight_case(row)=='expiry'
    def held():
        barrier.stage('wait_held','held')
        if expiry:
            active=lease['active'];upper=active['returned_ns']+INITIAL_RENEWAL_LEASE_MS*1_000_000
            threshold=upper+50_000_000
            observed=dict(original_expires_ns=active['expires_ns'],original_expiry_upper_ns=upper,threshold_ns=threshold,
                          start_ns=time.monotonic_ns(),start_wall_ns=time.time_ns())
            case['expiry']=observed;run.save()
            if not observed['start_ns']<active['expires_ns']<=upper<threshold<=observed['start_ns']+1_100_000_000:
                raise CaptureError('actual accepted indication must be held before original lease expiry')
            # No app request here. Existing actor's original lease timer alone
            # must initiate disable;Host checks real disableTX before unhold.
            while time.monotonic_ns()<threshold:
                if process.poll()is not None:raise CaptureError('subscriber exited before original expiry')
                time.sleep(min(.01,max(0,(threshold-time.monotonic_ns())/1e9)))
            observed.update(end_ns=time.monotonic_ns(),end_wall_ns=time.time_ns());run.save()
        else:
            case.update(release_request_wall_ns=time.time_ns(),release_request_monotonic_ns=time.monotonic_ns());run.save()
            process.stdin.write('release-observe\n');process.stdin.flush()
            case['release_started']=wait_stage(process,app,'ssap_subscription_release_started',1,time.monotonic()+1)
            if any(r.get('stage')=='ssap_subscription_released'for r in app_rows(process,app)):
                raise CaptureError('cleanup completed before the controlled in-flight release point')
        # Host refuses unhold until actual disableTX is captured with the
        # provider's original ACK RX still absent. No guessed delay barrier.
        barrier.release();run.save()
    case['send']=command_receipt(owner,item,'indicate','SdkOwnedUpdate',before_receipt=held)
    if expiry:
        observed=case['expiry'];observed.update(read_request_wall_ns=time.time_ns(),read_request_ns=time.monotonic_ns())
        process.stdin.write('poll\n');process.stdin.flush()
        lease['expiry_observation']=wait_stage(process,app,'ssap_subscription_batch',COUNT+1,lease['active']['expires_ns']/1e9+5)
        if lease['expiry_observation']['state']==2:
            process.stdin.write('release\n');process.stdin.flush()
            lease['release']=wait_stage(process,app,'ssap_subscription_released',1,lease['active']['expires_ns']/1e9+5)
    else:lease['release']=wait_stage(process,app,'ssap_subscription_released',1,time.monotonic()+5)
    case.update(end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns());run.save()


def execute_supervised(run,row):
    """Only the existing root VM role supervisor calls this finite workload."""
    from ws73_application_role import require_vm
    require_vm('ws73.ssap_subscription=1')
    renewal=renewal_required(row)
    pressure=pressure_required(row)
    owner_loss=owner_loss_required(row)
    inflight=inflight_required(row)
    if ('ws73.ssap_subscription_renewal=1'in Path('/proc/cmdline').read_text().split())!=renewal:
        raise CaptureError('renewal boot/request mismatch')
    if ('ws73.ssap_subscription_pressure=1'in Path('/proc/cmdline').read_text().split())!=pressure:
        raise CaptureError('pressure boot/request mismatch')
    if ('ws73.ssap_subscription_owner_loss=1'in Path('/proc/cmdline').read_text().split())!=owner_loss:
        raise CaptureError('owner-loss boot/request mismatch')
    if ('ws73.ssap_subscription_inflight_release=1'in Path('/proc/cmdline').read_text().split())!=inflight:
        raise CaptureError('in-flight release boot/request mismatch')
    if boot_inflight_case(Path('/proc/cmdline').read_text().split(),inflight)!=inflight_case(row):raise CaptureError('in-flight original case boot/request mismatch')
    if shared_boot(Path('/proc/cmdline').read_text().split())!=shared_required(row):raise CaptureError('shared owner boot/request mismatch')
    if boot_shared_case(Path('/proc/cmdline').read_text().split(),shared_required(row))!=shared_case(row):raise CaptureError('shared lifetime boot/request mismatch')
    if shared_required(row):
        from ws73_ssap_shared import execute
        return execute(run,row)
    row.update(ssap_subscription=[],ssap_subscription_required=True,ssap_subscription_contract_version=1);run.save()
    for sender in (0,1):
        peer,server=row['owners'][sender],row['owners'][1-sender]
        api='c'if (row['phase']+sender)%2==0 else'python';reader='python'if api=='c'else'c'
        with publisher(run,row,sender,'allow',collection='ssap_subscription',label='subscription',
                       sdk_api=api,updates=True,application_uid=1005)as(owner,item):
            discover(run,peer,item);item['leases']=[];run.save()
            matrix=lease_matrix(row,sender)
            for mode,attempt in matrix:
                duration=lease_duration(row,sender,mode,attempt)
                prefix=['/bin/ws73-application-client-c']if reader=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
                args=prefix+['subscription',str(peer['owner']['index']),str(peer['owner']['generation']),
                             peer['object']['path'],str(item['handle']),str(mode),str(duration)]
                label=f'subscription-{row["phase"]}-{sender}-{mode}'
                if owner_loss:label+='-dead'if attempt==0 else'-replacement'
                if inflight:label+='-attempt-'+str(attempt)
                out=run.output/(label+'.stdout');err=run.output/(label+'.stderr')
                lease=dict(mode=mode,start_wall_ns=time.time_ns(),messages=[]);item['leases'].append(lease)
                if owner_loss or inflight:lease['attempt']=attempt
                app=dict(api=reader,args=args,environment=application_environment(),start_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
                lease['application']=app;run.save();process=None
                try:
                    with ExitStack()as files:
                        process=subprocess.Popen(args,user=1004,group=1004,extra_groups=[],env=dict(os.environ,**application_environment()),
                            stdin=subprocess.PIPE,stdout=files.enter_context(out.open('x')),stderr=files.enter_context(err.open('x')),text=True)
                        app.update(pid=process.pid);app['credentials'],app['process_status']=process_identity(process.pid,1004);run.save()
                        lease['active']=wait_stage(process,app,'ssap_subscription_active',1,time.monotonic()+6)
                        if (owner_loss or inflight)and attempt==1:
                            old=item['leases'][-2]['active'];fresh=lease['active']
                            if fresh['token']==old['token']or fresh['epoch']!=old['epoch']:raise CaptureError('fresh lease token and original epoch required')
                        lease['enabled']=configuration(owner,item,mode,process);run.save()
                        for number in range(PRESSURE_CAPACITY+2 if pressure else COUNT):
                            sequence=(row['phase']<<24)|(sender<<20)|(mode<<16)|((attempt<<12)if owner_loss or inflight else 0)|number
                            value=sequence.to_bytes(4,'little')+secrets.token_bytes(28)
                            reply=(sequence|0x80000000).to_bytes(4,'little')+secrets.token_bytes(28)
                            case=dict(number=number,value=value.hex(),reply=reply.hex(),start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns());lease['messages'].append(case)
                            case['replacement']=command_receipt(owner,item,'replace '+value.hex(),'SdkOwnedReplaced',limit=40 if pressure else 32)
                            case['before']=value_snapshot(owner,item,value.hex(),limit=80 if pressure else 32 if owner_loss or inflight else 16);run.save()
                            if pressure and number<=PRESSURE_CAPACITY:
                                overflow=number==PRESSURE_CAPACITY
                                case['send']=command_receipt(owner,item,'indicate-observe'if overflow and mode==2 else'indicate'if mode==2 else'notify',
                                    'SdkOwnedUpdateObserved'if overflow and mode==2 else'SdkOwnedUpdate',limit=40)
                                case['sent_wall_ns']=time.time_ns();run.save()
                                if not overflow:continue
                                process.stdin.write('drain\n');process.stdin.flush()
                                lease['drained']=wait_stage(process,app,'ssap_subscription_batch',1,time.monotonic()+6);run.save()
                                for position,filled in enumerate(lease['messages'][:PRESSURE_CAPACITY]):
                                    checked_cached_reply(process,app,owner,item,filled['value'],filled['reply'],position+1,limit=80,record=filled,save=run.save)
                                    filled['end_wall_ns']=time.time_ns();filled['end_monotonic_ns']=time.monotonic_ns();run.save()
                                case['end_wall_ns']=time.time_ns();case['end_monotonic_ns']=time.monotonic_ns();run.save();continue
                            case.update(checked_update_reply(process,app,owner,item,value.hex(),reply.hex(),number if pressure else number+1,2 if pressure else number+1,
                                limit=80 if pressure else 32 if owner_loss or inflight else 16,record=case,save=run.save,
                                before_wait=lambda:command_receipt(owner,item,'indicate'if mode==2 else'notify','SdkOwnedUpdate',limit=40 if pressure else 32)))
                            case['end_wall_ns']=time.time_ns();case['end_monotonic_ns']=time.monotonic_ns();run.save()
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
                        if owner_loss and attempt==0:
                            owner_cleanup(run,row,peer,owner,item,lease,process)
                        else:
                            if inflight and sender==0 and mode==2 and attempt==0:
                                execute_inflight_cleanup(run,row,owner,item,lease,process)
                            else:
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
                if not(owner_loss and attempt==0):lease['disabled']=configuration(owner,item,0)
                lease['end_wall_ns']=time.time_ns();run.save()
            owner.stdin.write('quit\n');owner.stdin.flush();owner.wait(timeout=2)
            if owner.returncode:raise CaptureError('original service owner cleanup failed')
            item['cleanup']=await_removed(run,server,item['start']);run.save()
    row['ssap_subscription_status']=STATUS;run.save()


def role(identity,uid):
    if (identity['uids']!=[uid]*4 or identity['gids']!=[uid]*4 or identity['groups']!=[]
            or set(identity['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'}
            or any(int(v,16)for v in identity['capabilities'].values())):
        raise CaptureError('exact independent cap-zero application/service-only credentials required')


def verify_supervisor_artifacts(control,evidence,*,pair=None):
    """Actual root outputs,not a caller-supplied completed summary."""
    from ws73_application_role import verify_probe
    evidence=Path(evidence);artifact,_=role_paths(pair);root=evidence/artifact.relative_to('/evidence')
    finished=json.loads((root/'finished.json').read_text())
    if (finished['status']!='TWO_FINITE_SUBSCRIPTION_PHASES_COMPLETED'
            or finished['daemon']!=control['daemon_before']or control['daemon_before']!=control['daemon_after']
            or len(control['channel_socket'])!=2 or finished.get('parallel_pair')!=pair):raise CaptureError('two actual root subscription phases and unchanged daemon required')
    from ws73_role_snapshot import requested as snapshot_required,verify as verify_snapshot,HELPER
    snapshots=[snapshot_required(row)for row in control['channel_socket']]
    if any(snapshots)and not all(snapshots):raise CaptureError('two matching snapshot phases required')
    if all(snapshots):
        if type(finished.get('snapshot_contract_version'))is not int or finished['snapshot_contract_version']!=1:raise CaptureError('completed snapshot supervisor required')
    elif finished.get('snapshot_contract_version')is not None:raise CaptureError('unrequested snapshot receipt')
    exported=[]
    for phase,row in enumerate(control['channel_socket']):
        original=json.loads((root/f'phase-{phase}'/'run.json').read_text())
        if original.get('parallel_pair')!=pair or row.get('parallel_pair')!=pair:raise CaptureError('original role pair namespace required')
        verify_probe(original)
        for key,value in row['ssap_subscription_request'].items():
            if original[key]!=value:raise CaptureError('original root request identity changed')
        for key in ('ssap_subscription','ssap_subscription_status','role_probe','role_supervisor','channel_role','application_role_contract_version'):
            if row[key]!=original[key]:raise CaptureError('root subscription record differs from control')
        if owner_loss_required(row)and row.get('role_ssap_commands')!=original.get('role_ssap_commands'):
            raise CaptureError('actual root same-actor read records required')
        if shared_required(original)!=shared_required(row)or shared_case(original)!=shared_case(row):raise CaptureError('original root shared request differs from parent result')
        if (original['ssap_subscription_status']!=STATUS or original['ssap_subscription_contract_version']!=1
                or original['role_supervisor']!=finished['supervisor']):raise CaptureError('completed original root subscription phase required')
        if snapshot_required(row):
            if snapshot_required(original)is not True or HELPER not in row['ssap_subscription_tools']:raise CaptureError('actual snapshot helper identity required')
            exported.append(verify_snapshot(root/f'phase-{phase}',phase=phase,expected_helper=row['ssap_subscription_tools'][HELPER]['sha256'],pair=pair))
        apps=[original['role_probe']]
        for item in original['ssap_subscription']:
            apps.append(item);apps.extend(l['application']for l in item['leases'])
        for app in apps:
            for filename in app['output_files']:
                relative=Path(filename).relative_to('/evidence')
                if not relative.is_relative_to(artifact.relative_to('/evidence')/f'phase-{phase}'):
                    raise CaptureError('fixed phase output paths required')
                if (evidence/relative).read_text()!=app['stdout'if filename.endswith('.stdout')else'stderr']:
                    raise CaptureError('raw process stream differs from original subscription record')
    renewals=[renewal_required(row)for row in control['channel_socket']]
    if any(renewals)and not all(renewals):raise CaptureError('both real renewal phases required')
    pressures=[pressure_required(row)for row in control['channel_socket']]
    if any(pressures)and not all(pressures):raise CaptureError('both real pressure phases required')
    losses=[owner_loss_required(row)for row in control['channel_socket']]
    if any(losses)and not all(losses):raise CaptureError('both real owner-loss phases required')
    inflights=[inflight_required(row)for row in control['channel_socket']]
    if any(inflights)and not all(inflights):raise CaptureError('both real in-flight release phases required')
    shared=[shared_required(row)for row in control['channel_socket']]
    if any(shared)and not all(shared):raise CaptureError('both shared phases required')
    shared_cases=[shared_case(row)for row in control['channel_socket']]
    shared_pressure=all(shared)and shared_cases==['pressure','pressure']
    result=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,
                phases=2,reader_UID=1004,provider_UID=1005,readers=24 if all(shared)else 16 if all(losses)else 10 if all(inflights)else 8,providers=4,updates=176 if shared_pressure else 56 if all(shared)else 144 if all(pressures)else 48 if all(losses)else 32 if all(inflights)else 24,
                daemon=finished['daemon'],supervisor=finished['supervisor'],
                scope='Fixed actual role supervision only;not raw RF replay or full lifecycle/recovery qualification')
    if all(renewals):result.update(renewal_contract_version=1,renewals=8,post_original_expiry_updates=16)
    if all(pressures):result.update(pressure_contract_version=1,checked_replies=136,notification_drops=4,indication_refusals=4,resumed=8)
    if all(losses):result.update(owner_loss_contract_version=1,owner_losses=8,replacement_leases=8,cleanup_read_barriers=8)
    if all(inflights):
        cases=[inflight_case(row)for row in control['channel_socket']]
        if len(set(cases))!=1:raise CaptureError('same original in-flight case in both phases required')
        result.update(inflight_release_contract_version=1,replacement_leases=2,checked_replies=30,discarded_pending=2)
        if cases[0]=='expiry':result.update(inflight_case='expiry',inflight_expiry_contract_version=1,inflight_expirations=2)
        else:result['inflight_releases']=2
    if all(shared):
        cases=[shared_case(row)for row in control['channel_socket']]
        if len(set(cases))!=1:raise CaptureError('same shared lifetime case in both phases required')
        result.update(shared_contract_version=1,shared_groups=8,shared_joins=16,checked_replies=328 if shared_pressure else 96,retained_releases=8 if cases[0]=='owner-exit'else 16,last_disables=8)
        if shared_pressure:result.update(shared_case='pressure',shared_pressure_contract_version=1,slow_notification_drops=4,slow_indication_refusals=4,healthy_losses=0,ordered_drains=8,resumed=8,healthy_replies=176)
        elif cases[0]!='release':result.update(shared_case=cases[0],shared_lifetime_contract_version=1,**({'partial_expirations':8,'expired_discarded':8}if cases[0]=='expiry'else{'partial_owner_exits':8,'unconsumed_published':8}))
    if exported:result.update(snapshot_contract_version=1,snapshot_phases=2,snapshot_files=sum(len(s['files'])for s in exported),snapshot_bytes=sum(s['bytes']for s in exported))
    if pair is not None:result['parallel_pair']=pair
    return result


def valid_snapshot_supervision(proof):
    from ws73_role_snapshot import FILES,LIMIT
    return(valid_supervision(proof)and type(proof.get('snapshot_contract_version'))is int and proof['snapshot_contract_version']==1
        and type(proof.get('snapshot_phases'))is int and proof['snapshot_phases']==2
        and type(proof.get('snapshot_files'))is int and 28<=proof['snapshot_files']<=2*FILES
        and type(proof.get('snapshot_bytes'))is int and 0<proof['snapshot_bytes']<=2*LIMIT)


def valid_supervision(proof):
    try:
        shared=proof.get('shared_contract_version')is not None
        if shared and(type(proof['shared_contract_version'])is not int or proof['shared_contract_version']!=1 or any(proof.get(k)is not None for k in ('owner_loss_contract_version','inflight_release_contract_version','pressure_contract_version','renewal_contract_version'))):return False
        loss=proof.get('owner_loss_contract_version')is not None
        inflight=proof.get('inflight_release_contract_version')is not None
        if loss and(type(proof['owner_loss_contract_version'])is not int or proof['owner_loss_contract_version']!=1
                or inflight or proof.get('pressure_contract_version')is not None or proof.get('renewal_contract_version')is not None):return False
        if inflight and(type(proof['inflight_release_contract_version'])is not int or proof['inflight_release_contract_version']!=1
                or proof.get('pressure_contract_version')is not None or proof.get('renewal_contract_version')is not None):return False
        shared_pressure=proof.get('shared_pressure_contract_version')is not None
        if shared_pressure and(not shared or type(proof['shared_pressure_contract_version'])is not int or proof['shared_pressure_contract_version']!=1 or proof.get('shared_case')!='pressure'):return False
        expected=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,
                      phases=2,reader_UID=1004,provider_UID=1005,readers=24 if shared else 16 if loss else 10 if inflight else 8,providers=4,
                      updates=176 if shared_pressure else 56 if shared else 144 if proof.get('pressure_contract_version')==1 else 48 if loss else 32 if inflight else 24)
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


def valid_owner_loss_supervision(proof):
    return(valid_supervision(proof)and all(type(proof.get(k))is int and proof[k]==v
        for k,v in dict(owner_loss_contract_version=1,owner_losses=8,replacement_leases=8,cleanup_read_barriers=8).items()))


def valid_inflight_supervision(proof,*,case='release'):
    return(case in ('release','expiry')and valid_supervision(proof)
        and proof.get('inflight_case','release')==case
        and (proof.get('inflight_expiry_contract_version')==1 and type(proof['inflight_expiry_contract_version'])is int if case=='expiry'else proof.get('inflight_expiry_contract_version')is None)
        and ('inflight_releases'not in proof if case=='expiry'else 'inflight_expirations'not in proof)
        and all(type(proof.get(k))is int and proof[k]==v
        for k,v in dict(inflight_release_contract_version=1,**{'inflight_expirations'if case=='expiry'else'inflight_releases':2},replacement_leases=2,checked_replies=30,discarded_pending=2).items()))


def valid_shared_supervision(proof,*,case='release'):
    if case not in ('release','expiry','owner-exit','pressure')or proof.get('shared_case','release')!=case:return False
    if case in ('release','pressure'):
        if any(proof.get(k)is not None for k in ('shared_lifetime_contract_version','partial_expirations','expired_discarded','partial_owner_exits','unconsumed_published')):return False
    elif type(proof.get('shared_lifetime_contract_version'))is not int or proof['shared_lifetime_contract_version']!=1:return False
    wanted=dict(shared_contract_version=1,shared_groups=8,shared_joins=16,checked_replies=328 if case=='pressure'else 96,retained_releases=8 if case=='owner-exit'else 16,last_disables=8)
    if case=='pressure':wanted.update(shared_pressure_contract_version=1,slow_notification_drops=4,slow_indication_refusals=4,healthy_losses=0,ordered_drains=8,resumed=8,healthy_replies=176)
    elif any(proof.get(k)is not None for k in ('shared_pressure_contract_version','slow_notification_drops','slow_indication_refusals','healthy_losses','ordered_drains','resumed','healthy_replies')):return False
    if case=='expiry':
        if any(proof.get(k)is not None for k in ('partial_owner_exits','unconsumed_published')):return False
        wanted.update(partial_expirations=8,expired_discarded=8)
    if case=='owner-exit':
        if any(proof.get(k)is not None for k in ('partial_expirations','expired_discarded')):return False
        wanted.update(partial_owner_exits=8,unconsumed_published=8)
    return valid_supervision(proof)and all(type(proof.get(k))is int and proof[k]==v for k,v in wanted.items())


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


def verify_owner_loss(lease,peer,handle):
    """Actual child death and bounded same-actor read;not config0 alone."""
    death=lease['owner_loss'];app=lease['application']
    integers=('start_wall_ns','end_wall_ns','exit_wall_ns','start_monotonic_ns',
              'end_monotonic_ns','exit_monotonic_ns','observation_deadline_ns','pid','signal','exit')
    if (any(type(death[k])is not int for k in integers)
            or type(app['pid'])is not int or app['pid']!=death['pid']or death['pid']<=0
            or death['signal']!=9 or death['exit']!=-9 or app['exit']!=-9 or 'release'in lease
            or not lease['messages'][-1]['end_wall_ns']<=death['start_wall_ns']<=death['exit_wall_ns']<=death['end_wall_ns']<=app['end_wall_ns']
            or not lease['messages'][-1]['end_monotonic_ns']<=death['start_monotonic_ns']<=death['exit_monotonic_ns']<=death['end_monotonic_ns']<death['observation_deadline_ns']
            or death['exit_monotonic_ns']-death['start_monotonic_ns']>2_000_000_000
            or death['observation_deadline_ns']!=death['start_monotonic_ns']+5_000_000_000):
        raise CaptureError('actual known reader death and unchanged original observation deadline required')
    attempts=death['read_attempts']
    if not 1<=len(attempts)<=16:raise CaptureError('bounded complete actor convergence attempts required')
    previous=death['exit_wall_ns'];previous_mono=death['exit_monotonic_ns']
    for n,command in enumerate(attempts):
        role(command['credentials'],1000)
        if (command['args']!=['/bin/slctl','--adapter',peer['owner']['path'],'ssap-read',peer['object']['path'],str(handle),'0']
                or type(command['exit'])is not int
                or any(type(command[k])is not int for k in ('start_wall_ns','end_wall_ns','start_monotonic_ns','end_monotonic_ns'))
                or not previous<=command['start_wall_ns']<=command['end_wall_ns']<=death['end_wall_ns']
                or not previous_mono<=command['start_monotonic_ns']<=command['end_monotonic_ns']<=death['end_monotonic_ns']):
            raise CaptureError('original credential-bound same-actor read intervals required')
        if n==len(attempts)-1:
            expected=f'SsapPeerValue: operation=ssap-read path={peer["object"]["path"]} handle={handle} value={lease["messages"][-1]["reply"]}'
            if command['exit']or command['stderr']or command['stdout'].splitlines().count(expected)!=1:
                raise CaptureError('actual successful same-actor value read required')
        elif not command['exit']or 'SSAP client sequence owned by receive transaction'not in command['stderr']:
            raise CaptureError('only original Busy refusals may precede successful read')
        previous=command['end_wall_ns'];previous_mono=command['end_monotonic_ns']
    return attempts[-1]


def verify_inflight_release(row,item,lease,api,reader,exchange):
    from ws73_ssap_sender_deadline import check_selection
    from ws73_diagnostic_hold import PROPERTIES
    case=lease['inflight_release'];value=bytes.fromhex(case['value']);h=item['handle']
    sequence=(row['phase']<<24)|(2<<16)|COUNT
    if len(value)!=32 or value[:4]!=sequence.to_bytes(4,'little')or case['mode']!=2:
        raise CaptureError('original fresh sequence-bearing pending indication required')
    selection=case['selection'];check_selection(selection,row['phase'])
    owners=[dict(bus=v['owner']['bus'],device=v['owner']['device'],index=v['owner']['index'],generation=v['owner']['generation'],lifetime=v['object']['lifetime'],handle=v['object']['handle'],port=v['owner']['port'])for v in row['owners']]
    if selection['controllers']!=owners or selection['property']!=h or selection['value']!=case['value']:
        raise CaptureError('original pending indication and endpoint binding required')
    expiry=inflight_case(row)=='expiry'
    if expiry:
        trigger=verify_expiry_observation(lease,reader)
    else:
        trigger=case['release_request_wall_ns']
        started=case['release_started']
    if not expiry and(set(started)!={'stage','api','started_ns','deadline_ns'}
            or started['stage']!='ssap_subscription_release_started'or started['api']!=reader
            or any(type(started[k])is not int for k in ('started_ns','deadline_ns'))
            or started['deadline_ns']-started['started_ns']!=5_000_000_000
            or not case['release_request_monotonic_ns']<=started['started_ns']<=case['end_monotonic_ns']<started['deadline_ns']):
        raise CaptureError('actual SDK close started once with original5s deadline required')
    hold=case['hold'];markers=hold['markers'];acks=hold['acks'];receipts=hold['ack_receipts']
    if any(len(v)!=3 for v in (markers,acks,receipts)):raise CaptureError('complete original hold handshake required')
    states=[[True,False,0,0,0,0,False,0],[False,True,1,0,0,0,False,0],[False,False,1,1,0,0,False,0]]
    for n,(marker,ack,receipt)in enumerate(zip(markers,acks,receipts,strict=True)):
        if(marker['hold_phase']!=['arm_ready','wait_held','release_ready'][n]or ack['stage']!=['armed','held','released'][n]
                or ack['request']!=marker or ack['state']!=dict(zip(PROPERTIES,states[n]))
                or any(type(ack['state'][k])is not type(v)for k,v in zip(PROPERTIES,states[n]))
                or receipt['stage']!=ack['stage']or receipt['wall_ns']<marker['wall_ns']):
            raise CaptureError('one explicit unhold with no automaticrelease/drop/error required')
    if not(lease['messages'][-1]['end_wall_ns']<=case['start_wall_ns']<=markers[0]['wall_ns']<receipts[0]['wall_ns']
            <=case['send']['start_wall_ns']<=markers[1]['wall_ns']<receipts[1]['wall_ns']<=trigger
            <=markers[2]['wall_ns']<receipts[2]['wall_ns']<=case['send']['end_wall_ns']<=case['end_wall_ns']<=lease['application']['end_wall_ns']):
        raise CaptureError('original update submission,held,close-start,unhold and completion order required')
    sent=sdk_receipt(case['send'],api,h,{'stage','pdu','ack'});replaced=sdk_receipt(case['replacement'],api,h,{'value'})
    pdu=b'\x10\x03'+h.to_bytes(2,'little')+b'\x20\0'+value
    if sent['stage']!=2 or sent['pdu']!=pdu.hex()or sent['ack']!='110301'or replaced['value']!=case['value']or case['before']['value']!=case['value']:
        raise CaptureError('actual original provider indication completion and value required')
    data=exchange(1,0,pdu,case);ack=exchange(0,1,b'\x11\x03\x01',case)
    if not(data['tx']['wall_ns']<=data['rx']['wall_ns']<=ack['tx']['wall_ns']<trigger
            <=markers[2]['wall_ns']<=ack['rx']['wall_ns']<=case['send']['end_wall_ns']):
        raise CaptureError('actual paired indication/ACK source before release and late ACK RX required')
    if expiry:
        clock=selection['clock'];upper=ack['tx']['wall_ns']-clock['wall_ns']+clock['after_ns']
        if upper>=lease['active']['expires_ns']:raise CaptureError('accepted indication/ACK must precede original expiry')
    return value,ack


def verify_expiry_observation(lease,reader):
    case=lease['inflight_release'];e=case['expiry'];a=lease['active']
    if any(k in case for k in ('release_started','release_request_wall_ns','release_request_monotonic_ns')):
        raise CaptureError('application close must not substitute for autonomous expiry')
    if (set(e)!={'original_expires_ns','original_expiry_upper_ns','threshold_ns','start_ns','start_wall_ns','end_ns','end_wall_ns','read_request_wall_ns','read_request_ns'}
            or any(type(v)is not int or v<=0 for v in e.values())
            or e['original_expires_ns']!=a['expires_ns']
            or e['original_expiry_upper_ns']!=a['returned_ns']+INITIAL_RENEWAL_LEASE_MS*1_000_000
            or e['threshold_ns']!=e['original_expiry_upper_ns']+50_000_000
            or not e['start_ns']<a['expires_ns']<=e['original_expiry_upper_ns']<e['threshold_ns']<=e['end_ns']<=e['read_request_ns']<=case['end_monotonic_ns']<a['expires_ns']+5_000_000_000
            or not e['threshold_ns']<=e['start_ns']+1_100_000_000
            or not e['start_wall_ns']<=e['end_wall_ns']<=case['hold']['markers'][2]['wall_ns']<=case['hold']['ack_receipts'][2]['wall_ns']<=case['send']['end_wall_ns']<=e['read_request_wall_ns']<=case['end_wall_ns']):
        raise CaptureError('original finite autonomous expiry and only post-unhold observation required')
    b=lease['expiry_observation']
    if (set(b)!={'stage','api','last','dropped','refused','state','flags','reason','discarded','packets'}
            or b['stage']!='ssap_subscription_batch'or b['api']!=reader or b['packets']!=[]
            or any(type(b[k])is not int for k in ('last','dropped','refused','state','flags','reason','discarded'))
            or (b['last'],b['dropped'],b['refused'],b['reason'],b['discarded'])!=(4,0,0,2,1)
            or (b['state'],b['flags'])not in ((2,0),(3,1))
            or (b['state']==2 and lease.get('release')!={'stage':'ssap_subscription_released','api':reader,'flags':1,'discarded':1})
            or (b['state']==3 and 'release'in lease)):
        raise CaptureError('actual EXPIRED tombstone,one discarded accepted packet and confirmed cleanup required')
    return e['start_wall_ns']


def lease_cases(lease):
    return lease['messages']+([lease['inflight_release']]if 'inflight_release'in lease else[])


def corroborate(row,matched):
    if not row.get('ssap_subscription_required',False):return [],{0:0,1:0}
    from ws73_application_role import verify_probe
    verify_probe(row)
    if (type(row.get('ssap_subscription_contract_version'))is not int or row['ssap_subscription_contract_version']!=1 or row.get('ssap_subscription_status')!=STATUS
            or row.get('security_requirement')!=2 or row.get('message_security_required')is not True
            or len(row.get('ssap_subscription',[]))!=2):raise CaptureError('completed protected continuous subscription phase required')
    if shared_required(row):
        from ws73_ssap_shared import corroborate as shared_corroborate
        return shared_corroborate(row,matched)
    renewal=renewal_required(row);pressure=pressure_required(row);owner_loss=owner_loss_required(row);inflight=inflight_required(row);expiry=inflight_case(row)=='expiry'
    owners=row['owners'];proof=[];credit={0:0,1:0};fresh=set();reads=[]
    for sender,item in enumerate(row['ssap_subscription']):
        s,t=sender,1-sender;peer,server=owners[s],owners[t];api='c'if (row['phase']+s)%2==0 else'python';reader='python'if api=='c'else'c';h=item['handle']
        if (item['sender']!=s or item['target']!=t or item.get('publisher_api')!=api or item['policy']!='allow'
                or item['args']!=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'allow',update_connection=server['object']['path'])
                or item['environment']!=application_environment()or type(item['exit'])is not int or item['exit']!=0 or item['stderr']):raise CaptureError('actual original service-only SDK provider required')
        role(item['credentials'],1005)
        matrix=lease_matrix(row,sender)
        if not 16<=item['start']<h<=item['end']<=65535 or len(item.get('leases',[]))!=len(matrix):raise CaptureError('actual property and explicit distinct lease matrix required')
        lines=item['stdout'].splitlines()
        if lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only']or lines[-1:]!=[f'SdkOwnedRemoved: api={api} start={item["start"]}']:raise CaptureError('complete original owner stream required')
        legs=[]
        def exchange(a,b,pdu,window):
            from ws73_ssap_value import pair_wire,physical_sends
            leg=pair_wire(row,matched,owners[a],owners[b],pdu,window);legs.append(leg);credit[a]+=physical_sends(leg['tx']);return leg
        discovery_wire(item,peer,exchange)
        tokens=set()
        for position,((mode,attempt),lease)in enumerate(zip(matrix,item['leases'],strict=True)):
            duration=lease_duration(row,sender,mode,attempt)
            killed=owner_loss and attempt==0
            pending=inflight and sender==0 and mode==2 and attempt==0
            if not pending and 'inflight_release'in lease:raise CaptureError('unrequested in-flight release evidence')
            app=lease['application'];role(app['credentials'],1004)
            prefix=['/bin/ws73-application-client-c']if reader=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
            if (type(lease['mode'])is not int or lease['mode']!=mode or app['api']!=reader or app['environment']!=application_environment()
                    or app['args']!=prefix+['subscription',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(h),str(mode),str(duration)]
                    or type(app['exit'])is not int or app['exit']!=(-9 if killed else 0)or app['stderr']or len(lease['messages'])!=(18 if pressure else COUNT)
                    or (owner_loss or inflight)and(type(lease.get('attempt'))is not int or lease['attempt']!=attempt)):
                raise CaptureError('actual continuous SDK reader process and finite workload required')
            if not killed and 'owner_loss'in lease:raise CaptureError('unrequested process death evidence')
            active=lease['active'];raw=[json.loads(v)for v in app['stdout'].splitlines()]
            expected=[active]
            if (set(active)!={'stage','api','token','epoch','expires_ns','started_ns','deadline_ns','returned_ns','client_closed'}
                    or active['stage']!='ssap_subscription_active'or active['api']!=reader or active['client_closed']is not True
                    or any(type(active[k])is not int or active[k]<=0 for k in ('token','epoch','expires_ns','started_ns','deadline_ns','returned_ns'))
                    or active['deadline_ns']-active['started_ns']!=5_000_000_000
                    or not active['started_ns']<=active['returned_ns']<active['deadline_ns']
                    or not active['started_ns']+duration*1_000_000<=active['expires_ns']<=active['deadline_ns']+duration*1_000_000):raise CaptureError('original actual acquisition/expiry/epoch required')
            if owner_loss or inflight:
                if active['token']in tokens:raise CaptureError('new replacement token required')
                tokens.add(active['token'])
                if attempt:
                    old=item['leases'][position-1]
                    closed=old['owner_loss']['end_wall_ns']if owner_loss else old['inflight_release']['end_wall_ns']
                    if(active['epoch']!=old['active']['epoch']or app['pid']==old['application']['pid']
                            or not closed<=old['end_wall_ns']<=app['start_wall_ns']):
                        raise CaptureError('same original epoch after old actor convergence and new reader process required')
            if renewal:renewed=verify_renewal(lease,reader)
            elif 'renewal'in lease or'old_expiry_barrier'in lease:raise CaptureError('unrequested renewal evidence')
            if pressure:
                drained=pressure_batch(lease,reader,h)
                if lease.get('drained')!=drained:raise CaptureError('actual full16 original ordered batch and one overflow counter required')
                expected.append(drained)
            elif 'drained'in lease:raise CaptureError('unrequested pressure batch')
            for number,case in enumerate(lease['messages']):
                sequence=(row['phase']<<24)|(s<<20)|(mode<<16)|((attempt<<12)if owner_loss or inflight else 0)|number;value=bytes.fromhex(case['value']);reply=bytes.fromhex(case['reply'])
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
                # Buffered application checks intentionally overlap earlier
                # sends. Identical ACK bytes belong to the original SDK send
                # interval,not the longer fill-to-application-write interval.
                if mode==2:exchange(s,t,b'\x11\x03'+bytes([0 if overflow else 1]),case['send']if pressure else case)
                if overflow:continue
                exchange(s,t,b'\x0d\x23'+h.to_bytes(2,'little')+b'\0'+reply,case)
                exchange(t,s,b'\x0e\x03'+h.to_bytes(2,'little')+b'\0'+reply,case)
            if pending:
                value,pending_ack=verify_inflight_release(row,item,lease,api,reader,exchange)
                if value in fresh:raise CaptureError('pending update payload must be distinct')
                fresh.add(value)
                expected.append(lease['expiry_observation']if expiry else lease['inflight_release']['release_started'])
            release={'stage':'ssap_subscription_released','api':reader,'flags':1,'discarded':1 if pending else 0}
            if killed:
                cleanup_read=verify_owner_loss(lease,peer,h);reads.extend(lease['owner_loss']['read_attempts'])
            elif not(pending and expiry and lease['expiry_observation']['state']==3):
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
                window=lease['owner_loss']if killed and req==disable else lease
                config_request=exchange(s,t,req,window);response=exchange(t,s,rsp,window)
            if pending:
                if not((lease['inflight_release']['expiry']['start_wall_ns']if expiry else lease['inflight_release']['release_request_wall_ns'])<=config_request['tx']['wall_ns']<pending_ack['rx']['wall_ns']
                        <=response['tx']['wall_ns']<=response['rx']['wall_ns']<=lease['end_wall_ns']):
                    raise CaptureError('actual disableTX while ACK in-flight and confirmed cleanup after late ACK required')
                if expiry:
                    clock=lease['inflight_release']['selection']['clock']
                    lower=config_request['tx']['wall_ns']-clock['wall_ns']+clock['before_ns']
                    if lower<active['expires_ns']:raise CaptureError('actual autonomous disableTX must not precede original expiry')
            if killed:
                request=exchange(s,t,b'\x08\x03'+h.to_bytes(2,'little')+b'\0',cleanup_read)
                exchange(t,s,b'\x09\x03'+bytes.fromhex(lease['messages'][-1]['reply']),cleanup_read)
                if not(max(response[k]['wall_ns']for k in ('tx','rx'))<=min(request[k]['wall_ns']for k in ('tx','rx'))<=cleanup_read['end_wall_ns']):
                    raise CaptureError('paired physical disable reply must precede same-actor read and replacement')
        decisions=[json.loads(v.removeprefix('SdkAuthorizationDecision: '))for v in lines if v.startswith('SdkAuthorizationDecision: ')]
        wanted=tuple(v for m,n in matrix for v in(bytes([m,0]).hex(),'0000'))
        if len(decisions)!=len(wanted):raise CaptureError('exact enable/disable approvals required')
        for d,value in zip(decisions,wanted,strict=True):
            authorization_context({k:v for k,v in d.items()if k not in {'allow','decision_ns','decision_wall_ns'}},api,level=2,data_type=2)
            if ((d['index'],d['generation'],d['lifetime'],d['handle'],d['property'])!=(server['owner']['index'],server['owner']['generation'],server['object']['lifetime'],server['object']['handle'],h)
                    or d['value']!=value or d['allow']is not True or d['decision_ns']>=d['deadline_ns']
                    or not item['start_wall_ns']<=d['decision_wall_ns']<=item['end_wall_ns']):raise CaptureError('original authenticated typed owner decision required')
        snapshots=[]
        for lease in item['leases']:
            cases=lease['messages']
            snapshots.extend((str(h),v)for v in ([c['value']for c in cases[:17]]+[c['reply']for c in cases[:16]]+[cases[-1]['value'],cases[-1]['reply']]if pressure else[c[k]for c in cases for k in ('value','reply')]))
            if 'inflight_release'in lease:snapshots.append((str(h),lease['inflight_release']['value']))
        import re
        if re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]+)$',item['stdout'],re.M)!=snapshots:raise CaptureError('actual original owner store snapshots required')
        for prefix,observations in [('SdkOwnedReplaced',[c['replacement']for l in item['leases']for c in lease_cases(l)]),
                ('SdkOwnedUpdate',[c['send']for l in item['leases']for c in lease_cases(l)if not(pressure and l['mode']==2 and c['number']==16)]),
                ('SdkOwnedUpdateObserved',[c['send']for l in item['leases']for c in l['messages']if pressure and l['mode']==2 and c['number']==16]),
                ('SdkOwnedConfiguration',[o for l in item['leases']for key in ('enabled','disabled')for o in l[key]])]:
            raw=[json.loads(v)for v in re.findall('^'+prefix+r': (.+)$',item['stdout'],re.M)]
            if raw!=[o['receipt']for o in observations]:raise CaptureError('actual provider SDK output differs from original receipts')
        result=dict(sender=s,target=t,publisher=api,peer=reader,leases=4 if owner_loss else 2,updates=36 if pressure else 12 if owner_loss else 6,application_replies=34 if pressure else 12 if owner_loss else 6,decisions=8 if owner_loss else 4,wire=legs)
        if renewal:result.update(renewal_contract_version=1,renewals=2,post_original_expiry_updates=4)
        if pressure:result.update(pressure_contract_version=1,notification_drops=1,indication_refusals=1,resumed=2)
        if owner_loss:result.update(owner_loss_contract_version=1,owner_losses=2,replacement_leases=2,cleanup_read_barriers=2)
        if inflight:
            result.update(leases=3 if sender==0 else 2,updates=10 if sender==0 else 6,application_replies=9 if sender==0 else 6,decisions=6 if sender==0 else 4,inflight_release_contract_version=1,replacement_leases=1 if sender==0 else 0,discarded_pending=1 if sender==0 else 0)
            if expiry:result.update(inflight_case='expiry',inflight_expiry_contract_version=1,inflight_expirations=1 if sender==0 else 0)
            else:result['inflight_releases']=1 if sender==0 else 0
        proof.append(result)
    if owner_loss and row.get('role_ssap_commands')!=reads:raise CaptureError('all actual actor read attempts must be retained without extras')
    return proof,credit


def valid_summary(proof):
    from ws73_ssap_value import valid_wire
    try:
        if proof['status']!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'or len(proof['proofs'])!=2:return False
        for phase,row in enumerate(proof['proofs']):
            if row['phase']!=phase or len(row['ssap_subscription'])!=2:return False
            for sender,value in enumerate(row['ssap_subscription']):
                api='c'if (phase+sender)%2==0 else'python'
                if value.get('shared_contract_version')is not None:
                    from ws73_ssap_shared import part_valid
                    if not part_valid(value,phase,sender):return False
                    continue
                pressure=value.get('pressure_contract_version')is not None
                if pressure and(type(value['pressure_contract_version'])is not int or value['pressure_contract_version']!=1):return False
                loss=value.get('owner_loss_contract_version')is not None
                inflight=value.get('inflight_release_contract_version')is not None
                if loss and(type(value['owner_loss_contract_version'])is not int or value['owner_loss_contract_version']!=1
                        or inflight or pressure or value.get('renewal_contract_version')is not None):return False
                if inflight and(type(value['inflight_release_contract_version'])is not int or value['inflight_release_contract_version']!=1
                        or pressure or value.get('renewal_contract_version')is not None):return False
                extra=inflight and sender==0
                for k,v in dict(sender=sender,target=1-sender,leases=4 if loss else 3 if extra else 2,updates=36 if pressure else 12 if loss else 10 if extra else 6,application_replies=34 if pressure else 12 if loss else 9 if extra else 6,decisions=8 if loss else 6 if extra else 4).items():
                    if type(value[k])is not int or value[k]!=v:return False
                if value['publisher']!=api or value['peer']!=('python'if api=='c'else'c')or len(value['wire'])!=(144 if pressure else 80 if loss else 63 if extra else 43):return False
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


def valid_owner_loss_summary(proof):
    return(valid_summary(proof)and all(type(v.get(k))is int and v[k]==n
        for row in proof['proofs']for v in row['ssap_subscription']
        for k,n in dict(owner_loss_contract_version=1,owner_losses=2,replacement_leases=2,cleanup_read_barriers=2).items()))


def valid_inflight_summary(proof,*,case='release'):
    return(case in ('release','expiry')and valid_summary(proof)and all(
        v.get('inflight_case','release')==case
        and (type(v.get('inflight_expiry_contract_version'))is int and v['inflight_expiry_contract_version']==1 if case=='expiry'else v.get('inflight_expiry_contract_version')is None)
        and ('inflight_releases'not in v if case=='expiry'else 'inflight_expirations'not in v)
        and all(type(v.get(k))is int and v[k]==n for k,n in dict(inflight_release_contract_version=1,
            **{'inflight_expirations'if case=='expiry'else'inflight_releases':1 if sender==0 else 0},
            replacement_leases=1 if sender==0 else 0,discarded_pending=1 if sender==0 else 0).items())
        for row in proof['proofs']for sender,v in enumerate(row['ssap_subscription'])))


def valid_shared_summary(proof,*,case='release',expected_round_trips=8):
    return(type(expected_round_trips)is int and expected_round_trips in(8,40)and case in ('release','expiry','owner-exit','pressure')and valid_summary(proof)and proof.get('round_trips')==expected_round_trips and all(type(v.get('shared_contract_version'))is int and v['shared_contract_version']==1 and v.get('shared_case','release')==case for row in proof['proofs']for v in row['ssap_subscription']))
