# SPDX-License-Identifier: GPL-2.0-only
"""Finite explicit management preference in the existing two-radio VM gate.

No Host, business loop, MTU update or automatic default. A real command
acknowledgment is not its effective link budget or peer application delivery.
"""
import json
import re
from ws73_capture import CaptureError, command_reply
from ws73_link_measurement import unique_object

MODE = 'reported-acb-maximum'
TOKEN = 'ws73.link_payload_preference=' + MODE


def acknowledgment(row, entry):
    owner, link = entry['owner'], entry['object']
    if (type(owner['generation']) is not int or any(type(link[k]) is not int for k in ('generation','lifetime','handle','role','address_type'))
            or not 0 < link['generation'] < 1 << 64 or not 0 < link['lifetime'] < 1 << 64
            or not 0 <= link['handle'] <= 65535 or link['role'] not in (0,1) or not 0 <= link['address_type'] <= 255):
        raise CaptureError('typed bounded original connection identity required')
    maximum = owner['buffers'][0]
    if type(maximum) is not int or not 1 <= maximum <= 65535:
        raise CaptureError('explicit encodable original controller ACB maximum required')
    args = row.get('args', [])
    if (len(args) != 7 or not re.fullmatch(r'(?:/bin|/usr/libexec/opensparklink/native-lab/[0-9a-f]{12})/slctl', args[0])
            or args[1:] != ['--adapter', owner['path'], 'link-payload-preference', link['path'], str(maximum), '5000']
            or type(row.get('exit')) is not int or row['exit'] != 0 or row.get('stderr')):
        raise CaptureError('original successful finite slctl preference command required')
    text = row.get('stdout', '')
    prefix = 'Selected ' + owner['path'] + '\n'
    if text.startswith(prefix): text = text[len(prefix):]
    if len(text.encode()) > 4096 or not text.startswith('NativeLinkPayloadAcknowledgment: ') or text.count('\n') != 1 or not text.endswith('\n'):
        raise CaptureError('one bounded original acknowledgment required')
    value = json.loads(text[len('NativeLinkPayloadAcknowledgment: '):], object_pairs_hook=unique_object)
    fields = {'generation','lifetime','handle','role','address_type','address','request_id',
              'deadline_monotonic_ns','requested_octets','state','error','status','flags'}
    if type(value) is not dict or set(value) != fields or any(type(value[k]) is not int for k in fields-{'address'}):
        raise CaptureError('exact typed acknowledgment fields required')
    if owner['generation'] != link['generation'] or any(value[k] != link[k] for k in ('generation','lifetime','handle','role','address_type','address')):
        raise CaptureError('full original physical lifetime required')
    if (not 0 < value['request_id'] < 1 << 64 or not 0 < value['deadline_monotonic_ns'] < 1 << 64
            or value['requested_octets'] != maximum or (value['state'],value['error'],value['status'],value['flags']) != (2,0,0,5)):
        raise CaptureError('actual current status-only command success required;no available/effective value')
    return value


def execute(run, entry):
    """One command after each real connection and before its workloads;no retry."""
    if 'link_payload_preference' in entry:
        raise CaptureError('preference must not be repeated silently')
    record = dict(version=1, mode=MODE, status='RUNNING_NOT_QUALIFIED')
    entry['link_payload_preference'] = record
    run.data.setdefault('link_payload_attempts', []).append(dict(owner=entry['owner'], object=entry['object'], record=record))
    run.save()
    try:
        maximum = entry['owner']['buffers'][0]
        if type(maximum) is not int or not 1 <= maximum <= 65535:
            raise CaptureError('bounded reported ACB maximum required before command')
        command = [str(run.args.slctl), '--adapter', entry['owner']['path'],
                   'link-payload-preference', entry['object']['path'], str(maximum), '5000']
        record['command'] = run.command(command, 7, collection='link_payload_commands')
        run.save()
        record['acknowledgment'] = acknowledgment(record['command'], entry)
        record['status'] = 'REAL_ACK_PENDING_RAW_AUDIT'
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__+': '+str(error))
        raise
    finally: run.save()


