# SPDX-License-Identifier: GPL-2.0-only
"""Two ordinary applications; independent two-end USB/CMTC/NOCP proof."""
from contextlib import ExitStack
from pathlib import Path
import re
import subprocess
import time
from ws73_capture import CaptureError, reassemble_acb


def test_program(run):
    from ws73_north_star import file_record
    program=Path(run.args.slctl).with_name('slktest').resolve(strict=True)
    if program.name!='slktest':raise CaptureError('actual sibling slktest required')
    record=file_record(program)
    previous=run.data.get('slktest')
    if previous is not None and previous!=record:raise CaptureError('slktest changed during gate')
    run.data['slktest']=record
    return record


def check_arguments(binary, entry, peer, rounds, message_bytes, exercise='regular', route=None, hold=False, start_barrier=False, security=0, message_security=False):
    args=[str(binary),'--adapter',entry['owner']['path'],'channel','peer' if peer else 'ping',
          entry['object']['path'],'--check','--count',str(rounds),'--bytes',str(message_bytes)]
    if message_security:
        if route is not None or exercise not in ('regular','boundaries'):raise CaptureError('receipt context requires fixed regular/boundaries exercise')
        args+=['--message-security']
    if security:
        if security not in [1,2] or route is not None:raise CaptureError('explicit supported fixed security requirement needed')
        args+=['--security',str(security)]
    if exercise!='regular':args+=['--exercise',exercise]
    if route is not None:args+=['--source-port',str(route[0]),'--destination-port',str(route[1]),'--aid',str(route[2])]
    if hold:args+=['--hold']
    if start_barrier:args+=['--start-barrier']
    return args


def validate_application_binary(binary, root=None, guest_files=None):
    import hashlib
    if not isinstance(binary,dict) or not re.fullmatch(r'(?:/usr/libexec/opensparklink/native-lab/[0-9a-f]{12}|/bin)/slktest',binary.get('path','')) or not re.fullmatch(r'[0-9a-f]{64}',binary.get('sha256','')):
        raise CaptureError('exact versioned slktest artifact identity required')
    if root is not None:
        expected=Path(root).resolve(strict=True)/binary['path'].lstrip('/')
        matches=[v for v in guest_files if Path(v['path'])==expected]
        if len(matches)!=1 or matches[0]['sha256']!=binary['sha256'] or hashlib.sha256(expected.read_bytes()).hexdigest()!=binary['sha256']:
            raise CaptureError('slktest differs from sealed VM artifact')


def validate_application_tools(run, root=None, guest_files=None):
    used=[]
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='application_tool':used.append(item)
                if key=='channel_socket' and isinstance(item,list):
                    if any('application_tool' not in row for row in item):raise CaptureError('current channel gate requires slktest identity')
                visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(run)
    if not used:raise CaptureError('actual slktest application evidence required')
    for item in used:validate_application_binary(item,root,guest_files)
    if any(item!=used[0] for item in used):raise CaptureError('mixed application test binaries in one VM run')
    return used[0]


def credentials(pid):
    fields = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    value = dict(uids=list(map(int, fields['Uid'].split())),
                 capabilities={k: fields[k].strip() for k in ['CapEff', 'CapPrm', 'CapAmb', 'CapInh']})
    if value['uids'] != [1000]*4 or any(int(v,16) for v in value['capabilities'].values()):
        raise CaptureError('each socket application must be uid1000 without capabilities')
    return value


def verify_retired_uapi_receipt(receipt):
    expected = ('RETIRED_UAPI_ENOTTY_PASS: uid=1000 cases=103 unchanged=103 '
                'checks=309 invalid_user_address=1 mixed_stats=ENOTTY')
    if (type(receipt.get('exit')) is not int or receipt['exit'] != 0
            or receipt.get('stdout', '').strip() != expected
            or receipt.get('stderr', '').strip()):
        raise CaptureError('actual retired raw UAPI rejection failed')


def channel_security_for_agent(mode):
    """Required test admission level, not evidence of mechanism installation.

    CLI/probe are two callers of the same method. Kernel binds, message receipts
    and independent two-end relay/install/application proofs still must pass.
    """
    from ws73_security_agent import MODES
    if mode is not None and mode not in MODES:
        raise CaptureError('unknown Agent mode cannot choose a weaker channel test')
    return {'approve':1,'cli-approve':1,'numeric-approve':2}.get(mode,0)


def wait_application(process, deadline, progress=None):
    """Observe an owned child without refreshing its original absolute budget.

    A progress callback coordinates a test supervisor, never the child's socket
    RX/TX or protocol deadlines. The actual applications keep running.
    """
    if progress is None:
        process.wait(timeout=max(.001,deadline-time.monotonic()))
        return
    while process.poll() is None:
        progress()
        remaining=deadline-time.monotonic()
        if remaining<=0:raise subprocess.TimeoutExpired(process.args,0)
        try:process.wait(timeout=min(.02,remaining))
        except subprocess.TimeoutExpired:continue
    progress()
    if time.monotonic()>deadline:raise subprocess.TimeoutExpired(process.args,0)


def run_applications(run,row,processes,files,original_deadline=None):
    """The sole existing ordinary slktest pair, once per physical lifetime."""
    if row['applications']:raise CaptureError('applications must not rebind after final close')
    # Both binds must occur during the same live connection. Never synthesize RX.
    for role, entry in [('peer', row['owners'][1]), ('initiator', row['owners'][0])]:
        exercise='boundaries' if row['boundary_check'] else 'prefix-close' if row['close_prefix'] and role=='initiator' else 'burst' if row['burst'] and role=='initiator' else 'regular'
        args=check_arguments(row['application_tool']['path'],entry,role=='peer',row['rounds'],row['message_bytes'],exercise,security=row['security_requirement'],message_security=row['message_security_required'])
        app=dict(role=role,args=args,start_wall_ns=time.time_ns())
        row['applications'].append(app);run.save()
        stdout=run.output/f'channel-{row["phase"]}-{role}.stdout'
        stderr=run.output/f'channel-{row["phase"]}-{role}.stderr'
        app['output_files']=[str(stdout),str(stderr)]
        proc=subprocess.Popen(args,stdout=files.enter_context(stdout.open('xb')),stderr=files.enter_context(stderr.open('xb')))
        processes.append((proc,app));app['pid']=proc.pid
        app['credentials']=credentials(proc.pid);run.save()
    deadline=time.monotonic()+row['rounds']*10+5
    if original_deadline is not None:
        deadline=min(deadline,original_deadline)
    waiting=sorted(processes,key=lambda item:item[1]['role']!='initiator') if row['close_prefix'] else processes
    observer=getattr(run,'channel_application_progress',None)
    for proc,app in waiting:
        wait_application(proc,deadline,(lambda:observer(row)) if observer is not None else None)
        app['stdout'],app['stderr']=[Path(p).read_text() for p in app['output_files']]
        app.update(exit=proc.returncode,end_wall_ns=time.time_ns());run.save()
        if proc.returncode:raise CaptureError('actual socket application failed: '+app['stderr'])
    for app in row['applications']:
        if app['stdout'].count('NativeChannelDup: original_closed=1 duplicate_live=1') != 1 or app['stdout'].count('NativeChannelLastClose: same_lifetime_reopen=NotSupported') != 1:
            raise CaptureError('actual duplicate/last-close/reopen rejection receipts required')
    row['session_binding_lifecycle'] = 'DUP_ALIVE_LAST_CLOSE_REBIND_UNSUPPORTED'
    if row['close_prefix']:
        row['end_wall_ns']=time.time_ns()
        prefix_application_frames(row)
        row['after_close_ssap_start_wall_ns']=time.time_ns()
        from ws73_ssap_value import execute as ssap_value_execute
        ssap_value_execute(run,row) # actual other Channel traffic after fd release
    else:application_frames(row)


