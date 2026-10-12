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


def execute(run, a, b):
    """Run once, before ordinary RF rounds, and retain every failed command."""
    record = dict(status='RUNNING', owners=[a,b], phases=[],
        release_acceptance=False, last_file_acceptance=False, dup_acceptance=False,
        inflight_acceptance=False, ssap_acceptance=False,
        automatic_recovery_acceptance=False, start_wall_ns=time.time_ns())
    run.data['connection_control'] = record
    run.save()
    try:
        for caller, peer in [(a,b), (b,a)]:
            phase = dict(caller=caller, peer=peer, start_wall_ns=time.time_ns())
            record['phases'].append(phase); run.save()
            run.check(caller); run.check(peer)
            advertisement = run.ctl(peer, 'advertise', 'connectable')
            parse_result(advertisement['stdout'], peer, 1)
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
            phase['disconnect_command'] = len(run.data['commands'])
            row = run.command([str(run.args.slctl), '--adapter', caller['path'],
                'disconnect', peer['address']], 18, collection='commands')
            phase['disconnect'] = result(row['stdout'], caller, 2)
            if row['exit'] or phase['disconnect']['handle'] != phase['connect']['handle']:
                raise CaptureError('exact established handle must disconnect')
            for owner, remote in [(caller,peer), (peer,caller)]:
                deadline = time.monotonic()+1
                while True:
                    row = run.ctl(owner, 'info', remote['address'])
                    if '  Connected: false\n' in row['stdout']: break
                    if time.monotonic() >= deadline:
                        raise CaptureError('both real Down events must reach Device properties')
                    time.sleep(.01)
            # Require the original advertisement's actual STOP. If firmware
            # has independently stopped it and rejects STOP, preserve that
            # failure; no local connected/disconnected state means radio OFF.
            run.stop(peer, 'advertise')
            run.check(caller); run.check(peer)
            phase['end_wall_ns'] = time.time_ns(); run.save()
        record['status'] = 'CONNECTION_CONTROL_EVIDENCE_PENDING'
    except BaseException as error:
        record.update(status='FAIL', error=str(error), error_type=type(error).__name__)
        raise
    finally:
        record['end_wall_ns'] = time.time_ns(); run.save()


def corroborate(run, capture):
    record = run['connection_control']
    if record['status'] != 'CONNECTION_CONTROL_EVIDENCE_PENDING' or len(record['phases']) != 2:
        raise CaptureError('both original role-exchange connection phases required')
    proofs = []
    for phase in record['phases']:
        caller, peer = phase['caller'], phase['peer']
        advertisement = run['commands'][phase['advertisement_command']]
        query = run['commands'][phase['policy_query_command']]
        policies = re.findall(r'^  Radio policy: version=(\d+) adv_slots=(\d+)\.\.(\d+) tx_power_dbm=(-?\d+) scan_slots=(\d+)/(\d+)$', query['stdout'], re.M)
        if (advertisement['exit'] or advertisement['args'][-2:] != ['advertise','connectable']
                or query['exit'] or query['args'][-1] != 'show' or len(policies)!=1
                or int(policies[0][0])!=3):
            raise CaptureError('explicit connectable request and policy readback required')
        _, minimum, maximum, power, _, _ = map(int,policies[0])
        expected=bytearray(49)
        expected[1]=1; expected[2]=2; expected[3:6]=minimum.to_bytes(3,'little')
        expected[6:9]=maximum.to_bytes(3,'little'); expected[9]=7
        expected[12:18]=bytes.fromhex(peer['address'].replace(':',''))
        expected[25]=power&255; expected[33]=1; expected[43:45]=(200).to_bytes(2,'little')
        advertisement_proof=command_reply(capture,peer,0x0c02,advertisement['start_wall_ns'],advertisement['end_wall_ns'],bytes(expected))
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
            elif commands[0]['params'] != (terminal['handle'].to_bytes(2,'little')+b'\x13').hex():
                raise CaptureError('Disconnect body must target exact handle/reason')
            outcomes=[]
            # Peer publication may follow the caller's terminal slightly; use
            # the phase's bounded observations, without borrowing another phase.
            for owner, remote in [(caller,peer), (peer,caller)]:
                events=[e for e in capture['native_events'] if e['event'] in event_ids
                    and (e['bus'],e['device'])==(owner['bus'],owner['device'])
                    and start<=e['wall_ns']<=phase['end_wall_ns']]
                if len(events)!=1: raise CaptureError('one matching raw physical outcome on each controller required')
                body=bytes.fromhex(events[0]['params'])
                if len(body)<(11 if operation==1 else 4) or body[0]:
                    raise CaptureError('successful bounded physical outcome required')
                if owner==caller and int.from_bytes(body[1:3],'little')!=terminal['handle']:
                    raise CaptureError('caller outcome handle disagrees with result')
                if operation==1 and (body[3]>1 or body[4]!=0 or body[5:11]!=bytes.fromhex(remote['address'].replace(':',''))):
                    raise CaptureError('raw physical peer/role/type mismatch')
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
