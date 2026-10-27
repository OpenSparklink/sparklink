# SPDX-License-Identifier: GPL-2.0-only
"""Pending SDK WRITE -> existing typed Disconnect; no second protocol engine.

Down retires a connection, not the controller's Owned service. The publisher
stays alive until both original links are Down. No provider answer is issued.
This gate does not claim daemon restart, remote application rollback, natural
recovery or late-provider-reply isolation. Those remain separate requirements.
"""
import copy
import errno
import json
from pathlib import Path
import re
import secrets
import time

from ws73_capture import CaptureError, packet_interval
from ws73_ssap_sdk_read_provider import need, integer, _wait_json, BOUND
import ws73_ssap_sdk_write_provider as write
import ws73_ssap_provider_owner_exit as shared

PREFIX = 'ssap_write_provider_down'
VERSION = 1
PENDING = 'SDK_WRITE_PROVIDER_DOWN_PENDING_PAIRED_USB'
STATUS = 'SDK_WRITE_PROVIDER_DOWN_APPLICATION_PAIRED_USB'
EXTRA_TOOLS = write.EXTRA_TOOLS + tuple('/usr/share/sparklink/tools/'+name for name in (
    'ws73_ssap_provider_owner_exit.py', 'ws73_ssap_provider_unregister.py',
    'ws73_ssap_write_unregister.py', 'ws73_ssap_write_down.py'))


def requested(args, *, passthrough=None):
    return write.requested(args, passthrough=passthrough, selector=PREFIX)


def boot_requested(tokens):
    return write.boot_requested(tokens, selector=PREFIX)


def tool_records(root=Path('/')):
    from ws73_ssap_write_unregister import tool_records as records
    return records(root, extra_tools=EXTRA_TOOLS)


def validate_tools(records, root, manifest):
    from ws73_ssap_write_unregister import validate_tools as validate
    return validate(records, root, manifest, extra_tools=EXTRA_TOOLS)


def validate_inputs(package):
    from ws73_ssap_write_unregister import validate_inputs as validate
    return validate(package, extra_tools=EXTRA_TOOLS)


def validate_rows(rows, selected):
    need(type(rows) is list and type(selected) is bool, 'explicit pending WRITE Down selection required')
    for phase, row in enumerate(rows):
        need(type(row.get(PREFIX+'_required', False)) is bool and row.get(PREFIX+'_required', False) == selected,
             'pending WRITE Down row/selector mismatch')
        if not selected:
            need(not any(k.startswith(PREFIX+'_') for k in row if k != PREFIX+'_required'), 'unrequested Down evidence')
            continue
        need(type(row.get('phase')) is int and row['phase'] == phase and row.get('post_application_disconnect') is True
             and row.get('ssap_owned_required') is True and len(row.get('ssap_owned', [])) == 4
             and type(row.get(PREFIX+'_version')) is int and row[PREFIX+'_version'] == VERSION
             and len(row.get(PREFIX+'_cases', [])) == 1 and row.get(PREFIX+'_status') == PENDING,
             'one pending WRITE Down after original Owned and ordinary business required')
    if selected:
        need(len(rows) == 2 and len({(r['owners'][1]['owner']['index'], r['owners'][1]['owner']['generation']) for r in rows}) == 2,
             'both original physical Provider receivers required')


