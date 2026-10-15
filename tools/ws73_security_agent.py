# SPDX-License-Identifier: GPL-2.0-only
"""Actual D-Bus Agent witness plus independent USB/relay/application checks.

No protocol engine, keys or successful dependencies are simulated. Captures
may contain actual install material and must remain private.
"""
import json
import time
from ws73_capture import CaptureError
from ws73_security_capabilities import OFFER

MODES=('approve','reject','timeout','cancel','agent-exit','caller-exit','cli-approve','cli-reject')

def execute(run,phase):
    mode=run.args.security_agent
    if mode not in MODES:raise CaptureError('explicit Agent mode required')
    row=dict(mode=mode,status='RUNNING',start_wall_ns=time.time_ns(),physical_acceptance=False)
    run.data.setdefault('security_agent',[]).append(row);run.save()
    if mode.startswith('cli-'):
        from ws73_security_cli import execute as cli_execute
        return cli_execute(run,phase,row)
    paths=[v['object']['path'] for v in phase['typed_objects']]
    command=['/bin/ws73-security-agent-probe','--connections',*paths,'--mode',mode]
    if mode=='timeout':command+=['--timeout-ms','500','--approval-delay-ms','800']
    elif mode in ['cancel','agent-exit','caller-exit']:command+=['--approval-delay-ms','700']
    result=run.command(command,20,collection='security_agent_commands')
    row['command']=result;run.save()
    if result['exit']:raise CaptureError('actual Agent witness failed: '+result['stderr'])
    row['events']=[json.loads(line) for line in result['stdout'].splitlines()]
    row['end_wall_ns']=time.time_ns();row['status']='PENDING_USB_AND_APPLICATION_CORROBORATION';run.save()

def witness(row,phase,daemon,binary=None):
    if row.get('mode','').startswith('cli-'):
        from ws73_security_cli import witness as cli_witness
        return cli_witness(row,phase,daemon,binary)
    if row['status']!='PENDING_USB_AND_APPLICATION_CORROBORATION' or row['mode'] not in MODES:raise CaptureError('complete explicit Agent witness required')
    if [json.loads(line) for line in row['command']['stdout'].splitlines()] != row['events']:raise CaptureError('sealed Agent transcript mismatch')
    if row['command']['exit']!=0 or not row['events']:raise CaptureError('Agent process did not finish')
    stages={}
    for event in row['events']:stages.setdefault(event['stage'],[]).append(event)
    expected={'probe_identity':1,'allocated':2,'agent_callback':2,'probe_complete':1,
              'caller_loss_cleanup':2} if row['mode']=='caller-exit' else {
                  'probe_identity':1,'allocated':2,'agent_callback':2,'probe_complete':1,'policy_result':2}
    if {key:len(value) for key,value in stages.items()}!=expected:raise CaptureError('missing/duplicate/unexpected Agent witness stages')
    identity=stages['probe_identity'][0]
    if (identity['daemon_owner']!=daemon['owner'] or identity['daemon_pid']!=daemon['pid'] or daemon['uid']!=0
            or identity['missing_agent_refusals']!=2 or identity['unknown_registration_refusals']!=2):raise CaptureError('original authenticated daemon and actual capability refusals required')
    fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in identity['process_status'].splitlines() if ':' in line}
    if (list(map(int,fields['Uid'].split()))!=[1000]*4 or list(map(int,fields['Gid'].split()))!=[1002]*4
            or any(int(fields[k],16) for k in ['CapEff','CapPrm','CapInh','CapAmb'])):raise CaptureError('actual ordinary control-group identity required')
    complete=stages['probe_complete'][0]
    if complete['status']!='PENDING_INDEPENDENT_USB_AND_BUSINESS_CORROBORATION' or complete['authenticated_identity'] or complete['bond'] or complete['physical_recovery_acceptance']:raise CaptureError('probe cannot self-qualify protocol/trust/Bond/recovery')
    paths=[v['object']['path'] for v in phase['typed_objects']]
    if identity['connections']!=paths:raise CaptureError('original two connection paths required')
    for i,entry in enumerate(phase['typed_objects']):
        obj=entry['object'];info=identity['infos'][i];path=paths[i]
        if info!=[obj[k] for k in ['generation','lifetime','handle','role','address_type','address']]+[True,True]:raise CaptureError('full canonical identity mismatch')
        allocation=[v for v in stages['allocated'] if v['path']==path]
        callback=[v for v in stages['agent_callback'] if v['prompt'][0]==path]
        if len(allocation)!=1 or len(callback)!=1:raise CaptureError('one original allocation and callback per controller')
        allocation=allocation[0];callback=callback[0]
        expected_prompt=[path,allocation['request_id'],*info[:2],info[2],info[3],info[4],info[5], 'sdk111-no-mitm',allocation['deadline_monotonic_ns']]
        if (callback['prompt']!=expected_prompt or callback['daemon_owner']!=daemon['owner'] or not allocation['unknown_begin_refused']
                or not row['start_wall_ns']<=allocation['start_wall_ns']<=callback['wall_ns']<=complete['wall_ns']<=row['end_wall_ns']):raise CaptureError('actual request/method/original deadline callback linkage required')
        if row['mode']=='caller-exit':
            cleanup=[v for v in stages['caller_loss_cleanup'] if v['path']==path]
            if len(cleanup)!=1 or cleanup[0]['old_request']!=allocation['request_id'] or cleanup[0]['new_request']<=allocation['request_id'] or not cleanup[0]['old_result_access_denied'] or not cleanup[0]['fresh_cancelled']:raise CaptureError('distinct new caller must not inherit old operation')
        else:
            result=[v for v in stages['policy_result'] if v['path']==path]
            if len(result)!=1:raise CaptureError('one terminal policy observation required')
            result=result[0]
            phase_value={'approve':4,'reject':5,'timeout':7,'cancel':6,'agent-exit':10}[row['mode']]
            if any(result[k]!=allocation[k] for k in ['request_id','generation','lifetime','deadline_monotonic_ns']) or result['phase']!=phase_value:raise CaptureError('old identity/terminal state mismatch')
            if row['mode']=='approve':
                if (not result['agent_approved'] or not result['native_admitted'] or result['kernel_state']!=9
                        or any(result[k] for k in ['error','kernel_error','kernel_status','cleanup_error'])):raise CaptureError('actual native result distinct from policy yes required')
            elif result['native_admitted'] or result['kernel_state']:raise CaptureError('pre-admission negative path cannot enter physical mechanism')
    return stages

