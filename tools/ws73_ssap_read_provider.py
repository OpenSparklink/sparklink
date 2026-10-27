# SPDX-License-Identifier: GPL-2.0-only
"""Finite opt-in dynamic READ gate using the existing Owned and SDK supervisor.

Execution only records pending evidence. A PASS additionally needs both original
USB legs, unchanged Owned baseline verification and the actual peer comparison.
"""
import copy
import errno
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from ws73_capture import CaptureError, packet_interval

TOKEN = 'ws73.ssap_read_provider=1'
STATUS = 'DYNAMIC_READ_PROVIDER_APPLICATION_PAIRED_USB'
STATUS_V2 = 'DYNAMIC_READ_PROVIDER_SEQUENCE_APPLICATION_PAIRED_USB'
PENDING = 'DYNAMIC_READ_PROVIDER_PENDING_PAIRED_USB'
VERSION = 2
VERSIONS = (1, 2)
MODES = ('application-error-ff', 'empty', 'value32')
SIZE = 32
PROMPT = (r'^SsapReadProviderPrompt: token=p(?P<token>[1-9]\d*) request=(?P<request>[1-9]\d*) '
          r'index=(?P<index>\d+) generation=(?P<generation>[1-9]\d*) lifetime=(?P<lifetime>[1-9]\d*) '
          r'handle=(?P<handle>\d+) epoch=(?P<epoch>[1-9]\d*) security=(?P<security>\d+) '
          r'local_tcid=(?P<local_tcid>\d+) remote_tcid=(?P<remote_tcid>\d+) pi=(?P<pi>\d+) '
          r'property=(?P<property>[1-9]\d*) deadline_ns=(?P<deadline_ns>[1-9]\d*) '
          r'maximum_bytes=(?P<maximum_bytes>\d+); answer \'provide p(?P=token) HEX\' '
          r'\(\'-\' for empty\) or \'provider-error p(?P=token) AF\.\.FF\'$')


def requested(args, *, passthrough=None):
    selected = getattr(args, 'ssap_read_provider_verify', False)
    if type(selected) is not bool:
        raise ValueError('explicit read-provider selector boolean required')
    if not selected:
        return False
    if passthrough is None:
        passthrough = getattr(args, 'passthrough', False)
    incompatible = ('ssap_description_verify', 'parallel', 'parallel_business',
                    'application_client_verify', 'ssap_write_command_verify',
                    'ssap_owned_update_verify', 'ssap_update_delivery_verify',
                    'ssap_value_lengths_verify', 'ssap_requester_lifecycle_verify',
                    'ssap_owner_lifecycle_verify', 'ssap_initialization_verify',
                    'ssap_subscription_verify', 'ssap_sender_deadline_verify',
                    'channel_benchmark', 'dynamic_channel_verify', 'channel_fairness_verify',
                    'channel_socket_boundaries', 'channel_socket_close_prefix', 'channel_socket_burst')
    if (not passthrough or not getattr(args, 'ssap_owned_verify', False)
            or not getattr(args, 'channel_socket_verify', False)
            or getattr(args, 'channel_socket_rounds', 4) != 4
            or getattr(args, 'channel_socket_bytes', 61) != 61
            or getattr(args, 'security_agent', None) is not None
            or any(getattr(args, name, False) for name in incompatible)):
        raise ValueError('read-provider requires dedicated passthrough Owned ordinary61/4 gate')
    return True


def boot_requested(tokens):
    if type(tokens) not in (list, tuple) or any(type(t) is not str for t in tokens):
        raise ValueError('original tokenized boot arguments required')
    selected = [t for t in tokens if t == 'ws73.ssap_read_provider' or t.startswith('ws73.ssap_read_provider=')]
    if selected not in ([], [TOKEN]) or selected and tokens.count('ws73.ssap_owned=1') != 1:
        raise ValueError('one exact read-provider selector and Owned dependency required')
    return bool(selected)


