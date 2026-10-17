# SPDX-License-Identifier: GPL-2.0-only
"""Ordinary slctl connection gate; USB corroboration is a separate step.

No connection success, cancellation or recovery is synthesized here. This
first gate excludes release/last-File/dup/in-flight and SSAP acceptance.
"""
import re
import time

from ws73_capture import CaptureError, command_reply
from ws73_north_star import parse_result, parse_match
from ws73_capture import marker_data


def result(text, owner, operation):
    rows = re.findall(r'^NativeConnectionResult: generation=(\d+) request=(\d+) operation=(\d+) state=(\d+) errno=(-?\d+) fault=(-?\d+) command_status=(\d+) outcome_status=(\d+) handle=(\d+) flags=(\d+)$', text, re.M)
    if len(rows) != 1 or text.count('NativeConnectionResult:') != 1:
        raise CaptureError('one original typed connection result required')
    values = tuple(map(int, rows[0]))
    if (values[0] != owner['generation'] or not values[1] or values[2] != operation
            or values[3:8] != (4, 0, 0, 0, 0) or values[8] > 65535
            or values[9] & 7 != 7):
        raise CaptureError('connection requires OUT, Status and matching successful outcome')
    return dict(zip(['generation','request','operation','state','error','fault','command_status','outcome_status','handle','flags'], values))


def link_reference(text, owner, peer, handle):
    headers=re.findall(r'^NativeLinksSnapshot: generation=(\d+) event_seq=(\d+) revision=(\d+) flags=(\d+) errno=(-?\d+)$',text,re.M)
    rows=re.findall(r'^NativeLink: lifetime=(\d+) handle=(\d+) role=(\d+) type=(\d+) address=([0-9A-F:]{17})$',text,re.M)
    if len(headers)!=1 or text.count('NativeLinksSnapshot:')!=1 or len(rows)!=text.count('NativeLink:'):
        raise CaptureError('one original canonical link snapshot required')
    generation,seq,revision,flags,error=map(int,headers[0])
    if generation!=owner['generation'] or flags!=1 or error or not revision or not seq or len(rows)!=1:
        raise CaptureError('one known current physical link required')
    lifetime,current,role,kind=map(int,rows[0][:4]);address=rows[0][4]
    if not lifetime or lifetime>revision or current!=handle or role>1 or kind!=0 or address!=peer['address']:
        raise CaptureError('canonical reference must match actual connected peer')
    return dict(lifetime=lifetime,handle=current,role=role,address_type=kind,address=address)


DOWN_OBSERVATION_BUDGET_SECONDS = 5


def await_down_properties(run, phase, caller, peer):
    """One original diagnostic deadline for both asynchronous physical ends.

    This is not a protocol/hardware latency guarantee. Capture corroboration
    must independently find each real Down before its false-property receipt.
    """
    started = time.time_ns()
    deadline = time.monotonic() + DOWN_OBSERVATION_BUDGET_SECONDS
    observation = dict(version=1, budget_seconds=DOWN_OBSERVATION_BUDGET_SECONDS,
                       start_wall_ns=started, receipts=[])
    phase['down_property_observation'] = observation
    run.save()
    for owner, remote in [(caller, peer), (peer, caller)]:
        while True:
            if time.monotonic() >= deadline:
                raise CaptureError('both real Down events must reach Device properties within shared budget')
            row = run.ctl(owner, 'info', remote['address'])
            if '  Connected: false\n' in row['stdout']:
                if time.monotonic() >= deadline:
                    raise CaptureError('Down property receipt exceeded original shared budget')
                observation['receipts'].append(dict(owner=owner, remote_address=remote['address'],
                                                     command=len(run.data['commands'])-1))
                run.save()
                break
            time.sleep(.01)
    observation['end_wall_ns'] = time.time_ns()
    run.save()