def wire(row,phase,capture):
    low,high=row['start_wall_ns'],row['end_wall_ns']
    approved=row['mode'] in ['approve','cli-approve']
    received={};sent={};completed={};installs=[];keys=[];install_commands={}
    for entry in phase['typed_objects']:
        owner=entry['owner'];obj=entry['object'];role=obj['role'];handle=obj['handle'].to_bytes(2,'little')
        same=lambda v:(v['bus'],v['device'])==(owner['bus'],owner['device']) and low<=v['wall_ns']<=high
        commands=[v for v in capture['commands'] if same(v) and v['opcode'] in [0x1812,0x1c03,0x1c05]]
        if not approved:
            if commands or any(same(v) and v['event'] in [0xe,0x11,0x14] for v in capture['native_events']):raise CaptureError('negative Agent policy must have no security wire activity')
            continue
        indices=[0x134,0x136,0x139,0x141] if role==0 else [0x135,0x137,0x138,0x13a,0x142]
        relays=[v for v in commands if v['opcode']==0x1812]
        if len(relays)!=len(indices):raise CaptureError('all role-specific relay commands required')
        for cmd,index in zip(relays,indices):
            raw=bytes.fromhex(cmd['params']);size=10 if index in [0x134,0x135] else 70 if index==0x136 else 64 if index==0x137 else 16
            if raw[:4]!=handle+index.to_bytes(2,'little') or len(raw)!=size+5 or raw[4]!=size or not cmd.get('completion'):raise CaptureError('relay schema/handle/type/actual USB completion required')
            if index==0x136 and raw[5:11]!=bytes([16,1,2,2,2,2]):raise CaptureError('explicit no-entry/no-MITM public-key envelope required')
            if index in [0x134,0x135] and raw[5:]!=OFFER:raise CaptureError('only known no-MITM/no-Bond offer permitted')
            reply=[v for v in capture['complete'] if same(v) and v['opcode']==0x1812 and v['status']==0 and v['value']==raw[:4].hex() and v['wall_ns']>=cmd['wall_ns']]
            if len(reply)!=1:raise CaptureError('real exact command Complete required')
            sent[index]=(cmd,raw[5:]);completed[index]=reply[0]
        events=[v for v in capture['native_events'] if same(v) and v['event']==0x14]
        expected_rx=[0x135,0x137,0x138,0x13a,0x142] if role==0 else [0x134,0x136,0x139,0x141]
        if len(events)!=len(expected_rx):raise CaptureError('all opposite real RX required')
        for event,index in zip(events,expected_rx):
            raw=bytes.fromhex(event['params'])
            if raw[:4]!=handle+index.to_bytes(2,'little'):raise CaptureError('opposite exact handle/index required')
            received[index]=event
        installs_for_role=[v for v in commands if v['opcode'] in [0x1c03,0x1c05]]
        if len(installs_for_role)!=1:raise CaptureError('one installation per real role required')
        cmd=installs_for_role[0];raw=bytes.fromhex(cmd['params']);opcode=0x1c03 if role==0 else 0x1c05
        if cmd['opcode']!=opcode or len(raw)!=(21 if role==0 else 20) or raw[:2]!=handle or raw[18:]!=(b'\1\1\0' if role==0 else b'\1\1') or not any(raw[2:18]) or not cmd.get('completion'):raise CaptureError('role-specific actual install schema required')
        keys.append(raw[2:18])
        accepted=[v for v in capture['native_events'] if same(v) and v['event']==1 and v['params']==(opcode.to_bytes(2,'little')+b'\1\0').hex() and v['wall_ns']>=cmd['wall_ns']]
        accepted += [v for v in capture['complete'] if same(v) and v['opcode']==opcode and v['status']==0 and v['wall_ns']>=cmd['wall_ns']]
        on=[v for v in capture['native_events'] if same(v) and v['event']==0x11 and v['params']==(b'\0'+handle+b'\1').hex() and v['wall_ns']>=cmd['wall_ns']]
        if not accepted or len(on)!=1 or len([v for v in capture['native_events'] if same(v) and v['event']==0x11])!=1:raise CaptureError('actual acceptance AND exact initial encryption event required')
        install_commands[role]=cmd
        installs.append(dict(role=role,opcode=opcode,key_redacted=True,command_record=cmd['record'],event_record=on[0]['record'],wall_ns=on[0]['wall_ns']))
    if approved:
        if len(keys)!=2 or keys[0]!=keys[1]:raise CaptureError('actual same derived material at both controllers required')
        for index,(cmd,payload) in sent.items():
            event=received[index];raw=bytes.fromhex(event['params'])
            if len(raw)!=len(payload)+5 or raw[4]!=len(payload) or raw[5:]!=payload or event['wall_ns']<cmd['wall_ns']:raise CaptureError('USB success cannot replace exact peer receipt')
        order=[0x134,0x135,0x136,0x137,0x138,0x139,0x13a,0x141,0x142]
        for previous,index in zip(order,order[1:]):
            prerequisite=completed[previous] if index==0x138 else received[previous]
            if prerequisite['wall_ns']>sent[index][0]['wall_ns']:raise CaptureError('actual peer/Complete dependency order required')
        gp,tp=sent[0x136][1][6:],sent[0x137][1]
        gn,tn=sent[0x139][1],sent[0x13a][1]
        if gp==tp or not any(gp) or not any(tp) or gn==tn or not any(gn) or not any(tn):raise CaptureError('distinct real public material and role nonces required')
        target=next(v for v in phase['typed_objects'] if v['object']['role']==1)
        req=[v for v in capture['native_events'] if (v['bus'],v['device'])==(target['owner']['bus'],target['owner']['device']) and low<=v['wall_ns']<=high and v['event']==0xe]
        if len(req)!=1 or req[0]['params']!=target['object']['handle'].to_bytes(2,'little').hex() or not received[0x142]['wall_ns']<=install_commands[0]['wall_ns']<=req[0]['wall_ns']<=install_commands[1]['wall_ns'] or completed[0x142]['wall_ns']>install_commands[1]['wall_ns']:raise CaptureError('real T key request and final proof must precede installation')
        return dict(relay_indices=list(sent),opposite_receipts=len(received),installations=installs)
    return dict(no_security_commands_or_events=True)

def corroborate(control,capture):
    from ws73_channel_socket import corroborate as channel_corroborate
    business_proof=channel_corroborate(control,capture)
    phases=control['connection_control']['phases'];rows=control.get('security_agent',[])
    if len(rows)!=2 or len(phases)!=2:raise CaptureError('both exchanged connection roles required')
    result=[]
    for row,phase,business in zip(rows,phases,control['channel_socket'],strict=True):
        witness(row,phase,control['bus_before'],control.get('slctl'))
        proof=wire(row,phase,capture)
        if business['session_start_wall_ns']!=phase['start_wall_ns'] or business['start_wall_ns']<row['end_wall_ns'] or business.get('close_prefix'):raise CaptureError('same physical Session ordinary application delivery must follow Agent procedure')
        result.append(dict(mode=row['mode'],wire=proof,application_phase=business['phase']))
    return dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',phases=result,
        business_round_trips=business_proof['round_trips'],scope='Actual ordinary control user Agent callbacks, original owner/reference/deadline, real dual-controller wire and subsequent peer-checked business. Not authentication/Bond/full deployment/udev/systemd/natural recovery.')
