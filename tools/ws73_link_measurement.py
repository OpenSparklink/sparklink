# SPDX-License-Identifier: GPL-2.0-only
"""Finite management observations through slctl; independent raw DLI matching.

No controller open, Host, data loop or radio configuration. A measurement is
neither application delivery nor RF/PHY policy qualification.
"""
import json
import re
import time
from ws73_capture import CaptureError, command_reply

TOKEN = 'ws73.link_measurements=1'
KINDS = ((1, 'rssi', 0x180c, 3), (2, 'phy', 0x1805, 10))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CaptureError('duplicate observation field')
        result[key] = value
    return result


def observation(row, entry, kind):
    owner, identity = entry['owner'], entry['object']
    args = row.get('args', [])
    if (len(args) != 7 or not re.fullmatch(r'(?:/bin|/usr/libexec/opensparklink/native-lab/[0-9a-f]{12})/slctl', args[0])
            or args[1:] != ['--adapter', owner['path'], 'link-measurement', identity['path'], dict((n, word) for n, word, _, _ in KINDS)[kind], '5000']
            or row.get('exit') != 0 or row.get('stderr')):
        raise CaptureError('actual successful slctl management observation required')
    text = row.get('stdout', '')
    prefix = 'Selected '+owner['path']+'\n'
    if text.startswith(prefix):
        text = text[len(prefix):]
    if len(text.encode()) > 4096 or not text.startswith('NativeLinkMeasurement: ') or text.count('\n') != 1 or not text.endswith('\n'):
        raise CaptureError('one bounded original observation receipt required')
    value = json.loads(text[len('NativeLinkMeasurement: '):], object_pairs_hook=unique_object)
    fields = {'generation','lifetime','handle','role','address_type','address','request_id',
              'deadline_monotonic_ns','kind','state','error','status','flags','data'}
    if type(value) is not dict or set(value) != fields:
        raise CaptureError('exact typed observation fields required')
    for name in fields-{'address','data'}:
        if type(value[name]) is not int:
            raise CaptureError('integer observation field required')
    if identity['generation'] != owner['generation'] or any(value[name] != identity[name] for name in ['generation','lifetime','handle','role','address_type','address']):
        raise CaptureError('full original physical lifetime required')
    if (value['kind'] != kind or not 0 < value['request_id'] < 1 << 64
            or not 0 < value['deadline_monotonic_ns'] < 1 << 64
            or (value['state'],value['error'],value['status'],value['flags']) != (2,0,0,7)):
        raise CaptureError('current available real successful Complete required')
    data = value['data']
    size = dict((n, size) for n, _, _, size in KINDS)[kind]
    if type(data) is not list or len(data) != size or any(type(n) is not int or not 0 <= n <= 255 for n in data):
        raise CaptureError('exact bounded reply bytes required')
    if int.from_bytes(bytes(data[:2]), 'little') != identity['handle'] or kind == 1 and data[2] == 127:
        raise CaptureError('echoed handle and available RSSI required')
    return value


def execute(run, entry):
    """Before application workloads; never refresh their leases or deadlines."""
    if 'link_measurements' in entry:
        raise CaptureError('observations must not be silently repeated')
    record = dict(version=1, status='RUNNING_NOT_QUALIFIED', queries=[])
    entry['link_measurements'] = record
    run.data.setdefault('link_measurement_attempts', []).append(dict(owner=entry['owner'], object=entry['object'], record=record))
    run.save()
    try:
        for kind, word, _, _ in KINDS:
            command = [str(run.args.slctl), '--adapter', entry['owner']['path'],
                       'link-measurement', entry['object']['path'], word, '5000']
            row = run.command(command, 7, collection='link_measurement_commands')
            query = dict(kind=kind, command=row)
            record['queries'].append(query); run.save()
            query['observation'] = observation(row, entry, kind)
            run.save()
        record['status'] = 'REAL_REPLY_PENDING_RAW_AUDIT'
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__+': '+str(error))
        raise
    finally:
        record['end_monotonic_ns'] = time.monotonic_ns()
        run.save()


