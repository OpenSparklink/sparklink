# SPDX-License-Identifier: GPL-2.0-only
"""Actual D-Bus Agent witness plus independent USB/relay/application checks.

No protocol engine, keys or successful dependencies are simulated. Captures
may contain actual install material and must remain private.
"""
import json
import time
from ws73_capture import CaptureError
from ws73_security_capabilities import OFFER

MODES=('approve','reject','timeout','cancel','agent-exit','caller-exit','cli-approve','cli-reject','install-cancel','numeric-approve','numeric-reject','numeric-late')

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
    if mode=='install-cancel':
        from ws73_security_install_hold import arm
        folder=arm(run,phase,row);command+=['--install-hold-directory',str(folder)]
    result=run.command(command,20,collection='security_agent_commands')
    row['command']=result;run.save()
    if result['exit']:raise CaptureError('actual Agent witness failed: '+result['stderr'])
    row['events']=[json.loads(line) for line in result['stdout'].splitlines()]
    if mode=='install-cancel':
        from ws73_security_install_hold import collect
        collect(row,folder)
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
    numeric=row['mode'].startswith('numeric-')
    if numeric:expected.update(numeric_callback=2,numeric_decision=2)
    if row['mode']=='install-cancel':expected.update(install_barrier=2,install_before_cancel=1,install_cancelled=1,install_terminal_stable=1)
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
        expected_prompt=[path,allocation['request_id'],*info[:2],info[2],info[3],info[4],info[5], 'sdk111-numeric-comparison' if numeric else 'sdk111-no-mitm',allocation['deadline_monotonic_ns']]
        if (callback['prompt']!=expected_prompt or callback['daemon_owner']!=daemon['owner'] or not allocation['unknown_begin_refused']
                or not row['start_wall_ns']<=allocation['start_wall_ns']<=callback['wall_ns']<=complete['wall_ns']<=row['end_wall_ns']):raise CaptureError('actual request/method/original deadline callback linkage required')
        if row['mode']=='caller-exit':
            cleanup=[v for v in stages['caller_loss_cleanup'] if v['path']==path]
            if len(cleanup)!=1 or cleanup[0]['old_request']!=allocation['request_id'] or cleanup[0]['new_request']<=allocation['request_id'] or not cleanup[0]['old_result_access_denied'] or not cleanup[0]['fresh_cancelled']:raise CaptureError('distinct new caller must not inherit old operation')
        else:
            result=[v for v in stages['policy_result'] if v['path']==path]
            if len(result)!=1:raise CaptureError('one terminal policy observation required')
            result=result[0]
            phase_value={'approve':4,'reject':5,'timeout':7,'cancel':6,'agent-exit':10,'install-cancel':6 if obj['role']==0 else 4,'numeric-approve':4,'numeric-reject':5,'numeric-late':7}[row['mode']]
            if any(result[k]!=allocation[k] for k in ['request_id','generation','lifetime','deadline_monotonic_ns']) or result['phase']!=phase_value:raise CaptureError('old identity/terminal state mismatch')
            if numeric:
                callbacks=[v for v in stages['numeric_callback'] if v['prompt'][0]==path]
                decisions=[v for v in stages['numeric_decision'] if v['prompt'][0]==path]
                if len(callbacks)!=1 or len(decisions)!=1:raise CaptureError('one live original numeric callback and decision required')
                cb,dec=callbacks[0],decisions[0]
                if cb['prompt']!=expected_prompt or dec['prompt']!=expected_prompt or cb['daemon_owner']!=daemon['owner'] or type(cb['code']) is not int or not 0<=cb['code']<1_000_000 or dec['code']!=cb['code'] or not callback['wall_ns']<=cb['wall_ns']<=dec['wall_ns']<=result['wall_ns']<=complete['wall_ns']:raise CaptureError('actual numeric code/decision/original author/terminal causal chain required')
                late=row['mode']=='numeric-late'
                if (dec['accepted'] is not (row['mode']!='numeric-reject') or not late and dec['reply_delivered'] is not True
                        or (dec['monotonic_ns']>=allocation['deadline_monotonic_ns'])!=late):raise CaptureError('explicit confirmation and original nanosecond deadline required')
                wanted=(11,0,119) if row['mode']=='numeric-approve' else (5,-13,7) if row['mode']=='numeric-reject' else (7,-110,7)
                if not result['agent_approved'] or not result['native_admitted'] or (result['kernel_state'],result['kernel_error'],result['kernel_flags'])!=wanted or result['kernel_status'] or result['cleanup_error'] or result['error']!=(0 if row['mode']=='numeric-approve' else -110 if late else -125):raise CaptureError('numeric policy decision does not replace real original native terminal')
            elif row['mode']=='install-cancel' and obj['role']==0:
                if not result['agent_approved'] or not result['native_admitted'] or result['kernel_state']!=6 or result['cleanup_error']:
                    raise CaptureError('original native in-flight cancellation must settle')
                before=stages['install_before_cancel'][0];withdrawn=stages['install_cancelled'][0];late=stages['install_terminal_stable'][0]
                raw=[result[k] for k in ['request_id','generation','lifetime','phase','error','deadline_monotonic_ns','agent_approved','native_admitted','kernel_state','kernel_error','kernel_flags','kernel_status','cleanup_error']]
                if (any(e['path']!=path for e in [before,withdrawn,late]) or withdrawn['raw']!=raw or late['raw']!=raw
                        or before['raw'][:3]!=raw[:3] or before['raw'][5]!=raw[5]
                        or before['raw'][3]!=3 or before['raw'][6:8]!=[True,True]
                        or before['raw'][8] not in [1,2,3]):raise CaptureError('exact admitted/cancelled/late original request witness required')
            elif row['mode'] in ['approve','install-cancel']:
                if (not result['agent_approved'] or not result['native_admitted'] or result['kernel_state']!=9
                        or any(result[k] for k in ['error','kernel_error','kernel_status','cleanup_error'])):raise CaptureError('actual native result distinct from policy yes required')
            elif result['native_admitted'] or result['kernel_state']:raise CaptureError('pre-admission negative path cannot enter physical mechanism')
    return stages