def passive_controller_checks(run,row,expected_connections,stage):
    """Retain the same passive probes at an explicit physical-link state."""
    if type(expected_connections) is not int or expected_connections not in (0,1):
        raise CaptureError('explicit connected/down passive observation required')
    collections=['controller_event_positions','retired_uapi_refusals','controller_link_summaries','controller_event_copy','genl_registry']
    before={key:len(run.data.get(key,[]))for key in collections}
    stage_record=dict(stage=stage,expected_connections=expected_connections,start_wall_ns=time.time_ns())
    row.setdefault('passive_controller_checks',[]).append(stage_record);run.save()
    # Passive VFS checks use current full records; old read/stats never
    # re-enter the producer. Older packages have no such test artifact and
    # retain their original qualification, not a new copy-gate receipt.
    probe = Path(run.args.slctl).parent/'controller-event-copy-probe'
    if not probe.is_file() and Path('/scratch-root-uuid').is_file():
        probe = Path('/bin/controller-event-copy-probe')
    if probe.is_file():
        for entry in row['owners']:
            owner = entry['owner']
            position = run.command([str(run.args.slctl),'--adapter',owner['path'],'events'],
                                   10, collection='controller_event_positions')
            expected = rf'^ControllerEventPosition: index={owner["index"]} generation={owner["generation"]} sequence=(\d+)$'
            if position['exit'] or len(re.findall(expected,position['stdout'],re.M)) != 1:
                raise CaptureError('actual canonical event-position interface failed')
            retired_probe = Path(run.args.slctl).parent/'retired-uapi-probe'
            if not retired_probe.is_file() and Path('/scratch-root-uuid').is_file():
                retired_probe = Path('/bin/retired-uapi-probe')
            if retired_probe.is_file():
                refused = run.command([str(retired_probe),str(owner['index'])],10,collection='retired_uapi_refusals')
                verify_retired_uapi_receipt(refused)
            summary = run.command([str(run.args.slctl),'--adapter',owner['path'],'stats'],
                                  10,collection='controller_link_summaries')
            pattern = rf'^ControllerLinkSummary: index={owner["index"]} generation={owner["generation"]} revision=([1-9]\d*) event_sequence=([1-9]\d*) connections={expected_connections}$'
            if summary['exit'] or len(re.findall(pattern,summary['stdout'],re.M)) != 1:
                raise CaptureError('actual validated physical link summary failed')
            receipt = run.command([str(probe),str(owner['index']),str(owner['generation'])],
                                  10, collection='controller_event_copy')
            expected = f'CONTROLLER_EVENT_COPY_PASS: uid=1000 index={owner["index"]} generation={owner["generation"]} partial=4 retry=4 peer_replay=4 readiness_preserved=4 removed_read=1 removed_stats=2'
            if receipt['exit'] or receipt['stdout'].strip() != expected:
                raise CaptureError('actual ControllerEvent copy/alias/replay gate failed')
    registry_probe = Path(run.args.slctl).parent/'genl-registry-probe'
    if not registry_probe.is_file() and Path('/scratch-root-uuid').is_file():
        registry_probe = Path('/bin/genl-registry-probe')
    if registry_probe.is_file():
        receipt = run.command([str(registry_probe)],10,collection='genl_registry')
        expected = r'^GENL_REGISTRY_PASS: uid=1000 count=\d+ version=2 retired=31 extra_attr=1 no_multicast=1 count_preserved=1$'
        if receipt['exit'] or not re.fullmatch(expected,receipt['stdout'].strip()):
            raise CaptureError('actual registry-only netlink/retired mutation gate failed')
    stage_record.update(end_wall_ns=time.time_ns(),collections={key:[before[key],len(run.data.get(key,[]))]for key in collections})
    run.save()


def validate_passive_controller_stages(run,row,phase):
    """The new Disconnect contract retains every probe at both link states."""
    stages=row.get('passive_controller_checks',[])
    if any(type(s.get('expected_connections'))is not int for s in stages)or [(s.get('stage'),s.get('expected_connections'))for s in stages]!=[
            ('before-applications',1),('after-applications-and-down',0)]:
        raise CaptureError('both connected and after-Down passive checks required')
    apps=row['applications'];begin=min(a['start_wall_ns']for a in apps);end=max(a['end_wall_ns']for a in apps)
    command=run['commands'][phase['disconnect_command']]
    if not (row['start_wall_ns']<=stages[0]['start_wall_ns']<=stages[0]['end_wall_ns']<=begin
            and end<=command['start_wall_ns']<=phase['down_property_observation']['end_wall_ns']
            <=phase['disconnect_completed_wall_ns']<=stages[1]['start_wall_ns']<=stages[1]['end_wall_ns']<=row['end_wall_ns']):
        raise CaptureError('passive checks must bracket apps and actual observed Down')
    keys=['controller_event_positions','retired_uapi_refusals','controller_link_summaries','controller_event_copy','genl_registry']
    for stage in stages:
        ranges=stage.get('collections',{})
        if set(ranges)!=set(keys):raise CaptureError('all original passive probe groups required')
        for key in keys:
            span=ranges[key];count=1 if key=='genl_registry'else 2;records=run.get(key,[])
            if (not isinstance(span,list)or len(span)!=2 or any(type(n)is not int for n in span)
                    or not 0<=span[0]<=span[1]<=len(records)or span[1]-span[0]!=count):
                raise CaptureError('exact complete passive probe slice required')
            for i,receipt in enumerate(records[span[0]:span[1]]):
                if (receipt['exit']or not stage['start_wall_ns']<=receipt['start_wall_ns']<=receipt['end_wall_ns']<=stage['end_wall_ns']):
                    raise CaptureError('actual successful passive receipt required')
                if key=='genl_registry':
                    if (len(receipt['args'])!=1 or Path(receipt['args'][0]).name!='genl-registry-probe'
                            or not re.fullmatch(r'GENL_REGISTRY_PASS: uid=1000 count=4 version=2 retired=31 extra_attr=1 no_multicast=1 count_preserved=1',receipt['stdout'].strip())):
                        raise CaptureError('actual four-controller registry preservation required')
                    continue
                owner=row['owners'][i]['owner'];cli=run['slctl']['path'];args=receipt['args']
                if key=='controller_event_positions':
                    expected=[cli,'--adapter',owner['path'],'events']
                    pattern=rf'^ControllerEventPosition: index={owner["index"]} generation={owner["generation"]} sequence=(\d+)$'
                elif key=='controller_link_summaries':
                    expected=[cli,'--adapter',owner['path'],'stats']
                    pattern=rf'^ControllerLinkSummary: index={owner["index"]} generation={owner["generation"]} revision=([1-9]\d*) event_sequence=([1-9]\d*) connections={stage["expected_connections"]}$'
                elif key=='retired_uapi_refusals':
                    if len(args)!=2 or Path(args[0]).name!='retired-uapi-probe'or args[1]!=str(owner['index']):raise CaptureError('exact retired-UAPI probe affinity required')
                    verify_retired_uapi_receipt(receipt);continue
                else:
                    if (len(args)!=3 or Path(args[0]).name!='controller-event-copy-probe'
                            or args[1:]!=[str(owner['index']),str(owner['generation'])]
                            or receipt['stdout'].strip()!=f'CONTROLLER_EVENT_COPY_PASS: uid=1000 index={owner["index"]} generation={owner["generation"]} partial=4 retry=4 peer_replay=4 readiness_preserved=4 removed_read=1 removed_stats=2'):
                        raise CaptureError('actual original ControllerEvent copy probes required')
                    continue
                if args!=expected or len(re.findall(pattern,receipt['stdout'],re.M))!=1:raise CaptureError('passive metadata receipt identity/state mismatch')