def corroborate_entry(entry, capture):
    record = entry.get('link_measurements', {})
    if record.get('version') != 1 or record.get('status') != 'REAL_REPLY_PENDING_RAW_AUDIT' or len(record.get('queries', [])) != 2:
        raise CaptureError('two original completed observations required')
    proofs = []
    for query, (kind, _, opcode, _) in zip(record['queries'], KINDS):
        if query['kind'] != kind:
            raise CaptureError('original RSSI then PHY order required')
        row = query['command']
        value = observation(row, entry, kind)
        if value != query['observation']:
            raise CaptureError('observation differs from original command receipt')
        proof = command_reply(capture, entry['owner'], opcode, row['start_wall_ns'], row['end_wall_ns'],
                              entry['object']['handle'].to_bytes(2, 'little'), bytes(value['data']).hex())
        proofs.append(dict(kind=kind, scope=value, real_DLI=proof))
    if proofs[0]['scope']['request_id'] >= proofs[1]['scope']['request_id']:
        raise CaptureError('distinct monotonic query author IDs required')
    return dict(status='FINITE_REAL_LINK_OBSERVATIONS', queries=proofs,
                scope='Actual typed management/DLI RSSI and eight opaque PHY bytes;not application delivery,RF timing or PHY policy.')


def corroborate(run, capture, requested):
    if type(requested) is not bool:
        raise CaptureError('explicit observation scope required')
    phases = run.get('connection_control', {}).get('phases', [])
    entries = [entry for phase in phases for entry in phase.get('typed_objects', [])]
    present = [entry for entry in entries if 'link_measurements' in entry]
    commands = run.get('link_measurement_commands', [])
    if not requested:
        if present or commands or run.get('link_measurement_attempts'):
            raise CaptureError('unrequested observations cannot be awarded')
        return None
    if len(entries) != 4 or len(present) != 4 or len(commands) != 8:
        raise CaptureError('both controllers and both connection roles required')
    identity = run.get('application_identity', {})
    uids = identity.get('uids', [])
    if len(uids) != 4 or any(type(uid) is not int or uid <= 0 for uid in uids) or len(set(uids)) != 1 or any(int(identity.get(k, '1'),16) for k in ['cap_eff','cap_prm','cap_amb']):
        raise CaptureError('actual ordinary caller identity required')
    if len(phases) != 2 or any(len(p.get('typed_objects', [])) != 2 for p in phases):
        raise CaptureError('two complete connection phases required')
    registrations = [set(tuple(e['owner'][k] for k in ['bus','device','generation','path']) for e in p['typed_objects']) for p in phases]
    if len(registrations[0]) != 2 or registrations[0] != registrations[1]:
        raise CaptureError('same two distinct original registrations required')
    recorded = [query['command'] for entry in entries for query in entry['link_measurements']['queries']]
    if recorded != commands:
        raise CaptureError('all actual supervisor commands must be accounted for')
    if run.get('link_measurement_attempts') != [dict(owner=e['owner'], object=e['object'], record=e['link_measurements']) for e in entries]:
        raise CaptureError('all original attempts and outcomes must be retained')
    proofs, last_ids = [], {}
    for entry in entries:
        proof = corroborate_entry(entry, capture)
        key = tuple(entry['owner'][k] for k in ['bus','device','generation'])
        for query in proof['queries']:
            request_id = query['scope']['request_id']
            if request_id <= last_ids.get(key, 0):
                raise CaptureError('old query author ID reused in this registration')
            last_ids[key] = request_id
        proofs.append(proof)
    return proofs


def exit_gate(record):
    requested = record.get('link_measurements_requested', False)
    if type(requested) is not bool:
        return False
    if not requested:
        return not any(k in record for k in ['link_measurement_acceptance','link_measurement_corroboration','link_measurement_verifier'])
    args = record.get('qemu_args', [])
    append = [args[i+1] for i, word in enumerate(args[:-1]) if word == '-append']
    if len(append) != 1 or append[0].split().count(TOKEN) != 1 or record.get('link_measurement_acceptance') is not True:
        return False
    proofs = record.get('link_measurement_corroboration', [])
    verifier = record.get('link_measurement_verifier', {})
    return (len(proofs) == 4 and bool(re.fullmatch('[0-9a-f]{64}', verifier.get('sha256', '')))
            and all(p.get('status') == 'FINITE_REAL_LINK_OBSERVATIONS'
                    and [q.get('kind') for q in p.get('queries', [])] == [1,2] for p in proofs))