def wire(row,phase,capture):
    low,high=row['start_wall_ns'],row['end_wall_ns']
    numeric=row['mode'].startswith('numeric-')
    approved=row['mode'] in ['approve','cli-approve','install-cancel','numeric-approve']
    active=approved or numeric
    order=([0x134,0x135,0x136,0x137,0x13c,0x139]+([0x141,0x142] if approved else [])) if numeric else [0x134,0x135,0x136,0x137,0x138,0x139,0x13a,0x141,0x142]
    offer=bytes([1,0,4,16,0,2,2,2,2,0]) if numeric else OFFER
    received={};sent={};completed={};installs=[];keys=[];install_commands={}
    for entry in phase['typed_objects']:
        owner=entry['owner'];obj=entry['object'];role=obj['role'];handle=obj['handle'].to_bytes(2,'little')
        same=lambda v:(v['bus'],v['device'])==(owner['bus'],owner['device']) and low<=v['wall_ns']<=high
        commands=[v for v in capture['commands'] if same(v) and v['opcode'] in [0x1812,0x1c03,0x1c05]]
        if not active:
            if commands or any(same(v) and v['event'] in [0xe,0x11,0x14] for v in capture['native_events']):raise CaptureError('negative Agent policy must have no security wire activity')
            continue
        indices=[v for v in order if (v in [0x134,0x136,0x139,0x141])==(role==0)]
        relays=[v for v in commands if v['opcode']==0x1812]
        if len(relays)!=len(indices):raise CaptureError('all role-specific relay commands required')
        for cmd,index in zip(relays,indices):
            raw=bytes.fromhex(cmd['params']);size=10 if index in [0x134,0x135] else 70 if index==0x136 else 64 if index==0x137 else 32 if index==0x13c else 16
            if raw[:4]!=handle+index.to_bytes(2,'little') or len(raw)!=size+5 or raw[4]!=size or not cmd.get('completion'):raise CaptureError('relay schema/handle/type/actual USB completion required')
            if index==0x136 and raw[5:11]!=bytes([16,0 if numeric else 1,2,2,2,2]):raise CaptureError('explicit no-entry/no-MITM public-key envelope required')
            if index in [0x134,0x135] and raw[5:]!=offer:raise CaptureError('only known no-MITM/no-Bond offer permitted')
            reply=[v for v in capture['complete'] if same(v) and v['opcode']==0x1812 and v['status']==0 and v['value']==raw[:4].hex() and v['wall_ns']>=cmd['wall_ns']]
            if len(reply)!=1:raise CaptureError('real exact command Complete required')
            sent[index]=(cmd,raw[5:]);completed[index]=reply[0]
        events=[v for v in capture['native_events'] if same(v) and v['event']==0x14]
        expected_rx=[v for v in order if v not in indices]
        if len(events)!=len(expected_rx):raise CaptureError('all opposite real RX required')
        for event,index in zip(events,expected_rx):
            raw=bytes.fromhex(event['params'])
            if raw[:4]!=handle+index.to_bytes(2,'little'):raise CaptureError('opposite exact handle/index required')
            received[index]=event
        if not approved:
            if any(v['opcode'] in [0x1c03,0x1c05] for v in commands) or any(same(v) and v['event'] in [0xe,0x11] for v in capture['native_events']):raise CaptureError('rejected/expired numeric decision cannot install or enable encryption')
            continue
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
    if active:
        if approved and (len(keys)!=2 or keys[0]!=keys[1]):raise CaptureError('actual same derived material at both controllers required')
        for index,(cmd,payload) in sent.items():
            event=received[index];raw=bytes.fromhex(event['params'])
            if len(raw)!=len(payload)+5 or raw[4]!=len(payload) or raw[5:]!=payload or event['wall_ns']<cmd['wall_ns']:raise CaptureError('USB success cannot replace exact peer receipt')
        for previous,index in zip(order,order[1:]):
            prerequisite=completed[previous] if index in [0x138,0x13c] else received[previous]
            if prerequisite['wall_ns']>sent[index][0]['wall_ns']:raise CaptureError('actual peer/Complete dependency order required')
        gp,tp=sent[0x136][1][6:],sent[0x137][1]
        gn,tn=sent[0x139][1],sent[0x13c][1][16:] if numeric else sent[0x13a][1]
        if gp==tp or not any(gp) or not any(tp) or gn==tn or not any(gn) or not any(tn):raise CaptureError('distinct real public material and role nonces required')
        if numeric:
            from ws73_security_numeric import public_comparison
            code=public_comparison(gp,tp,gn,tn)
            events=[json.loads(v) for v in row['command']['stdout'].splitlines()]
            cb=[v for v in events if v['stage']=='numeric_callback']
            if len(cb)!=2 or any(v['code']!=code for v in cb):raise CaptureError('both actual numeric Agent codes must match independently checked public transcript')
            if approved:
                for role,index in [(0,0x141),(1,0x142)]:
                    path=next(v['object']['path'] for v in phase['typed_objects'] if v['object']['role']==role)
                    decision=next(v for v in events if v['stage']=='numeric_decision' and v['prompt'][0]==path)
                    if sent[index][0]['wall_ns']<decision['wall_ns']:raise CaptureError('DH proof cannot precede explicit local Agent decision')
        if approved:
            target=next(v for v in phase['typed_objects'] if v['object']['role']==1)
            req=[v for v in capture['native_events'] if (v['bus'],v['device'])==(target['owner']['bus'],target['owner']['device']) and low<=v['wall_ns']<=high and v['event']==0xe]
            if len(req)!=1 or req[0]['params']!=target['object']['handle'].to_bytes(2,'little').hex() or not received[0x142]['wall_ns']<=install_commands[0]['wall_ns']<=req[0]['wall_ns']<=install_commands[1]['wall_ns'] or completed[0x142]['wall_ns']>install_commands[1]['wall_ns']:raise CaptureError('real T key request and final proof must precede installation')
        return dict(relay_indices=list(sent),opposite_receipts=len(received),installations=installs)
    return dict(no_security_commands_or_events=True)

