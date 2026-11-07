# SPDX-License-Identifier: GPL-2.0-only
"""Pending real SDK WRITE across the existing VM-init daemon death gate.

Only coordinates existing consumers. No daemon, Engine, protocol or native
submission implementation. Init remains the sole owner of SIGKILL/reap/start.
"""
from contextlib import contextmanager
import copy
import hashlib
import errno
import secrets
import time
from pathlib import Path

from ws73_capture import CaptureError, reassemble_acb, packet_interval
from ws73_ssap_sdk_read_provider import need, integer, _wait_json, BOUND, json_rows
from ws73_ssap_provider_owner_exit import pending_callback, _sdk_pending, _registration
from ws73_ssap_sdk_write_provider import VALUE, tool_records

VERSION = 2
ARMED = {'api', 'token', 'deadline_ns', 'armed_ns'}
OBSERVED = {'api', 'ordinal', 'token', 'deadline_ns', 'observation_deadline_ns',
            'started_ns', 'returned_ns', 'notification_events', 'next_result',
            'authorization_result', 'reply_result', 'info_preserved',
            'value_preserved', 'notification_fd_alive', 'local_observation_only'}


def validate_observation(value, prompt, api, ordinal, lower_ns, upper_ns):
    need(integer(lower_ns) and integer(upper_ns) and lower_ns < upper_ns, 'finite original observation interval required')
    need(type(value) is dict and set(value) == OBSERVED, 'complete actual SDK owner-loss observation required')
    for k in OBSERVED-{'api', 'info_preserved', 'value_preserved', 'notification_fd_alive', 'local_observation_only'}:
        need(type(value[k]) is int, 'exact integer SDK observation field required')
    need(value['api'] == api and value['ordinal'] == ordinal
         and value['token'] == prompt['token'] and value['deadline_ns'] == prompt['deadline_ns'],
         'original SDK request identity and deadline required')
    need(lower_ns <= value['started_ns'] <= value['returned_ns'] < min(value['observation_deadline_ns'], upper_ns)
         and all(value[k] == -errno.ESTALE for k in ('next_result', 'authorization_result', 'reply_result'))
         and value['notification_events'] == 1
         and all(value[k] is True for k in ('info_preserved', 'value_preserved', 'notification_fd_alive', 'local_observation_only')),
         'actual old views must remain stale within the original observation budget')
    if ordinal == 1:
        need(value['observation_deadline_ns'] <= prompt['deadline_ns'], 'first revocation must precede original WRITE deadline')
    else:
        need(value['observation_deadline_ns'] <= upper_ns, 'original process observation budget required')
    return value


@contextmanager
def pending_write(run, phase, die):
    from ws73_application_client import ssap_error_command
    from ws73_ssap_owned import publisher, wait_output, output_text
    owners = phase['typed_objects']
    row = dict(phase=run.args.index, owners=owners, tools=tool_records(), cases=[], ssap_receipts=[])
    run.data['pending_write_restart'] = row; run.save()
    # ExchangeInfo uses the same physical Session; finish before the pending
    # WRITE and the eight-second blocked socket witness are armed.
    for entry in owners:
        receipt = run.command([str(run.args.slctl), '--adapter', entry['owner']['path'],
            'ssap-info', entry['object']['path']], 10, collection='ssap_exchange')
        need(receipt['exit'] == 0, 'actual original Session ExchangeInfo required')
        row['ssap_receipts'].append(receipt)
    api = ('python', 'c')[row['phase']]
    with publisher(run, row, 0, 'allow', collection='cases', label='write-daemon-restart',
                   sdk_api=api, operations=6, write_provider=True) as (process, item):
        item['publisher_budget_start_ns'] = time.monotonic_ns()
        item['proposed'] = secrets.token_hex(32)
        need(item['proposed'] != item['secret'], 'fresh actual WRITE value required')
        item['bind_before_monotonic_ns'] = time.monotonic_ns()
        process.stdin.write('provider\n'); process.stdin.flush()
        item['bound'] = _wait_json(process, item, 'SdkWriteProviderBound', BOUND, 1,
                                   item['bind_before_monotonic_ns']+5_000_000_000)
        item['bound_wall_ns'] = time.time_ns()
        def arrived(app, supervisor):
            deadline = pending_callback(run, row, process, item, app, supervisor, writing=True)
            item['pending_stdout'] = output_text(process, Path(item['output_files'][0]))
            process.stdin.write('hold-owner-loss\n'); process.stdin.flush()
            item['armed'] = _wait_json(process, item, 'SdkWriteProviderOwnerLossArmed', ARMED, 1, deadline)
            prompt = item['callback']['prompt']; armed = item['armed']
            need(armed['api'] == api and type(armed['token']) is int and armed['token'] == prompt['token']
                 and armed['deadline_ns'] == prompt['deadline_ns'] and integer(armed['armed_ns'])
                 and item['callback']['observed_monotonic_ns'] <= armed['armed_ns'] < deadline,
                 'real pending request hold before daemon death required')
            run.save()
            die(deadline)  # Existing init supervisor, never a second kill path.
            observe(1, deadline)
        def observe(ordinal, deadline):
            lower = time.monotonic_ns(); wall = time.time_ns()
            need(process.poll() is None and lower < deadline, 'original publisher/observation budget expired')
            process.stdin.write('observe-owner-loss\n'); process.stdin.flush()
            value = _wait_json(process, item, 'SdkWriteProviderOwnerLoss', OBSERVED, ordinal, deadline)
            validate_observation(value, item['callback']['prompt'], api, ordinal, lower, deadline)
            item.setdefault('observations', []).append(dict(receipt=value, start_wall_ns=wall,
                end_wall_ns=time.time_ns(), lower_ns=lower, upper_ns=deadline))
            run.save()
        source = owners[0]
        item['read'] = ssap_error_command(run, row, source,
            ['ssap-write', source['object']['path'], str(item['handle']), item['proposed']],
            errno.ESTALE, api=('c', 'python')[row['phase']], after_start=arrived)
        def successor():
            # Original process observation budget, never a renewed WRITE deadline.
            observe(2, item['bind_before_monotonic_ns']+30_000_000_000)
            process.stdin.write('value\n'); process.stdin.flush()
            item['application_value'] = _wait_json(process, item, 'SdkWriteProviderValue', VALUE, 1,
                                                   item['bind_before_monotonic_ns']+30_000_000_000)
        yield successor
        item['quit_wall_ns'] = time.time_ns()
        process.stdin.write('quit\n'); process.stdin.flush(); wait_output(process, 2)
        need(process.returncode == 0, 'retired SDK view release failed')
        item['owner_exit_wall_ns'] = time.time_ns(); run.save()
    row['status'] = 'PENDING_WRITE_DAEMON_RESTART_EVIDENCE_PENDING'; run.save()


