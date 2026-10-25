# SPDX-License-Identifier: GPL-2.0-only
"""Finite opt-in Provider owner loss, using the sole Engine and SDK supervisor.

The actual value-provider prompt is the arrival barrier. This is not the older
policy-prompt exit gate: the only admitted on-wire READ errors are AF and 4.
Execution is pending evidence until original paired USB corroboration succeeds.
"""
import copy
import errno
import hashlib
import json
from pathlib import Path
import re
import time

from ws73_capture import CaptureError, packet_interval
from ws73_ssap_read_provider import PROMPT, prompt, _cleanup, _wire

TOKEN = 'ws73.ssap_provider_owner_exit=1'
VERSION = 1
STATUS = 'PROVIDER_OWNER_EXIT_APPLICATION_PAIRED_USB'
PENDING = 'PROVIDER_OWNER_EXIT_PENDING_PAIRED_USB'
PREFIX = 'ssap_provider_owner_exit'
CLOCK_CONTRACT = dict(version=1, domain='same-guest',
                      offset_assumption='no-clock-adjustment-between-samples',
                      usbmon_quantization_ns=1000)


def requested(args, *, passthrough=None):
    selected = getattr(args, PREFIX+'_verify', False)
    if type(selected) is not bool:
        raise ValueError('explicit provider owner-exit selector boolean required')
    if not selected:
        return False
    from ws73_ssap_read_provider import requested as provider_requested
    if not provider_requested(args, passthrough=passthrough):
        raise ValueError('provider owner-exit requires the original read-provider/Owned baseline')
    return True


def boot_requested(tokens):
    from ws73_ssap_read_provider import boot_requested as provider_boot
    if type(tokens) not in (list, tuple) or any(type(t) is not str for t in tokens):
        raise ValueError('original tokenized boot arguments required')
    selected = [t for t in tokens if t == 'ws73.ssap_provider_owner_exit' or t.startswith('ws73.ssap_provider_owner_exit=')]
    if selected not in ([], [TOKEN]) or selected and not provider_boot(tokens):
        raise ValueError('one exact owner-exit selector and original provider dependency required')
    return bool(selected)


