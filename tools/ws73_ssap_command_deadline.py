# SPDX-License-Identifier: GPL-2.0-only
"""Original command authorization deadline, through existing SDK/Owner paths.

One case per connection role, after all positive and explicit-policy cases.
The timeout retires the receiving SSAP actor, not the physical Session. Ordinary
application replies must still complete. Only phase 0 has a subsequent new
lifetime positive witness in this two-phase gate. No automatic recovery claim.
"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

import ws73_ssap_command as base
import ws73_ssap_command_policy as policy
from ws73_capture import CaptureError, packet_interval
from ws73_ssap_owned import (publisher, value_snapshot, wait_text, wait_output,
                             output_text, verify_output, await_removed)
from ws73_ssap_value import pair_wire, valid_wire, physical_sends, command_packet

VERSION = 1
PREFIX = 'ssap_command_deadline'
TOKEN = 'ws73.ssap_command_deadline=1'
COLLECTION = PREFIX + '_publishers'
STATUS = 'COMMAND_DEADLINE_TERMINAL_AND_BUSINESS_PENDING_CAPTURE'
PROOF = 'COMMAND_ORIGINAL_DEADLINE_AND_ORDINARY_BUSINESS'
ERRORS = ('original SSAP authorization deadline', 'original SSAP obligation deadline')
need = policy.need


def requested(args, *, passthrough=None):
    selected = getattr(args, 'ssap_write_command_deadline_verify', False)
    need(type(selected) is bool, 'typed explicit command deadline selector required')
    if selected:
        need(policy.requested(args, passthrough=passthrough), 'command deadline requires original policy and positive gates')
    return selected


def boot_requested(tokens):
    need(isinstance(tokens, (list, tuple)) and all(type(t) is str for t in tokens), 'tokenized boot arguments required')
    found = [t for t in tokens if t == TOKEN.split('=')[0] or t.startswith(TOKEN.split('=')[0]+'=')]
    need(found in ([], [TOKEN]), 'one exact command deadline boot version required')
    if found:
        need(policy.boot_requested(tokens), 'command deadline requires original policy boot gate')
    return bool(found)


def validate_rows(rows, selected):
    need(type(selected) is bool and isinstance(rows, list), 'typed command deadline request and rows required')
    if selected:
        policy.validate_rows(rows, True)
    for phase, row in enumerate(rows):
        need(type(row.get(PREFIX+'_required', False)) is bool
             and row.get(PREFIX+'_required', False) == selected, 'deadline request/row mismatch')
        if selected:
            need(row['phase'] == phase and type(row.get(PREFIX+'_contract')) is int
                 and row[PREFIX+'_contract'] == VERSION and len(row.get(COLLECTION, [])) == 1
                 and isinstance(row.get(PREFIX+'_case'), dict), 'one original deadline case per phase required')
        else:
            need(not any(k.startswith(PREFIX) and k != PREFIX+'_required' for k in row), 'unrequested deadline evidence')


def validate_inputs(package):
    policy.validate_inputs(package)
    here = Path(__file__).resolve()
    entries = [r for r in package.get('inputs', []) if Path(r['path']).resolve() == here]
    need(len(entries) == 1 and entries[0]['sha256'] == hashlib.sha256(here.read_bytes()).hexdigest(),
         'exact command deadline guest source required')


def info_arguments(program, entry):
    return [program, '--adapter', entry['owner']['path'], 'ssap-info', entry['object']['path']]


def terminal_receipt(receipt, program, entry):
    need(receipt['args'] == info_arguments(program, entry) and type(receipt['exit']) is int
         and receipt['exit'] != 0 and receipt['stdout'].splitlines() == [f"Selected {entry['owner']['path']}"],
         'actual original connection GetSsapInfo refusal required')
    matches = [message for message in ERRORS if message in receipt['stderr']]
    need('org.freedesktop.DBus.Error.Failed' in receipt['stderr'] and len(matches) == 1,
         'actual actor deadline Failed required, not arbitrary RPC/permission/transport failure')
    need(receipt['start_monotonic_ns'] <= receipt['end_monotonic_ns']
         <= receipt['start_monotonic_ns'] + 2_000_000_000, 'bounded original observation call required')
    return matches[0]


def healthy_receipt(receipt, original):
    need(receipt['args'] == original['args'] and receipt['exit'] == 0 and not receipt['stderr']
         and receipt['stdout'] == original['stdout'], 'same source Engine and exact negotiated identity required')


def execute(run, row, business):
    need(callable(business) and base.negotiated(row) == 2042 and row.get('security_requirement', 0) == 0,
         'existing basic Engine and ordinary application runner required')
    # Connection control swaps caller/peer, so the caller is index 0 in both phases.
    sender = 0; api = base.APIS[row['phase']]
    source, target = row['owners'][sender], row['owners'][1-sender]
    row.update(ssap_command_deadline_required=True, ssap_command_deadline_contract=VERSION,
               ssap_command_deadline_publishers=[], ssap_command_deadline_tools=base.tool_records())
    with publisher(run, row, sender, 'ask', collection=COLLECTION,
                   label='command-original-deadline', operations=3) as (process, owner):
        owner['api'] = api
        case = dict(sequence=row['phase'], sender=sender, target=1-sender, api=api, handle=owner['handle'],
                    value=(row['phase'].to_bytes(4, 'little')+secrets.token_bytes(28)).hex(), start_wall_ns=time.time_ns(), status='RUNNING')
        row[PREFIX+'_case'] = case; run.save()
        case['local_before'] = value_snapshot(process, owner, owner['secret'])
        base.execute_command(run, row, case, source, label='command-original-deadline')
        matches, _ = wait_text(process, Path(owner['output_files'][0]), policy.PROMPT,
                               time.monotonic()+2, max_count=1)
        need(len(matches) == 1, 'one original Write Command authorization prompt required')
        prompt = policy.parse_prompt(matches[0])
        policy.check_prompt(prompt, target, owner['handle'], True, 32, 1)
        case['prompt'] = dict(fields=prompt, wall_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())
        need(0 < prompt['deadline_ns']-case['prompt']['monotonic_ns'] <= 5_000_000_000,
             'live original server deadline required')
        run.save()
        # Drain bounded child output while waiting for the original protocol
        # deadline. This is not a replacement/renewal of that deadline.
        while time.monotonic_ns() < prompt['deadline_ns']:
            output_text(process, Path(owner['output_files'][0]))
            need(process.poll() is None, 'Owner exited before original deadline')
            time.sleep(max(0, min(.02, (prompt['deadline_ns']-time.monotonic_ns())/1e9)))
        # Native/actor termination must be observed, not inferred from sleep.
        # Transient failures remain evidence but do not count as a terminal.
        observation = time.monotonic_ns()+2_000_000_000
        case['terminal_observation_deadline_ns'] = observation
        case['terminal_attempts'] = []
        for _ in range(16):
            budget = (observation-time.monotonic_ns())/1e9
            need(budget > 0, 'original terminal observation budget expired')
            receipt = run.command(info_arguments(str(run.args.slctl), target), budget,
                                  collection=PREFIX+'_observations')
            case['terminal_attempts'].append(receipt); run.save()
            try:
                case['terminal'] = terminal_receipt(receipt, str(run.args.slctl), target)
                break
            except CaptureError:
                need(receipt['exit'] != 0 and 'SsapExchangeInfo:' not in receipt['stdout'],
                     'receiver remained negotiated after original command deadline')
                time.sleep(.02)
        else:
            raise CaptureError('finite original terminal observation count exhausted')
        case['late_input'] = dict(text='yes 1', wall_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())
        process.stdin.write('yes 1\n'); process.stdin.flush()
        case['local_after_late'] = value_snapshot(process, owner, owner['secret'])
        case['source_info'] = run.command(info_arguments(str(run.args.slctl), source), 2,
                                          collection=PREFIX+'_observations')
        healthy_receipt(case['source_info'], row['ssap_receipts'][sender])
        case['business_window'] = dict(start_wall_ns=time.time_ns(), start_monotonic_ns=time.monotonic_ns())
        run.save()
        # Independent supervisor budget, never an extension of expired SSAP.
        business(time.monotonic()+30)
        case['business_window'].update(end_wall_ns=time.time_ns(), end_monotonic_ns=time.monotonic_ns())
        case['terminal_after_business'] = run.command(info_arguments(str(run.args.slctl), target), 2,
                                                       collection=PREFIX+'_observations')
        need(terminal_receipt(case['terminal_after_business'], str(run.args.slctl), target) == case['terminal'],
             'same actor must retain the original terminal after business')
        case['local_after_business'] = value_snapshot(process, owner, owner['secret'])
        case.update(end_wall_ns=time.time_ns(), status=STATUS); run.save()
        process.stdin.write('quit\n'); process.stdin.flush()
        need(wait_output(process, 5) == 0, 'original Owner must withdraw cleanly')
        owner['removal'] = await_removed(run, target, owner['start']); run.save()


def case_contract(row, case, owner):
    sender = 0; source, target = row['owners'][sender], row['owners'][1-sender]
    program = owner['args'][0]; prompt = case['prompt']; p = prompt['fields']; handle = owner['handle']
    need(case['status'] == STATUS and type(case['sender']) is int and case['sender'] == sender
         and case['target'] == 1-sender and case['api'] == owner['api'] == base.APIS[row['phase']]
         and type(case['sequence']) is int and case['sequence'] == row['phase']
         and case['handle'] == handle and owner['sender'] == sender and owner['target'] == 1-sender,
         'original finite role/API/Owner mapping required')
    verify_output(owner); base.ordinary(owner)
    need(owner['args'] == [program, '--adapter', target['owner']['path'], 'ssap-serve', owner['service'], owner['uuid'],
                          '3', '36', owner['secret'], 'ask'] and owner['operations'] == 3
         and owner['policy'] == 'ask' and owner['exit'] == 0 and not owner['stderr']
         and 0 < owner['start'] <= handle <= owner['end'] <= 65535, 'original live command ask Owner required')
    need(len(bytes.fromhex(case['value'])) == len(bytes.fromhex(owner['secret'])) == 32
         and case['value'] != owner['secret']
         and int.from_bytes(bytes.fromhex(case['value'])[:4], 'little') == case['sequence'], 'distinct actual 32-byte random command required')
    base.admission(case['command'], source, handle, case['value'])
    policy.check_prompt(p, target, handle, True, 32, 1)
    need([policy.parse_prompt(m) for m in re.findall(policy.PROMPT, owner['stdout'], re.M)] == [p],
         'exact single retained original prompt required')
    decisions = re.findall(policy.DECISION, owner['stdout'], re.M)
    need(decisions in ([], [(str(p['request']), str(handle), 'true', 'false')])
         and 'approved=true' not in owner['stdout'], 'no late or manufactured approval allowed')
    need(owner['stdout'].splitlines().count(f'SsapOwnedService: start={owner["start"]} end={owner["end"]} property={handle}; local registration only') == 1,
         'one original registration required')
    attempts = case['terminal_attempts']; late = case['late_input']; window = case['business_window']
    need(isinstance(attempts, list) and 1 <= len(attempts) <= 16
         and case['terminal_observation_deadline_ns'] <= p['deadline_ns']+3_000_000_000,
         'finite original post-deadline observation budget required')
    previous = p['deadline_ns']
    for receipt in attempts:
        need(receipt['args'] == info_arguments(program, target) and receipt['exit'] != 0
             and 'SsapExchangeInfo:' not in receipt['stdout']
             and previous <= receipt['start_monotonic_ns'] <= receipt['end_monotonic_ns']
             <= case['terminal_observation_deadline_ns'], 'original bounded terminal attempts required')
        previous = receipt['end_monotonic_ns']
    need(terminal_receipt(attempts[-1], program, target) == case['terminal']
         == terminal_receipt(case['terminal_after_business'], program, target), 'persistent exact actor terminal required')
    healthy_receipt(case['source_info'], row['ssap_receipts'][sender])
    need(case['command']['start_wall_ns'] <= prompt['wall_ns']
         and prompt['monotonic_ns'] < p['deadline_ns'] <= prompt['monotonic_ns']+5_000_000_000
         and previous <= late['monotonic_ns'] and late['text'] == 'yes 1',
         'original prompt and approval only after actual terminal required')
    snapshots = [case['local_before'], case['local_after_late'], case['local_after_business']]
    need(owner['value_snapshots'] == snapshots
         and re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]*)$', owner['stdout'], re.M)
         == [(str(handle), owner['secret'])]*3, 'three exact original Owner values required')
    for i, snapshot in enumerate(snapshots, 1):
        need(snapshot['handle'] == handle and snapshot['value'] == owner['secret'] and snapshot['ordinal'] == i
             and snapshot['start_wall_ns'] <= snapshot['end_wall_ns'], 'unchanged actual Owner value required')
    need(row['start_wall_ns'] <= owner['start_wall_ns'] <= case['start_wall_ns']
         <= snapshots[0]['start_wall_ns'] <= snapshots[0]['end_wall_ns'] <= case['command']['start_wall_ns']
         <= case['command']['end_wall_ns'] <= prompt['wall_ns'] <= attempts[0]['start_wall_ns']
         <= attempts[-1]['end_wall_ns'] <= late['wall_ns'] <= snapshots[1]['start_wall_ns']
         <= snapshots[1]['end_wall_ns'] <= case['source_info']['start_wall_ns'] <= case['source_info']['end_wall_ns']
         <= window['start_wall_ns'] <= window['end_wall_ns'] <= case['terminal_after_business']['start_wall_ns']
         <= case['terminal_after_business']['end_wall_ns'] <= snapshots[2]['start_wall_ns'] <= snapshots[2]['end_wall_ns']
         <= case['end_wall_ns'] <= owner['end_wall_ns'] <= row['end_wall_ns'], 'original event ordering required')
    need(late['monotonic_ns'] <= snapshots[1]['start_monotonic_ns'] <= window['start_monotonic_ns']
         <= window['end_monotonic_ns'] <= window['start_monotonic_ns']+31_000_000_000,
         'independent finite ordinary business budget required')
    apps = row['applications']
    need(len(apps) == 2 and all(app['exit'] == 0 and window['start_wall_ns'] <= app['start_wall_ns']
         <= app['end_wall_ns'] <= window['end_wall_ns'] for app in apps),
         'both actual ordinary applications must complete after receiver terminal')
    removal = owner['removal']; lists = re.findall(r'^SsapLocalServices: (.+)$', removal['stdout'], re.M)
    need(removal['exit'] == 0 and not removal['stderr'] and len(lists) == 1
         and case['end_wall_ns'] <= removal['start_wall_ns'] <= removal['end_wall_ns'] <= owner['end_wall_ns']
         and not any(v[0] == owner['start'] for v in json.loads(lists[0])), 'original Owned withdrawal required')
    return b'\x0c\x03'+handle.to_bytes(2, 'little')+b'\0'+bytes.fromhex(case['value'])


def verify_wire(row, case, pdu, wire, inventory):
    need(valid_wire(wire) and wire['expected_pdu'] == pdu.hex()
         and wire['capture_window'] == {k:case[k] for k in ('start_wall_ns','end_wall_ns')},
         'complete paired original command required')
    for side, index, direction in (('tx', case['sender'], 'out'), ('rx', case['target'], 'in')):
        identity = base._identity(row['owners'][index]); packet = wire[side]
        need('ssap_fragments' not in packet, 'short command only')
        for fragment in [packet, *packet['fragments']]:
            need(tuple(fragment[k] for k in ('bus','device','handle','direction')) ==
                 (identity['bus'],identity['device'],identity['handle'],direction), 'original fragment identity required')
        need(packet_interval(wire[side])[1] <= case['prompt']['wall_ns'], 'whole command must arrive before actual prompt')
    need(sorted(inventory,key=policy.packet_key) == sorted([wire['tx'],wire['rx']],key=policy.packet_key),
         'complete two-ended window: no response, duplicate, late commit or renegotiation')


def verify_business(row, case, legs):
    """Recheck original application transcripts against the parent's USB legs.

    Reuses the existing random message/peer reply parser; there is no second
    application protocol here. Retained summaries must keep the same evidence.
    """
    from ws73_channel_socket import application_frames, message_security_receipts, send_constraint_receipts
    need(row['rounds'] == 4 and row['message_bytes'] == 61
         and row['channel_info_required'] is True and row['tx_status_required'] is True
         and row['message_security_required'] is True and row['security_requirement'] == 0
         and row['tx_constraint_required'] is True
         and row['dtap_limits_version'] == 1 and row['cmtc_local_capability'] == dict(mtu=2042,mps=2047)
         and row.get('start_barrier', False) is False and not row.get('ports')
         and not any(row.get(k, False) for k in ('boundary_check','close_prefix','burst')),
         'original fixed ordinary four-round 61-byte application gate required')
    sent, replies = application_frames(row)
    message_security_receipts(row)
    send_constraint_receipts(row)
    need(len(legs) == 8, 'all four paired ordinary round trips required')
    window = case['business_window']; previous = None
    for i, leg in enumerate(legs):
        sequence, sender = i//2, i%2
        payload = (sent if sender == 0 else replies)[sequence]
        frame = b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
        need(type(leg['sequence']) is int and leg['sequence'] == sequence, 'ordered actual ordinary sequence required')
        for side, index, direction in (('tx',sender,'out'),('rx',1-sender,'in')):
            packet = leg[side]; identity = base._identity(row['owners'][index])
            need(packet['data'] == frame.hex(), 'ordinary wire must match actual peer-validated bytes')
            command_packet(packet, frame, window)
            for fragment in [packet,*packet['fragments']]:
                need(tuple(fragment[k] for k in ('bus','device','handle','direction')) ==
                     (identity['bus'],identity['device'],identity['handle'],direction),
                     'ordinary fragments must retain original physical identity')
        need(packet_interval(leg['tx'])[1] <= packet_interval(leg['rx'])[0], 'ordinary TX then complete peer RX required')
        if previous is not None:
            need(packet_interval(previous['rx'])[1] <= packet_interval(leg['tx'])[0],
                 'ordinary request/reply and next request retain causal order')
        previous = leg


def corroborate(row, matched, sdus):
    if not row.get(PREFIX+'_required', False):
        need(not any(k.startswith(PREFIX) and k != PREFIX+'_required' for k in row), 'unrequested deadline data')
        return [], {0:0,1:0}
    need(type(row.get(PREFIX+'_contract')) is int and row[PREFIX+'_contract'] == VERSION
         and base.negotiated(row) == 2042 and len(row[COLLECTION]) == 1, 'original deadline contract required')
    case = row[PREFIX+'_case']; owner = row[COLLECTION][0]
    pdu = case_contract(row, case, owner); inventory = policy.window_packets(row, case, sdus)
    wire = pair_wire(row, matched, row['owners'][case['sender']], row['owners'][case['target']], pdu, case)
    verify_wire(row, case, pdu, wire, inventory)
    credit = {0:0,1:0}; credit[case['sender']] = physical_sends(wire['tx'])
    return [dict(status=PROOF, contract=VERSION, phase=row['phase'], case=case, publisher=owner,
                 wire=wire, window_packets=inventory, source_info_original=row['ssap_receipts'][case['sender']],
                 applications=row['applications'], application_tool=row['application_tool'],
                 bounded_absence_only=True, automatic_recovery_qualification=False)], credit


def verify_new_lifetime(first, second):
    need(first[PREFIX][0]['case']['end_wall_ns'] < packet_interval(second['ssap_write_commands'][0]['wire'][0]['tx'])[0],
         'new-lifetime positive commands must follow original terminal')
    # The existing connection gate reverses caller/peer when roles exchange.
    # Controller identity, not its position in that array, owns the lifetime.
    def endpoints(row):
        values = row['owners']
        result = {(e['owner']['index'],e['owner']['generation']):e for e in values}
        need(len(values) == len(result) == 2, 'two distinct original controllers required')
        return result
    old, new = endpoints(first), endpoints(second)
    need(old.keys() == new.keys(), 'new physical lifetime on the same controllers required')
    for key in old:
        need(old[key]['object']['lifetime'] != new[key]['object']['lifetime'],
             'actual new physical lifetime required')



def verify_deadline_receivers(first, second):
    receivers = []
    for row in (first, second):
        case = row[PREFIX][0]['case']
        owner = row['owners'][case['target']]['owner']
        receivers.append((owner['index'], owner['generation']))
    need(receivers[0] != receivers[1], 'each physical controller must receive one expired command')


def valid_summary(summary):
    try:
        need(policy.valid_summary(summary), 'original positive/policy paired evidence required')
        for phase, row in enumerate(summary['proofs']):
            proof, = row[PREFIX]
            need(proof['status'] == PROOF and type(proof['contract']) is int and proof['contract'] == VERSION
                 and type(proof['phase']) is int and proof['phase'] == phase
                 and proof['bounded_absence_only'] is True and proof['automatic_recovery_qualification'] is False,
                 'exact scoped deadline proof required')
            case, owner = proof['case'], proof['publisher']
            receipts = [None, None]; receipts[case['sender']] = proof['source_info_original']
            context = dict(phase=phase, owners=row['owners'], ssap_receipts=receipts,
                applications=proof['applications'], application_tool=proof['application_tool'],
                rounds=4, message_bytes=61, channel_info_required=True, tx_status_required=True,
                message_security_required=True, tx_constraint_required=True, security_requirement=0, dtap_limits_version=1,
                cmtc_local_capability=dict(mtu=2042,mps=2047),
                start_wall_ns=owner['start_wall_ns'], end_wall_ns=owner['end_wall_ns'])
            pdu = case_contract(context, case, owner)
            verify_wire(context, case, pdu, proof['wire'], proof['window_packets'])
            verify_business(context, case, row['legs'])
        verify_new_lifetime(*summary['proofs'])
        verify_deadline_receivers(*summary['proofs'])
        return True
    except (AttributeError, KeyError, ValueError, TypeError, IndexError, CaptureError):
        return False


def valid_manifest(record):
    try:
        selected = record.get(PREFIX+'_requested', False)
        need(type(selected) is bool, 'typed deadline manifest request required')
        args = record.get('qemu_args', [])
        need(isinstance(args,list) and all(type(x) is str for x in args)
             and boot_requested([t for arg in args for t in arg.split()]) == selected, 'deadline boot/manifest mismatch')
        if not selected:
            return (record.get(PREFIX+'_acceptance', False) is False
                and not any(k.startswith(PREFIX) and k not in (PREFIX+'_requested',PREFIX+'_acceptance') for k in record)
                and not any(PREFIX in row for row in record.get('channel_socket_corroboration',{}).get('proofs',[])))
        verifier = record.get(PREFIX+'_verifier')
        need(isinstance(verifier,dict) and set(verifier) >= {'path','sha256'}
             and Path(verifier['path']).name == 'ws73_ssap_command_deadline.py'
             and re.fullmatch('[0-9a-f]{64}',verifier['sha256']), 'retained deadline verifier required')
        return (policy.valid_manifest(record) and record.get(PREFIX+'_acceptance') is True
            and type(record.get(PREFIX+'_contract_version')) is int and record[PREFIX+'_contract_version'] == VERSION
            and valid_summary(record['channel_socket_corroboration']))
    except (AttributeError, KeyError, ValueError, TypeError, IndexError, CaptureError):
        return False