def verify(record):
    from ws73_application_client import ssap_error_receipt
    row = record['pending_write_restart']
    need(row['status'] == 'PENDING_WRITE_DAEMON_RESTART_EVIDENCE_PENDING' and len(row['cases']) == 1,
         'one completed original pending WRITE required')
    item = row['cases'][0]; _registration(row, item, sdk=True, writing=True)
    prompt = _sdk_pending(row, item, item['pending_stdout'], writing=True)
    need(prompt == item['callback']['prompt'] and row['owners'] == record['connection_control']['phases'][0]['typed_objects'],
         'same physical pre-death Session required')
    call = ssap_error_receipt(item['read'], row['owners'][0], expected_errno=errno.ESTALE)
    need(item['read']['ssap_proposed'] == item['proposed'] and item['read']['ssap_operation'] == 'ssap-write',
         'actual original WRITE requester required')
    need(item['callback']['exit_deadline_ns'] == min(prompt['deadline_ns'], call['deadline_ns'], item['read']['ssap_supervisor_deadline_ns'])
         and item['callback']['supervisor_deadline_ns'] == item['read']['ssap_supervisor_deadline_ns'],
         'original request, SDK and supervisor deadlines must not be renewed')
    observations = item['observations']; need(len(observations) == 2, 'before and after successor observations required')
    actual = json_rows(item['stdout'], 'SdkWriteProviderOwnerLoss', OBSERVED, 2)
    for ordinal, observation in enumerate(observations, 1):
        need(observation['receipt'] == actual[ordinal-1], 'original stdout observation required')
        need(observation['upper_ns'] == (item['callback']['exit_deadline_ns'] if ordinal == 1 else item['bind_before_monotonic_ns']+30_000_000_000),
             'observation uses the original phase budget')
        validate_observation(observation['receipt'], prompt, item['publisher_api'], ordinal,
                             observation['lower_ns'], observation['upper_ns'])
    need(item['armed'] == json_rows(item['stdout'], 'SdkWriteProviderOwnerLossArmed', ARMED, 1)[0]
         and call['call_ns'] <= prompt['observed_ns'] <= item['armed']['armed_ns'] < call['returned_ns']
         and prompt['observed_wall_ns'] <= item['callback']['observed_wall_ns'] < record['armed_wall_ns']
         and record['death']['reaped_wall_ns'] <= observations[0]['start_wall_ns'] <= observations[0]['end_wall_ns']
         <= record['successor']['wall_ns'] <= observations[1]['start_wall_ns'] <= observations[1]['end_wall_ns'] < item['quit_wall_ns'],
         'actual callback, reap, stale and successor chronology required')
    need(item['application_value'] == dict(api=item['publisher_api'], property=item['handle'], value=None, application_memory_only=True)
         and item['application_value'] == json_rows(item['stdout'], 'SdkWriteProviderValue', VALUE, 1)[0]
         and item['stdout'].splitlines()[-1] == f'SdkOwnedRetiredExit: api={item["publisher_api"]} start={item["start"]}; local release only'
         and len(item['stdout'].splitlines()) == 10 and item['exit'] == 0,
         'complete transcript, unchanged app value and local release only required')
    return row