def execute(run, phase, after_application=None):
    if after_application is not None and not callable(after_application):
        raise CaptureError('explicit application completion callback required')
    row = dict(dtap_limits_version=1,cmtc_local_capability=dict(mtu=2042,mps=2047),cmtc_identifier=0,phase=len(run.data['connection_control']['phases'])-1, owners=phase['typed_objects'],
               rounds=getattr(run.args,'channel_socket_rounds',4), message_bytes=getattr(run.args,'channel_socket_bytes',61),
               boundary_check=getattr(run.args,'channel_socket_boundaries',False), close_prefix=getattr(run.args,'channel_socket_close_prefix',False), burst=getattr(run.args,'channel_socket_burst',False), tx_status_required=True, channel_info_required=True, ssap_exchange_required=True, ssap_exchange_contract=2, session_start_wall_ns=phase['start_wall_ns'], ssap_receipts=[], status='RUNNING', start_wall_ns=time.time_ns(), applications=[])
    row['message_security_required']=not (row['close_prefix'] or row['burst'])
    row['tx_constraint_required']=row['message_security_required']
    row['application_tool']=test_program(run)
    if after_application is not None:
        if row['close_prefix'] or row['burst'] or row['boundary_check']:
            raise CaptureError('early Disconnect requires dedicated regular channel exercise')
        row['post_application_disconnect']=True
    row['security_requirement']=channel_security_for_agent(getattr(run.args,'security_agent',None))
    if run.data.get('security_agent') and run.data['security_agent'][-1].get('ssap_security_requirement'):
        row['ssap_security_requirement']=run.data['security_agent'][-1]['ssap_security_requirement']
    run.data.setdefault('channel_socket', []).append(row); run.save()
    processes=[];files=ExitStack()
    try:
        for entry in row['owners']:
            receipt=run.command([str(run.args.slctl),'--adapter',entry['owner']['path'],'ssap-info',entry['object']['path']],10,collection='ssap_exchange')
            if receipt['exit']: raise CaptureError('actual SMTC ExchangeInfo failed')
            row['ssap_receipts'].append(receipt);run.save()
        from ws73_ssap_value import execute as ssap_value_execute
        if not row['close_prefix']:ssap_value_execute(run,row)
        if row['message_security_required']:
            from ws73_ssap_access import execute as access_execute
            access_execute(run,row)
        if getattr(run.args,'ssap_owned_verify',False):
            from ws73_ssap_owned import execute as owned_execute
            owned_execute(run,row)
        if getattr(run.args,'ssap_read_provider_verify',False):
            from ws73_ssap_read_provider import execute as provider_execute
            provider_execute(run,row)
        if getattr(run.args,'ssap_owned_update_verify',False):
            from ws73_ssap_owned_update import execute as update_execute
            update_execute(run,row)
        if getattr(run.args,'ssap_sender_deadline_verify',False):
            from ws73_ssap_sender_deadline import execute as sender_execute
            sender_execute(run,row)
        if getattr(run.args,'ssap_subscription_verify',False):
            from ws73_ssap_subscription import request as subscription_request
            subscription_request(run,row)
        if getattr(run.args,'ssap_update_delivery_verify',False):
            from ws73_ssap_update_delivery import execute as delivery_execute
            delivery_execute(run,row)
        if getattr(run.args,'ssap_owner_lifecycle_verify',False):
            from ws73_ssap_owner_lifecycle import execute as owner_lifecycle_execute
            owner_lifecycle_execute(run,row)
        if getattr(run.args,'ssap_requester_lifecycle_verify',False):
            from ws73_ssap_requester_lifecycle import execute as requester_execute
            requester_execute(run,row,lambda deadline:run_applications(run,row,processes,files,deadline))
        if getattr(run.args,'ssap_update_lifecycle_verify',False):
            from ws73_ssap_receive_lifecycle import execute as receive_execute
            receive_execute(run,row,lambda deadline:run_applications(run,row,processes,files,deadline))
        if getattr(run.args,'ssap_write_command_verify',False):
            from ws73_ssap_command import execute as command_execute
            command_execute(run,row)
        if getattr(run.args,'ssap_write_command_policy_verify',False):
            from ws73_ssap_command_policy import execute as command_policy_execute
            command_policy_execute(run,row)
        if getattr(run.args,'ssap_write_command_deadline_verify',False):
            from ws73_ssap_command_deadline import execute as command_deadline_execute
            command_deadline_execute(run,row,lambda deadline:run_applications(run,row,processes,files,deadline))
        if after_application is not None:
            passive_controller_checks(run,row,1,'before-applications')
        if hasattr(run, 'channel_barrier'):
            run.channel_barrier(row)
        if not (getattr(run.args,'ssap_requester_lifecycle_verify',False) or getattr(run.args,'ssap_update_lifecycle_verify',False) or getattr(run.args,'ssap_write_command_deadline_verify',False)):
            run_applications(run,row,processes,files)
        if after_application is not None:
            after_application()
        passive_controller_checks(run,row,0 if after_application is not None else 1,
                                  'after-applications-and-down' if after_application is not None else 'after-applications')
        row['status']='ORDINARY_CHANNEL_SOCKET_EVIDENCE_PENDING'
    except BaseException as error:
        import traceback
        row.update(status='FAIL',error=str(error),error_type=type(error).__name__,
                   error_traceback=traceback.format_exc());raise
    finally:
        for proc,app in processes:
            if proc.poll() is None:proc.kill()
            if 'exit' not in app:
                proc.wait()
                app['stdout'],app['stderr']=[Path(p).read_text() for p in app['output_files']];app.update(exit=proc.returncode,end_wall_ns=time.time_ns())
        files.close()
        row['end_wall_ns']=time.time_ns();run.save()


def rejected_frames(row):
    result=[]
    for app in row['applications']:
        values=re.findall(r'^NativeChannelRejected: length=(\d+) errno=(\d+) bytes=([0-9a-f]+)$',app['stdout'],re.M)
        if row.get('boundary_check',False):
            receipts = channel_info_receipts(row)
            mtu = next((receipt['fields'][7] for receipt in receipts if receipt['role']==app['role']),249)
            if [int(v[0]) for v in values]!=[mtu+1,mtu+4,mtu+5,mtu+6] or len(values)!=app['stdout'].count('NativeChannelRejected:'):
                raise CaptureError('all original length boundary rejection receipts required')
            for length,error,raw in values:
                data=bytes.fromhex(raw)
                if int(error)!=90 or len(data)!=int(length) or data[:8]!=b'SLKBOUND':raise CaptureError('exact x86_64 EMSGSIZE and original rejected bytes required')
                result.append(data)
        elif values or 'NativeChannelRejected:' in app['stdout']:
            raise CaptureError('boundary receipts without explicit requested boundary check')
    if len({v.hex() for v in result})!=len(result):raise CaptureError('fresh rejected boundary payloads required')
    return result


def dtap_limits(row):
    if 'dtap_limits_version' not in row:
        return None  # Preserve historical identity; never add MPS conformance.
    cap = row.get('cmtc_local_capability')
    if type(row['dtap_limits_version']) is not int or row['dtap_limits_version'] != 1 or not isinstance(cap,dict) or set(cap) != {'mtu','mps'}:
        raise CaptureError('versioned independent MTU/MPS contract required')
    if any(type(v) is not int for v in cap.values()) or cap != dict(mtu=2042,mps=2047) or not row.get('channel_info_required'):
        raise CaptureError('exact current Native capability advertisement and channel receipts required')
    return cap


def channel_info_receipts(row):
    if not row.get('channel_info_required', False):
        return []  # Historical records never gain this qualification.
    limits = dtap_limits(row)
    owners = row['owners']; result = []
    for app in row['applications']:
        entry = owners[0 if app['role'] == 'initiator' else 1]
        expected = (entry['owner']['index'], entry['owner']['generation'],
                    entry['object']['lifetime'], entry['object']['handle'], 31, 31, 241)
        values = re.findall(r'^NativeChannelInfo: index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) local=(\d+) remote=(\d+) pi=(\d+) mtu=(\d+) mps=(\d+) mode=(\d+) directions=(\d+)$', app['stdout'], re.M)
        copies = re.findall(r'^NativeChannelInfoCopy: partial=(\d+) retry=1 unchanged=1$',app['stdout'],re.M)
        if len(values) != 1 or len(copies) != 1 or not 1 <= int(copies[0]) <= 16:
            raise CaptureError('original channel capability and guarded copy receipts required')
        fields = tuple(map(int, values[0]))
        if fields[:7] != expected or fields[-2:] != (0, 3) or min(fields[7:9]) < row.get('message_bytes',61):
            raise CaptureError('channel capabilities disagree with original owner/lifetime/mode/budget')
        if limits and (fields[7] > limits['mtu'] or fields[8] > limits['mps'] or fields[7]+5 > fields[8]):
            raise CaptureError('CUTC SDU budget plus complete header exceeds independent PDU MPS')
        result.append(dict(role=app['role'], fields=fields, partial_copy_bytes=int(copies[0])))
    return result


def message_security_receipts(row):
    if not row.get('message_security_required',False):return [],[]
    if row.get('close_prefix') or row.get('burst') or 'ports' in row:raise CaptureError('unsupported receipt exercise')
    receipts=[];rejected=[]
    fields=['sequence','index','generation','lifetime','handle','local','remote','pi','security','epoch','flags']
    pattern=r'^NativeMessageSecurity: '+r' '.join(name+r'=(\d+)' for name in fields)+r'$'
    for app in row['applications']:
        owner=row['owners'][app['role']=='peer'];o=owner['owner'];c=owner['object']
        values=re.findall(pattern,app['stdout'],re.M)
        if len(values)!=row['rounds'] or len(values)!=app['stdout'].count('NativeMessageSecurity:'):
            raise CaptureError('each actual message needs one original complete security receipt')
        samples=[dict(zip(fields,map(int,v))) for v in values]
        for n,m in enumerate(samples):
            if (m['sequence'],m['index'],m['generation'],m['lifetime'],m['handle'],m['local'],m['remote'],m['pi'])!=(n,o['index'],o['generation'],c['lifetime'],c['handle'],31,31,241):
                raise CaptureError('receipt scope differs from original authorized fd')
            if m['flags']!=3 or not m['epoch'] or not row.get('security_requirement',0)<=m['security']<=2:
                raise CaptureError('receipt lacks known/current required mechanism')
        refusal=re.findall(r'^NativeControlRejected: errno=(\d+) bytes=([0-9a-f]+)$',app['stdout'],re.M)
        if len(refusal)!=1 or app['stdout'].count('NativeControlRejected:')!=1 or int(refusal[0][0])!=95:
            raise CaptureError('unsupported ancillary must refuse before admission')
        raw=bytes.fromhex(refusal[0][1])
        if len(raw)!=61 or raw[:8]!=b'SLKCMREJ':raise CaptureError('original random refused control payload required')
        rejected.append(raw);receipts.extend(dict(role=app['role'],**m) for m in samples)
    return receipts,rejected