def validate_inputs(package):
    from ws73_ssap_read_provider import validate_inputs as provider_inputs
    provider_inputs(package)
    path = Path(__file__).resolve()
    matches = [r for r in package.get('inputs', []) if Path(r['path']).resolve() == path]
    if len(matches) != 1 or matches[0]['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise CaptureError('fresh exact Provider owner-exit verifier required')


def validate_rows(rows, selected):
    if type(selected) is not bool or type(rows) is not list or selected and len(rows) != 2:
        raise CaptureError('explicit owner-exit selector and two original phases required')
    for phase, row in enumerate(rows):
        if type(row.get(PREFIX+'_required', False)) is not bool or row.get(PREFIX+'_required', False) != selected:
            raise CaptureError('provider owner-exit request/row mismatch')
        keys = (PREFIX+'_version', PREFIX+'_cases', PREFIX+'_guards', PREFIX+'_tools', PREFIX+'_status')
        if not selected:
            if any(k in row for k in keys):
                raise CaptureError('unrequested Provider owner-exit evidence')
            continue
        if (type(row.get('phase')) is not int or row['phase'] != phase
                or type(row.get(PREFIX+'_version')) is not int or row[PREFIX+'_version'] != VERSION
                or row.get('ssap_read_provider_required') is not True or row.get('ssap_read_provider_version') != 2
                or type(row.get(PREFIX+'_tools')) is not dict
                or len(row.get(PREFIX+'_cases', [])) != 1 or len(row.get(PREFIX+'_guards', [])) != 1
                or row[PREFIX+'_cases'][0].get('sender') != 0):
            raise CaptureError('one exit per role and original provider v2 baseline required')
    if selected and len({(row['owners'][1]['owner']['index'], row['owners'][1]['owner']['generation']) for row in rows}) != 2:
        raise CaptureError('both physical Provider receivers must undergo owner exit')


def _remaining(deadline):
    remaining = deadline-time.monotonic_ns()
    if remaining <= 0:
        raise CaptureError('Provider owner exit exceeded original SDK/provider deadline')
    return remaining/1e9


def _clock_sample():
    """Same guest clocks only; samples do not prove the absence of clock steps."""
    before = time.monotonic_ns()
    wall = time.time_ns()
    after = time.monotonic_ns()
    return dict(monotonic_before_ns=before, realtime_ns=wall, monotonic_after_ns=after)


def _clock_bounds(item):
    """Conditional offset intersection, not an invented host/guest mapping.

    Guest usbmon uses CLOCK_REALTIME, truncated to microseconds; SDK receipts
    and the supervisor use the same guest CLOCK_MONOTONIC. A stable offset
    between these bracketing samples is an explicit environment assumption.
    Conflicting samples or uncertainty overlapping the required upper bound
    are not qualified. The pcap/header timestamp check is not this mapping.
    """
    contract = item.get('clock_contract')
    if (contract != CLOCK_CONTRACT or type(contract.get('version')) is not int
            or type(contract.get('usbmon_quantization_ns')) is not int):
        raise CaptureError('explicit same-guest clock and no-adjustment scope required')
    bounds = []
    for name in ('clock_before', 'clock_after'):
        sample = item[name]
        if (type(sample) is not dict or set(sample) != {'monotonic_before_ns', 'realtime_ns', 'monotonic_after_ns'}
                or any(type(value) is not int or value <= 0 for value in sample.values())
                or sample['monotonic_before_ns'] > sample['monotonic_after_ns']):
            raise CaptureError('original ordered monotonic/realtime clock bracket required')
        bounds.append((sample['realtime_ns']-sample['monotonic_after_ns'],
                       sample['realtime_ns']-sample['monotonic_before_ns']))
    before, after = item['clock_before'], item['clock_after']
    if (not item['callback']['observed_monotonic_ns'] <= before['monotonic_before_ns']
            <= before['monotonic_after_ns'] <= item['kill_before_monotonic_ns']
            or not item['read']['end_monotonic_ns'] <= after['monotonic_before_ns']
            or not item['callback']['observed_wall_ns'] <= before['realtime_ns'] <= item['kill_before_wall_ns']
            or not item['read']['end_wall_ns'] <= after['realtime_ns'] <= item['retired_read']['start_wall_ns']):
        raise CaptureError('clock samples must bracket original kill through SDK completion')
    lower, upper = max(v[0] for v in bounds), min(v[1] for v in bounds)
    if lower > upper:
        raise CaptureError('clock samples contradict the stated stable-offset assumption')
    return lower, upper


def _owner_exit(run, row, process, item, app, supervisor_deadline_ns):
    """After-start hook; no answer, renewed deadline or synthetic Complete."""
    from ws73_ssap_owned import wait_text, wait_output, await_removed
    item['read'] = app
    run.save()
    sdk_deadline = app['ssap_error_deadline_ns']
    _, text = wait_text(process, Path(item['output_files'][0]), PROMPT,
                        min(sdk_deadline, supervisor_deadline_ns)/1e9, max_count=1)
    observed = time.monotonic_ns()
    data = prompt(text)
    target = row['owners'][item['target']]
    identity, link = target['owner'], target['object']
    if ((data['index'], data['generation'], data['lifetime'], data['handle'], data['property'])
            != (identity['index'], identity['generation'], link['lifetime'], link['handle'], item['handle'])
            or not observed < data['deadline_ns'] <= observed+5_000_000_000
            or process.poll() is not None):
        raise CaptureError('one live original Provider callback identity and deadline required')
    deadline = min(data['deadline_ns'], sdk_deadline, supervisor_deadline_ns)
    item['callback'] = dict(prompt=data, observed_monotonic_ns=observed, observed_wall_ns=time.time_ns(),
                            publisher_pid=process.pid, supervisor_deadline_ns=supervisor_deadline_ns,
                            exit_deadline_ns=deadline)
    run.save()
    _remaining(deadline)
    item['clock_contract'] = copy.deepcopy(CLOCK_CONTRACT)
    item['clock_before'] = _clock_sample()
    # This pre-kill timestamp is the causal lower bound. A real wire refusal may
    # precede wait() returning, so wait completion is not the response barrier.
    item.update(kill_before_wall_ns=time.time_ns(), kill_before_monotonic_ns=time.monotonic_ns())
    if item['kill_before_monotonic_ns'] >= deadline:
        raise CaptureError('no late owner kill after the original deadline')
    process.kill()
    item.update(kill_returned_wall_ns=time.time_ns(), kill_returned_monotonic_ns=time.monotonic_ns())
    wait_output(process, _remaining(deadline))
    item.update(owner_exit=process.returncode, owner_exit_wall_ns=time.time_ns(), owner_exit_monotonic_ns=time.monotonic_ns())
    if item['owner_exit'] != -9:
        raise CaptureError('original pending Provider owner must actually die by SIGKILL')
    _remaining(deadline)
    item['cleanup'] = await_removed(run, target, item['start'], deadline_ns=deadline)
    item['cleanup_completed_monotonic_ns'] = time.monotonic_ns()
    _remaining(deadline)
    run.save()


def execute(run, row):
    from ws73_application_client import ssap_command, ssap_error_command
    from ws73_ssap_owned import publisher, wait_text, wait_output, await_removed
    from ws73_ssap_update_delivery import tool_records
    if (row.get('ssap_read_provider_required') is not True or row.get('ssap_read_provider_version') != 2
            or len(row.get('ssap_read_provider_cases', [])) != 2):
        raise CaptureError('original provider sequence must finish before owner-exit extension')
    row.update({PREFIX+'_required': True, PREFIX+'_version': VERSION, PREFIX+'_tools': tool_records(),
                PREFIX+'_cases': [], PREFIX+'_guards': []})
    run.save()
    phase = row['phase']
    if type(phase) is not int or phase not in (0, 1):
        raise CaptureError('original two-role phase required')
    # owners are role ordered and reverse physical identities on phase 1.
    # A fixed role position tests each physical Provider receiver once.
    sender = 0
    source, target = row['owners'][sender], row['owners'][1-sender]
    api = ('c', 'python')[phase]
    with publisher(run, row, sender, 'allow', operations=1,
                   collection=PREFIX+'_guards', label='provider-exit-guard') as (guard_process, guard):
        guard['registered_wall_ns'] = time.time_ns()
        run.save()
        with publisher(run, row, sender, 'allow', operations=1,
                       collection=PREFIX+'_cases', label='provider-owner-exit') as (process, item):
            item['guard'] = guard
            process.stdin.write('provider\n'); process.stdin.flush()
            found, _ = wait_text(process, Path(item['output_files'][0]),
                r'^SsapReadProviderBound: handle=(\d+); stored value discarded, no rebind or fallback$',
                time.monotonic()+5, max_count=1)
            if found != [str(item['handle'])]:
                raise CaptureError('same original publisher must bind one provider')
            item['bound_wall_ns'] = time.time_ns(); run.save()
            item['read'] = ssap_error_command(run, row, source,
                ['ssap-read', source['object']['path'], str(item['handle'])], errno.EIO,
                api=api, after_start=lambda app, deadline: _owner_exit(run, row, process, item, app, deadline))
            item['clock_after'] = _clock_sample()
            run.save()
            item['retired_read'] = run.command([str(run.args.slctl), '--adapter', source['owner']['path'],
                'ssap-read', source['object']['path'], str(item['handle']), '0'], 10, collection=PREFIX)
            if guard_process.poll() is not None:
                raise CaptureError('independent original guard Owner exited during Provider loss')
            guard['read'] = ssap_command(run, row, source,
                ['ssap-read', source['object']['path'], str(guard['handle'])], bytes.fromhex(guard['secret']), api=api)
            guard['alive_after_read_wall_ns'] = time.time_ns()
            if guard_process.poll() is not None:
                raise CaptureError('independent original guard must survive its actual peer read')
            run.save()
        guard['quit_wall_ns'] = time.time_ns(); run.save()
        guard_process.stdin.write('quit\n'); guard_process.stdin.flush()
        wait_output(guard_process, 2)
        if guard_process.returncode != 0:
            raise CaptureError('independent guard explicit cleanup failed')
        guard['owner_exit_wall_ns'] = time.time_ns()
        guard['cleanup'] = await_removed(run, target, guard['start'])
        run.save()
    row[PREFIX+'_status'] = PENDING; run.save()


def _ordinary(item):
    from ws73_ssap_owned import verify_output
    verify_output(item)
    credentials = item['credentials']
    if (credentials['uids'] != [1000]*4
            or set(credentials['capabilities']) != {'CapEff', 'CapPrm', 'CapAmb', 'CapInh'}
            or any(int(v, 16) for v in credentials['capabilities'].values()) or item['stderr']):
        raise CaptureError('original cap-zero owner and complete output required')


def _registration(row, item):
    _ordinary(item)
    target = row['owners'][item['target']]
    if (type(item['sender']) is not int or item['sender'] != 0 or type(item['target']) is not int or item['target'] != 1
            or any(type(item[k]) is not int for k in ('start', 'end', 'handle', 'pid', 'operations'))
            or not 0 < item['start'] < item['handle'] == item['end'] < 65535 or item['pid'] <= 0
            or item['operations'] != 1 or item['policy'] != 'allow'
            or item['args'] != [row['ssap_receipts'][0]['args'][0], '--adapter', target['owner']['path'],
                'ssap-serve', item['service'], item['uuid'], '1', '36', item['secret'], 'allow']
            or any(not re.fullmatch('[0-9a-f]{32}', item[k]) for k in ('service', 'uuid'))
            or not re.fullmatch('[0-9a-f]{64}', item['secret'])):
        raise CaptureError('one original READ-only allow publisher with full identity required')
    registration = f'SsapOwnedService: start={item["start"]} end={item["end"]} property={item["handle"]}; local registration only'
    lines = item['stdout'].splitlines()
    if lines.count(registration) != 1 or sum(l.startswith('SsapOwnedService:') for l in lines) != 1:
        raise CaptureError('one original registration required')
    return registration


def _response(row, item, packets):
    """Select exactly one actual paired READ_RSP; EIO never selects its code."""
    s, t = item['sender'], item['target']
    window = item['read']
    chosen = []
    for endpoint, direction in ((t, 'out'), (s, 'in')):
        owner, link = row['owners'][endpoint]['owner'], row['owners'][endpoint]['object']
        found = [p for p in packets if (p['bus'], p['device'], p['handle'], p['direction'])
                 == (owner['bus'], owner['device'], link['handle'], direction)
                 and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']
                 and bytes.fromhex(p['data'])[:2] == b'\x0a\0']
        if len(found) != 1 or found[0]['data'] not in ('0a000400090baf00', '0a000400090b0400'):
            raise CaptureError('one actual AF/4 READ_RSP on each original endpoint required')
        chosen.append(bytes.fromhex(found[0]['data'])[4:])
    if chosen[0] != chosen[1]:
        raise CaptureError('original Provider exit wire response must match at both ends')
    return chosen[0]


def _case(row, item, matched, packets):
    from ws73_application_client import ssap_receipt, ssap_error_receipt
    from ws73_ssap_command import _identity
    registration = _registration(row, item)
    guard = item['guard']; guard_registration = _registration(row, guard)
    identities = [_identity(owner) for owner in row['owners']]
    if (len({(i['index'], i['generation']) for i in identities}) != 2
            or len({(i['bus'], i['device']) for i in identities}) != 2):
        raise CaptureError('two original physical controller identities required')
    s, t, h = item['sender'], item['target'], item['handle']
    source, target = row['owners'][s], row['owners'][t]
    app, callback, data = item['read'], item['callback'], prompt(item['stdout'])
    if (any(k in item for k in ('reply_command', 'quit_wall_ns', 'steps'))
            or type(item['exit']) is not int or item['exit'] != -9 or type(item['owner_exit']) is not int or item['owner_exit'] != -9
            or callback['prompt'] != data or callback['publisher_pid'] != item['pid']
            or (data['index'], data['generation'], data['lifetime'], data['handle'], data['property'])
                != (identities[t]['index'], identities[t]['generation'], identities[t]['lifetime'], identities[t]['handle'], h)
            or guard['pid'] == item['pid'] or guard['handle'] == h
            or guard['service'] == item['service'] or guard['uuid'] == item['uuid'] or guard['secret'] == item['secret']):
        raise CaptureError('actual distinct guard and killed pending provider identity required')
    lines = item['stdout'].splitlines()
    bound = f'SsapReadProviderBound: handle={h}; stored value discarded, no rebind or fallback'
    decision = f'SsapAuthorizationDecision: request={data["request"]} property={h} data_type=0 write=false security=0 approved=true; local policy only'
    prompt_line = next(l for l in lines if l.startswith('SsapReadProviderPrompt:'))
    if (lines.count(bound) != 1 or lines.count(decision) != 1
            or sum(l.startswith('SsapReadProviderBound:') for l in lines) != 1
            or sum(l.startswith('SsapAuthorizationDecision:') for l in lines) != 1
            or any(l.startswith(('SsapReadProviderResult:', 'SsapReadProviderInput:')) for l in lines)
            or [lines.index(v) for v in (registration, bound, decision, prompt_line)] != sorted(lines.index(v) for v in (registration, bound, decision, prompt_line))):
        raise CaptureError('approved actual pending provider prompt without an application answer required')
    receipt = ssap_error_receipt(app, source, expected_errno=errno.EIO)
    if (app['api'] != ('c', 'python')[row['phase']] or app['ssap_operation'] != 'ssap-read' or app['ssap_handle'] != h
            or callback['supervisor_deadline_ns'] != app['ssap_supervisor_deadline_ns']
            or callback['exit_deadline_ns'] != min(data['deadline_ns'], receipt['deadline_ns'], callback['supervisor_deadline_ns'])):
        raise CaptureError('original C then Python peer READ and unchanged deadlines required')
    deadline = callback['exit_deadline_ns']
    times = [app['start_monotonic_ns'], receipt['call_ns'], callback['observed_monotonic_ns'],
             item['kill_before_monotonic_ns'], item['kill_returned_monotonic_ns'], item['owner_exit_monotonic_ns'],
             item['cleanup_completed_monotonic_ns'], deadline]
    if (any(type(v) is not int or v <= 0 for v in times) or times != sorted(times)
            or times[-2] >= deadline or not 0 < data['deadline_ns']-callback['observed_monotonic_ns'] <= 5_000_000_000
            or not item['kill_before_monotonic_ns'] <= receipt['returned_ns'] < deadline):
        raise CaptureError('kill, drain, cleanup and real refusal must fit both original deadlines')
    stamps = [guard['start_wall_ns'], guard['registered_wall_ns'], item['start_wall_ns'], item['bound_wall_ns'], app['start_wall_ns'],
              callback['observed_wall_ns'], item['kill_before_wall_ns'], item['kill_returned_wall_ns'],
              item['owner_exit_wall_ns'], item['cleanup']['start_wall_ns'], item['cleanup']['end_wall_ns'],
              app['end_wall_ns'], item['retired_read']['start_wall_ns'], item['retired_read']['end_wall_ns'],
              guard['read']['start_wall_ns'], guard['read']['end_wall_ns'], guard['alive_after_read_wall_ns'],
              item['end_wall_ns'], guard['quit_wall_ns'], guard['owner_exit_wall_ns'],
              guard['cleanup']['start_wall_ns'], guard['cleanup']['end_wall_ns'], guard['end_wall_ns']]
    if any(type(v) is not int or v <= 0 for v in stamps) or stamps != sorted(stamps):
        raise CaptureError('original guard/prompt/kill/cleanup/peer/guard chronology required')
    offset_lower, _ = _clock_bounds(item)
    _cleanup(row, item)
    if (type(guard['exit']) is not int or guard['exit'] != 0 or 'SsapReadProvider' in guard['stdout']
            or guard['stdout'].splitlines()[0] != guard_registration):
        raise CaptureError('independent original ordinary guard must stay live until explicit cleanup')
    guard_decisions = re.findall(r'^SsapAuthorizationDecision: request=(\d+) property=(\d+) data_type=0 write=false security=0 approved=true; local policy only$', guard['stdout'], re.M)
    if (len(guard_decisions) != 1 or int(guard_decisions[0][1]) != guard['handle']
            or sum(l.startswith('SsapAuthorizationDecision:') for l in guard['stdout'].splitlines()) != 1):
        raise CaptureError('one real independent guard READ approval required')
    ssap_receipt(guard['read'], source, expected_size=32)
    if (guard['read']['api'] != app['api'] or guard['read']['ssap_handle'] != guard['handle']
            or guard['read']['ssap_operation'] != 'ssap-read' or guard['read']['ssap_expected'] != guard['secret']):
        raise CaptureError('actual peer SDK must compare the independent guard value')
    cleanup = guard['cleanup']; lists = re.findall(r'^SsapLocalServices: (.+)$', cleanup['stdout'], re.M)
    if (type(cleanup['exit']) is not int or cleanup['exit'] != 0 or cleanup['stderr']
            or cleanup['args'] != [row['ssap_receipts'][0]['args'][0], '--adapter', target['owner']['path'], 'ssap-list']
            or len(lists) != 1 or any(v[0] == guard['start'] for v in json.loads(lists[0]))):
        raise CaptureError('independent guard explicit cleanup required')
    response = _response(row, item, packets)
    # _wire's causal barrier is generic: here it is a pre-SIGKILL observation,
    # never a fabricated Provider reply command or wait() completion time.
    wire, credit = _wire(row, item, matched, [
        (app, response, dict(observed_wall_ns=callback['observed_wall_ns'], reply_before_wall_ns=item['kill_before_wall_ns'])),
        (item['retired_read'], b'\x09\x0b\x04\0', None)])
    guard_wire, extra = _wire(row, guard, matched, [(guard['read'], b'\x09\x03'+bytes.fromhex(guard['secret']), None)])
    wire.extend(guard_wire)
    for endpoint in credit:
        credit[endpoint] += extra[endpoint]
    for leg in wire:
        for packet in leg.values():
            if packet['wall_ns'] != packet['fragments'][-1]['wall_ns']:
                raise CaptureError('original reassembled timestamp must match its final physical fragment')
    # Packet stamps are rounded down by mon_bin.c. Include the entire 0..999ns
    # quantization interval, then choose the latest possible monotonic time.
    # A wide supervisor end window never replaces the actual SDK return.
    for packet in wire[1].values():
        latest_mono = packet_interval(packet)[1]+999-offset_lower
        if latest_mono >= min(receipt['returned_ns'], deadline):
            raise CaptureError('paired Provider refusal must finish before actual SDK return and original deadlines')
    for ordinal in range(0, len(wire), 2):
        request, reply = wire[ordinal:ordinal+2]
        if (any(packet_interval(p['tx'])[1] > packet_interval(p['rx'])[0] for p in (request, reply))
                or packet_interval(request['rx'])[1] > packet_interval(reply['tx'])[0]):
            raise CaptureError('paired real request and refusal/value must preserve physical causal order')
    return dict(status=STATUS, version=VERSION, sender=s, target=t, api=app['api'],
                sdk_errno=receipt['errno'], peer_error=response[2], wire=wire,
                context=copy.deepcopy(dict(phase=row['phase'], owners=row['owners'], ssap_receipts=row['ssap_receipts'])),
                case=copy.deepcopy(item)), credit


def corroborate(row, matched, packets):
    if row.get(PREFIX+'_required', False) is not True:
        if any(k.startswith(PREFIX+'_') for k in row if k != PREFIX+'_required'):
            raise CaptureError('unrequested owner-exit evidence')
        return [], {0: 0, 1: 0}
    if (type(row.get(PREFIX+'_version')) is not int or row[PREFIX+'_version'] != VERSION
            or row.get('ssap_read_provider_required') is not True or row.get('ssap_read_provider_version') != 2
            or len(row.get(PREFIX+'_cases', [])) != 1 or len(row.get(PREFIX+'_guards', [])) != 1
            or row[PREFIX+'_cases'][0]['guard'] != row[PREFIX+'_guards'][0]):
        raise CaptureError('one original guard/case and provider v2 required')
    result, credit = _case(row, row[PREFIX+'_cases'][0], matched, packets)
    return [result], credit


def valid_summary(proof):
    try:
        rows = proof['proofs']
        if type(rows) is not list or len(rows) != 2:
            return False
        receivers = set()
        for phase, row in enumerate(rows):
            items = row[PREFIX]
            if type(row['phase']) is not int or row['phase'] != phase or len(items) != 1:
                return False
            item = items[0]; context, case = item['context'], item['case']
            if context['phase'] != phase or context['owners'] != row['owners'] or len(item['wire']) != 6:
                return False
            receiver = context['owners'][1]['owner']
            receivers.add((receiver['index'], receiver['generation']))
            packets = [copy.deepcopy(leg[side]) for leg in item['wire'] for side in ('tx', 'rx')]
            def matched(owner, direction, frame, window):
                key = (owner['owner']['bus'], owner['owner']['device'], owner['object']['handle'], direction, frame.hex())
                found = [p for p in packets if tuple(p[k] for k in ('bus', 'device', 'handle', 'direction', 'data')) == key
                         and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
                if len(found) != 1:
                    raise CaptureError('one exact retained Provider exit packet required')
                packets.remove(found[0]); return found[0]
            rebuilt, _ = _case(context, case, matched, packets)
            if packets or json.dumps(rebuilt, sort_keys=True) != json.dumps(item, sort_keys=True):
                return False
        return len(receivers) == 2
    except (KeyError, AttributeError, IndexError, TypeError, ValueError, StopIteration):
        return False


def valid_manifest(record):
    try:
        selected = record.get(PREFIX+'_requested', False)
        if type(selected) is not bool or boot_requested([t for arg in record.get('qemu_args', []) for t in arg.split()]) != selected:
            return False
        proof = record.get('channel_socket_corroboration', {})
        if not selected:
            return (record.get(PREFIX+'_acceptance', False) is False and PREFIX+'_version' not in record
                    and not any(PREFIX in row for row in proof.get('proofs', [])))
        from ws73_ssap_read_provider import valid_manifest as provider_manifest
        return (type(record.get(PREFIX+'_version')) is int and record[PREFIX+'_version'] == VERSION
                and record.get(PREFIX+'_acceptance') is True and record.get('ssap_read_provider_version') == 2
                and provider_manifest(record) and valid_summary(proof))
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