def corroborate(record, capture):
    row = verify(record); item = row['cases'][0]; owners = row['owners']
    payload = b'\x0d\x23'+item['handle'].to_bytes(2,'little')+b'\0'+bytes.fromhex(item['proposed'])
    frame = b'\x0a\0'+len(payload).to_bytes(2,'little')+payload
    sdus = reassemble_acb(capture); legs = []
    for entry, direction in [(owners[0], 'out'), (owners[1], 'in')]:
        o,v=entry['owner'],entry['object']
        found=[p for p in sdus if (p['bus'],p['device'],p['handle'],p['direction'],p['data']) ==
            (o['bus'],o['device'],v['handle'],direction,frame.hex())
            and item['read']['start_wall_ns'] <= p['wall_ns'] <= item['callback']['observed_wall_ns']]
        need(len(found)==1, 'one real two-end original WRITE leg before callback required'); legs.append(found[0])
    from ws73_ssap_read_provider import paired_leg
    def matched(entry, direction, expected, window):
        need(expected == frame, 'same original WRITE frame required')
        return legs[0 if direction == 'out' else 1]
    pair = paired_leg(row,0,1,frame,item['read'],matched)
    need(packet_interval(pair['tx'])[1] <= packet_interval(pair['rx'])[0]
         and packet_interval(pair['rx'])[1] <= item['callback']['observed_wall_ns'],
         'complete paired WRITE request must precede actual callback')
    # No successful old response may appear before the successor acquires a new
    # connection. The old physical handle is insufficient after reuse.
    from ws73_ssap_access import value_operations
    reply=value_operations(item['handle'],b'',b'',bytes.fromhex(item['proposed']),0)[2][2]
    for p in sdus:
        o=owners[1]['owner'];v=owners[1]['object']
        if ((p['bus'],p['device'],p['handle'],p['direction']) == (o['bus'],o['device'],v['handle'],'out')
            and item['callback']['observed_wall_ns'] <= p['wall_ns'] <= record['successor']['wall_ns']):
            need(p['data'] != (b'\x0a\0'+len(reply).to_bytes(2,'little')+reply).hex(), 'old WRITE success reached wire')
    context=copy.deepcopy({k:record[k] for k in ('pending_write_restart','connection_control','armed_wall_ns','death','successor')})
    packets=[copy.deepcopy(p) for p in capture['acb_packets'] if item['read']['start_wall_ns'] <= p['wall_ns'] <= record['successor']['wall_ns']]
    return dict(status='PENDING_WRITE_DAEMON_RESTART_PAIRED_USB',request_legs=legs,
                old_sdk_errno=errno.ESTALE,observations=2,application_value_changed=False,
                context=context,acb_packets=packets,native_events=copy.deepcopy(capture['native_events']))


def summary_valid(proof):
    """Replay retained receipt/wire evidence; no boolean-only qualification."""
    from ws73_ssap_sdk_write_provider import valid_summary
    try:
        need(type(proof['daemon_restart_version']) is int and proof['daemon_restart_version']==VERSION,
             'explicit pending-WRITE restart version required')
        pending=proof['pending_write']
        need(corroborate(pending['context'],dict(acb_packets=pending['acb_packets'],native_events=pending['native_events']))==pending,
             'pending WRITE proof must replay exact original receipts and packets')
        data=proof['successor_data']
        need(data['status']=='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
             and type(data['round_trips']) is int and data['round_trips']==8
             and len(proof['successor_connections'])==len(proof['successor_objects'])==2,
             'two real successor connection roles and eight ordinary replies required')
        return valid_summary(data)
    except (KeyError,TypeError,ValueError,IndexError,AttributeError):return False


def validate_inputs(package):
    from ws73_ssap_sdk_write_provider import validate_inputs as write_inputs
    write_inputs(package)
    for name in ('ws73_ssap_daemon_restart.py','ws73_channel_daemon_crash.py','ws73_channel_socket.py',
                 'ws73_ssap_initialization.py'):
        path=Path(__file__).resolve().with_name(name)
        matches=[r for r in package.get('inputs',[]) if Path(r['path']).resolve()==path]
        need(len(matches)==1 and matches[0]['sha256']==hashlib.sha256(path.read_bytes()).hexdigest(),
             'exact new pending WRITE daemon gate required before attachment')
