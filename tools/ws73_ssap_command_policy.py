# SPDX-License-Identifier: GPL-2.0-only
"""Finite actual SDK rejection / remote command denial / later delivery gate.

Extends the original positive command gate, without replacing its 24 cases.
The only protocol implementation remains the daemon Engine. An absence claim
requires complete paired positive evidence and an exact bounded SDU inventory;
this module never treats missing capture as successful rejection.
"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

import ws73_ssap_command as base
from ws73_capture import CaptureError, packet_interval
from ws73_ssap_owned import (publisher, value_snapshot, await_removed, wait_output,
                             wait_text, output_text, verify_output)
from ws73_ssap_value import pair_wire, valid_wire, physical_sends

VERSION = 1
TOKEN = 'ws73.ssap_command_policy=1'
PREFIX = 'ssap_command_policy'
COLLECTION = PREFIX + '_publishers'
STATUS = 'ACTUAL_COMMAND_POLICY_PENDING_PAIRED_CAPTURE'
PROOF = 'COMMAND_POLICY_SDK_REJECTION_DENIAL_AND_DELIVERY'
PROMPT = (r'^SsapAuthorizationPrompt: token=(\d+) request=(\d+) index=(\d+) generation=(\d+) '
          r'lifetime=(\d+) handle=(\d+) epoch=(\d+) security=(\d+) property=(\d+) data_type=(\d+) '
          r'write=(true|false) bytes=(\d+) deadline_ns=(\d+); answer \'yes (\d+)\' or \'no (\d+)\'$')
DECISION = (r'^SsapAuthorizationDecision: request=(\d+) property=(\d+) data_type=0 '
            r'write=(true|false) security=0 approved=(true|false); local policy only$')
STEPS = ('oversized', 'denied', 'allowed')


def need(condition, why):
    if not condition:
        raise CaptureError(why)


def requested(args, *, passthrough=None):
    selected = getattr(args, 'ssap_write_command_policy_verify', False)
    need(type(selected) is bool, 'typed explicit command policy selector required')
    if selected:
        need(base.requested(args, passthrough=passthrough), 'policy gate requires original positive command gate')
    return selected


def boot_requested(tokens):
    need(isinstance(tokens, (list, tuple)) and all(type(t) is str for t in tokens), 'tokenized boot arguments required')
    found = [t for t in tokens if t == 'ws73.ssap_command_policy' or t.startswith('ws73.ssap_command_policy=')]
    need(found in ([], [TOKEN]), 'one exact command policy boot version required')
    if found:
        need(base.boot_requested(tokens), 'positive command boot gate required')
    return bool(found)


def validate_rows(rows, selected):
    need(type(selected) is bool and isinstance(rows, list), 'typed command policy request and rows required')
    if selected:
        base.validate_rows(rows, True)
    for phase, row in enumerate(rows):
        need(type(row.get(PREFIX + '_required', False)) is bool
             and row.get(PREFIX + '_required', False) == selected, 'policy request/row mismatch')
        if selected:
            need(row['phase'] == phase and type(row.get(PREFIX + '_contract')) is int
                 and row[PREFIX + '_contract'] == VERSION
                 and len(row.get(PREFIX + '_cases', [])) == 4
                 and len(row.get(COLLECTION, [])) == 4, 'four complete policy groups per phase required')
        else:
            need(not any(k.startswith(PREFIX) and k != PREFIX + '_required' for k in row), 'unrequested policy evidence')


def validate_inputs(package):
    base.validate_inputs(package)
    here = Path(__file__).resolve()
    entries = [r for r in package.get('inputs', []) if Path(r['path']).resolve() == here]
    need(len(entries) == 1 and entries[0]['sha256'] == hashlib.sha256(here.read_bytes()).hexdigest(),
         'exact policy guest source input required')


def rejection_receipt(app, entry, handle, payload):
    verify_output(app); base.ordinary(app)
    need(len(bytes.fromhex(payload)) == 2043, 'exact bounded oversized SDK value required')
    need(app['args'] == base.command_arguments(app['api'], entry, handle, payload, mode='ssap-command-reject')
         and app['environment'] == base.application_environment() and app['exit'] == 0 and not app['stderr'],
         'actual bounded SDK rejection helper required')
    lines = app['stdout'].splitlines()
    need(len(lines) == 2 and lines[1].startswith('SSAP_COMMAND_REJECTED: '), 'actual SDK rejection receipt required')
    barrier, result = json.loads(lines[0]), json.loads(lines[1].split(': ', 1)[1])
    need(set(barrier) == {'stage', 'api', 'deadline_ns', 'client_closed', 'mode', 'schema_version'}
         and barrier['stage'] == 'ssap_command_start_barrier' and barrier['api'] == app['api']
         and barrier['client_closed'] is True and barrier['mode'] == 'ssap-command-reject'
         and type(barrier['schema_version']) is int and barrier['schema_version'] == 1, 'explicit rejection barrier required')
    expected = dict(schema_version=1, mode='ssap-command-reject', api=app['api'], method='WriteSsapCommand',
        index=entry['owner']['index'], generation=entry['owner']['generation'], path=entry['object']['path'],
        handle=handle, value=payload, application_bytes=2043, minimum=0, sdk_entered=True, errno=22,
        operation_success=False, peer_delivery_confirmed=False)
    need(set(result) == set(expected) | {'deadline_ns', 'call_ns', 'returned_ns'}
         and all(type(result[k]) is type(v) and result[k] == v for k, v in expected.items()),
         'specific SDK InvalidArgs/EINVAL rejection, not parser or arbitrary failure, required')
    need(all(type(result[k]) is int for k in ('deadline_ns', 'call_ns', 'returned_ns'))
         and type(barrier['deadline_ns']) is int and result['deadline_ns'] == barrier['deadline_ns']
         and app['start_monotonic_ns'] <= app['barrier_monotonic_ns'] <= app['release_monotonic_ns']
         <= result['call_ns'] < result['returned_ns'] < result['deadline_ns']
         <= app['barrier_monotonic_ns'] + 5_000_000_000
         and app['start_wall_ns'] <= app['barrier_wall_ns'] <= app['release_wall_ns'] <= app['end_wall_ns'],
         'SDK rejection must retain the actual original deadline and start barrier')
    return result


def parse_prompt(match):
    keys = ('token', 'request', 'index', 'generation', 'lifetime', 'handle', 'epoch',
            'security', 'property', 'data_type', 'write', 'bytes', 'deadline_ns', 'yes', 'no')
    return {key: value == 'true' if key == 'write' else int(value)
            for key, value in zip(keys, match, strict=True)}


def check_prompt(p, target, handle, write, size, ordinal):
    expected = dict(index=target['owner']['index'], generation=target['owner']['generation'],
        lifetime=target['object']['lifetime'], handle=target['object']['handle'],
        security=0, property=handle, data_type=0, write=write, bytes=size,
        token=ordinal, yes=ordinal, no=ordinal)
    need(all(type(p[k]) is type(v) and p[k] == v for k, v in expected.items())
         and all(type(p[k]) is int and p[k] > 0 for k in ('request', 'epoch', 'deadline_ns')),
         'fresh CLI token and original receiving connection/property/operation identity required')


def decide(run, process, owner, target, *, write, size, approve, deadline):
    events = owner.setdefault('policy_decisions', [])
    ordinal = len(events) + 1; need(ordinal <= 5, 'five finite original policy prompts required')
    out = Path(owner['output_files'][0])
    matches, _ = wait_text(process, out, PROMPT, deadline, min_count=ordinal, max_count=5)
    need(len(matches) == ordinal, 'one new prompt, no duplicate or skipped prompt')
    p = parse_prompt(matches[-1]); check_prompt(p, target, owner['handle'], write, size, ordinal)
    now = time.monotonic_ns()
    need(now < p['deadline_ns'] <= now + 5_000_000_000, 'live original server authorization deadline required')
    if events:
        need(p['request'] > events[-1]['prompt']['request'] and p['epoch'] == events[-1]['prompt']['epoch'],
             'one continuing original Engine observation and security epoch required')
    event = dict(prompt=p, approved=approve, observed_wall_ns=time.time_ns(), observed_monotonic_ns=now,
                 sent=('yes' if approve else 'no') + f' {p["token"]}', sent_monotonic_ns=time.monotonic_ns())
    events.append(event); run.save()
    need(event['sent_monotonic_ns'] < p['deadline_ns'], 'decision cannot renew the original authorization deadline')
    process.stdin.write(event['sent'] + '\n'); process.stdin.flush()
    decisions, _ = wait_text(process, out, DECISION, min(deadline, p['deadline_ns'] / 1e9),
                             min_count=ordinal, max_count=5)
    need(len(decisions) == ordinal and decisions[-1] == (str(p['request']), str(owner['handle']),
         str(write).lower(), str(approve).lower()), 'actual exact original owner decision required')
    event.update(completed_wall_ns=time.time_ns(), completed_monotonic_ns=time.monotonic_ns())
    need(event['completed_monotonic_ns'] < p['deadline_ns'], 'policy decision observed after original deadline')
    run.save(); return event


def execute(run, row):
    need(base.negotiated(row) == 2042 and row.get('security_requirement', 0) == 0, 'original basic negotiated Engine required')
    row.update(ssap_command_policy_required=True, ssap_command_policy_contract=VERSION,
               ssap_command_policy_cases=[], ssap_command_policy_publishers=[],
               ssap_command_policy_tools=base.tool_records()); run.save()
    phase_deadline = time.monotonic() + 180
    for sender in (0, 1):
        source, target = row['owners'][sender], row['owners'][1 - sender]
        for api in base.APIS:
            with publisher(run, row, sender, 'ask', collection=COLLECTION,
                           label='command-policy-' + api, operations=3) as (process, owner):
                owner['api'] = api
                sequence = row['phase'] * 4 + len(row[PREFIX + '_cases'])
                group = dict(sequence=sequence, sender=sender, target=1-sender, api=api, handle=owner['handle'],
                    publisher=len(row[COLLECTION])-1, before=owner['secret'], start_wall_ns=time.time_ns(), status='RUNNING')
                row[PREFIX + '_cases'].append(group); run.save()
                try:
                    group['local_before'] = value_snapshot(process, owner, owner['secret'])
                    for step_index, name in enumerate(STEPS):
                        size = 2043 if name == 'oversized' else 32
                        value = (sequence.to_bytes(4, 'little') + bytes([step_index]) + secrets.token_bytes(size-5)).hex()
                        step = dict(sequence=sequence, api=api, handle=owner['handle'], value=value, start_wall_ns=time.time_ns())
                        group[name] = step; run.save()
                        need(time.monotonic() < phase_deadline, 'original bounded policy phase expired')
                        base.execute_command(run, row, step, source, rejected=name == 'oversized', label='command-policy-' + name)
                        if name != 'oversized':
                            step['decision'] = decide(run, process, owner, target, write=True, size=32,
                                approve=name == 'allowed', deadline=min(phase_deadline, time.monotonic()+5))
                        expected = value if name == 'allowed' else owner['secret']
                        def started(child, receipt):
                            receipt['credentials'], receipt['process_status'] = base.process_identity(child.pid)
                            step['read_decision'] = decide(run, process, owner, target, write=False, size=0, approve=True,
                                deadline=min(phase_deadline, receipt['start_monotonic_ns']/1e9+7))
                        step['read'] = run.command([str(run.args.slctl), '--adapter', source['owner']['path'], 'ssap-read',
                            source['object']['path'], str(owner['handle']), '0'], 7,
                            collection='ssap_command_policy_reads', on_started=started)
                        base.read_receipt(step['read'], source, owner['handle'], expected, str(run.args.slctl))
                        step['local_after'] = value_snapshot(process, owner, expected)
                        step['end_wall_ns'] = time.time_ns(); run.save()
                    group['status'] = STATUS
                finally:
                    group['end_wall_ns'] = time.time_ns(); run.save()
                process.stdin.write('quit\n'); process.stdin.flush()
                need(wait_output(process, 5) == 0, 'original ask publisher must exit cleanly')
                owner['removal'] = await_removed(run, target, owner['start']); run.save()
                need(time.monotonic() < phase_deadline, 'original bounded policy phase expired')


def case_contract(row, case, owner):
    sender, api = case['sender'], case['api']; source, target = row['owners'][sender], row['owners'][1-sender]
    handle = owner['handle']; program = row['ssap_receipts'][0]['args'][0]
    need(case['status'] == STATUS and case['handle'] == handle and case['before'] == owner['secret']
         and owner['api'] == api and owner['sender'] == sender and owner['target'] == case['target'] == 1-sender,
         'original policy group/publisher mapping required')
    verify_output(owner); base.ordinary(owner)
    need(owner['args'] == [program, '--adapter', target['owner']['path'], 'ssap-serve', owner['service'], owner['uuid'],
                           '3', '36', owner['secret'], 'ask']
         and owner['operations'] == 3 and owner['policy'] == 'ask' and owner['exit'] == 0 and not owner['stderr'],
         'one original READ/WRITE_NO_RSP ask publisher required')
    registration = f'SsapOwnedService: start={owner["start"]} end={owner["end"]} property={handle}; local registration only'
    need(owner['stdout'].splitlines().count(registration) == 1 and 0 < owner['start'] <= handle <= owner['end'] <= 65535,
         'one retained original registration required')
    prompts = [parse_prompt(m) for m in re.findall(PROMPT, owner['stdout'], re.M)]
    decisions = re.findall(DECISION, owner['stdout'], re.M); events = owner['policy_decisions']
    need(len(prompts) == len(decisions) == len(events) == 5, 'five actual exact prompts and decisions required')
    specs = [(False, 0, True), (True, 32, False), (False, 0, True), (True, 32, True), (False, 0, True)]
    for i, (event, p, (write, size, approved)) in enumerate(zip(events, prompts, specs, strict=True)):
        check_prompt(p, target, handle, write, size, i+1)
        need(event['prompt'] == p and event['approved'] is approved
             and event['sent'] == ('yes' if approved else 'no') + f' {i+1}'
             and decisions[i] == (str(p['request']), str(handle), str(write).lower(), str(approved).lower())
             and event['observed_monotonic_ns'] <= event['sent_monotonic_ns'] <= event['completed_monotonic_ns'] < p['deadline_ns']
             <= event['observed_monotonic_ns'] + 5_000_000_000
             and case['start_wall_ns'] <= event['observed_wall_ns'] <= event['completed_wall_ns'] <= case['end_wall_ns'],
             'original token/decision/server deadline required')
        if i:
            need(p['request'] > prompts[i-1]['request'] and p['epoch'] == prompts[0]['epoch'], 'continuing request namespace/epoch required')
    need(case['oversized']['read_decision'] == events[0]
         and case['denied']['decision'] == events[1] and case['denied']['read_decision'] == events[2]
         and case['allowed']['decision'] == events[3] and case['allowed']['read_decision'] == events[4],
         'each actual prompt must belong to its original command or independent Read')
    snapshots = [case['local_before'], *[case[n]['local_after'] for n in STEPS]]
    expected_values = [owner['secret']]*3 + [case['allowed']['value']]
    need(owner['value_snapshots'] == snapshots and re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]*)$',
         owner['stdout'], re.M) == [(str(handle), v) for v in expected_values], 'four actual original owner values required')
    for snapshot, expected in zip(snapshots, expected_values, strict=True):
        base._snapshot(snapshot, handle, expected)
    before = case['local_before']['end_wall_ns']; specs = []
    for index, name in enumerate(STEPS):
        step = case[name]; payload = bytes.fromhex(step['value'])
        need(len(payload) == (2043 if index == 0 else 32) and int.from_bytes(payload[:4], 'little') == case['sequence']
             and payload[4] == index and step['api'] == api and step['handle'] == handle and step['sequence'] == case['sequence'],
             'distinct random typed values and original group sequence required')
        expected = step['value'] if name == 'allowed' else owner['secret']
        if name == 'oversized':
            rejection_receipt(step['command'], source, handle, step['value'])
            need('decision' not in step, 'oversized rejection cannot have a remote write policy decision')
        else:
            base.admission(step['command'], source, handle, step['value'])
            need(step['command']['start_wall_ns'] <= step['decision']['observed_wall_ns']
                 <= step['decision']['completed_wall_ns'] <= step['read']['start_wall_ns'], 'actual policy decision before independent Read required')
            specs.append((sender, 1-sender, b'\x0c\x03'+handle.to_bytes(2, 'little')+b'\0'+payload,
                          dict(start_wall_ns=step['command']['start_wall_ns'], end_wall_ns=step['read']['end_wall_ns'])))
        base.read_receipt(step['read'], source, handle, expected, program)
        read = step['read']; event = step['read_decision']
        need(all(type(read[k]) is int and read[k] > 0 for k in ('start_monotonic_ns', 'end_monotonic_ns'))
             and read['start_monotonic_ns'] <= event['observed_monotonic_ns']
             <= event['completed_monotonic_ns'] <= read['end_monotonic_ns']
             <= read['start_monotonic_ns'] + 7_000_000_000,
             'Read supervisor retains its original seven-second budget; protocol deadline is separate')
        need(before <= step['start_wall_ns'] <= step['command']['start_wall_ns'] <= step['command']['end_wall_ns']
             <= step['read']['start_wall_ns'] <= step['read_decision']['observed_wall_ns']
             <= step['read_decision']['completed_wall_ns'] <= step['read']['end_wall_ns']
             <= step['local_after']['start_wall_ns'] <= step['local_after']['end_wall_ns'] <= step['end_wall_ns'],
             'original bounded invocation/Read/owner timeline required')
        before = step['end_wall_ns']
        specs.extend([(sender, 1-sender, b'\x08\x03'+handle.to_bytes(2, 'little')+b'\0', step['read']),
                      (1-sender, sender, b'\x09\x03'+bytes.fromhex(expected), step['read'])])
    need(len({owner['secret'], case['denied']['value'], case['allowed']['value']}) == 3,
         'initial, rejected and approved application values must differ')
    removal = owner['removal']; lists = re.findall(r'^SsapLocalServices: (.+)$', removal['stdout'], re.M)
    need(removal['exit'] == 0 and not removal['stderr'] and len(lists) == 1
         and not any(v[0] == owner['start'] for v in json.loads(lists[0])), 'actual original Owned cleanup required')
    need(row['start_wall_ns'] <= owner['start_wall_ns'] <= case['start_wall_ns'] <= case['local_before']['start_wall_ns']
         <= before <= case['end_wall_ns'] <= removal['start_wall_ns'] <= removal['end_wall_ns']
         <= owner['end_wall_ns'] <= row['end_wall_ns'], 'one original connection/group/publisher lifetime required')
    return specs


def packet_key(p):
    return tuple(p.get(k, 0) for k in ('bus', 'device', 'handle', 'direction', 'record', 'hcc_offset', 'data'))


def window_packets(row, case, sdus):
    owners = {(e['owner']['bus'], e['owner']['device'], e['object']['handle']) for e in row['owners']}
    selected = []
    for p in sdus:
        if (p['bus'], p['device'], p['handle']) not in owners or bytes.fromhex(p['data'])[:2] != b'\x0a\0':
            continue
        a, b = packet_interval(p)
        if a <= case['end_wall_ns'] and b >= case['start_wall_ns']:
            need(case['start_wall_ns'] <= a <= b <= case['end_wall_ns'], 'SSAP SDU crosses original policy window')
            selected.append(p)
    return selected


def verify_wire(row, case, specs, wire, inventory):
    need(len(specs) == len(wire) == 8 and all(valid_wire(p) for p in wire), 'eight complete paired policy legs required')
    expected_packets = []
    for (sender, target, pdu, interval), leg in zip(specs, wire, strict=True):
        need(leg.get('expected_pdu') == pdu.hex() and leg.get('capture_window') == {k:interval[k] for k in ('start_wall_ns', 'end_wall_ns')},
             'original independent PDU and observation interval required')
        for side, entry, direction in (('tx', row['owners'][sender], 'out'), ('rx', row['owners'][target], 'in')):
            owner = base._identity(entry); p = leg[side]
            need('ssap_fragments' not in p, 'only short policy wire PDUs are covered')
            for fragment in [p, *p['fragments']]:
                need(tuple(fragment[k] for k in ('bus', 'device', 'handle', 'direction')) ==
                     (owner['bus'], owner['device'], owner['handle'], direction), 'every fragment belongs to the original endpoint')
            expected_packets.append(p)
    for index in (2, 5):
        base._ordered(wire[index:index+3])
    # Do not infer absence from matcher failure. Every complete SSAP SDU in
    # the original two-ended window must be one of the positively proven legs.
    need(sorted(inventory, key=packet_key) == sorted(expected_packets, key=packet_key)
         and len({packet_key(p) for p in inventory}) == 16,
         'exact complete window required: no oversized command, extra response, duplicate or renegotiation')
    for side in ('tx', 'rx'):
        need(base._edge(wire[0], side, True) < base._edge(wire[2], side)
             and base._edge(wire[3], side, True) < base._edge(wire[5], side), 'ordered independent Read barriers required')


def corroborate(row, matched, sdus):
    if not row.get(PREFIX + '_required', False):
        need(not any(k.startswith(PREFIX) and k != PREFIX+'_required' for k in row), 'unrequested policy data')
        return [], {0:0, 1:0}
    need(type(row.get(PREFIX+'_contract')) is int and row[PREFIX+'_contract'] == VERSION
         and base.negotiated(row) == 2042 and row.get('security_requirement', 0) == 0, 'original basic policy contract required')
    cases, publishers = row[PREFIX+'_cases'], row[COLLECTION]
    need(len(cases) == len(publishers) == 4, 'four policy groups/publishers per original phase required')
    original = list(sdus); proof = []; credit = {0:0, 1:0}
    for ordinal, (case, pair) in enumerate(zip(cases, [(s,a) for s in (0,1) for a in base.APIS], strict=True)):
        need(all(type(case[k]) is int for k in ('sender','target','sequence','publisher','handle'))
             and (case['sender'],case['api']) == pair and case['publisher'] == ordinal
             and case['sequence'] == row['phase']*4+ordinal, 'complete original policy role/API matrix required')
        if ordinal:
            need(cases[ordinal-1]['end_wall_ns'] <= case['start_wall_ns'], 'sequential policy groups required')
        owner = publishers[ordinal]; specs = case_contract(row, case, owner)
        inventory = window_packets(row, case, original)
        wire = [pair_wire(row, matched, row['owners'][s], row['owners'][t], pdu, interval) for s,t,pdu,interval in specs]
        verify_wire(row, case, specs, wire, inventory)
        for (sender,_,_,_), leg in zip(specs, wire, strict=True):
            credit[sender] += physical_sends(leg['tx'])
        proof.append(dict(status=PROOF, contract=VERSION, phase=row['phase'], case=case, publisher=owner,
            wire=wire, window_packets=inventory, bounded_absence_only=True, apps_only_qualification=False))
    return proof, credit


def valid_summary(summary):
    try:
        need(base.valid_summary(summary) and summary['status'] == 'ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
             and len(summary['proofs']) == 2,
             'two original parent socket phases required')
        for phase, row in enumerate(summary['proofs']):
            groups = row[PREFIX]
            need(type(row['phase']) is int and row['phase'] == phase and len(groups) == 4, 'complete policy phases required')
            for ordinal, (p, pair) in enumerate(zip(groups, [(s,a) for s in (0,1) for a in base.APIS], strict=True)):
                case = p['case']; owner = p['publisher']
                need(p['status'] == PROOF and type(p['contract']) is int and p['contract'] == VERSION
                     and type(p['phase']) is int and p['phase'] == phase
                     and p['bounded_absence_only'] is True and p['apps_only_qualification'] is False
                     and all(type(case[k]) is int for k in ('sender','target','sequence','publisher','handle'))
                     and (case['sender'],case['api']) == pair and case['sequence'] == phase*4+ordinal
                     and case['publisher'] == ordinal, 'exact finite policy proof required')
                # The parent proof retains owners but not the raw row clocks or
                # ExchangeInfo stdout. Reuse original per-group clocks/program;
                # caller separately validates parent exchange/lifetime evidence.
                context = dict(owners=row['owners'], ssap_receipts=[dict(args=[owner['args'][0]])],
                               start_wall_ns=owner['start_wall_ns'], end_wall_ns=owner['end_wall_ns'])
                specs = case_contract(context, case, owner)
                verify_wire(context, case, specs, p['wire'], p['window_packets'])
                need(window_packets(context, case, p['window_packets']) == p['window_packets'], 'original window inventory required')
        return True
    except (AttributeError, KeyError, ValueError, TypeError, IndexError, CaptureError):
        return False


def valid_manifest(record):
    try:
        selected = record.get(PREFIX+'_requested', False)
        need(type(selected) is bool, 'typed policy manifest request required')
        args = record.get('qemu_args', [])
        need(isinstance(args,list) and all(type(x) is str for x in args)
             and boot_requested([t for arg in args for t in arg.split()]) == selected, 'policy manifest/boot mismatch')
        if not selected:
            return (record.get(PREFIX+'_acceptance', False) is False
                and not any(k.startswith(PREFIX) and k not in (PREFIX+'_requested', PREFIX+'_acceptance') for k in record)
                and not any(PREFIX in row for row in record.get('channel_socket_corroboration', {}).get('proofs', [])))
        verifier = record.get(PREFIX+'_verifier')
        need(isinstance(verifier, dict) and set(verifier) >= {'path', 'sha256'}
             and type(verifier['path']) is str and Path(verifier['path']).name == 'ws73_ssap_command_policy.py'
             and type(verifier['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', verifier['sha256']),
             'retained policy verifier identity required; actual bytes checked by the executing host')
        return (base.valid_manifest(record) and record.get(PREFIX+'_acceptance') is True
            and type(record.get(PREFIX+'_contract_version')) is int and record[PREFIX+'_contract_version'] == VERSION
            and valid_summary(record['channel_socket_corroboration']))
    except (AttributeError, KeyError, ValueError, TypeError, IndexError, CaptureError):
        return False