def validate_inputs(package):
    from ws73_application_client import validate_consumer_sources
    validate_consumer_sources(package)
    here = Path(__file__).resolve().parent
    for name in ('ws73_ssap_read_provider.py', 'ws73_ssap_owned.py', 'ws73_application_client.py',
                 'ws73_ssap_value.py', 'ws73_ssap_command.py', 'ws73_ssap_update_delivery.py',
                 'ws73_channel_socket.py', 'ws73_target_control.py', 'ws73_target_guest.py', 'ws73_target_init.sh'):
        path = here / name
        matches = [r for r in package.get('inputs', []) if Path(r['path']).resolve() == path.resolve()]
        if len(matches) != 1 or matches[0]['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise CaptureError('fresh exact read-provider input required: ' + name)


def validate_rows(rows, selected):
    if type(selected) is not bool or type(rows) is not list or selected and len(rows) != 2:
        raise CaptureError('explicit provider selector and two original phases required')
    if selected and len({r.get('ssap_read_provider_version') for r in rows}) != 1:
        raise CaptureError('one original provider report version across both phases required')
    for phase, row in enumerate(rows):
        if type(row.get('ssap_read_provider_required', False)) is not bool or row.get('ssap_read_provider_required', False) != selected:
            raise CaptureError('read-provider request/row mismatch')
        if not selected:
            if any(k in row for k in ('ssap_read_provider_version', 'ssap_read_provider_cases', 'ssap_read_provider_tools')):
                raise CaptureError('unrequested read-provider evidence')
            continue
        if (type(row.get('phase')) is not int or row['phase'] != phase
                or type(row.get('ssap_read_provider_version')) is not int or row['ssap_read_provider_version'] not in VERSIONS
                or row.get('ssap_owned_required') is not True or len(row.get('ssap_owned', [])) != 4
                or {(i['sender'], i['policy']) for i in row['ssap_owned']} != {(s, p) for s in (0, 1) for p in ('allow', 'deny')}
                or type(row.get('ssap_read_provider_tools')) is not dict
                or len(row.get('ssap_read_provider_cases', [])) != 2
                or {i['sender'] for i in row['ssap_read_provider_cases']} != {0, 1}):
            raise CaptureError('complete Owned baseline and two provider directions required')


def prompts(text, count):
    matches = list(re.finditer(PROMPT, text, re.M))
    if (type(count) is not int or count not in (1, 2, 3) or len(matches) != count
            or sum(line.startswith('SsapReadProviderPrompt:') for line in text.splitlines()) != count):
        raise CaptureError('exact bounded original provider callback sequence required')
    result = []
    for match in matches:
        data = {k: int(v) for k, v in match.groupdict().items()}
        if (any(v > (1 << 64)-1 for v in data.values()) or data['maximum_bytes'] != 2042
                or (data['local_tcid'], data['remote_tcid'], data['pi'], data['security']) != (10, 10, 0, 0)):
            raise CaptureError('bounded basic-SMTC original provider context required')
        result.append(data)
    return result


def prompt(text):
    # Retained v1 reports contain exactly one positive callback.
    return prompts(text, 1)[0]


def execute(run, row):
    from ws73_application_client import ssap_commands, ssap_error_command
    from ws73_ssap_owned import publisher, wait_text, wait_output, await_removed
    from ws73_ssap_update_delivery import tool_records
    if row.get('ssap_owned_required') is not True or len(row.get('ssap_owned', [])) != 4:
        raise CaptureError('existing Owned gate must finish before provider extension')
    row.update(ssap_read_provider_required=True, ssap_read_provider_version=VERSION,
               ssap_read_provider_tools=tool_records(), ssap_read_provider_cases=[])
    run.save()
    for sender in (0, 1):
        source, target = row['owners'][sender], row['owners'][1-sender]
        with publisher(run, row, sender, 'allow', operations=1,
                       collection='ssap_read_provider_cases', label='read-provider') as (process, item):
            value = secrets.token_bytes(SIZE)
            if value.hex() == item['secret']:
                raise CaptureError('dynamic value must differ from discarded stored value')
            item.update(dynamic_value=value.hex(), bytes=SIZE, prepared_wall_ns=time.time_ns(), steps=[])
            run.save()
            process.stdin.write('provider\n'); process.stdin.flush()
            found, _ = wait_text(process, Path(item['output_files'][0]),
                r'^SsapReadProviderBound: handle=(\d+); stored value discarded, no rebind or fallback$',
                time.monotonic()+5, max_count=1)
            if found != [str(item['handle'])]:
                raise CaptureError('same original publisher must bind exactly one provider')
            item['bound_wall_ns'] = time.time_ns(); run.save()

            api = 'c' if (row['phase']+sender)%2 == 0 else 'python'
            for ordinal, mode in enumerate(MODES, 1):
                step = dict(mode=mode)
                item['steps'].append(step); run.save()

                def provide(app, original_deadline_ns):
                    step['read'] = app; run.save()
                    _, text = wait_text(process, Path(item['output_files'][0]), PROMPT,
                        min(original_deadline_ns/1e9, time.monotonic()+5),
                        min_count=ordinal, max_count=ordinal)
                    observed = time.monotonic_ns()
                    data = prompts(text, ordinal)[-1]
                    identity = target['owner']; link = target['object']
                    if ((data['index'], data['generation'], data['lifetime'], data['handle'], data['property'])
                            != (identity['index'], identity['generation'], link['lifetime'], link['handle'], item['handle'])
                            or not observed < data['deadline_ns'] <= observed+5_000_000_000
                            or data['deadline_ns'] > original_deadline_ns
                            or ordinal > 1 and any(data[k] <= item['steps'][-2]['callback']['prompt'][k]
                                                   for k in ('token', 'request'))):
                        raise CaptureError('original live publisher callback identity/deadline/sequence required')
                    step['callback'] = dict(prompt=data, observed_monotonic_ns=observed,
                        observed_wall_ns=time.time_ns(), publisher_pid=process.pid,
                        supervisor_deadline_ns=original_deadline_ns)
                    step['reply_command'] = (f'provider-error p{data["token"]} FF' if mode == MODES[0]
                        else f'provide p{data["token"]} ' + ('-' if mode == MODES[1] else value.hex()))
                    run.save()
                    step['callback'].update(reply_before_monotonic_ns=time.monotonic_ns(), reply_before_wall_ns=time.time_ns())
                    process.stdin.write(step['reply_command']+'\n'); process.stdin.flush()
                    step['callback'].update(replied_monotonic_ns=time.monotonic_ns(), replied_wall_ns=time.time_ns())
                    if step['callback']['replied_monotonic_ns'] >= data['deadline_ns']:
                        raise CaptureError('provider reply missed original callback deadline')
                    run.save()

                args = ['ssap-read', source['object']['path'], str(item['handle'])]
                if mode == MODES[0]:
                    step['read'] = ssap_error_command(run, row, source, args, errno.EIO,
                                                    api=api, after_start=provide)
                else:
                    expected = b'' if mode == MODES[1] else value
                    step['read'] = ssap_commands(run, row, [(source, args, expected)],
                        api=api, expected_size=len(expected), after_start=provide)[0]
                run.save()
            item['quit_wall_ns'] = time.time_ns(); run.save()
            process.stdin.write('quit\n'); process.stdin.flush()
            wait_output(process, 2)
            if process.returncode != 0:
                raise CaptureError('original provider explicit cleanup failed')
            item['owner_exit_wall_ns'] = time.time_ns()
            item['cleanup'] = await_removed(run, target, item['start'])
            item['retired_read'] = run.command([str(run.args.slctl), '--adapter', source['owner']['path'],
                'ssap-read', source['object']['path'], str(item['handle']), '0'], 10, collection='ssap_read_providers')
            run.save()
    row['ssap_read_provider_status'] = PENDING; run.save()


def _publisher(row, item):
    from ws73_ssap_command import _identity
    from ws73_ssap_owned import verify_output
    verify_output(item)
    if (type(row['phase']) is not int or row['phase'] not in (0, 1) or len(row['owners']) != 2
            or any(type(item[k]) is not int for k in ('sender', 'target', 'start', 'end', 'handle', 'pid', 'bytes', 'operations'))
            or item['sender'] not in (0, 1) or item['target'] != 1-item['sender']
            or not 0 < item['handle'] < 65535 or item['pid'] <= 0
            or not 0 < item['start'] < item['handle'] == item['end']
            or item['bytes'] != SIZE or item['operations'] != 1 or item['policy'] != 'allow'):
        raise CaptureError('original provider role/direction/READ property required')
    identities = [_identity(o) for o in row['owners']]
    if (len({(i['index'], i['generation']) for i in identities}) != 2
            or len({(i['bus'], i['device']) for i in identities}) != 2):
        raise CaptureError('two original physical controller identities required')
    s, t, h = item['sender'], item['target'], item['handle']
    source, target = row['owners'][s], row['owners'][t]
    value = bytes.fromhex(item['dynamic_value'])
    if len(value) != SIZE or item['dynamic_value'] == item['secret']:
        raise CaptureError('fresh prepared dynamic value required')
    if (item['args'] != [row['ssap_receipts'][0]['args'][0], '--adapter', target['owner']['path'],
            'ssap-serve', item['service'], item['uuid'], '1', '36', item['secret'], 'allow']
            or any(not re.fullmatch('[0-9a-f]{32}', item[k]) for k in ('service', 'uuid'))
            or not re.fullmatch('[0-9a-f]{64}', item['secret'])
            or type(item['exit']) is not int or item['exit'] != 0 or item['stderr']
            or item['credentials']['uids'] != [1000]*4
            or set(item['credentials']['capabilities']) != {'CapEff', 'CapPrm', 'CapAmb', 'CapInh'}
            or any(int(v, 16) for v in item['credentials']['capabilities'].values())):
        raise CaptureError('same cap-zero CLI publisher and explicit successful exit required')
    return identities, source, target, value


def _case(row, item, matched):
    from ws73_application_client import ssap_receipt
    identities, source, target, value = _publisher(row, item)
    s, t, h = item['sender'], item['target'], item['handle']
    data = prompt(item['stdout']); callback = item['callback']; app = item['read']; removed = item['retired_read']
    if (callback['prompt'] != data or any(type(v) is not int for v in callback['prompt'].values())
            or type(callback['publisher_pid']) is not int or callback['publisher_pid'] != item['pid']
            or (data['index'], data['generation'], data['lifetime'], data['handle'], data['property'])
                != (identities[t]['index'], identities[t]['generation'], identities[t]['lifetime'], identities[t]['handle'], h)
            or item['reply_command'] != f'provide p{data["token"]} {value.hex()}'):
        raise CaptureError('callback must belong to the original publisher and complete connection lifetime')
    bound = f'SsapReadProviderBound: handle={h}; stored value discarded, no rebind or fallback'
    registration = f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only'
    decisions = re.findall(r'^SsapAuthorizationDecision: request=(\d+) property=(\d+) data_type=0 write=false security=0 approved=true; local policy only$', item['stdout'], re.M)
    if (item['stdout'].splitlines().count(registration) != 1
            or sum(line.startswith('SsapOwnedService:') for line in item['stdout'].splitlines()) != 1
            or item['stdout'].splitlines().count(bound) != 1
            or sum(line.startswith('SsapReadProviderBound:') for line in item['stdout'].splitlines()) != 1
            or decisions != [(str(data['request']), str(h))]
            or sum(line.startswith('SsapAuthorizationDecision:') for line in item['stdout'].splitlines()) != 1
            or 'SsapReadProviderInput:' in item['stdout']):
        raise CaptureError('one separate actual approval and one bound provider callback required')
    stamps = [item['start_wall_ns'], item['prepared_wall_ns'], item['bound_wall_ns'], app['start_wall_ns'],
              app['ssap_released_wall_ns'], callback['observed_wall_ns'], callback['reply_before_wall_ns'], callback['replied_wall_ns'],
              app['end_wall_ns'], item['quit_wall_ns'], item['owner_exit_wall_ns'],
              item['cleanup']['start_wall_ns'], item['cleanup']['end_wall_ns'],
              removed['start_wall_ns'], removed['end_wall_ns'], item['end_wall_ns']]
    if any(type(v) is not int or v <= 0 for v in stamps) or stamps != sorted(stamps):
        raise CaptureError('original ordered prepare/bind/read/callback/cleanup intervals required')
    times = [app['ssap_release_monotonic_ns'], callback['observed_monotonic_ns'],
             callback['reply_before_monotonic_ns'], callback['replied_monotonic_ns'],
             data['deadline_ns'], callback['supervisor_deadline_ns']]
    if (any(type(v) is not int or v <= 0 for v in times) or times != sorted(times)
            or times[3] >= times[4] or not 0 < times[4]-times[1] <= 5_000_000_000
            or times[-1] != times[0]+7_000_000_000):
        raise CaptureError('unchanged callback and supervisor monotonic deadlines required')
    ssap_receipt(app, source, expected_size=SIZE)
    if (app['api'] != ('c' if (row['phase']+s)%2 == 0 else 'python')
            or app['ssap_operation'] != 'ssap-read' or app['ssap_handle'] != h
            or app['ssap_expected'] != value.hex()):
        raise CaptureError('actual opposite C/Python client must compare the prepared value')
    _cleanup(row, item)
    wire, credit = _wire(row, item, matched, [(app, b'\x09\x03'+value, callback),
                                             (removed, b'\x09\x0b\x04\0', None)])
    return dict(status=STATUS, sender=s, target=t, api=app['api'], bytes=SIZE, value=value.hex(), wire=wire,
                context=copy.deepcopy(dict(phase=row['phase'], owners=row['owners'], ssap_receipts=row['ssap_receipts'])),
                case=copy.deepcopy(item)), credit


def _cleanup(row, item):
    s, t, h = item['sender'], item['target'], item['handle']
    source, target = row['owners'][s], row['owners'][t]
    removed = item['retired_read']
    cleanup = item['cleanup']; lists = re.findall(r'^SsapLocalServices: (.+)$', cleanup['stdout'], re.M)
    if (type(cleanup['exit']) is not int or cleanup['exit'] != 0 or cleanup['stderr']
            or cleanup['args'] != [row['ssap_receipts'][0]['args'][0], '--adapter', target['owner']['path'], 'ssap-list']
            or len(lists) != 1 or any(v[0] == item['start'] for v in json.loads(lists[0]))
            or removed['args'] != [row['ssap_receipts'][0]['args'][0], '--adapter', source['owner']['path'],
                                   'ssap-read', source['object']['path'], str(h), '0']
            or type(removed['exit']) is not int or removed['exit'] == 0 or 'peer read error 4' not in removed['stderr']):
        raise CaptureError('original owner cleanup and actual retired remote refusal required')


def paired_leg(row, sender, receiver, frame, window, matched):
    """One real paired frame, shared by complete exchanges and pending Down."""
    leg = dict(tx=matched(row['owners'][sender], 'out', frame, window),
               rx=matched(row['owners'][receiver], 'in', frame, window))
    validate_paired_leg(row,sender,receiver,frame,window,leg)
    return leg


def validate_paired_leg(row,sender,receiver,frame,window,leg):
    from ws73_ssap_command import _identity
    from ws73_ssap_value import command_packet
    identities=[_identity(o) for o in row['owners']]
    for side, endpoint, direction in [('tx', sender, 'out'), ('rx', receiver, 'in')]:
        packet = leg[side]; command_packet(packet, frame, window)
        for fragment in [packet, *packet['fragments']]:
            if (any(type(fragment[k]) is not int for k in ('bus', 'device', 'handle'))
                    or tuple(fragment[k] for k in ('bus', 'device', 'handle', 'direction'))
                        != (identities[endpoint]['bus'], identities[endpoint]['device'], identities[endpoint]['handle'], direction)):
                raise CaptureError('original endpoint required on every provider USB fragment')
    return leg


def _wire(row, item, matched, exchanges, *, requests=None, write_version=1):
    from ws73_ssap_value import physical_sends
    if type(write_version)is not int or write_version not in (1,2,3):raise CaptureError('explicit WRITE capture version required')
    s, t, h = item['sender'], item['target'], item['handle']
    wire = []; credit = {0: 0, 1: 0}
    request = b'\x08\x03'+h.to_bytes(2, 'little')+b'\0'
    if requests is not None and (len(requests)!=len(exchanges) or any(type(p) is not bytes for p in requests)):
        raise CaptureError('explicit expected request for every provider exchange required')
    for ordinal, (window, response, callback) in enumerate(exchanges):
        if requests is not None:request=requests[ordinal]
        if response is None and not(write_version==3 and request[:2]==b'\x0c\x03'):
            raise CaptureError('only explicit version3 Write Command has no response')
        legs=[(s,t,request)] if response is None else [(s,t,request),(t,s,response)]
        for sender, receiver, pdu in legs:
            frame = b'\x0a\0'+len(pdu).to_bytes(2, 'little')+pdu
            if write_version==2:
                from ws73_ssap_value import pair_wire,fragment_parts
                from ws73_ssap_value import physical_packets,wire_interval as interval
                leg=pair_wire(row,matched,row['owners'][sender],row['owners'][receiver],pdu,window)
                parts=fragment_parts(pdu) if len(pdu)>2042 else [pdu]
                for n,part in enumerate(parts):
                    physical={side:physical_packets(leg[side])[n] for side in ('tx','rx')}
                    validate_paired_leg(row,sender,receiver,b'\x0a\0'+len(part).to_bytes(2,'little')+part,window,physical)
            else:
                leg = paired_leg(row, sender, receiver, frame, window, matched)
                interval=packet_interval
            if callback is not None:
                if sender == s and interval(leg['rx'])[1] > callback['observed_wall_ns']:
                    raise CaptureError('original peer request must precede the observed provider callback')
                if sender == t and interval(leg['tx'])[0] < callback['reply_before_wall_ns']:
                    raise CaptureError('dynamic response cannot precede the original provider answer')
            wire.append(leg); credit[sender] += physical_sends(leg['tx'])
    return wire, credit


def _case_v2(row, item, matched):
    from ws73_application_client import ssap_receipt, ssap_error_receipt
    identities, source, target, value = _publisher(row, item)
    s, t, h = item['sender'], item['target'], item['handle']
    if (any(k in item for k in ('read', 'callback', 'reply_command'))
            or type(item.get('steps')) is not list or len(item['steps']) != 3
            or [step.get('mode') for step in item['steps']] != list(MODES)):
        raise CaptureError('version2 requires the complete ordered error/empty/value sequence')
    data = prompts(item['stdout'], 3)
    if (any(data[n][k] >= data[n+1][k] for n in (0, 1) for k in ('token', 'request'))
            or any({k:v for k,v in d.items() if k not in ('token', 'request', 'deadline_ns')}
                   != {k:v for k,v in data[0].items() if k not in ('token', 'request', 'deadline_ns')} for d in data)):
        raise CaptureError('fresh tokens and requests in one unchanged physical provider context required')
    registration = f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only'
    bound = f'SsapReadProviderBound: handle={h}; stored value discarded, no rebind or fallback'
    lines = item['stdout'].splitlines()
    if (lines.count(registration) != 1 or lines.count(bound) != 1
            or sum(l.startswith('SsapOwnedService:') for l in lines) != 1
            or sum(l.startswith('SsapReadProviderBound:') for l in lines) != 1
            or sum(l.startswith('SsapAuthorizationDecision:') for l in lines) != 3
            or sum(l.startswith('SsapReadProviderResult:') for l in lines) != 3
            or any(l.startswith('SsapReadProviderInput:') for l in lines)):
        raise CaptureError('one bound owner and three actual policy/value outcomes required')
    line_order = [lines.index(registration), lines.index(bound)]
    stamps = [item['start_wall_ns'], item['prepared_wall_ns'], item['bound_wall_ns']]
    exchanges = []; outcomes = []
    for ordinal, (step, d) in enumerate(zip(item['steps'], data, strict=True)):
        callback, app = step['callback'], step['read']
        expected = b'' if ordinal < 2 else value
        status = 255 if ordinal == 0 else 0
        command = (f'provider-error p{d["token"]} FF' if ordinal == 0
                   else f'provide p{d["token"]} ' + ('-' if ordinal == 1 else value.hex()))
        if (callback['prompt'] != d or any(type(v) is not int for v in callback['prompt'].values())
                or type(callback['publisher_pid']) is not int or callback['publisher_pid'] != item['pid']
                or (d['index'], d['generation'], d['lifetime'], d['handle'], d['property'])
                   != (identities[t]['index'], identities[t]['generation'], identities[t]['lifetime'], identities[t]['handle'], h)
                or step['reply_command'] != command):
            raise CaptureError('every value outcome must belong to the same original publisher and lifetime')
        decision = f'SsapAuthorizationDecision: request={d["request"]} property={h} data_type=0 write=false security=0 approved=true; local policy only'
        result = f'SsapReadProviderResult: request={d["request"]} property={h} status={status} bytes={len(expected)}; application response only'
        prompt_line = [l for l in lines if l.startswith(f'SsapReadProviderPrompt: token=p{d["token"]} ') ]
        if lines.count(decision) != 1 or lines.count(result) != 1 or len(prompt_line) != 1:
            raise CaptureError('separate exact approval, value callback and application result required')
        line_order.extend([lines.index(decision), lines.index(prompt_line[0]), lines.index(result)])
        if (app['api'] != ('c' if (row['phase']+s)%2 == 0 else 'python')
                or app['ssap_operation'] != 'ssap-read' or app['ssap_handle'] != h):
            raise CaptureError('actual same retained C/Python peer READ consumer required')
        if ordinal == 0:
            receipt = ssap_error_receipt(app, source, expected_errno=errno.EIO)
            origin = app['start_monotonic_ns']
            if callback['supervisor_deadline_ns'] != app['ssap_supervisor_deadline_ns']:
                raise CaptureError('original negative SDK supervisor deadline required')
            stamps.append(app['start_wall_ns'])
            outcomes.append(dict(mode=step['mode'], application_status=status, sdk_errno=receipt['errno']))
        else:
            ssap_receipt(app, source, expected_size=len(expected))
            if app['ssap_expected'] != expected.hex():
                raise CaptureError('empty or random value must be completely checked by the actual SDK')
            origin = app['ssap_release_monotonic_ns']
            stamps.extend([app['start_wall_ns'], app['ssap_released_wall_ns']])
            outcomes.append(dict(mode=step['mode'], application_status=0, bytes=len(expected)))
        times = [origin, callback['observed_monotonic_ns'], callback['reply_before_monotonic_ns'],
                 callback['replied_monotonic_ns'], d['deadline_ns'], callback['supervisor_deadline_ns']]
        if (any(type(v) is not int or v <= 0 for v in times) or times != sorted(times)
                or times[3] >= times[4] or not 0 < times[4]-times[1] <= 5_000_000_000
                or times[-1] != times[0]+7_000_000_000):
            raise CaptureError('each callback and supervisor retain their own original deadline')
        stamps.extend([callback['observed_wall_ns'], callback['reply_before_wall_ns'],
                       callback['replied_wall_ns'], app['end_wall_ns']])
        response = b'\x09\x0b\xff\0' if ordinal == 0 else b'\x09\x03'+expected
        exchanges.append((app, response, callback))
    removed = item['retired_read']
    stamps.extend([item['quit_wall_ns'], item['owner_exit_wall_ns'], item['cleanup']['start_wall_ns'],
                   item['cleanup']['end_wall_ns'], removed['start_wall_ns'], removed['end_wall_ns'], item['end_wall_ns']])
    if (line_order != sorted(line_order) or len(set(line_order)) != len(line_order)
            or any(type(v) is not int or v <= 0 for v in stamps) or stamps != sorted(stamps)):
        raise CaptureError('original sequential error/empty/recovery and cleanup chronology required')
    _cleanup(row, item)
    exchanges.append((removed, b'\x09\x0b\x04\0', None))
    wire, credit = _wire(row, item, matched, exchanges)
    # Completion accounting uses actual TX fragments once. Opposite RX proves
    # delivery; it never credits a second physical submission.
    for ordinal in range(0, len(wire), 2):
        request, response = wire[ordinal:ordinal+2]
        if (any(packet_interval(p['tx'])[1] > packet_interval(p['rx'])[0] for p in (request, response))
                or packet_interval(request['rx'])[1] > packet_interval(response['tx'])[0]):
            raise CaptureError('paired request and response must preserve physical causal order')
    return dict(status=STATUS_V2, version=2, sender=s, target=t, api=item['steps'][0]['read']['api'],
                bytes=SIZE, value=value.hex(), outcomes=outcomes, wire=wire,
                context=copy.deepcopy(dict(phase=row['phase'], owners=row['owners'], ssap_receipts=row['ssap_receipts'])),
                case=copy.deepcopy(item)), credit


def corroborate(row, matched):
    if row.get('ssap_read_provider_required', False) is not True:
        if any(k in row for k in ('ssap_read_provider_cases', 'ssap_read_provider_version')):
            raise CaptureError('unrequested provider evidence')
        return [], {0: 0, 1: 0}
    if (row.get('ssap_owned_required') is not True or len(row.get('ssap_owned', [])) != 4
            or type(row.get('ssap_read_provider_version')) is not int or row['ssap_read_provider_version'] not in VERSIONS
            or len(row.get('ssap_read_provider_cases', [])) != 2
            or {i['sender'] for i in row['ssap_read_provider_cases']} != {0, 1}):
        raise CaptureError('original Owned baseline and two provider cases required')
    proofs = []; credit = {0: 0, 1: 0}
    for item in row['ssap_read_provider_cases']:
        verify = _case if row['ssap_read_provider_version'] == 1 else _case_v2
        proof, extra = verify(row, item, matched); proofs.append(proof)
        for endpoint in credit: credit[endpoint] += extra[endpoint]
    if len({p['value'] for p in proofs}) != 2:
        raise CaptureError('distinct original prepared provider values required')
    return proofs, credit


def valid_summary(proof, *, version=None):
    try:
        rows = proof['proofs']; values = set()
        if version is not None and (type(version) is not int or version not in VERSIONS):
            return False
        observed_version = version
        if type(rows) is not list or len(rows) != 2:
            return False
        for phase, row in enumerate(rows):
            items = row['ssap_read_providers']
            if (type(row['phase']) is not int or row['phase'] != phase or len(items) != 2
                    or {i['sender'] for i in items} != {0, 1}):
                return False
            for item in items:
                context, case = item['context'], item['case']
                item_version = item.get('version', 1)
                if type(item_version) is not int or item_version not in VERSIONS:
                    return False
                if observed_version is None: observed_version = item_version
                if item_version != observed_version:
                    return False
                if (context['phase'] != phase or context['owners'] != row['owners']
                        or item['value'] in values or len(item['wire']) != (4 if item_version == 1 else 8)):
                    return False
                packets = [copy.deepcopy(leg[side]) for leg in item['wire'] for side in ('tx', 'rx')]
                def matched(owner, direction, frame, window):
                    wanted = (owner['owner']['bus'], owner['owner']['device'], owner['object']['handle'], direction, frame.hex())
                    found = [p for p in packets if tuple(p[k] for k in ('bus', 'device', 'handle', 'direction', 'data')) == wanted
                             and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
                    if len(found) != 1:
                        raise CaptureError('one original retained provider packet required')
                    packets.remove(found[0]); return found[0]
                rebuilt, _ = (_case if item_version == 1 else _case_v2)(context, case, matched)
                if packets or json.dumps(rebuilt, sort_keys=True) != json.dumps(item, sort_keys=True):
                    return False
                values.add(item['value'])
        return True
    except (KeyError, AttributeError, IndexError, TypeError, ValueError):
        return False


def valid_manifest(record):
    try:
        selected = record.get('ssap_read_provider_requested', False)
        if type(selected) is not bool or boot_requested([t for arg in record.get('qemu_args', []) for t in arg.split()]) != selected:
            return False
        proof = record.get('channel_socket_corroboration', {})
        if not selected:
            return (record.get('ssap_read_provider_acceptance', False) is False
                    and 'ssap_read_provider_version' not in record
                    and not any('ssap_read_providers' in row for row in proof.get('proofs', [])))
        return (type(record.get('ssap_read_provider_version')) is int and record['ssap_read_provider_version'] in VERSIONS
                and record.get('ssap_read_provider_acceptance') is True
                and record.get('ssap_owned_acceptance') is True
                and record.get('ordinary_channel_socket_acceptance') is True
                and record.get('status') == 'PASSTHROUGH_SUPPORT_PASS'
                and type(record.get('qemu_exit')) is int and record['qemu_exit'] == 0 and valid_summary(proof, version=record['ssap_read_provider_version']))
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
