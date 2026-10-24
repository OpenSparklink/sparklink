# SPDX-License-Identifier: GPL-2.0-only
"""Finite actual WRITE_NO_RSP SDK/Owned gate, reusing the existing VM facilities.

Admission is not delivery. Every command needs a following real Read, an
original-owner local read and independent paired USB witnesses. No Engine or
wire send implementation lives here. This uid1000/caps0 gate does not qualify
apps-only deployment, security, performance, recovery or generic long writes.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from ws73_capture import CaptureError
from ws73_application_client import application_environment, process_identity, validate_consumer_sources
from ws73_ssap_owned import publisher, observed_process, wait_text, wait_output, verify_output, value_snapshot, await_removed
from ws73_ssap_value import length_mtu, pair_wire, physical_sends, valid_wire
from ws73_ssap_update_delivery import tool_records, validate_tools

CONTRACT_VERSION = 1
LENGTHS = (0, 32, 2042)
APIS = ('c', 'python')
STATUS = 'ACTUAL_COMMAND_READ_OWNER_PENDING_PAIRED_CAPTURE'
PROOF_STATUS = 'WRITE_COMMAND_READ_OWNER_PAIRED_USB'
COLLECTION = 'ssap_write_command_publishers'
INPUTS = ('ws73_ssap_command.py', 'ws73_ssap_owned.py', 'ws73_ssap_value.py',
          'ws73_channel_socket.py', 'ws73_target_control.py', 'ws73_target_guest.py',
          'ws73_target_init.sh', 'ws73_application_client.py')


def requested(args, *, passthrough=None):
    value = getattr(args, 'ssap_write_command_verify', False)
    if type(value) is not bool:
        raise ValueError('explicit Write Command selector boolean required')
    if not value:
        return False
    if passthrough is None:
        passthrough = getattr(args, 'passthrough', False)
    incompatible = ('application_client_verify', 'ssap_owned_verify', 'ssap_value_lengths_verify',
                    'ssap_owned_update_verify', 'ssap_update_delivery_verify', 'ssap_subscription_verify',
                    'ssap_update_lifecycle_verify', 'ssap_sender_deadline_verify',
                    'ssap_owner_lifecycle_verify', 'ssap_requester_lifecycle_verify',
                    'ssap_initialization_verify', 'channel_socket_close_prefix', 'channel_socket_burst',
                    'channel_socket_boundaries', 'dynamic_channel_verify', 'channel_fairness_verify',
                    'channel_benchmark', 'parallel_business', 'parallel')
    if (not passthrough or not getattr(args, 'channel_socket_verify', False)
            or getattr(args, 'channel_socket_rounds', 4) != 4
            or getattr(args, 'channel_socket_bytes', 61) != 61
            or getattr(args, 'security_agent', None) is not None
            or any(getattr(args, name, False) for name in incompatible)):
        raise ValueError('Write Command requires dedicated passthrough ordinary61 socket gate')
    return True


def validate(args, *, passthrough=None):
    return requested(args, passthrough=passthrough)


def boot_requested(tokens):
    """Only the one explicit opt-in is supported; malformed selectors fail closed."""
    if not isinstance(tokens, (list, tuple)) or any(type(t) is not str for t in tokens):
        raise ValueError('original tokenized boot arguments required')
    selected = [t for t in tokens if t == 'ws73.ssap_write_command'
                or t.startswith('ws73.ssap_write_command=')]
    if selected not in ([], ['ws73.ssap_write_command=1']):
        raise ValueError('one exact Write Command boot selector required')
    return bool(selected)


def validate_rows(rows, requested):
    """Validate completed raw rows before dispatching their original capture."""
    if type(requested) is not bool or not isinstance(rows, list):
        raise CaptureError('typed original command request and phase list required')
    if requested and len(rows) != 2:
        raise CaptureError('exactly two original command phases required')
    for phase, row in enumerate(rows):
        if not isinstance(row, dict) or type(row.get('ssap_write_command_required', False)) is not bool:
            raise CaptureError('typed original command row selector required')
        if row.get('ssap_write_command_required', False) != requested:
            raise CaptureError('command row/request mismatch')
        if requested:
            if (type(row.get('phase')) is not int or row['phase'] != phase
                    or type(row.get('ssap_write_command_contract')) is not int
                    or row['ssap_write_command_contract'] != CONTRACT_VERSION
                    or not isinstance(row.get('ssap_write_commands'), list)
                    or len(row['ssap_write_commands']) != 12
                    or not isinstance(row.get(COLLECTION), list) or len(row[COLLECTION]) != 4):
                raise CaptureError('complete original contract1 command row required')
        elif any(k.startswith('ssap_write_command') and k != 'ssap_write_command_required' for k in row):
            raise CaptureError('unrequested command contract or evidence')


def valid_manifest(record):
    """A manifest assertion cannot substitute for the finite paired proof."""
    try:
        selected = record.get('ssap_write_command_requested', False)
        args = record.get('qemu_args', [])
        if type(selected) is not bool or not isinstance(args, list) or any(type(a) is not str for a in args):
            return False
        if boot_requested([token for arg in args for token in arg.split()]) != selected:
            return False
        proof = record.get('channel_socket_corroboration', {})
        if not isinstance(proof, dict) or not isinstance(proof.get('proofs', []), list):
            return False
        if not selected:
            if record.get('ssap_write_command_acceptance', False) is not False:
                return False
            if any(k.startswith('ssap_write_command') and k not in (
                    'ssap_write_command_requested', 'ssap_write_command_acceptance') for k in record):
                return False
            return not any(not isinstance(row, dict) or any(
                k.startswith('ssap_write_command') for k in row) for row in proof.get('proofs', []))
        return (type(record.get('ssap_write_command_contract_version')) is int
                and record['ssap_write_command_contract_version'] == CONTRACT_VERSION
                and record.get('ssap_write_command_acceptance') is True
                and record.get('status') == 'PASSTHROUGH_SUPPORT_PASS'
                and type(record.get('qemu_exit')) is int and record['qemu_exit'] == 0
                and record.get('ordinary_channel_socket_acceptance') is True
                and valid_summary(proof))
    except (AttributeError, KeyError, TypeError, ValueError, CaptureError):
        return False


def validate_inputs(package):
    validate_consumer_sources(package)
    here = Path(__file__).resolve().parent
    for name in INPUTS:
        path = here / name
        records = [r for r in package.get('inputs', []) if Path(r['path']).resolve() == path.resolve()]
        if len(records) != 1 or records[0]['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise CaptureError('fresh exact Write Command guest input required: ' + name)


def command_arguments(api, entry, handle, payload):
    if api not in APIS or type(handle) is not int or not 1 <= handle <= 65535:
        raise CaptureError('explicit command language/property required')
    prefix = ['/bin/ws73-application-client-c'] if api == 'c' else [
        '/bin/python3', '/usr/share/sparklink/tools/ws73-application-client.py']
    return prefix + ['ssap-command', str(entry['owner']['index']), str(entry['owner']['generation']),
                     entry['object']['path'], str(handle), payload, '0']


def ordinary(record):
    creds = record['credentials']
    if (creds['uids'] != [1000] * 4 or not isinstance(creds['capabilities'], dict)
            or not {'CapEff', 'CapPrm', 'CapAmb'} <= set(creds['capabilities'])
            or any(int(v, 16) for v in creds['capabilities'].values())):
        raise CaptureError('exact uid1000 cap-zero process required; not apps-only qualification')


def admission(app, entry, handle, payload):
    verify_output(app)
    ordinary(app)
    if (app['api'] not in APIS or app['args'] != command_arguments(app['api'], entry, handle, payload)
            or app['environment'] != application_environment() or app['exit'] != 0 or app['stderr']):
        raise CaptureError('exact successful actual command helper required')
    lines = app['stdout'].splitlines()
    if len(lines) != 2 or not lines[1].startswith('SSAP_COMMAND_ADMITTED: '):
        raise CaptureError('one command barrier and admission-only receipt required')
    barrier = json.loads(lines[0]); result = json.loads(lines[1].split(': ', 1)[1])
    if (set(barrier) != {'stage', 'api', 'deadline_ns', 'client_closed'}
            or barrier['stage'] != 'ssap_command_start_barrier' or barrier['api'] != app['api']
            or barrier['client_closed'] is not True
            or set(result) != {'api', 'handle', 'value', 'minimum', 'admission_only',
                               'peer_delivery_confirmed', 'deadline_ns', 'call_ns', 'returned_ns'}
            or result['api'] != app['api'] or result['handle'] != handle
            or result['value'] != payload or type(result['minimum']) is not int or result['minimum'] != 0
            or result['admission_only'] is not True or result['peer_delivery_confirmed'] is not False
            or any(type(result[n]) is not int for n in ('handle', 'deadline_ns', 'call_ns', 'returned_ns'))
            or type(barrier['deadline_ns']) is not int
            or result['deadline_ns'] != barrier['deadline_ns']
            or not app['start_monotonic_ns'] <= app['barrier_monotonic_ns'] <= app['release_monotonic_ns'] <= result['call_ns']
            < result['returned_ns'] <= result['deadline_ns'] <= app['barrier_monotonic_ns'] + 5_000_000_000
            or not app['start_wall_ns'] <= app['barrier_wall_ns'] <= app['release_wall_ns'] <= app['end_wall_ns']):
        raise CaptureError('original command scope/deadline/admission semantics differ')
    return result


def execute_command(run, row, case, entry):
    payload, api, handle = case['value'], case['api'], case['handle']
    args = command_arguments(api, entry, handle, payload)
    prefix = run.output / f'write-command-{row["phase"]}-{case["sequence"]}-{api}'
    out, err = Path(str(prefix) + '.stdout'), Path(str(prefix) + '.stderr')
    app = dict(api=api, args=args, environment=application_environment(), start_wall_ns=time.time_ns(),
               start_monotonic_ns=time.monotonic_ns())
    case['command'] = app; run.save()
    deadline = time.monotonic() + 7
    try:
        with observed_process(args, app, out, err, env=dict(os.environ, **application_environment()),
                              stdin=subprocess.PIPE, text=True) as process:
            app.update(pid=process.pid)
            app['credentials'], app['process_status'] = process_identity(process.pid)
            wait_text(process, out, r'^\{.*"stage"\s*:\s*"ssap_command_start_barrier".*\}$', deadline)
            app['barrier_wall_ns'] = time.time_ns(); app['barrier_monotonic_ns'] = time.monotonic_ns()
            app['release_monotonic_ns'] = time.monotonic_ns(); app['release_wall_ns'] = time.time_ns()
            process.stdin.write('start\n'); process.stdin.flush(); run.save()
            wait_output(process, max(.001, deadline - time.monotonic()))
    finally:
        run.save()
    admission(app, entry, handle, payload)


def negotiated(row):
    if type(row.get('ssap_exchange_contract')) is not int or row['ssap_exchange_contract'] != 2:
        raise CaptureError('captured sequence-capable ExchangeInfo contract2 required')
    length_mtu(row)
    request = '0207fa07010204000000'; response = '0307fa07010204000000'
    for receipt in row['ssap_receipts']:
        fields = re.findall(r' request=([0-9a-f]+) peer_reply=([0-9a-f]+) peer_request=([0-9a-f]+) response=([0-9a-f]+)$', receipt['stdout'], re.M)
        if fields != [(request, response, request, response)]:
            raise CaptureError('actual original two-role sequence capability required')
    # The encompassing channel corroborator also matches these four exchange
    # legs against raw USB; this receipt check alone is not wire qualification.
    return 2042


def execute(run, row):
    if type(row['phase']) is not int or row['phase'] not in (0, 1) or row.get('security_requirement', 0) != 0:
        raise CaptureError('two ordinary original connection phases required')
    negotiated(row)
    row.update(ssap_write_command_required=True, ssap_write_command_contract=CONTRACT_VERSION,
               ssap_write_commands=[], ssap_write_command_tools=tool_records())
    row[COLLECTION] = []; run.save()
    phase_deadline = time.monotonic() + 180
    for sender in (0, 1):
        source, target = row['owners'][sender], row['owners'][1 - sender]
        for api in APIS:
            with publisher(run, row, sender, 'allow', collection=COLLECTION,
                           label='write-command-' + api, operations=3) as (process, owner):
                owner['api'] = api; owner_index = len(row[COLLECTION]) - 1
                previous = owner['secret']
                for size in LENGTHS:
                    sequence = row['phase'] * 12 + len(row['ssap_write_commands'])
                    payload = (sequence.to_bytes(4, 'little') + secrets.token_bytes(size - 4)).hex() if size else ''
                    case = dict(sequence=sequence, sender=sender, target=1 - sender, api=api,
                                application_bytes=size, handle=owner['handle'], publisher=owner_index,
                                value=payload, before=previous, start_wall_ns=time.time_ns(), status='RUNNING')
                    row['ssap_write_commands'].append(case); run.save()
                    try:
                        if time.monotonic() >= phase_deadline:
                            raise CaptureError('original bounded command phase observation deadline')
                        case['local_before'] = value_snapshot(process, owner, previous)
                        execute_command(run, row, case, source)
                        # The following actual Read is a separate operation and delivery barrier,
                        # never a fabricated command response or renewed command deadline.
                        case['read'] = run.command([str(run.args.slctl), '--adapter', source['owner']['path'],
                            'ssap-read', source['object']['path'], str(owner['handle']), '0'], 7,
                            collection='ssap_write_command_reads',
                            on_started=lambda p, r: r.update(credentials=process_identity(p.pid)[0]))
                        read_receipt(case['read'], source, owner['handle'], payload, str(run.args.slctl))
                        case['local_after'] = value_snapshot(process, owner, payload)
                        if time.monotonic() >= phase_deadline:
                            raise CaptureError('original bounded command phase observation deadline')
                        previous = payload; case['status'] = STATUS
                    finally:
                        case['end_wall_ns'] = time.time_ns(); run.save()
                process.stdin.write('quit\n'); process.stdin.flush()
                if wait_output(process, 5) != 0:
                    raise CaptureError('original Owned publisher did not unregister cleanly')
                owner['removal'] = await_removed(run, target, owner['start']); run.save()
                if time.monotonic() >= phase_deadline:
                    raise CaptureError('original bounded command phase observation deadline')


def read_receipt(receipt, source, handle, payload, program):
    ordinary(receipt)
    wanted = f'SsapPeerValue: operation=ssap-read path={source["object"]["path"]} handle={handle} value={payload}'
    expected = [program, '--adapter', source['owner']['path'], 'ssap-read', source['object']['path'], str(handle), '0']
    lines = receipt['stdout'].splitlines()
    if (receipt['args'] != expected or receipt['exit'] != 0 or receipt['stderr']
            or lines not in ([wanted], [f'Selected {source["owner"]["path"]}', wanted])):
        raise CaptureError('actual following Read must validate complete peer command value')


def _identity(entry):
    owner, obj = entry['owner'], entry['object']
    if (any(type(owner[k]) is not int or owner[k] < 0 for k in ('index', 'generation', 'bus', 'device'))
            or not owner['generation'] or not owner['device'] or type(obj['generation']) is not int
            or obj['generation'] != owner['generation']
            or type(obj['lifetime']) is not int or obj['lifetime'] <= 0
            or type(obj['handle']) is not int or not 0 <= obj['handle'] <= 65535
            or not obj['path'].startswith(owner['path'] + '/peer_')):
        raise CaptureError('original controller/generation/connection lifetime mapping required')
    return dict(index=owner['index'], generation=owner['generation'], lifetime=obj['lifetime'],
                handle=obj['handle'], path=obj['path'], bus=owner['bus'], device=owner['device'])


def _snapshot(snapshot, handle, value):
    if snapshot['handle'] != handle or snapshot['value'] != value:
        raise CaptureError('actual original-owner value differs from command')
    if not snapshot['start_wall_ns'] <= snapshot['end_wall_ns']:
        raise CaptureError('owner value original observation interval required')


def _edge(leg, side, last=False):
    packets = leg[side].get('ssap_fragments', [leg[side]])
    packet = packets[-1 if last else 0]
    packets = packet.get('fragments', [packet]); packet = packets[-1 if last else 0]
    return packet['record'], packet.get('hcc_offset', 0)


def _ordered(wire):
    command, request, response = wire
    if not (_edge(command, 'tx', True) < _edge(request, 'tx')
            and _edge(command, 'rx', True) < _edge(request, 'rx')
            and _edge(request, 'rx', True) < _edge(response, 'tx')
            and _edge(request, 'tx', True) < _edge(response, 'rx')):
        raise CaptureError('actual command before following Read/response on both endpoint streams required')


def _wire_identity(wire, source, destination):
    """Rebind retained SDUs and every physical fragment to the original owner."""
    for leg, origin, peer in zip(wire, (source, source, destination),
                                 (destination, destination, source), strict=True):
        for side, owner, direction in (('tx', origin, 'out'), ('rx', peer, 'in')):
            packets = leg[side].get('ssap_fragments', [leg[side]])
            for packet in packets:
                for fragment in [packet, *packet['fragments']]:
                    if (any(type(fragment[k]) is not int for k in ('bus', 'device', 'handle'))
                            or tuple(fragment[k] for k in ('bus', 'device', 'handle', 'direction'))
                            != (owner['bus'], owner['device'], owner['handle'], direction)):
                        raise CaptureError('original controller/connection endpoint required on every captured fragment')


def _publishers(row):
    owners = row[COLLECTION]
    if len(owners) != 4 or {(p['sender'], p['api']) for p in owners} != {(s, a) for s in (0, 1) for a in APIS}:
        raise CaptureError('four actual original Owned publishers per phase required')
    for item in owners:
        verify_output(item); ordinary(item)
        target = row['owners'][1 - item['sender']]
        args = [row['ssap_receipts'][0]['args'][0], '--adapter', target['owner']['path'], 'ssap-serve',
                item['service'], item['uuid'], '3', '36', item['secret'], 'allow']
        if (item['args'] != args or item['operations'] != 3 or item['policy'] != 'allow'
                or item['target'] != 1 - item['sender'] or item['exit'] != 0 or item['stderr']
                or not 0 < item['start'] <= item['handle'] <= item['end'] <= 65535):
            raise CaptureError('original READ/WRITE_NO_RSP Owned publisher and clean exit required')
        lines = item['stdout'].splitlines()
        registration = f'SsapOwnedService: start={item["start"]} end={item["end"]} property={item["handle"]}; local registration only'
        if lines.count(registration) != 1:
            raise CaptureError('one original Owned registration required')
        decisions = re.findall(r'^SsapAuthorizationDecision: request=(\d+) property=(\d+) data_type=0 write=(true|false) security=(\d+) approved=(true|false); local policy only$', item['stdout'], re.M)
        if (len(decisions) != 6 or [d[2] for d in decisions] != ['true', 'false'] * 3
                or len({d[0] for d in decisions}) != 6
                or any(int(d[1]) != item['handle'] or d[3:] != ('0', 'true') for d in decisions)):
            raise CaptureError('actual per-command and Read original owner policy decisions required')
        snapshots = item['value_snapshots']
        observed = re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]*)$', item['stdout'], re.M)
        if len(snapshots) != 6 or observed != [(str(s['handle']), s['value']) for s in snapshots]:
            raise CaptureError('six actual retained-owner snapshots required')
        removal = item['removal']; values = re.findall(r'^SsapLocalServices: (.+)$', removal['stdout'], re.M)
        if removal['exit'] != 0 or len(values) != 1 or any(v[0] == item['start'] for v in json.loads(values[0])):
            raise CaptureError('original owner registration cleanup observation required')
    return owners


def corroborate(row, matched):
    if row.get('ssap_write_command_required', False) is not True:
        if row.get('ssap_write_commands') or row.get(COLLECTION):
            raise CaptureError('unrequested command evidence')
        return [], {0: 0, 1: 0}
    if (type(row.get('ssap_write_command_contract')) is not int or row['ssap_write_command_contract'] != CONTRACT_VERSION
            or type(row.get('phase')) is not int or row['phase'] not in (0, 1)
            or row.get('security_requirement', 0) != 0 or negotiated(row) != 2042):
        raise CaptureError('exact ordinary command contract/phase/MTU required')
    identities = [_identity(e) for e in row['owners']]
    if len(identities) != 2 or identities[0]['index'] == identities[1]['index'] or (identities[0]['bus'], identities[0]['device']) == (identities[1]['bus'], identities[1]['device']):
        raise CaptureError('two independent original controllers required')
    owners = _publishers(row); cases = row['ssap_write_commands']; proof = []; credit = {0: 0, 1: 0}; fresh = set()
    matrix = [(s, a, n) for s in (0, 1) for a in APIS for n in LENGTHS]
    if len(cases) != len(matrix):
        raise CaptureError('twelve actual command/read/owner cases per phase required')
    for ordinal, (case, expected) in enumerate(zip(cases, matrix, strict=True)):
        sender, api, size = expected; target = 1 - sender; owner = owners[case['publisher']]
        if (any(type(case[k]) is not int for k in ('sender', 'target', 'sequence', 'application_bytes', 'handle', 'publisher'))
                or (case['sender'], case['api'], case['application_bytes']) != expected or case['target'] != target
                or case['sequence'] != row['phase'] * 12 + ordinal or case['status'] != STATUS
                or (owner['sender'], owner['api'], owner['handle']) != (sender, api, case['handle'])):
            raise CaptureError('original command matrix/role/publisher identity required')
        payload = bytes.fromhex(case['value']); handle = case['handle']
        if len(payload) != size or (size and (payload in fresh or int.from_bytes(payload[:4], 'little') != case['sequence'])):
            raise CaptureError('exact random sequence/value length and uniqueness required')
        if payload:
            fresh.add(payload)
        index = LENGTHS.index(size)
        before = owner['secret'] if index == 0 else cases[ordinal - 1]['value']
        if (case['before'] != before or case['local_before'] != owner['value_snapshots'][index * 2]
                or case['local_after'] != owner['value_snapshots'][index * 2 + 1]):
            raise CaptureError('original before/after owner snapshots required')
        _snapshot(case['local_before'], handle, before); _snapshot(case['local_after'], handle, case['value'])
        app, read = case['command'], case['read']
        if app['api'] != api:
            raise CaptureError('command process API differs from declared case')
        result = admission(app, row['owners'][sender], handle, case['value'])
        read_receipt(read, row['owners'][sender], handle, case['value'], row['ssap_receipts'][0]['args'][0])
        if not (row['start_wall_ns'] <= owner['start_wall_ns'] <= case['start_wall_ns']
                <= case['local_before']['start_wall_ns'] <= case['local_before']['end_wall_ns']
                <= app['start_wall_ns'] <= app['end_wall_ns'] <= read['start_wall_ns'] <= read['end_wall_ns']
                <= case['local_after']['start_wall_ns'] <= case['local_after']['end_wall_ns']
                <= case['end_wall_ns'] <= owner['removal']['start_wall_ns'] <= owner['removal']['end_wall_ns']
                <= owner['end_wall_ns'] <= row['end_wall_ns']):
            raise CaptureError('original command/read/owner/removal timeline required')
        if ordinal and case['start_wall_ns'] < cases[ordinal - 1]['end_wall_ns']:
            raise CaptureError('bounded sequential command groups required')
        command = b'\x0c\x03' + handle.to_bytes(2, 'little') + b'\0' + payload
        request = b'\x08\x03' + handle.to_bytes(2, 'little') + b'\0'
        response = b'\x09\x03' + payload
        # Complete delivery window, not the command's admission-return interval.
        window = dict(start_wall_ns=app['start_wall_ns'], end_wall_ns=read['end_wall_ns'])
        wire = [pair_wire(row, matched, row['owners'][s], row['owners'][t], pdu, interval)
                for s, t, pdu, interval in ((sender, target, command, window),
                    (sender, target, request, read), (target, sender, response, read))]
        if not all(valid_wire(leg) for leg in wire):
            raise CaptureError('complete original command/Read two-ended USB legs required')
        _ordered(wire)
        _wire_identity(wire, identities[sender], identities[target])
        for s, leg in zip((sender, sender, target), wire, strict=True):
            credit[s] += physical_sends(leg['tx'])
        proof.append(dict(status=PROOF_STATUS, contract=CONTRACT_VERSION, phase=row['phase'], sequence=case['sequence'],
            sender=sender, target=target, api=api, application_bytes=size, handle=handle, value=case['value'],
            source=identities[sender], destination=identities[target], admission=result,
            owner_value=case['local_after']['value'], read_value=case['value'], wire=wire,
            uid=1000, capabilities_zero=True, apps_only_qualification=False))
    return proof, credit


def valid_summary(value):
    try:
        if value['status'] != 'ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED' or len(value['proofs']) != 2:
            return False
        seen = set()
        for phase, row in enumerate(value['proofs']):
            if type(row['phase']) is not int or row['phase'] != phase or len(row['ssap_write_commands']) != 12:
                return False
            for ordinal, item in enumerate(row['ssap_write_commands']):
                sender, api, size = [(s, a, n) for s in (0, 1) for a in APIS for n in LENGTHS][ordinal]
                payload = bytes.fromhex(item['value']); handle = item['handle']
                if (item['status'] != PROOF_STATUS or type(item['contract']) is not int or item['contract'] != CONTRACT_VERSION
                        or any(type(item[k]) is not int for k in ('phase', 'sequence', 'sender', 'target', 'application_bytes', 'uid'))
                        or (item['phase'], item['sequence'], item['sender'], item['target'], item['api'], item['application_bytes'])
                        != (phase, phase * 12 + ordinal, sender, 1 - sender, api, size)
                        or type(handle) is not int or not 1 <= handle <= 65535 or len(payload) != size
                        or item['owner_value'] != item['value'] or item['read_value'] != item['value']
                        or item['source'] != _identity(row['owners'][sender])
                        or item['destination'] != _identity(row['owners'][1 - sender])
                        or any(type(item[role][k]) is not int for role in ('source', 'destination')
                               for k in ('index', 'generation', 'lifetime', 'handle', 'bus', 'device'))
                        or item['admission']['api'] != api or item['admission']['handle'] != handle
                        or item['admission']['value'] != item['value'] or item['admission']['minimum'] != 0
                        or any(type(item['admission'][k]) is not int for k in ('handle', 'minimum', 'deadline_ns', 'call_ns', 'returned_ns'))
                        or not 0 < item['admission']['call_ns'] < item['admission']['returned_ns'] <= item['admission']['deadline_ns']
                        or item['uid'] != 1000 or item['capabilities_zero'] is not True or item['apps_only_qualification'] is not False
                        or item['admission']['admission_only'] is not True or item['admission']['peer_delivery_confirmed'] is not False
                        or len(item['wire']) != 3 or not all(valid_wire(leg) for leg in item['wire'])):
                    return False
                if payload and (payload in seen or int.from_bytes(payload[:4], 'little') != item['sequence']):
                    return False
                seen.add(payload)
                expected = [b'\x0c\x03' + handle.to_bytes(2, 'little') + b'\0' + payload,
                            b'\x08\x03' + handle.to_bytes(2, 'little') + b'\0', b'\x09\x03' + payload]
                if [leg.get('expected_pdu') for leg in item['wire']] != [p.hex() for p in expected]:
                    return False
                _ordered(item['wire'])
                _wire_identity(item['wire'], item['source'], item['destination'])
        return True
    except (KeyError, ValueError, TypeError, IndexError, CaptureError):
        return False
