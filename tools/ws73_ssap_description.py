# SPDX-License-Identifier: GPL-2.0-only
"""Finite type1 description gate on the existing Owned/SDK/USB facilities.

Only an explicit opt-in augments the existing allow/deny owner matrix. Local
staging, child success and USB submission are not substitutes for the actual
opposite application's value comparison and both capture legs.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from ws73_capture import CaptureError

TOKEN = 'ws73.ssap_description=1'
STATUS = 'OWNED_DESCRIPTION_DISCOVERED_AND_READ_PAIRED_USB'
SIZES = {'allow': 32, 'deny': 244}


def requested(args, *, passthrough=None):
    selected = getattr(args, 'ssap_description_verify', False)
    if type(selected) is not bool:
        raise ValueError('explicit description selector boolean required')
    if selected:
        if passthrough is None:
            passthrough = getattr(args, 'passthrough', False)
        if (not passthrough or not getattr(args, 'ssap_owned_verify', False)
                or not getattr(args, 'channel_socket_verify', False)
                or getattr(args, 'channel_socket_rounds', 4) != 4
                or getattr(args, 'channel_socket_bytes', 61) != 61
                or getattr(args, 'security_agent', None) is not None
                or any(getattr(args, k, False) for k in (
                    'parallel', 'parallel_business', 'application_client_verify',
                    'ssap_write_command_verify', 'ssap_owned_update_verify',
                    'ssap_requester_lifecycle_verify', 'ssap_owner_lifecycle_verify',
                    'ssap_subscription_verify', 'ssap_sender_deadline_verify',
                    'channel_benchmark', 'dynamic_channel_verify', 'channel_fairness_verify',
                    'channel_socket_boundaries', 'channel_socket_close_prefix', 'channel_socket_burst'))):
            raise ValueError('description requires dedicated passthrough Owned ordinary61 gate')
    return selected


def boot_requested(tokens):
    if type(tokens) not in (list, tuple) or any(type(t) is not str for t in tokens):
        raise ValueError('original tokenized boot arguments required')
    values = [t for t in tokens if t == 'ws73.ssap_description' or t.startswith('ws73.ssap_description=')]
    if values not in ([], [TOKEN]) or values and tokens.count('ws73.ssap_owned=1') != 1:
        raise ValueError('one exact description selector and Owned dependency required')
    return bool(values)


def validate_inputs(package):
    from ws73_application_client import validate_consumer_sources
    validate_consumer_sources(package)
    here = Path(__file__).resolve().parent
    for name in ('ws73_ssap_description.py', 'ws73_ssap_owned.py', 'ws73_application_client.py',
                 'ws73_channel_socket.py', 'ws73_target_control.py', 'ws73_target_guest.py', 'ws73_target_init.sh'):
        path = here / name
        found = [r for r in package.get('inputs', []) if Path(r['path']).resolve() == path.resolve()]
        if len(found) != 1 or found[0]['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise CaptureError('fresh exact description input required: ' + name)


def validate_rows(rows, selected):
    if type(selected) is not bool or type(rows) is not list or selected and len(rows) != 2:
        raise CaptureError('explicit description selector and two original phases required')
    for phase, row in enumerate(rows):
        if type(row.get('ssap_description_required', False)) is not bool or row.get('ssap_description_required', False) != selected:
            raise CaptureError('description request/row mismatch')
        items = row.get('ssap_owned', [])
        if selected:
            if (row.get('phase') != phase or row.get('ssap_owned_required') is not True
                    or type(row.get('ssap_description_version')) is not int or row['ssap_description_version'] != 1
                    or len(items) != 4 or any(not isinstance(i.get('description'), dict) for i in items)):
                raise CaptureError('complete version1 Owned description rows required')
        elif 'ssap_description_version' in row or any('description' in i for i in items):
            raise CaptureError('unrequested descriptor evidence')


def discovered(receipt, source, item):
    """Parse the actual CLI observation; no local registration fallback."""
    pattern = r'^SsapRemoteEntry: category=10 handle=(\d+) end=(\d+) uuid=([0-9a-f]+) operations=(\d+) descriptors=([0-9a-f]*) members=0$'
    rows = re.findall(pattern, receipt['stdout'], re.M)
    expected = [(str(item['handle']), str(item['handle']), item['uuid'], '5', '01')]
    if receipt['exit'] or receipt['stderr'] or rows != expected:
        raise CaptureError('actual peer discovery must advertise this property description')
    h = int(rows[0][0])
    trace = re.findall(r'^SsapRemoteDiscovery: path=' + re.escape(source['object']['path'])
                      + r' kind=3 entries=1 requests=([0-9a-f|]+) responses=([0-9a-f|]+)$', receipt['stdout'], re.M)
    if len(trace) != 1:
        raise CaptureError('one original description discovery trace required')
    request = b'\x06\x13\x01\x00\xff\xff' + bytes.fromhex(item['uuid'])
    next_handle = (h + 1).to_bytes(2, 'little')
    requests = [request, b'\x06\x13' + next_handle + b'\xff\xff' + bytes.fromhex(item['uuid'])]
    responses = [b'\x07\x0b\x81' + h.to_bytes(2, 'little') + bytes.fromhex(item['uuid']) + b'\x05\0\0\0\x01\x01',
                 b'\x01\0\x06' + next_handle + b'\x0b']
    if trace[0] != ('|'.join(p.hex() for p in requests), '|'.join(p.hex() for p in responses)):
        raise CaptureError('original descriptor discovery page/terminal trace differs')
    return h, list(zip(requests, responses))


def execute(run, row, process, item):
    from ws73_application_client import ssap_command
    from ws73_ssap_owned import wait_text
    source = row['owners'][item['sender']]
    size = SIZES[item['policy']]
    # Random bytes are rendered as printable UTF-8 before the actual setter.
    text = '说明-' + secrets.token_hex(size)[:size - len('说明-'.encode())]
    value = text.encode()
    if len(value) != size:
        raise CaptureError('exact bounded UTF-8 description input required')
    record = dict(text=text, value=value.hex(), bytes=size, start_wall_ns=time.time_ns())
    item['description'] = record; run.save()
    process.stdin.write('description ' + text + '\n'); process.stdin.flush()
    matches, _ = wait_text(process, Path(item['output_files'][0]),
        r'^SsapOwnedDescription: handle=(\d+) bytes=(\d+); local commit only$', time.monotonic() + 5)
    if matches != [(str(item['handle']), str(size))]:
        raise CaptureError('one exact actual Owned description local commit required')
    record['committed_wall_ns'] = time.time_ns()
    record['discovery'] = run.command([str(run.args.slctl), '--adapter', source['owner']['path'],
        'ssap-discover', source['object']['path'], 'property', item['uuid']], 10, collection='ssap_descriptions')
    handle, _ = discovered(record['discovery'], source, item)
    api = 'c' if item['policy'] == 'allow' else 'python'
    record['read'] = ssap_command(run, row, source,
        ['ssap-read-description', source['object']['path'], str(handle)], value,
        api=api, expected_size=size)
    record['end_wall_ns'] = time.time_ns(); run.save()


def retired(run, row, item):
    source = row['owners'][item['sender']]
    receipt = run.command([str(run.args.slctl), '--adapter', source['owner']['path'],
        'ssap-read-description', source['object']['path'], str(item['handle']), '0'], 10,
        collection='ssap_descriptions')
    item['description']['retired_read'] = receipt; run.save()
    if not receipt['exit'] or 'peer read error 4' not in receipt['stderr']:
        raise CaptureError('retired description must be rejected by the actual peer')


def corroborate(row, item, matched):
    from ws73_application_client import ssap_receipt
    from ws73_ssap_command import _identity
    from ws73_ssap_value import command_packet, physical_sends
    if (type(row['phase']) is not int or row['phase'] not in (0, 1)
            or len(row['owners']) != 2
            or any(type(item[k]) is not int for k in ('sender', 'target', 'handle'))
            or item['sender'] not in (0, 1) or item['target'] != 1-item['sender']
            or not 0 < item['handle'] < 65535):
        raise CaptureError('original phase, opposite endpoints and discovered handle required')
    identities = [_identity(owner) for owner in row['owners']]
    if (len({(i['index'], i['generation']) for i in identities}) != 2
            or len({(i['bus'], i['device']) for i in identities}) != 2):
        raise CaptureError('two distinct original controller/USB identities required')
    source, target = row['owners'][item['sender']], row['owners'][item['target']]
    record = item['description']; h = item['handle']; size = SIZES[item['policy']]
    if any(line.startswith('SsapAuthorizationDecision:') and ' data_type=0 ' not in line
           for line in item['stdout'].splitlines()):
        raise CaptureError('public description must not create a descriptor policy decision')
    value = bytes.fromhex(record['value'])
    intervals = (item, record, record['discovery'], record['read'], record['retired_read'])
    if any(type(v) is not int or v <= 0 for interval in intervals
           for k, v in interval.items() if k.endswith('_wall_ns')):
        raise CaptureError('original positive integer observation timestamps required')
    if (type(record['bytes']) is not int or record['bytes'] != size or len(value) != size
            or value != record['text'].encode() or not record['text'].startswith('说明-')
            or not re.fullmatch('[0-9a-f]+', record['text'][3:])
            or f'SsapOwnedDescription: handle={h} bytes={size}; local commit only' not in item['stdout'].splitlines()
            or not item['start_wall_ns'] <= record['start_wall_ns'] <= record['committed_wall_ns']
            <= record['discovery']['start_wall_ns'] <= record['discovery']['end_wall_ns']
            <= record['read']['start_wall_ns'] <= record['read']['end_wall_ns'] <= record['end_wall_ns'] <= item['end_wall_ns']):
        raise CaptureError('original bounded description/local commit/application interval required')
    found, exchanges = discovered(record['discovery'], source, item)
    if found != h:
        raise CaptureError('description read must use the actual discovered handle')
    app = record['read']; ssap_receipt(app, source, expected_size=size)
    if (app['api'] != ('c' if item['policy'] == 'allow' else 'python')
            or app['ssap_operation'] != 'ssap-read-description' or app['ssap_handle'] != h
            or app['ssap_expected'] != value.hex()):
        raise CaptureError('opposite actual SDK must validate original description bytes')
    missing = record['retired_read']
    if (not missing['exit'] or 'peer read error 4' not in missing['stderr']
            or not item['owner_exit_wall_ns'] < missing['start_wall_ns'] <= missing['end_wall_ns'] <= item['end_wall_ns']):
        raise CaptureError('actual owner loss must precede description refusal')
    steps = [(record['discovery'], req, rsp) for req, rsp in exchanges]
    request = b'\x08\x03' + h.to_bytes(2, 'little') + b'\x01'
    steps += [(app, request, b'\x09\x03' + value), (missing, request, b'\x09\x0b\x04\x00')]
    wire = []; credit = {0: 0, 1: 0}
    for window, req, rsp in steps:
        for sender, receiver, pdu in ((item['sender'], item['target'], req), (item['target'], item['sender'], rsp)):
            frame = b'\x0a\0' + len(pdu).to_bytes(2, 'little') + pdu
            leg = dict(tx=matched(row['owners'][sender], 'out', frame, window),
                       rx=matched(row['owners'][receiver], 'in', frame, window))
            for side, endpoint, direction in (('tx', sender, 'out'), ('rx', receiver, 'in')):
                packet = leg[side]
                command_packet(packet, frame, window)
                identity = identities[endpoint]
                for fragment in [packet, *packet['fragments']]:
                    if (any(type(fragment[k]) is not int for k in ('bus', 'device', 'handle'))
                            or tuple(fragment[k] for k in ('bus', 'device', 'handle', 'direction'))
                            != (identity['bus'], identity['device'], identity['handle'], direction)):
                        raise CaptureError('original endpoint required on every description PB fragment')
            wire.append(leg)
            credit[sender] += physical_sends(leg['tx'])
    return dict(status=STATUS, api=app['api'], bytes=size, value=value.hex(),
                property_policy=item['policy'], wire=wire, read=app,
                context=copy.deepcopy(dict(phase=row['phase'], owners=row['owners'])),
                case=copy.deepcopy(item)), credit


def valid_summary(proof):
    """Replay the same verdict over retained original receipts and captured SDUs.

    The matcher can only consume each retained packet once; it cannot invent a
    peer leg or replace absent application, discovery or lifetime evidence.
    """
    try:
        phases = proof['proofs']
        if type(phases) is not list or len(phases) != 2:
            return False
        values = set()
        for phase, row in enumerate(phases):
            items = row['ssap_owned']
            if (type(row['phase']) is not int or row['phase'] != phase
                    or type(items) is not list or len(items) != 4
                    or any(type(i['sender']) is not int for i in items)
                    or {(i['sender'], i['policy']) for i in items} != {(s, p) for s in (0, 1) for p in SIZES}):
                return False
            for item in items:
                d = item['description']
                context, case = d['context'], d['case']
                if (type(context['phase']) is not int or context['phase'] != phase
                        or context['owners'] != row['owners']
                        or case['sender'] != item['sender'] or case['policy'] != item['policy']
                        or d['value'] in values or type(d['wire']) is not list or len(d['wire']) != 8):
                    return False
                packets = [copy.deepcopy(leg[side]) for leg in d['wire'] for side in ('tx', 'rx')]

                def matched(owner, direction, frame, window):
                    wanted = (owner['owner']['bus'], owner['owner']['device'],
                              owner['object']['handle'], direction, frame.hex())
                    found = [packet for packet in packets
                             if tuple(packet[k] for k in ('bus', 'device', 'handle', 'direction', 'data')) == wanted
                             and window['start_wall_ns'] <= packet['wall_ns'] <= window['end_wall_ns']]
                    if len(found) != 1:
                        raise CaptureError('one exact retained description packet required')
                    packets.remove(found[0])
                    return found[0]

                rebuilt, _ = corroborate(context, case, matched)
                if packets or json.dumps(rebuilt, sort_keys=True) != json.dumps(d, sort_keys=True):
                    return False
                values.add(d['value'])
        return True
    except (KeyError, AttributeError, IndexError, TypeError, ValueError):
        return False


def valid_manifest(record):
    try:
        selected = record.get('ssap_description_requested', False)
        if type(selected) is not bool or boot_requested([t for arg in record.get('qemu_args', []) for t in arg.split()]) != selected:
            return False
        proof = record.get('channel_socket_corroboration', {})
        if not selected:
            return (record.get('ssap_description_acceptance', False) is False
                    and 'ssap_description_version' not in record
                    and not any('description' in i for r in proof.get('proofs', []) for i in r.get('ssap_owned', [])))
        return (type(record.get('ssap_description_version')) is int and record['ssap_description_version'] == 1
                and record.get('ssap_description_acceptance') is True and record.get('ssap_owned_acceptance') is True
                and record.get('status') == 'PASSTHROUGH_SUPPORT_PASS'
                and type(record.get('qemu_exit')) is int and record['qemu_exit'] == 0
                and record.get('ordinary_channel_socket_acceptance') is True and valid_summary(proof))
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