def execute(run, row, phase, finish_connection):
    from ws73_application_client import ssap_error_command
    from ws73_ssap_owned import publisher, wait_output, await_removed
    need(row['owners'] == phase['typed_objects'] and row.get('ssap_owned_required') is True
         and len(row.get('ssap_owned', [])) == 4 and row.get('post_application_disconnect') is True,
         'same original connected owners and completed Owned baseline required')
    row.update({PREFIX+'_required': True, PREFIX+'_version': VERSION,
                PREFIX+'_tools': tool_records(), PREFIX+'_cases': []})
    source, target = row['owners']
    with publisher(run, row, 0, 'allow', operations=6, write_provider=True,
                   sdk_api=('python', 'c')[row['phase']], collection=PREFIX+'_cases',
                   label='write-provider-down') as (process, item):
        item['proposed'] = secrets.token_hex(32)
        item['bind_before_monotonic_ns'] = time.monotonic_ns()
        process.stdin.write('provider\n'); process.stdin.flush()
        item['bound'] = _wait_json(process, item, 'SdkWriteProviderBound', BOUND, 1,
                                   item['bind_before_monotonic_ns']+5_000_000_000)
        item['bound_wall_ns'] = time.time_ns(); run.save()
        def disconnect(app, supervisor):
            deadline = shared.pending_callback(run, row, process, item, app, supervisor, writing=True)
            # Save the exact five-line pending transcript before later explicit
            # service cleanup appends its own receipt. Never synthesize a prompt.
            item['pending_stdout'] = Path(item['output_files'][0]).read_text()
            item.update(down_before_monotonic_ns=time.monotonic_ns(), down_before_wall_ns=time.time_ns())
            need(item['down_before_monotonic_ns'] < deadline, 'Disconnect must start within original WRITE deadline')
            run.save()
            finish_connection()  # existing command, shared 5s Down, stale objects and peer checks
            need(process.poll() is None, 'Provider process must survive actual connection Down')
            item.update(down_completed_wall_ns=phase['disconnect_completed_wall_ns'],
                        provider_alive_after_down_wall_ns=time.time_ns(),
                        down_command=phase['disconnect_command'])
            run.save()
        item['read'] = ssap_error_command(run, row, source,
            ['ssap-write', source['object']['path'], str(item['handle']), item['proposed']],
            errno.EIO, api=('c', 'python')[row['phase']], after_start=disconnect)
        # Explicit unregister is cleanup AFTER the Down experiment, not evidence
        # that physical Down automatically removes controller-owned services.
        item['quit_wall_ns'] = time.time_ns()
        process.stdin.write('quit\n'); process.stdin.flush(); wait_output(process, 2)
        need(process.returncode == 0, 'original SDK publisher explicit cleanup failed')
        item['owner_exit_wall_ns'] = time.time_ns()
        item['cleanup'] = await_removed(run, target, item['start']); run.save()
    row[PREFIX+'_status'] = PENDING; run.save()


def validate_phases(run):
    """Bind the callback barrier to the SAME command/Down proof used by the runner."""
    for row in run.get('channel_socket', []):
        if not row.get(PREFIX+'_required', False):
            continue
        phase = run['connection_control']['phases'][row['phase']]
        item, = row[PREFIX+'_cases']
        command = run['commands'][phase['disconnect_command']]
        need(row['owners'] == phase['typed_objects'] and item['down_command'] == phase['disconnect_command']
             and item['down_completed_wall_ns'] == phase['disconnect_completed_wall_ns']
             and item['callback']['observed_wall_ns'] <= item['down_before_wall_ns'] <= command['start_wall_ns']
             and command['end_wall_ns'] <= phase['down_property_observation']['end_wall_ns']
             <= item['down_completed_wall_ns'] <= item['provider_alive_after_down_wall_ns'] < item['quit_wall_ns'],
             'same callback -> original typed Disconnect -> bounded two-end Down -> live publisher required')
        need(max(a['end_wall_ns'] for a in row['applications']) <= item['read']['start_wall_ns'],
             'ordinary application replies must finish before the pending WRITE Down experiment')