def send_constraint_receipts(row):
    if not row.get('tx_constraint_required',False):return [],[]
    contexts,_=message_security_receipts(row)
    if not contexts:raise CaptureError('TX constraints require actual receipt evidence')
    receipts=[];rejected=[]
    for app in row['applications']:
        values=re.findall(r'^NativeConstrainedReply: sequence=(\d+) epoch=(\d+) minimum=(\d+) deadline_ns=(\d+)$',app['stdout'],re.M)
        invalid=re.findall(r'^NativeConstraintRejected: sequence=(\d+) kind=(epoch|lifetime|deadline) errno=(\d+) bytes=([0-9a-f]+)$',app['stdout'],re.M)
        if len(values)!=app['stdout'].count('NativeConstrainedReply:') or len(invalid)!=app['stdout'].count('NativeConstraintRejected:'):
            raise CaptureError('malformed original constraint receipts')
        if app['role']=='initiator':
            if values or invalid:raise CaptureError('this gate constrains only actual responder messages')
            continue
        if len(values)!=row['rounds'] or len(invalid)!=3*row['rounds']:
            raise CaptureError('each response needs one constrained send and three real refusals')
        for n,value in enumerate(values):
            seq,epoch,minimum,deadline=map(int,value)
            m=next(c for c in contexts if c['role']=='peer' and c['sequence']==n)
            if (seq,epoch,minimum)!=(n,m['epoch'],m['security']) or not deadline:
                raise CaptureError('response constraint differs from original receipt')
            receipts.append(dict(sequence=seq,epoch=epoch,minimum=minimum,deadline_monotonic_ns=deadline))
        expected=[(n,k) for n in range(row['rounds']) for k in ['epoch','lifetime','deadline']]
        if [(int(n),k) for n,k,_,_ in invalid]!=expected:raise CaptureError('original ordered rejection coverage required')
        for n,kind,error,raw in invalid:
            data=bytes.fromhex(raw)
            if int(error)!=(110 if kind=='deadline' else 13) or len(data)!=61 or data[:8]!=b'SLKINTRE':
                raise CaptureError('invalid intent must refuse with original errno/payload')
            rejected.append(data)
    if len(set(rejected))!=len(rejected):raise CaptureError('random rejected intents must be distinct')
    return receipts,rejected


def validate_application_arguments(row):
    # Historical receipts remain readable with their original commands. Current
    # execution always records a slktest artifact and must match the new argv.
    if 'application_tool' not in row:return
    validate_application_binary(row['application_tool'])
    for app in row['applications']:
        if app['role'] not in ('peer','initiator'):raise CaptureError('invalid application role')
        peer=app['role']=='peer'
        entry=row['owners'][1 if peer else 0]
        exercise='boundaries' if row.get('boundary_check') else 'prefix-close' if row.get('close_prefix') and not peer else 'burst' if row.get('burst') and not peer else 'regular'
        route=None
        if 'ports' in row:
            ports=row['ports'][::-1] if peer else row['ports']
            route=(*ports,row['aid'])
        expected=check_arguments(row['application_tool']['path'],entry,peer,row['rounds'],row.get('message_bytes',61),exercise,route,route is not None,row.get('start_barrier',False),row.get('security_requirement',0),row.get('message_security_required',False))
        if app.get('args')!=expected:raise CaptureError('actual slktest channel arguments/identity mismatch')