def corroborate_down_property(run, phase, owner, event):
    observation = phase.get('down_property_observation')
    if observation is None:
        return None  # historical format, not the new bounded sub-gate
    if (observation.get('version') != 1 or observation.get('budget_seconds') != 5
            or len(observation.get('receipts', [])) != 2):
        raise CaptureError('complete shared Down observation receipt required')
    start = observation['start_wall_ns']
    limit = start + DOWN_OBSERVATION_BUDGET_SECONDS * 1_000_000_000
    if not start <= observation.get('end_wall_ns', limit+1) <= limit:
        raise CaptureError('Down observation exceeded original deadline')
    receipts = [v for v in observation['receipts'] if v['owner'] == owner]
    if len(receipts) != 1:
        raise CaptureError('one exact Down property owner required')
    receipt = receipts[0]
    index = receipt['command']
    if type(index) is not int or not 0 <= index < len(run['commands']):
        raise CaptureError('Down property command index invalid')
    row = run['commands'][index]
    if (row['exit'] or row['args'][-2:] != ['info', receipt['remote_address']]
            or row['args'][-3] != owner['path']
            or '  Connected: false\n' not in row['stdout']
            or not start <= row['start_wall_ns'] <= row['end_wall_ns'] <= limit
            or event['wall_ns'] > row['end_wall_ns']):
        raise CaptureError('actual physical Down must precede bounded false-property receipt')
    return dict(command=index, physical_down_wall_ns=event['wall_ns'],
                property_end_wall_ns=row['end_wall_ns'], deadline_wall_ns=limit)


def execute(run, a, b):
    """Run once, before ordinary RF rounds, and retain every failed command."""
    kind = getattr(run.args, 'connection_advertising', 'fixed-t')
    if kind not in ['fixed-t','negotiable-t']: raise ValueError('explicit supported connection advertising posture required')
    record = dict(status='RUNNING', advertising_kind=kind, owners=[a,b], phases=[],
        peer_lifetime_binding='v2-admission-selection',connection_objects='generation-type-lifetime-v1',
        advertising_set_lifecycle='remove-recreate-v1',
        release_acceptance=False, last_file_acceptance=False, dup_acceptance=False,
        inflight_acceptance=False, ssap_acceptance=False,
        automatic_recovery_acceptance=False, start_wall_ns=time.time_ns())
    run.data['connection_control'] = record
    run.save()
    previous_objects=[]
    try:
        for caller, peer in [(a,b), (b,a)]:
            phase = dict(caller=caller, peer=peer, start_wall_ns=time.time_ns())
            record['phases'].append(phase); run.save()
            run.check(caller); run.check(peer)
            advertisement = run.ctl(peer, 'advertise', 'negotiable' if kind=='negotiable-t' else 'connectable')
            if not parse_result(advertisement['stdout'], peer, 1, allow_recreate=True)['recreated']:
                raise CaptureError('fresh beacon-to-connectable gate requires a recreated set')
            phase['advertisement_command'] = len(run.data['commands'])-1
            run.ctl(peer, 'show')
            phase['policy_query_command'] = len(run.data['commands'])-1
            markers = re.findall(r'^NativeAdvertisementAccepted: request=(\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+)$', advertisement['stdout'], re.M)
            if len(markers)!=1 or markers[0][2]!=marker_data(markers[0][1]).hex():
                raise CaptureError('original connectable random marker admission required')
            phase['marker']=markers[0][1]
            scan = run.ctl(caller, 'scan', 'on', phase['marker'], peer['address'])
            phase['scan_command']=len(run.data['commands'])-1
            parse_result(scan['stdout'],caller,3)
            match = parse_match(scan['stdout'])
            if (match['generation']!=caller['generation'] or match['address']!=peer['address']
                    or match['marker']!=phase['marker'] or match['data']!=markers[0][2]
                    or match['elapsed_ms']>=10000 or match['lost']):
                raise CaptureError('connectable announcement must first be heard by the actual caller')
            phase['scan_match']=match
            if getattr(run.args,'daemon_link_resync',False):
                from ws73_link_resync import execute as resync_execute
                resync_execute(run,caller,peer,len(record['phases'])-1)
            run.stop(caller, 'scan')
            phase['scan_stop_command']=len(run.data['commands'])-1
            # Type 0 is an explicit candidate, not inferred from discovery's
            # legacy fixed PUBLIC parser. Both raw connection events must
            # corroborate the actual type and peer below.
            phase['peer_address_type'] = 0
            command = run.command([str(run.args.slctl), '--adapter', caller['path'],
                'connect', peer['address'], '0'], 18, collection='commands')
            phase['connect_command'] = len(run.data['commands'])-1
            phase['connect'] = result(command['stdout'], caller, 1)
            if command['exit']: raise CaptureError('ordinary connect command failed')
            for owner, remote in [(caller,peer), (peer,caller)]:
                deadline = time.monotonic()+1
                while True:
                    row = run.ctl(owner, 'info', remote['address'])
                    if '  Connected: true\n' in row['stdout']: break
                    if time.monotonic() >= deadline:
                        raise CaptureError('both real physical connections must reach Device properties')
                    time.sleep(.01)
            row=run.ctl(caller,'connections')
            phase['links_command']=len(run.data['commands'])-1
            phase['reference']=link_reference(row['stdout'],caller,peer,phase['connect']['handle'])
            from ws73_connection_objects import observe, reject_old
            phase['typed_objects']=[observe(run,owner,remote) for owner,remote in [(caller,peer),(peer,caller)]]
            phase['stale_object_rejections']=[]
            for old in previous_objects:
                phase['stale_object_rejections'].append(reject_old(run,old,'while-reused-handle-live'));run.save()
            selected=next(entry['object'] for entry in phase['typed_objects'] if entry['owner']==caller)
            if any(selected[key]!=phase['reference'][key] for key in ['lifetime','handle','role','address_type','address']):raise CaptureError('object differs from original canonical reference')
            if getattr(run.args, 'channel_daemon_crash', False):
                run.connected_gate(phase)
                record.update(status='DAEMON_CHANNEL_CONNECTED_GATE_PENDING',end_wall_ns=time.time_ns())
                run.save()
                return
            if getattr(run.args, 'acb_transport_probe', False):
                from ws73_acb_transport_probe import execute as acb_execute
                acb_execute(run, phase)
            if getattr(run.args,'security_agent',None):
                from ws73_security_agent import execute as agent_execute
                agent_execute(run,phase)
            if hasattr(run, 'connection_barrier'):
                run.connection_barrier('linked',phase)
            if getattr(run.args, 'channel_socket_verify', False):
                from ws73_channel_socket import execute as channel_execute
                channel_execute(run, phase)
            if getattr(run.args,'channel_benchmark',None):
                from ws73_socket_benchmark import execute as benchmark_execute
                benchmark_execute(run,phase)
            if getattr(run.args,'channel_fairness_verify',False):
                from ws73_channel_fairness import execute as fairness_execute
                fairness_execute(run,phase)
            if getattr(run.args, 'dynamic_channel_verify', False):
                from ws73_dynamic_channels import execute as dynamic_execute
                dynamic_execute(run, phase)
            if hasattr(run, 'connection_barrier'):
                run.connection_barrier('business-done',phase)
            phase['disconnect_command'] = len(run.data['commands'])
            row = run.command([str(run.args.slctl), '--adapter', caller['path'],
                'disconnect-object',selected['path']], 18, collection='commands')
            phase['disconnect'] = result(row['stdout'], caller, 2)
            if row['exit'] or phase['disconnect']['handle'] != phase['connect']['handle']:
                raise CaptureError('exact established handle must disconnect')
            await_down_properties(run, phase, caller, peer)
            for entry in phase['typed_objects']:
                phase['stale_object_rejections'].append(reject_old(run,entry,'after-down'));run.save()
            previous_objects=phase['typed_objects']
            # Require the original advertisement's actual STOP. If firmware
            # has independently stopped it and rejects STOP, preserve that
            # failure; no local connected/disconnected state means radio OFF.
            run.stop(peer, 'advertise')
            run.check(caller); run.check(peer)
            if hasattr(run, 'connection_barrier'):
                run.connection_barrier('down',phase)
            phase['end_wall_ns'] = time.time_ns(); run.save()
        record['status'] = 'CONNECTION_CONTROL_EVIDENCE_PENDING'
    except BaseException as error:
        record.update(status='FAIL', error=str(error), error_type=type(error).__name__)
        raise
    finally:
        record['end_wall_ns'] = time.time_ns(); run.save()