def _case(row, item, matched):
    from ws73_application_client import ssap_error_receipt
    from ws73_ssap_read_provider import paired_leg
    from ws73_ssap_value import physical_sends
    from ws73_ssap_update_delivery import TOOLS
    records = row[PREFIX+'_tools']
    need(type(row[PREFIX+'_version']) is int and row[PREFIX+'_version'] == VERSION
         and type(records) is dict and set(records) == set(TOOLS)|set(EXTRA_TOOLS)
         and all(type(v) is dict and set(v) == {'sha256','bytes'} and integer(v['bytes'])
                 and type(v['sha256']) is str and re.fullmatch('[0-9a-f]{64}',v['sha256']) for v in records.values()),
         'exact version and retained SDK/tool identity set required')
    shared._registration(row, item, sdk=True, writing=True)
    data = shared._sdk_pending(row, item, item['pending_stdout'], writing=True)
    cb, app = item['callback'], item['read']
    receipt = ssap_error_receipt(app, row['owners'][0], expected_errno=errno.EIO)
    deadline = min(data['deadline_ns'], receipt['deadline_ns'], cb['supervisor_deadline_ns'])
    times = [receipt['call_ns'], cb['observed_monotonic_ns'], item['down_before_monotonic_ns'], receipt['returned_ns'], deadline]
    need(all(integer(t) for t in times) and times == sorted(times) and times[-2] < deadline
         and cb['exit_deadline_ns'] == deadline and cb['prompt'] == data and cb['publisher_pid'] == item['pid']
         and data['observed_ns'] <= cb['observed_monotonic_ns']
         and data['observed_wall_ns'] <= cb['observed_wall_ns']
         and 0 < data['deadline_ns']-cb['observed_monotonic_ns'] <= 5_000_000_000,
         'actual pending callback and EIO must precede both original deadlines; timeout is not Down')
    need(app['ssap_operation'] == 'ssap-write' and app['ssap_proposed'] == item['proposed']
         and app['ssap_handle'] == item['handle'] and app['api'] == ('c', 'python')[row['phase']],
         'actual ordinary SDK WRITE caller and exact proposed random value required')
    need(item['stdout'] == item['pending_stdout']+f'SdkOwnedRemoved: api={item["publisher_api"]} start={item["start"]}\n'
         and type(item['exit']) is int and item['exit'] == 0
         and app['start_wall_ns'] <= cb['observed_wall_ns'] <= item['down_before_wall_ns']
         <= item['down_completed_wall_ns'] <= item['provider_alive_after_down_wall_ns'] < item['quit_wall_ns']
         <= item['owner_exit_wall_ns'] <= item['end_wall_ns']
         and not any(k in item for k in ('reply_command', 'kill_before_wall_ns', 'steps')),
         'no provider reply or owner kill; explicit successful cleanup only after Down')
    cleanup = item['cleanup']; lists = re.findall(r'^SsapLocalServices: (.+)$', cleanup['stdout'], re.M)
    need(type(cleanup['exit']) is int and cleanup['exit'] == 0 and not cleanup['stderr'] and len(lists) == 1
         and cleanup['args'] == [row['ssap_receipts'][0]['args'][0], '--adapter', row['owners'][1]['owner']['path'], 'ssap-list']
         and not any(v[0] == item['start'] for v in json.loads(lists[0]))
         and item['owner_exit_wall_ns'] <= cleanup['start_wall_ns'] <= cleanup['end_wall_ns'] <= item['end_wall_ns'],
         'original service must be explicitly removed after the connection experiment')
    pdu = b'\x0d\x23'+item['handle'].to_bytes(2, 'little')+b'\0'+bytes.fromhex(item['proposed'])
    frame = b'\x0a\0'+len(pdu).to_bytes(2, 'little')+pdu
    leg = paired_leg(row, 0, 1, frame, app, matched)
    need(packet_interval(leg['tx'])[1] <= packet_interval(leg['rx'])[0]
         and packet_interval(leg['rx'])[1] <= cb['observed_wall_ns'] <= item['down_before_wall_ns'],
         'actual paired WRITE must causally precede callback and Disconnect')
    context = {k: copy.deepcopy(row[k]) for k in ('phase', 'owners', 'ssap_receipts', PREFIX+'_version', PREFIX+'_tools')}
    return dict(status=STATUS, version=VERSION, context=context, case=copy.deepcopy(item),
                wire=[leg], result='ORIGINAL_PENDING_WRITE_EIO_NO_PROVIDER_ANSWER'), {0:physical_sends(leg['tx']), 1:0}


def corroborate(row, matched, packets):
    if not row.get(PREFIX+'_required', False):
        need(not any(k.startswith(PREFIX+'_') for k in row if k != PREFIX+'_required'), 'unrequested Down evidence')
        return [], {0:0, 1:0}
    item, = row[PREFIX+'_cases']
    result, credit = _case(row, item, matched)
    # The existing final reject_unattributed_ssap consumes the ENTIRE remaining
    # lifetime capture, so a synthetic/late WRITE response cannot be hidden.
    return [result], credit