def post_terminal_numeric(row,phase,capture):
    """Audit through physical Down; a short witness window is insufficient.

    Matching late Complete/NOCP can still pay an existing physical obligation.
    They are not a new relay/key command or an unsolicited cipher-on event.
    """
    if row['mode'] not in ['numeric-reject','numeric-late']:return
    if not phase['start_wall_ns']<=row['start_wall_ns']<=row['end_wall_ns']<=phase['end_wall_ns']:
        raise CaptureError('complete original connection lifetime window required')
    for entry in phase['typed_objects']:
        owner=entry['owner'];handle=entry['object']['handle'].to_bytes(2,'little')
        same=lambda v:(v['bus'],v['device'])==(owner['bus'],owner['device']) and row['end_wall_ns']<v['wall_ns']<=phase['end_wall_ns']
        for command in capture['commands']:
            if same(command) and command['opcode'] in [0x1812,0x1c03,0x1c05]:
                raw=bytes.fromhex(command['params'])
                if len(raw)<2 or raw[:2]==handle:raise CaptureError('new security command after numeric terminal before actual Down')
        for event in capture['native_events']:
            if same(event) and event['event'] in [0xe,0x11]:
                raw=bytes.fromhex(event['params']);matched=raw[:2]==handle if event['event']==0xe else raw[1:3]==handle
                if matched:raise CaptureError('unexpected installation/encryption after rejected or expired numeric request')

def corroborate(control,capture):
    from ws73_channel_socket import corroborate as channel_corroborate
    business_proof=channel_corroborate(control,capture)
    phases=control['connection_control']['phases'];rows=control.get('security_agent',[])
    if len(rows)!=2 or len(phases)!=2:raise CaptureError('both exchanged connection roles required')
    result=[]
    for row,phase,business in zip(rows,phases,control['channel_socket'],strict=True):
        witness(row,phase,control['bus_before'],control.get('slctl'))
        proof=wire(row,phase,capture)
        post_terminal_numeric(row,phase,capture)
        if business['session_start_wall_ns']!=phase['start_wall_ns'] or business['start_wall_ns']<row['end_wall_ns'] or business.get('close_prefix'):raise CaptureError('same physical Session ordinary application delivery must follow Agent procedure')
        result.append(dict(mode=row['mode'],wire=proof,application_phase=business['phase']))
    return dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',phases=result,
        business_round_trips=business_proof['round_trips'],scope='Actual ordinary control user Agent callbacks, original owner/reference/deadline, real dual-controller wire and subsequent peer-checked business. Not authentication/Bond/full deployment/udev/systemd/natural recovery.')