def corroborate(run, capture, *, expected_disconnect_reason=0x10):
    # Current daemon requests exactly the SLE reason. Historical retained
    # corpora may explicitly audit their old 0x13 request; never infer the
    # expected byte from captured input or silently accept both in a live gate.
    if type(expected_disconnect_reason) is not int or expected_disconnect_reason not in (0x10,0x13):
        raise CaptureError('explicit current or historical disconnect reason required')
    record = run['connection_control']
    if record['status'] != 'CONNECTION_CONTROL_EVIDENCE_PENDING' or len(record['phases']) != 2:
        raise CaptureError('both original role-exchange connection phases required')
    kind = record.get('advertising_kind','fixed-t')
    if kind not in ['fixed-t','negotiable-t']: raise CaptureError('explicit recorded advertising posture required')
    proofs = []
    for phase in record['phases']:
        caller, peer = phase['caller'], phase['peer']
        reference=None
        if record.get('peer_lifetime_binding'):
            if record['peer_lifetime_binding']!='v2-admission-selection':raise CaptureError('explicit reference binding scope required')
            links=run['commands'][phase['links_command']]
            reference=link_reference(links['stdout'],caller,peer,phase['connect']['handle'])
            disconnect=run['commands'][phase['disconnect_command']]
            if record.get('connection_objects'):
                if links['exit'] or links['args'][-1]!='connections' or reference!=phase['reference'] or not run['commands'][phase['connect_command']]['end_wall_ns']<=links['start_wall_ns']<=links['end_wall_ns']<=disconnect['start_wall_ns']:
                    raise CaptureError('original canonical snapshot must precede object Disconnect')
            else:
                expected=['disconnect-link',reference['address'],str(reference['address_type']),str(reference['handle']),str(reference['lifetime']),str(reference['role'])]
                if (links['exit'] or links['args'][-1]!='connections' or reference!=phase['reference']
                        or disconnect['args'][-6:]!=expected
                        or not run['commands'][phase['connect_command']]['end_wall_ns']<=links['start_wall_ns']<=links['end_wall_ns']<=disconnect['start_wall_ns']):
                    raise CaptureError('original canonical snapshot must precede exact bound Disconnect')
                receipts=re.findall(r'^NativeDisconnectReference: request=(\d+) address=([0-9A-F:]{17}) type=(\d+) handle=(\d+) lifetime=(\d+) role=(\d+)$',disconnect['stdout'],re.M)
                if receipts!=[(str(phase['disconnect']['request']),reference['address'],str(reference['address_type']),str(reference['handle']),str(reference['lifetime']),str(reference['role']))]:
                    raise CaptureError('original public Disconnect reference receipt required')
        advertisement = run['commands'][phase['advertisement_command']]
        query = run['commands'][phase['policy_query_command']]
        policies = re.findall(r'^  Radio policy: version=(\d+) adv_slots=(\d+)\.\.(\d+) tx_power_dbm=(-?\d+) scan_slots=(\d+)/(\d+)$', query['stdout'], re.M)
        if (advertisement['exit'] or advertisement['args'][-2:] != ['advertise','negotiable' if kind=='negotiable-t' else 'connectable']
                or query['exit'] or query['args'][-1] != 'show' or len(policies)!=1
                or int(policies[0][0])!=3):
            raise CaptureError('explicit connectable request and policy readback required')
        _, minimum, maximum, power, _, _ = map(int,policies[0])
        expected=bytearray(49)
        expected[1]=1; expected[2]=2; expected[3:6]=minimum.to_bytes(3,'little')
        expected[6:9]=maximum.to_bytes(3,'little'); expected[9]=7
        expected[12:18]=bytes.fromhex(peer['address'].replace(':',''))
        expected[25]=power&255; expected[33]=1; expected[43:45]=(200).to_bytes(2,'little')
        if kind=='negotiable-t':
            expected[1]=3;expected[2]=0;expected[33]=0;expected[34]=1
            expected[37:39]=(100).to_bytes(2,'little');expected[39:41]=expected[37:39]
        advertisement_proof=command_reply(capture,peer,0x0c02,advertisement['start_wall_ns'],advertisement['end_wall_ns'],bytes(expected))
        if record.get('advertising_set_lifecycle') == 'remove-recreate-v1':
            parsed = parse_result(advertisement['stdout'],peer,1,allow_recreate=True)
            if not parsed['recreated']:
                raise CaptureError('current gate requires actual recreated advertisement result')
            removed = command_reply(capture,peer,0x0c08,advertisement['start_wall_ns'],advertisement['end_wall_ns'],bytes(1),'')
            if removed['reply']['wall_ns'] > advertisement_proof['command']['wall_ns']:
                raise CaptureError('recreation parameter preceded real removal Complete')
            configured_data = command_reply(capture,peer,0x0c03,advertisement['start_wall_ns'],advertisement['end_wall_ns'],
                bytes([0,3,len(marker_data(phase['marker']))])+marker_data(phase['marker']), '')
            enabled = command_reply(capture,peer,0x0c05,advertisement['start_wall_ns'],advertisement['end_wall_ns'],b'\x01\0\0\0\0','')
            if (advertisement_proof['reply']['wall_ns'] > configured_data['command']['wall_ns']
                    or configured_data['reply']['wall_ns'] > enabled['command']['wall_ns']
                    or advertisement_proof['reply']['value'] != bytes([parsed['selected_power'] & 255]).hex()):
                raise CaptureError('recreated data/enable order or actual selected power mismatch')
            advertisement_proof['preceding_removal'] = removed
            advertisement_proof['configured_data'] = configured_data
            advertisement_proof['enabled'] = enabled
        scan = run['commands'][phase['scan_command']]
        parse_result(scan['stdout'],caller,3)
        match = parse_match(scan['stdout'])
        if match!=phase['scan_match'] or scan['exit']:
            raise CaptureError('original fresh connectable scan match required')
        heard=[e for e in capture['reports'] if (e['bus'],e['device'])==(caller['bus'],caller['device'])
            and scan['start_wall_ns']<=e['wall_ns']<=scan['end_wall_ns']
            and e['address']==peer['address'] and e['data']==marker_data(phase['marker']).hex()
            and e['rssi']==match['rssi']]
        if not heard: raise CaptureError('connectable peer must be independently heard in captured RX')
        stop = run['commands'][phase['scan_stop_command']]
        if stop['exit']: raise CaptureError('actual scanner must stop before Create')
        parse_result(stop['stdout'],caller,4)
        stop_proof=command_reply(capture,caller,0x1002,stop['start_wall_ns'],stop['end_wall_ns'],bytes(2),'')
        steps = []
        handles = {}
        for operation, opcode, key, event_ids in [(1,0x1401,'connect',{0x15,0x1401}), (2,0x1403,'disconnect',{5,0x1405})]:
            command_row = run['commands'][phase[key+'_command']]
            terminal = result(command_row['stdout'], caller, operation)
            if command_row['exit'] or terminal != phase[key]:
                raise CaptureError('serialized terminal disagrees with original command')
            start, end = command_row['start_wall_ns'], command_row['end_wall_ns']
            def within(row, owner):
                return (row['bus'],row['device']) == (owner['bus'],owner['device']) and start <= row['wall_ns'] <= end
            commands = [c for c in capture['commands'] if within(c,caller) and c['opcode']==opcode]
            statuses = [e for e in capture['native_events'] if within(e,caller) and e['event']==1
                and len(bytes.fromhex(e['params']))==4 and int.from_bytes(bytes.fromhex(e['params'])[:2],'little')==opcode]
            if (len(commands)!=1 or len(statuses)!=1 or bytes.fromhex(statuses[0]['params'])[3]
                    or not start<=commands[0]['completion']['wall_ns']<=end
                    or statuses[0]['wall_ns']<commands[0]['wall_ns']):
                raise CaptureError('one real paired OUT and successful CommandStatus required')
            if operation==1:
                body=bytes.fromhex(commands[0]['params'])
                if len(body)!=27 or body[2]!=phase['peer_address_type'] or body[3:9]!=bytes.fromhex(peer['address'].replace(':','')):
                    raise CaptureError('Create body must target actual peer/type')
            elif commands[0]['params'] != (terminal['handle'].to_bytes(2,'little')+bytes([expected_disconnect_reason])).hex():
                raise CaptureError('Disconnect body must target exact handle/reason')
            outcomes=[]
            # Peer publication may follow the caller's terminal slightly; use
            # the phase's bounded observations, without borrowing another phase.
            for owner, remote in [(caller,peer), (peer,caller)]:
                events=[e for e in capture['native_events'] if e['event'] in event_ids
                    and (e['bus'],e['device'])==(owner['bus'],owner['device'])
                    and start<=e['wall_ns']<=phase['end_wall_ns']]
                if len(events)!=1: raise CaptureError('one matching raw physical outcome on each controller required')
                if operation == 2:
                    corroborate_down_property(run, phase, owner, events[0])
                body=bytes.fromhex(events[0]['params'])
                if len(body)<(11 if operation==1 else 4) or body[0]:
                    raise CaptureError('successful bounded physical outcome required')
                if owner==caller and int.from_bytes(body[1:3],'little')!=terminal['handle']:
                    raise CaptureError('caller outcome handle disagrees with result')
                if operation==1 and (body[3]>1 or body[4]!=0 or body[5:11]!=bytes.fromhex(remote['address'].replace(':',''))):
                    raise CaptureError('raw physical peer/role/type mismatch')
                if operation==1 and owner==caller and reference is not None and (body[3]!=reference['role'] or body[4]!=reference['address_type']):
                    raise CaptureError('canonical reference must match actual physical Up role/type')
                identity=(owner['bus'],owner['device'])
                handle=int.from_bytes(body[1:3],'little')
                if operation==1: handles[identity]=handle
                elif handles.get(identity)!=handle:
                    raise CaptureError('peer Down must match its independently observed Up handle')
                outcomes.append(events[0])
            steps.append(dict(command=commands[0], status=statuses[0], outcomes=outcomes, terminal=terminal))
        proofs.append(dict(caller=caller, peer=peer, advertisement=advertisement_proof,
            connectable_rx=heard, scan_stop=stop_proof, steps=steps))
    return proofs