def valid_summary(proof, *, version=VERSION):
    try:
        need(type(version) is int and version == VERSION and len(proof['proofs']) == 2, 'two-role Down proof required')
        receivers = set()
        for phase, row in enumerate(proof['proofs']):
            item, = row[PREFIX]; context = item['context']; case = item['case']
            need(row['phase'] == context['phase'] == phase and row['owners'] == context['owners'], 'original Down phase/owners required')
            receiver = context['owners'][1]['owner']; receivers.add((receiver['index'], receiver['generation']))
            packets = [copy.deepcopy(p) for leg in item['wire'] for p in leg.values()]
            def matched(owner, direction, frame, window):
                key = (owner['owner']['bus'], owner['owner']['device'], owner['object']['handle'], direction, frame.hex())
                found = [p for p in packets if tuple(p[k] for k in ('bus','device','handle','direction','data')) == key
                         and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
                need(len(found) == 1, 'one exact retained pending WRITE packet required')
                packets.remove(found[0]); return found[0]
            rebuilt, _ = _case(context, case, matched)
            need(not packets and rebuilt == item, 'Down proof must rebuild from exact original evidence')
        return len(receivers) == 2
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False


def valid_manifest(record):
    try:
        selected = record.get(PREFIX+'_requested', False)
        need(type(selected) is bool and boot_requested([t for arg in record.get('qemu_args', []) for t in arg.split()]) == selected,
             'Down manifest/boot selector mismatch')
        proof = record.get('channel_socket_corroboration', {})
        if not selected:
            return record.get(PREFIX+'_acceptance', False) is False and not any(PREFIX+s in record for s in ('_version','_verifier')) and not any(PREFIX in r for r in proof.get('proofs', []))
        verifier = record[PREFIX+'_verifier']
        need(type(verifier) is dict and set(verifier) == {'path','sha256','bytes'} and Path(verifier['path']).name == 'ws73_ssap_write_down.py'
             and integer(verifier['bytes']) and re.fullmatch('[0-9a-f]{64}', verifier['sha256']), 'exact Down verifier identity required')
        connections = record.get('connection_corroboration', [])
        need(type(connections) is list and len(connections) == 2, 'original two physical connection proofs required')
        for phase, row in enumerate(proof.get('proofs', [])):
            connection = connections[phase]
            for item in row.get(PREFIX, []):
                owners = item['context']['owners']; case = item['case']
                need([connection['caller'], connection['peer']] == [o['owner'] for o in owners], 'same original connection owners required')
                step = connection['steps'][1]; command = step['command']
                need(command['opcode'] == 0x1403 and command['direction'] == 'out'
                     and (command['bus'], command['device']) == (owners[0]['owner']['bus'], owners[0]['owner']['device'])
                     and command['params'] == (owners[0]['object']['handle'].to_bytes(2,'little')+b'\x10').hex()
                     and case['down_before_wall_ns'] <= command['wall_ns'] <= case['down_completed_wall_ns'],
                     'actual original typed Disconnect OUT after callback required')
                need(len(step['outcomes']) == 2, 'both raw Down outcomes required')
                for owner in owners:
                    events = [e for e in step['outcomes'] if (e['bus'],e['device']) == (owner['owner']['bus'],owner['owner']['device'])]
                    need(len(events) == 1, 'one raw Down per original controller required')
                    event = events[0]; body = bytes.fromhex(event['params'])
                    need(event['event'] in (5,0x1405) and len(body) >= 4 and body[0] == 0
                         and int.from_bytes(body[1:3],'little') == owner['object']['handle']
                         and command['wall_ns'] <= event['wall_ns'] <= case['down_completed_wall_ns'],
                         'successful raw Down must match each original lifetime handle')
                need(item['context'][PREFIX+'_tools'][EXTRA_TOOLS[-1]] == {k:verifier[k] for k in ('sha256','bytes')}, 'guest Down verifier mismatch')
        return (record.get('status') == 'PASSTHROUGH_SUPPORT_PASS' and type(record.get('qemu_exit')) is int and record['qemu_exit'] == 0
                and record.get('ssap_owned_acceptance') is True and record.get('ordinary_channel_socket_acceptance') is True
                and type(record.get(PREFIX+'_version')) is int and record[PREFIX+'_version'] == VERSION
                and record.get(PREFIX+'_acceptance') is True and valid_summary(proof))
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False