def application_frames(row):
    validate_application_arguments(row)
    rounds=row['rounds'];message_bytes=row.get('message_bytes',61)
    if type(message_bytes) is not int or not 29<=message_bytes<=2042:raise CaptureError('supported basic channel message size required')
    if type(rounds) is not int or not 1<=rounds<=20:raise CaptureError('finite original round count required')
    apps={a['role']:a for a in row['applications']}
    if set(apps)!={'peer','initiator'} or len(row['applications'])!=2:
        raise CaptureError('two original application processes and bounded rounds required')
    for role,a in apps.items():
        if a['exit'] or a['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in a['credentials']['capabilities'].values()):
            raise CaptureError('successful ordinary applications required')
        if re.findall(r'^NativeChannelOpened: role=(\w+) rounds=(\d+)$',a['stdout'],re.M)!=[(role,str(rounds))]:
            raise CaptureError('one original socket opening per application required')
        declared=re.findall(r'^NativeChannelMessageSize: bytes=(\d+)$',a['stdout'],re.M)
        if declared and declared!=[str(message_bytes)] or (message_bytes!=61 and not declared):raise CaptureError('original application message size must match request')
    rejected_frames(row)
    channel_info_receipts(row)
    burst_pressure_receipts(row)
    tx_status_receipts(row)
    def rows(role,marker,elapsed=False):
        pattern=rf'^{marker}: sequence=(\d+) '+(r'elapsed_ms=(\d+) ' if elapsed else '')+r'bytes=([0-9a-f]+)$'
        values=re.findall(pattern,apps[role]['stdout'],re.M)
        if len(values)!=rounds or apps[role]['stdout'].count(marker+':')!=rounds:raise CaptureError('all original application receipts required')
        if [int(v[0]) for v in values]!=list(range(rounds)):raise CaptureError('ordered unique sequence required')
        if elapsed and any(int(v[1])>=10000 for v in values):raise CaptureError('ten second round trip deadline')
        return [bytes.fromhex(v[-1]) for v in values]
    sent=rows('initiator','NativeChannelSent');received=rows('peer','NativeChannelReceived')
    reply=rows('peer','NativeChannelReply');returned=rows('initiator','NativeChannelRoundTrip',True)
    nonces=set();wire_sequences=set()
    for i,data in enumerate(sent):
        if len(data)!=message_bytes or data[:8]!=b'SLKSOCK1' or data[28]!=0:
            raise CaptureError('exact random application protocol required')
        if data[8:24] in nonces:raise CaptureError('fresh nonce per round required')
        nonces.add(data[8:24])
        wire_sequence=int.from_bytes(data[24:28],'little')
        if wire_sequence in wire_sequences:raise CaptureError('fresh random wire sequence required')
        wire_sequences.add(wire_sequence)
        if any(data[29+j] != data[8+j%16]^((wire_sequence+j)&255) for j in range(message_bytes-29)):raise CaptureError('application payload mismatch')
        expected=bytearray(data);expected[28]=1
        if received[i]!=data or reply[i]!=expected or returned[i]!=expected:
            raise CaptureError('actual peer validation and exact reply required')
    return sent,reply


def controller_budget(entry):
    buffers=entry['owner'].get('buffers')
    if (not isinstance(buffers,(list,tuple)) or len(buffers)!=4
            or any(type(n) is not int for n in buffers)
            or not 1<=buffers[0]<=2047 or not 1<=buffers[1]<=255):
        raise CaptureError('actual supported per-controller DLI buffer metadata required')
    return buffers[0],buffers[1]


def physical_tx_fragments(row, leg):
    """Check the current Session cursor contract against this sender's DLI bound.

    DTAP bytes include the five-byte channel header. An application length of
    250 does not imply PB fragmentation on a controller with a larger packet.
    The actual reassembler/NOCP and opposite RX checks remain independent.
    """
    tx=leg['tx']
    senders=[entry for entry in row['owners'] if
             (entry['owner']['bus'],entry['owner']['device'])==(tx['bus'],tx['device'])]
    if len(senders)!=1:raise CaptureError('one original physical sender metadata required')
    maximum,_=controller_budget(senders[0])
    raw=bytes.fromhex(tx['data']);pieces=tx.get('fragments',[tx])
    count=(len(raw)+maximum-1)//maximum
    if not raw or len(pieces)!=count:
        raise CaptureError('actual TX fragment count must match sender controller DLI bound')
    expected_pb=[0] if count==1 else [1]+[2]*(count-2)+[3]
    if [p.get('boundary',0)for p in pieces]!=expected_pb:
        raise CaptureError('actual TX requires ordered full or first/middle/last PB')
    offset=0
    for piece in pieces:
        data=bytes.fromhex(piece['data'])
        if len(data)!=min(maximum,len(raw)-offset) or data!=raw[offset:offset+len(data)]:
            raise CaptureError('each actual TX fragment must match bounded ordered PDU bytes')
        offset+=len(data)
    return dict(controller_acb_maximum=maximum,packet_count=count,fragmented=count>1)


def tx_status_receipts(row):
    samples=[]
    if not row.get('tx_status_required',False):return samples # historical never upgrades
    fields=['sequence','index','generation','lifetime','handle','maximum','capacity','outstanding','debt','peak','queued','limit','busy','bytes','offset','flags','blocks']
    pattern=r'^NativeTxStatus: stage=(ready|blocked|replied) '+r' '.join(name+r'=(\d+)' for name in fields)+r'$'
    for app in row['applications']:
        values=re.findall(pattern,app['stdout'],re.M)
        if not values or len(values)!=app['stdout'].count('NativeTxStatus:'):
            raise CaptureError('original actual TX-status receipts required')
        owner=row['owners'][0 if app['role']=='initiator' else 1]
        maximum,capacity=controller_budget(owner)
        last_peak=last_blocks=0
        for value in values:
            sample=dict(zip(fields,map(int,value[1:])));sample.update(stage=value[0],role=app['role'])
            if (sample['index'],sample['generation'],sample['lifetime'],sample['handle'])!=(owner['owner']['index'],owner['owner']['generation'],owner['object']['lifetime'],owner['object']['handle']):
                raise CaptureError('TX status immutable identity mismatch')
            if sample['maximum']!=maximum or sample['capacity']!=capacity or sample['limit']!=8 or sample['busy']>1 or sample['queued']+sample['busy']>8 or not 0<=sample['debt']<=sample['outstanding']<=sample['peak']<=capacity:
                raise CaptureError('native TX status budget invariant mismatch')
            if sample['flags']&~3 or not 0<=sample['offset']<=sample['bytes']<=2047 or (sample['flags']&1==0 and any(sample[k] for k in ['bytes','offset','flags','busy'])) or (sample['flags']&1 and (not sample['bytes'] or sample['busy']!=1)):
                raise CaptureError('native TX status operation invariant mismatch')
            if sample['peak']<last_peak or sample['blocks']<last_blocks:raise CaptureError('controller counters cannot decrease within generation')
            last_peak=sample['peak'];last_blocks=sample['blocks'];samples.append(sample)
        if [v[0] for v in values].count('ready')!=1:raise CaptureError('one actual ready TX status per fd required')
    return samples


def burst_pressure_receipts(row):
    source=next(a for a in row['applications'] if a['role']=='initiator')
    blocked=re.findall(r'^NativeBurstBlocked: sequence=(\d+) poll_writable=([01])$',source['stdout'],re.M)
    resumed=re.findall(r'^NativeBurstResumed: sequence=(\d+)$',source['stdout'],re.M)
    summary=re.findall(r'^NativeBurstPressure: eagain=(\d+) not_writable=(\d+) replies=(\d+)$',source['stdout'],re.M)
    if not row.get('burst',False):
        if blocked or resumed or summary or 'NativeBurst' in source['stdout']:
            raise CaptureError('pressure receipts require explicit burst gate')
        return None
    if row['rounds']!=16 or row['message_bytes']!=2042 or row.get('close_prefix') or row.get('boundary_check'):
        raise CaptureError('burst requires16 ordinary2042-byte app round trips')
    if len(summary)!=1 or not blocked or not resumed:
        raise CaptureError('actual EAGAIN/poll withdrawal/resumed admission required')
    count,not_writable,replies=map(int,summary[0]);sequences={int(v[0]) for v in blocked}
    if count!=len(blocked) or not_writable!=sum(v[1]=='0' for v in blocked) or not not_writable or replies!=16:
        raise CaptureError('pressure counts disagree with original receipts')
    if {int(v) for v in resumed}!=sequences or len(resumed)!=len(sequences) or any(not 0<=v<16 for v in sequences):
        raise CaptureError('every stalled admission must resume once within original sequence budget')
    if source['stdout'].count('NativeBurstBlocked:')!=count or source['stdout'].count('NativeBurstResumed:')!=len(resumed) or source['stdout'].count('NativeBurstPressure:')!=1:
        raise CaptureError('extra or malformed pressure receipts')
    return dict(eagain=count,poll_not_writable=not_writable,resumed_sequences=sorted(sequences),replies=16,scope='Software finite queue pressure; not controller packet-credit depletion')


def prefix_application_frames(row):
    validate_application_arguments(row)
    if row.get('rounds')!=1 or row.get('message_bytes')!=2042 or row.get('boundary_check'):
        raise CaptureError('prefix-close requires one actual 2042-byte operation')
    apps={a['role']:a for a in row['applications']}
    if set(apps)!={'peer','initiator'} or len(row['applications'])!=2:
        raise CaptureError('two original prefix applications required')
    for app in apps.values():
        if app['exit'] or app['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in app['credentials']['capabilities'].values()):
            raise CaptureError('successful ordinary prefix applications required')
    channel_info_receipts(row)
    tx_status_receipts(row)
    def single(app, pattern):
        values=re.findall(pattern,app['stdout'],re.M)
        if len(values)!=1:raise CaptureError('one original prefix receipt required')
        return values[0]
    source=apps['initiator'];peer=apps['peer']
    payload=bytes.fromhex(single(source,r'^NativePrefixSent: bytes=([0-9a-f]+)$'))
    dropped=bytes.fromhex(single(source,r'^NativePrefixQueued: bytes=([0-9a-f]+)$'))
    before,after=map(int,single(source,r'^NativePrefixClosed: start_wall_ns=(\d+) end_wall_ns=(\d+)$'))
    received=bytes.fromhex(single(peer,r'^NativeChannelReceived: sequence=0 bytes=([0-9a-f]+)$'))
    reply=bytes.fromhex(single(peer,r'^NativeChannelReply: sequence=0 bytes=([0-9a-f]+)$'))
    if len(payload)!=2042 or payload[:8]!=b'SLKSOCK1' or payload[28]!=0:
        raise CaptureError('random full prefix application PDU required')
    sequence=int.from_bytes(payload[24:28],'little')
    if any(payload[29+j]!=payload[8+j%16]^((sequence+j)&255) for j in range(2013)):
        raise CaptureError('prefix payload checksum mismatch')
    expected=bytearray(payload);expected[28]=1
    if received!=payload or reply!=expected or len(dropped)!=61 or dropped[:8]!=b'SLKDROP1':
        raise CaptureError('peer must validate and reply to complete PDU; queued marker distinct')
    if not row['start_wall_ns']<=before<=after<=row['end_wall_ns'] or after-before>=1_000_000_000:
        raise CaptureError('bounded actual final fd release timestamps required')
    if 'NativeChannelRoundTrip:' in source['stdout']:
        raise CaptureError('closed source cannot claim application round-trip receipt')
    if source.get('end_wall_ns',0)<after or source['stdout'].count('NativeChannelLastClose: same_lifetime_reopen=NotSupported')!=1:
        raise CaptureError('actual source exit after final close and retired-binding rebind rejection required')
    return [payload],[reply],dict(start_wall_ns=before,end_wall_ns=after,source_reaped_wall_ns=source['end_wall_ns'],dropped=dropped)


def protected_ssap_wire(row,capture,sdus):
    required=row.get('ssap_security_requirement',0)
    if not required:return None
    if type(required) is not int or required not in (1,2):raise CaptureError('invalid protected SMTC requirement')
    packets=0;controllers=[]
    for entry in row['owners']:
        owner,obj=entry['owner'],entry['object'];key=(owner['bus'],owner['device']);handle=obj['handle']
        events=[v for v in capture['native_events'] if (v['bus'],v['device'])==key
            and row['session_start_wall_ns']<=v['wall_ns']<=row['end_wall_ns'] and v['event']==0x11
            and v['params']==(b'\0'+handle.to_bytes(2,'little')+b'\1').hex()]
        if len(events)!=1:raise CaptureError('one actual cipher-on before protected SMTC required')
        frames=[v for v in sdus if (v['bus'],v['device'])==key and v['handle']==handle
            and row['session_start_wall_ns']<=v['wall_ns']<=row['end_wall_ns'] and v['data'].startswith('0a00')]
        if not frames or any(v['wall_ns']<events[0]['wall_ns'] for v in frames):raise CaptureError('protected SMTC cannot transmit or receive before live installation')
        if {v['direction'] for v in frames}!={'in','out'}:raise CaptureError('both protected SMTC USB directions required')
        packets+=len(frames);controllers.append(dict(index=owner['index'],generation=obj['generation'],lifetime=obj['lifetime'],handle=handle,cipher_record=events[0]['record'],packets=len(frames)))
    return dict(required=required,controllers=controllers,packets=packets,scope='Same SMTC actual post-install TX/opposite RX and ordinary peer database checks;not attribute authorization,Bond or RF cipher attestation')

def reject_unattributed_ssap(row, sdus):
    """Check the residual SDUs after the versioned evidence matchers consume them.

    Preserve historical gate decoding; current sequence/update contracts must
    also account for updates, acknowledgements and the extended opcode bit.
    This is capture attribution, not permission to accept an unknown PDU.
    """
    tracked = ((1,4,5,6,7,8,9,10,11,13,14) if row.get('ssap_access_required',False)
               else (1,4,5,6,7,8,9,13,14) if row.get('ssap_discovery_required',False)
               else (8,9,13,14))
    current = (row.get('ssap_value_lengths_version') == 4
               or row.get('ssap_update_delivery_version') == 2
               or row.get('ssap_subscription_required',False))
    if 'ssap_write_command_contract' in row:
        if type(row['ssap_write_command_contract']) is not int or row['ssap_write_command_contract'] != 1:
            raise CaptureError('explicit supported Write Command capture contract required')
        tracked += (1,12)
        current = True
    if current:
        tracked += (15,16,17)
    for packet in sdus:
        raw = packet['data']
        if (not raw.startswith('0a00') or len(raw) < 10
                or not row['start_wall_ns'] <= packet['wall_ns'] <= row['end_wall_ns']):
            continue
        opcode = int(raw[8:10],16)
        if (opcode & 0x7f if current else opcode) in tracked:
            raise CaptureError('extra/unattributed SSAP value USB packet')


def corroborate(run,capture):
    rows=run.get('channel_socket')
    if rows is None or len(rows)!=2:raise CaptureError('two connection direction phases required')
    sdus=reassemble_acb(capture);proofs=[];all_nonces=set();all_sequences=set()
    for n,row in enumerate(rows):
        if row['phase']!=n or row['status']!='ORDINARY_CHANNEL_SOCKET_EVIDENCE_PENDING':raise CaptureError('original successful socket phase required')
        # Value/discovery matching consumes SDUs to detect unattributed input.
        # Audit the complete lifetime window before that intentional removal.
        protected=protected_ssap_wire(row,capture,sdus)
        from ws73_ssap_access import audit_rejections as access_audit
        access_audit(row,sdus)
        prefix=None
        if row.get('close_prefix',False):sent,replies,prefix=prefix_application_frames(row)
        else:sent,replies=application_frames(row)
        receipt_context,control_rejected=message_security_receipts(row)
        intents,intent_rejected=send_constraint_receipts(row)
        rejected=rejected_frames(row)+control_rejected+intent_rejected
        for raw in rejected:
            if any(raw.hex() in p['data'] and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns'] for p in sdus):raise CaptureError('rejected message reached USB data path')
        limits=dtap_limits(row)
        owners=row['owners']
        if len(owners)!=2 or owners[0]['owner']['index']==owners[1]['owner']['index']:raise CaptureError('independent controller identities required')
        def matched(entry,direction,payload,session=False):
            owner,obj=entry['owner'],entry['object']
            if limits and payload[:2]!=b'\x02\x00':
                receipt=next((x for x in channel_info_receipts(row) if x['fields'][0]==owner['index']),None)
                if not receipt or len(payload)>receipt['fields'][8]:raise CaptureError('complete business PDU exceeds negotiated MPS')
            if owner['generation']!=obj['generation'] or not obj['lifetime']:raise CaptureError('canonical generation/lifetime required')
            found=[p for p in sdus if (p['bus'],p['device'])==(owner['bus'],owner['device'])
                   and p['handle']==obj['handle'] and p['direction']==direction and p['data']==payload.hex()
                   and (row.get('session_start_wall_ns',row['start_wall_ns']) if session else row['start_wall_ns'])<=p['wall_ns']<=row['end_wall_ns']]
            if len(found)!=1:raise CaptureError('one exact USB TX/opposite RX per message required')
            return found[0]
        ssap_values=[];ssap_credit={0:0,1:0}
        if row.get('ssap_value_required',False):
            from ws73_ssap_value import corroborate as ssap_value_corroborate
            def value_matched(entry,direction,payload,item):
                owner,obj=entry['owner'],entry['object']
                found=[p for p in sdus if (p['bus'],p['device'])==(owner['bus'],owner['device']) and p['handle']==obj['handle'] and p['direction']==direction and p['data']==payload.hex() and item['start_wall_ns']<=p['wall_ns']<=item['end_wall_ns']]
                if len(found)!=1:raise CaptureError('one exact SSAP value USB leg in original command interval required')
                result=found.pop(0);sdus.remove(result);return result
            ssap_values,ssap_credit=ssap_value_corroborate(row,value_matched)
            ssap_discovery=[]
            if row.get('ssap_discovery_required',False):
                from ws73_ssap_discovery import corroborate as discovery_corroborate
                ssap_discovery,discovery_credit=discovery_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=discovery_credit[key]
            ssap_access=[]
            if row.get('ssap_access_required',False):
                from ws73_ssap_access import corroborate as access_corroborate
                ssap_access,access_credit=access_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=access_credit[key]
            ssap_owned=[]
            if row.get('ssap_owned_required',False):
                from ws73_ssap_owned import corroborate as owned_corroborate
                ssap_owned,owned_credit=owned_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=owned_credit[key]
            ssap_read_providers=[]
            if row.get('ssap_read_provider_required',False):
                from ws73_ssap_read_provider import corroborate as provider_corroborate
                ssap_read_providers,provider_credit=provider_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=provider_credit[key]
            ssap_write_commands=[]
            if row.get('ssap_write_command_required',False):
                from ws73_ssap_command import corroborate as command_corroborate
                ssap_write_commands,command_credit=command_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=command_credit[key]
            from ws73_ssap_command_policy import corroborate as command_policy_corroborate
            ssap_command_policy,policy_credit=command_policy_corroborate(row,value_matched,sdus)
            for key in ssap_credit:ssap_credit[key]+=policy_credit[key]
            from ws73_ssap_command_deadline import corroborate as command_deadline_corroborate
            ssap_command_deadline,deadline_credit=command_deadline_corroborate(row,value_matched,sdus)
            for key in ssap_credit:ssap_credit[key]+=deadline_credit[key]
            ssap_sender_deadline=[]
            if row.get('ssap_sender_deadline_required',False):
                from ws73_ssap_sender_deadline import corroborate as sender_corroborate
                ssap_sender_deadline,sender_credit=sender_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=sender_credit[key]
            ssap_receive_lifecycle=[]
            if row.get('ssap_receive_lifecycle_required',False):
                from ws73_ssap_receive_lifecycle import corroborate as receive_corroborate
                ssap_receive_lifecycle,receive_credit=receive_corroborate(row,value_matched,sdus)
                for key in ssap_credit:ssap_credit[key]+=receive_credit[key]
            ssap_owned_updates=[]
            ssap_update_delivery=[]
            ssap_subscription=[]
            if row.get('ssap_subscription_required',False):
                from ws73_ssap_subscription import corroborate as subscription_corroborate
                ssap_subscription,subscription_credit=subscription_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=subscription_credit[key]
            if row.get('ssap_update_delivery_required',False):
                from ws73_ssap_update_delivery import corroborate as delivery_corroborate
                ssap_update_delivery,delivery_credit=delivery_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=delivery_credit[key]
            if row.get('ssap_owned_update_required',False):
                from ws73_ssap_owned_update import corroborate as update_corroborate
                ssap_owned_updates,update_credit=update_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=update_credit[key]
            ssap_owner_lifecycle=[]
            if row.get('ssap_owner_lifecycle_required',False):
                from ws73_ssap_owner_lifecycle import corroborate as owner_lifecycle_corroborate
                ssap_owner_lifecycle,lifecycle_credit=owner_lifecycle_corroborate(row,value_matched,sdus)
                for key in ssap_credit:ssap_credit[key]+=lifecycle_credit[key]
            ssap_requester_lifecycle=[]
            if row.get('ssap_requester_lifecycle_required',False):
                from ws73_ssap_requester_lifecycle import corroborate as requester_corroborate
                ssap_requester_lifecycle,requester_credit=requester_corroborate(row,value_matched,sdus)
                for key in ssap_credit:ssap_credit[key]+=requester_credit[key]
            reject_unattributed_ssap(row,sdus)
        legs=[]
        for sequence,(data,reply) in enumerate(zip(sent,replies)):
            if data[8:24] in all_nonces:raise CaptureError('random nonce reused across direction phases')
            all_nonces.add(data[8:24])
            wire_sequence=int.from_bytes(data[24:28],'little')
            if wire_sequence in all_sequences:raise CaptureError('wire sequence reused across direction phases')
            all_sequences.add(wire_sequence)
            for sender,receiver,payload in [(owners[0],owners[1],data),(owners[1],owners[0],reply)]:
                frame=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                legs.append(dict(sequence=sequence,tx=matched(sender,'out',frame),rx=matched(receiver,'in',frame)))
        if row.get('ssap_command_deadline_required',False):
            from ws73_ssap_command_deadline import verify_business as command_deadline_business
            command_deadline_business(row,row['ssap_command_deadline_case'],legs)
        # Each endpoint sends one capability request, one response, the recorded number of business PDUs.
        if prefix:
            pieces=legs[0]['tx']['fragments']
            if len(pieces)!=9 or not pieces[0]['wall_ns']<prefix['start_wall_ns'] or not prefix['source_reaped_wall_ns']<pieces[-1]['wall_ns']:
                raise CaptureError('actual USB first submit < final fd close < source exit/rebind refusal < last submit required')
            if any(prefix['dropped'].hex() in p['data'] and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns'] for p in sdus):
                raise CaptureError('never-started queue reached USB after author close')
            if row.get('after_close_ssap_start_wall_ns',0)<=prefix['end_wall_ns'] or not row.get('ssap_values'):
                raise CaptureError('other SMTC must perform real app operations after close')
            if any(item['start_wall_ns']<row['after_close_ssap_start_wall_ns'] for item in row['ssap_values']):
                raise CaptureError('old SSAP traffic cannot stand in for post-close isolation')
        capabilities=[]
        for sender,receiver in [owners,owners[::-1]]:
            identifier=row.get('cmtc_identifier',1) # historical captures retain original identifier1
            if type(identifier) is not int or not 0<=identifier<=255:raise CaptureError('exact CMTC wire identifier required')
            query=bytes([2,0,8,0,1,identifier,4,0,0xe2,0,0,0])
            receipt=next((value for value in channel_info_receipts(row) if value['fields'][0]==sender['owner']['index']),None)
            mtu=receipt['fields'][7] if receipt else 249
            advertised=limits or dict(mtu=mtu,mps=mtu)
            response=bytes([2,0,16,0,2,identifier,12,0,0xe2,0,0,0,0,0])+advertised['mtu'].to_bytes(2,'little')+advertised['mps'].to_bytes(2,'little')+bytes.fromhex('0101')
            capabilities.append(dict(request_tx=matched(sender,'out',query,session=row.get('ssap_exchange_required',False)),request_rx=matched(receiver,'in',query,session=row.get('ssap_exchange_required',False)),
                                     response_tx=matched(sender,'out',response,session=row.get('ssap_exchange_required',False)),response_rx=matched(receiver,'in',response,session=row.get('ssap_exchange_required',False))))
            owner,obj=sender['owner'],sender['object']
            completed=[e for e in capture['native_events'] if e['event']==9 and (e['bus'],e['device'])==(owner['bus'],owner['device'])
                       and row.get('session_start_wall_ns',row['start_wall_ns'])<=e['wall_ns']<=row['end_wall_ns']]
            if any(len(bytes.fromhex(e['params']))!=3 or int.from_bytes(bytes.fromhex(e['params'])[:2],'little')!=obj['handle'] for e in completed):raise CaptureError('exact actual completion handle required')
            if sum(bytes.fromhex(e['params'])[2] for e in completed)!=sum(len(leg['tx'].get('fragments',[leg['tx']])) for leg in legs if (leg['tx']['bus'],leg['tx']['device'])==(owner['bus'],owner['device']))+(4 if row.get('ssap_exchange_required',False) else 2)+ssap_credit[owners.index(sender)]:raise CaptureError('exact actual completed packet count per controller required')
        ssap=[]
        if row.get('ssap_exchange_required',False):
            if len(row.get('ssap_receipts',[]))!=2:raise CaptureError('both original daemon SSAP receipts required')
            for source,owner in zip(row['ssap_receipts'],owners):
                pattern=r'^SsapExchangeInfo: index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) local_mtu=(\d+) negotiated_mtu=(\d+) request=([0-9a-f]+) peer_reply=([0-9a-f]+) peer_request=([0-9a-f]+) response=([0-9a-f]+)$'
                fields=re.findall(pattern,source['stdout'],re.M)
                if source['exit'] or len(fields)!=1:raise CaptureError('one original successful SSAP observation required')
                value=fields[0];o=owner['owner'];obj=owner['object']
                if tuple(map(int,value[:4]))!=(o['index'],o['generation'],obj['lifetime'],obj['handle']):raise CaptureError('SSAP owner/lifetime mismatch')
                mtu=int(value[4]);negotiated=int(value[5]);req,rsp,peer_req,response=map(bytes.fromhex,value[6:])
                version=row.get('ssap_exchange_contract',1)
                if type(version)is not int or version not in (1,2):raise CaptureError('known exact ExchangeInfo contract required')
                extra=b'\x04\0\0\0'if version==2 else b'';control=7 if version==2 else 3
                expected_req=bytes([2,control])+mtu.to_bytes(2,'little')+bytes([1,2])+extra;expected_rsp=bytes([3,control])+mtu.to_bytes(2,'little')+bytes([1,2])+extra
                if (req,rsp,peer_req,response)!=(expected_req,expected_rsp,expected_req,expected_rsp) or negotiated!=mtu:raise CaptureError('exact real basic ExchangeInfo required')
                receiver=next(e for e in owners if e!=owner)
                ssap_legs=[]
                for payload in [req,response]:
                    frame=bytes([10,0])+len(payload).to_bytes(2,'little')+payload
                    ssap_legs.append(dict(tx=matched(owner,'out',frame,True),rx=matched(receiver,'in',frame,True)))
                ssap.append(dict(receipt=source,wire=ssap_legs))
        entry = dict(phase=n,owners=owners,capabilities=capabilities,legs=legs)
        if row.get('message_security_required',False):
            entry['message_security']=receipt_context
            entry['unsupported_control_rejections']=len(control_rejected)
        if row.get('tx_constraint_required',False):
            entry['constrained_replies']=intents
            entry['invalid_intent_refusals']=len(intent_rejected)
        if limits:entry.update(dtap_limits_version=1,independent_mtu_mps=True)
        if row.get('tx_status_required',False):entry['tx_status']=tx_status_receipts(row)
        if row.get('burst',False):entry['burst_pressure']=burst_pressure_receipts(row)
        if prefix:entry['prefix_close']={k:v for k,v in prefix.items() if k!='dropped'}|dict(dropped_marker=prefix['dropped'].hex(),other_channel_after_close=True)
        if row.get("channel_info_required",False): entry["channel_info"] = channel_info_receipts(row)
        if row.get("ssap_exchange_required",False): entry["ssap_exchange"] = ssap
        if row.get("ssap_value_required",False): entry["ssap_values"] = ssap_values
        if row.get("ssap_access_required",False): entry["ssap_access"] = ssap_access
        if row.get("ssap_update_local_rejection_required",False): entry["ssap_local_update_rejection"] = row["unsupported_incoming"]
        if row.get("ssap_discovery_required",False): entry["ssap_discovery"] = ssap_discovery
        if row.get('ssap_owned_required',False):entry['ssap_owned']=ssap_owned
        if row.get('ssap_read_provider_required',False):entry['ssap_read_providers']=ssap_read_providers
        if row.get('ssap_write_command_required',False):entry['ssap_write_commands']=ssap_write_commands
        if row.get('ssap_command_policy_required',False):entry['ssap_command_policy']=ssap_command_policy
        if row.get('ssap_command_deadline_required',False):entry['ssap_command_deadline']=ssap_command_deadline
        if row.get('ssap_owned_update_required',False):entry['ssap_owned_updates']=ssap_owned_updates
        if row.get('ssap_subscription_required',False):entry['ssap_subscription']=ssap_subscription
        if row.get('ssap_update_delivery_required',False):entry['ssap_update_delivery']=ssap_update_delivery
        if row.get('ssap_receive_lifecycle_required',False):entry['ssap_receive_lifecycle']=ssap_receive_lifecycle
        if row.get('ssap_sender_deadline_required',False):entry['ssap_sender_deadline']=ssap_sender_deadline
        if row.get('ssap_owner_lifecycle_required',False):entry['ssap_owner_lifecycle']=ssap_owner_lifecycle
        if row.get('ssap_requester_lifecycle_required',False):entry['ssap_requester_lifecycle']=ssap_requester_lifecycle
        if protected is not None:entry['protected_ssap']=protected
        proofs.append(entry)
    proof=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=sum(row['rounds'] for row in rows if not row.get('close_prefix',False)),proofs=proofs,
                scope=f"uid1000/caps0 two applications; CMTC/basic CUTC31 PI241; {rows[0].get('message_bytes',61)}-byte peer-validated payload; both USB/HCC/A3 ends and NOCP",
                long_pdu_acceptance=False,credit_exhaustion_acceptance=False,four_device_acceptance=False)
    if any(row.get('burst',False) for row in rows):
        if not all(row.get('burst',False) for row in rows):raise CaptureError('both connection roles must observe real pressure')
        proof['software_backpressure_acceptance']=True
        proof['burst_pressure']=[burst_pressure_receipts(row) for row in rows]
    if any(row.get('close_prefix',False) for row in rows):
        proof['prefix_close_phases']=sum(bool(row.get('close_prefix',False)) for row in rows)
        proof['physical_prefix_delivery_acceptance']=all(row.get('close_prefix',False) for row in rows)
    fragmented=[]
    for row,phase in zip(rows,proofs):
        for leg in phase['legs']:
            shape=physical_tx_fragments(row,leg)
            fragmented.append(shape['fragmented'])
    proof['long_pdu_acceptance']=bool(fragmented) and all(fragmented) and not any(row.get('close_prefix',False) for row in rows)
    if any(row.get('boundary_check',False) for row in rows):
        proof['application_boundary_rejections']=sum(len(rejected_frames(row)) for row in rows)
        proof['application_message_bytes']=rows[0].get('message_bytes',61)
        proof['dtap_pdu_bytes']=proof['application_message_bytes']+5
    return proof


def benchmark_application_reports(source, peer):
    if isinstance(source,dict) and source.get("schema_version")==2:
        from ws73_benchmark import load_application_reports
        return load_application_reports(source,peer)
    """Check v1 ping-pong application reports, NOT artifact/USB/RF qualification.

    Reuses this gate's application evidence layer. Time arithmetic stays within
    each process clock; neither peer timestamps nor NOCP stand in for source RTT.
    A future VM gate must also bind owners/credentials/artifacts/captures.
    """
    def require(condition, message):
        if not condition:
            raise CaptureError('benchmark: ' + message)

    def integer(value, low=0, high=(1 << 64)-1):
        return type(value) is int and low <= value <= high

    def ranks(values):
        values = sorted(values)
        require(bool(values), 'empty RTT samples')
        def rank(p, denominator=100):
            return values[(p*len(values)+denominator-1)//denominator-1]
        return dict(successful_samples=len(values),min_ns=values[0],p50_ns=rank(50),
                    p90_ns=rank(90),p95_ns=rank(95),p99_ns=rank(99),
                    p999_ns=rank(999,1000) if len(values)>=10000 else None,max_ns=values[-1])

    require(isinstance(source,dict) and isinstance(peer,dict), 'both original reports required')
    config=source.get('config')
    require(isinstance(config,dict) and set(config)=={'count','bytes'},'exact workload parameters')
    count,size=config['count'],config['bytes']
    require(integer(count,1,10000) and integer(size,29,2042),'finite sample and byte bounds')
    replies=[];rtts=[];identities=[]
    for responder,report in [(False,source),(True,peer)]:
        require({'schema_version','status','performance_qualified','workload','responder','config','clock',
                 'rtt_definition','percentile_method','unmeasured','channel_identity','elapsed_ns','attempted',
                 'admitted','validated','timed_out','unattempted','success_only_rtt','error','samples'} <= set(report),
                'required report fields')
        require(type(report['config']) is dict and set(report['config'])=={'count','bytes'}
                and all(type(v) is int for v in report['config'].values()), 'exact integer config')
        require(isinstance(report['unmeasured'],list) and bool(report['unmeasured'])
                and all(isinstance(v,str) for v in report['unmeasured']), 'explicit incomplete evidence closure')
        require(report.get('schema_version')==1 and type(report.get('schema_version')) is int,'schema version')
        require(report.get('status')=='MEASURED_NOT_QUALIFIED' and report.get('performance_qualified') is False,'measurement is never qualification')
        require(report.get('responder') is responder and report.get('config')==config,'same workload, opposite application roles')
        require(report.get('workload')=='ping-pong-one-outstanding','supported workload')
        require(report.get('clock')=='process-local-Rust-Instant-relative-nanoseconds','explicit local ns clock domain')
        require(report.get('rtt_definition')=='successful send syscall entry to validated reply, same initiator clock','RTT origin')
        require(report.get('percentile_method')=='nearest-rank;success-only;p99.9 requires10000 successes','percentile method')
        require(type(report.get('late',0)) is int and report.get('late',0)==0,'late validations are not timely successes')
        require(report.get('error') is None and all(type(report.get(k)) is int and report[k]==v for k,v in
                [('attempted',count),('admitted',count),('validated',count),('timed_out',0),('unattempted',0)]),'all attempts and failures must be retained')
        require(integer(report.get('elapsed_ns'),1),'elapsed interval')
        samples=report.get('samples')
        require(isinstance(samples,list) and len(samples)==count,'all original samples')
        identity=report.get('channel_identity')
        require(isinstance(identity,dict),'channel identity')
        for name,low,high in [('controller',0,65535),('generation',1,(1<<64)-1),('lifetime',1,(1<<64)-1),('handle',0,4095),('mtu',size,2042),('mps',size+5,2047)]:
            require(integer(identity.get(name),low,high),'bounded identity/capability '+name)
        require(all(identity.get(k)==v and type(identity.get(k)) is int for k,v in [('local_tcid',31),('remote_tcid',31),('pi',241),('mode',0),('directions',3)]),'current basic CUTC capabilities')
        identities.append((identity['controller'],identity['generation']))
        nonces=set();sequences=set();frames=[];previous=0
        for index,row in enumerate(samples):
            require(isinstance(row,dict) and {'index','planned_ns','first_syscall_ns','syscall_ns','send_attempts',
                    'would_block','admitted_ns','read_ns','validated_ns','errno','timed_out','frame_hex'} <= set(row),
                    'required original sample fields')
            require(type(row.get('index')) is int and row['index']==index,'ordered sample indices')
            require(row.get('late',False) is False,'late sample cannot be successful')
            require(row.get('timed_out') is False and row.get('errno') is None,'failed sample cannot be successful')
            require(integer(row.get('send_attempts'),1,(1<<32)-1) and integer(row.get('would_block'),0,(1<<32)-1)
                    and row['send_attempts']==row['would_block']+1,'all send attempts accounted')
            fields=['planned_ns','read_ns','validated_ns','first_syscall_ns','syscall_ns','admitted_ns'] if responder else [
                'planned_ns','first_syscall_ns','syscall_ns','admitted_ns','read_ns','validated_ns']
            times=[row.get(k) for k in fields]
            require(all(integer(t) for t in times) and previous<=times[0] and times==sorted(times)
                    and times[-1]<=report['elapsed_ns'],'same-domain per-message ordering and finite elapsed')
            previous=times[-1]
            if not responder:
                latency=row['validated_ns']-row['syscall_ns']
                require(latency<=10_000_000_000,'original request deadline')
                rtts.append(latency)
            raw=row.get('frame_hex')
            require(isinstance(raw,str) and len(raw)==2*size and re.fullmatch('[0-9a-f]+',raw) is not None,'bounded original frame bytes')
            frame=bytes.fromhex(raw)
            require(frame[:8]==b'SLKSOCK1' and frame[28]==1,'actual validated reply encoding')
            nonce=frame[8:24];sequence=int.from_bytes(frame[24:28],'little')
            require(nonce not in nonces and sequence not in sequences,'unique nonce and sequence')
            nonces.add(nonce);sequences.add(sequence)
            require(all(frame[29+j]==nonce[j%16]^((sequence+j)&255) for j in range(size-29)),'payload validation')
            frames.append(frame)
        if not responder:
            distribution=report['success_only_rtt']
            require(isinstance(distribution,dict) and set(distribution)==set(ranks(rtts))
                    and all((v is None and k=='p999_ns' and count<10000) or integer(v)
                            for k,v in distribution.items()),'integer ns distribution fields')
        require(report.get('success_only_rtt')==(None if responder else ranks(rtts)),'recomputed successful RTT distribution')
        replies.append(frames)
    require(identities[0]!=identities[1],'two distinct controller identities')
    require(replies[0]==replies[1],'actual peer validated and replied to every random source message')
    return dict(status='APPLICATION_REPORTS_CONSISTENT_NOT_QUALIFIED',performance_qualified=False,
                messages=count,application_bytes=size,source_rtt=ranks(rtts),
                remaining=['artifact/source/tool/config/firmware closure','actual ordinary credentials and kernel ownership',
                           'independent both-end captures/drop checks','resource and trace-overhead measurements'])