def corroborate_entry(entry, capture):
    record = entry.get('link_payload_preference', {})
    if type(record.get('version')) is not int or (record.get('version'), record.get('mode'), record.get('status')) != (1, MODE, 'REAL_ACK_PENDING_RAW_AUDIT'):
        raise CaptureError('one original explicit preference attempt required')
    value = acknowledgment(record['command'], entry)
    if value != record.get('acknowledgment'):
        raise CaptureError('acknowledgment differs from original command output')
    params = entry['object']['handle'].to_bytes(2,'little') + value['requested_octets'].to_bytes(2,'little')
    row = record['command']
    wire = command_reply(capture, entry['owner'], 0x1804, row['start_wall_ns'], row['end_wall_ns'], params, '')
    owner = {k:entry['owner'][k] for k in ('path','bus','device','generation','buffers')}
    return dict(scope=value, real_DLI=wire, entry=dict(owner=owner,object=entry['object']), original=row)


def corroborate(run, capture, requested):
    if requested not in (None, MODE): raise CaptureError('explicit supported preference scope required')
    entries = [e for p in run.get('connection_control',{}).get('phases',[]) for e in p.get('typed_objects',[])]
    present = [e for e in entries if 'link_payload_preference' in e]
    commands, attempts = run.get('link_payload_commands',[]), run.get('link_payload_attempts',[])
    if requested is None:
        if present or commands or attempts: raise CaptureError('unrequested mutation evidence refused')
        return None
    if run.get('link_payload_preference_requested') != MODE or len(entries) != 4 or len(present) != 4 or len(commands) != 4 or len(attempts) != 4:
        raise CaptureError('both controllers and both roles must complete the original four commands')
    identity = run.get('application_identity',{})
    uids = identity.get('uids',[])
    if len(uids) != 4 or any(type(uid) is not int or uid <= 0 for uid in uids) or len(set(uids)) != 1 or any(int(identity.get(k,'1'),16) for k in ('cap_eff','cap_prm','cap_amb')):
        raise CaptureError('ordinary control-role process evidence required')
    proofs = []
    for entry, command, attempt in zip(entries,commands,attempts):
        if command != entry['link_payload_preference']['command'] or attempt != dict(owner=entry['owner'],object=entry['object'],record=entry['link_payload_preference']):
            raise CaptureError('original command/attempt association changed')
        proofs.append(corroborate_entry(entry,capture))
    return dict(version=1,status='FOUR_REAL_MANAGED_PAYLOAD_ACKS_NOT_EFFECTIVE_BUDGET',mode=MODE,proofs=proofs,
                scope='Four actual explicit commands only;not effective packet length,MTU,RF cause,performance or business delivery.')


def exit_gate(record):
    requested = record.get('link_payload_preference_requested')
    if requested is None:
        return 'link_payload_preference_acceptance' not in record and 'link_payload_preference_corroboration' not in record
    proof = record.get('link_payload_preference_corroboration',{})
    if not (requested == MODE and record.get('link_payload_preference_acceptance') is True
            and type(proof.get('version')) is int and proof.get('version') == 1 and proof.get('mode') == MODE
            and proof.get('status') == 'FOUR_REAL_MANAGED_PAYLOAD_ACKS_NOT_EFFECTIVE_BUDGET'
            and len(proof.get('proofs',[])) == 4): return False
    try:
        seen = {}
        for index, item in enumerate(proof['proofs']):
            entry, row, raw = item['entry'], item['original'], item['real_DLI']
            value = acknowledgment(row,entry)
            if value != item['scope']: return False
            params = value['handle'].to_bytes(2,'little') + value['requested_octets'].to_bytes(2,'little')
            expected = command_reply(dict(commands=[raw['command']],complete=[raw['reply']]),entry['owner'],
                0x1804,row['start_wall_ns'],row['end_wall_ns'],params,'')
            if expected != raw: return False
            key = (entry['owner']['bus'],entry['owner']['device'])
            previous = seen.get(key)
            if index < 2 and previous is not None: return False
            if index >= 2 and (previous is None or value['lifetime'] <= previous['lifetime']
                              or value['request_id'] <= previous['request_id']): return False
            seen[key] = value
        return len(seen) == 2
    except (ValueError,KeyError,TypeError,OverflowError,IndexError): return False
