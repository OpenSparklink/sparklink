# SPDX-License-Identifier: GPL-2.0-only
"""Finite opt-in dynamic READ gate using the existing Owned and SDK supervisor.

Execution only records pending evidence. A PASS additionally needs both original
USB legs, unchanged Owned baseline verification and the actual peer comparison.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from ws73_capture import CaptureError, packet_interval

TOKEN = 'ws73.ssap_read_provider=1'
STATUS = 'DYNAMIC_READ_PROVIDER_APPLICATION_PAIRED_USB'
PENDING = 'DYNAMIC_READ_PROVIDER_PENDING_PAIRED_USB'
VERSION = 1
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
    for phase, row in enumerate(rows):
        if type(row.get('ssap_read_provider_required', False)) is not bool or row.get('ssap_read_provider_required', False) != selected:
            raise CaptureError('read-provider request/row mismatch')
        if not selected:
            if any(k in row for k in ('ssap_read_provider_version', 'ssap_read_provider_cases', 'ssap_read_provider_tools')):
                raise CaptureError('unrequested read-provider evidence')
            continue
        if (type(row.get('phase')) is not int or row['phase'] != phase
                or type(row.get('ssap_read_provider_version')) is not int or row['ssap_read_provider_version'] != VERSION
                or row.get('ssap_owned_required') is not True or len(row.get('ssap_owned', [])) != 4
                or {(i['sender'], i['policy']) for i in row['ssap_owned']} != {(s, p) for s in (0, 1) for p in ('allow', 'deny')}
                or type(row.get('ssap_read_provider_tools')) is not dict
                or len(row.get('ssap_read_provider_cases', [])) != 2
                or {i['sender'] for i in row['ssap_read_provider_cases']} != {0, 1}):
            raise CaptureError('complete Owned baseline and two provider directions required')


def prompt(text):
    matches = list(re.finditer(PROMPT, text, re.M))
    if len(matches) != 1 or sum(line.startswith('SsapReadProviderPrompt:') for line in text.splitlines()) != 1:
        raise CaptureError('one exact actual provider callback required')
    result = {k: int(v) for k, v in matches[0].groupdict().items()}
    if (any(v > (1 << 64)-1 for v in result.values()) or result['maximum_bytes'] != 2042
            or (result['local_tcid'], result['remote_tcid'], result['pi'], result['security']) != (10, 10, 0, 0)):
        raise CaptureError('bounded basic-SMTC original provider context required')
    return result


def execute(run, row):
    from ws73_application_client import ssap_commands
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
            item.update(dynamic_value=value.hex(), bytes=SIZE, prepared_wall_ns=time.time_ns())
            run.save()
            process.stdin.write('provider\n'); process.stdin.flush()
            found, _ = wait_text(process, Path(item['output_files'][0]),
                r'^SsapReadProviderBound: handle=(\d+); stored value discarded, no rebind or fallback$',
                time.monotonic()+5, max_count=1)
            if found != [str(item['handle'])]:
                raise CaptureError('same original publisher must bind exactly one provider')
            item['bound_wall_ns'] = time.time_ns(); run.save()

            def provide(app, original_deadline_ns):
                item['read'] = app; run.save()
                _, text = wait_text(process, Path(item['output_files'][0]), PROMPT,
                    min(original_deadline_ns/1e9, time.monotonic()+5), max_count=1)
                observed = time.monotonic_ns()
                data = prompt(text)
                identity = target['owner']; link = target['object']
                if ((data['index'], data['generation'], data['lifetime'], data['handle'], data['property'])
                        != (identity['index'], identity['generation'], link['lifetime'], link['handle'], item['handle'])
                        or not observed < data['deadline_ns'] <= observed+5_000_000_000
                        or data['deadline_ns'] > original_deadline_ns):
                    raise CaptureError('original live publisher callback identity/deadline required')
                item['callback'] = dict(prompt=data, observed_monotonic_ns=observed,
                    observed_wall_ns=time.time_ns(), publisher_pid=process.pid,
                    supervisor_deadline_ns=original_deadline_ns)
                item['reply_command'] = f'provide p{data["token"]} {value.hex()}'
                run.save()
                item['callback'].update(reply_before_monotonic_ns=time.monotonic_ns(), reply_before_wall_ns=time.time_ns())
                process.stdin.write(item['reply_command']+'\n'); process.stdin.flush()
                item['callback'].update(replied_monotonic_ns=time.monotonic_ns(), replied_wall_ns=time.time_ns())
                if item['callback']['replied_monotonic_ns'] >= data['deadline_ns']:
                    raise CaptureError('provider reply missed original callback deadline')
                run.save()

            item['read'] = ssap_commands(run, row,
                [(source, ['ssap-read', source['object']['path'], str(item['handle'])], value)],
                api='c' if (row['phase']+sender)%2 == 0 else 'python', expected_size=SIZE,
                after_start=provide)[0]
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


def _case(row, item, matched):
    from ws73_application_client import ssap_receipt
    from ws73_ssap_command import _identity
    from ws73_ssap_owned import verify_output
    from ws73_ssap_value import command_packet, physical_sends
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
    cleanup = item['cleanup']; lists = re.findall(r'^SsapLocalServices: (.+)$', cleanup['stdout'], re.M)
    if (type(cleanup['exit']) is not int or cleanup['exit'] != 0 or cleanup['stderr']
            or cleanup['args'] != [row['ssap_receipts'][0]['args'][0], '--adapter', target['owner']['path'], 'ssap-list']
            or len(lists) != 1 or any(v[0] == item['start'] for v in json.loads(lists[0]))
            or removed['args'] != [row['ssap_receipts'][0]['args'][0], '--adapter', source['owner']['path'],
                                   'ssap-read', source['object']['path'], str(h), '0']
            or type(removed['exit']) is not int or removed['exit'] == 0 or 'peer read error 4' not in removed['stderr']):
        raise CaptureError('original owner cleanup and actual retired remote refusal required')
    wire = []; credit = {0: 0, 1: 0}
    request = b'\x08\x03'+h.to_bytes(2, 'little')+b'\0'
    for window, response in [(app, b'\x09\x03'+value), (removed, b'\x09\x0b\x04\0')]:
        for sender, receiver, pdu in [(s, t, request), (t, s, response)]:
            frame = b'\x0a\0'+len(pdu).to_bytes(2, 'little')+pdu
            leg = dict(tx=matched(row['owners'][sender], 'out', frame, window),
                       rx=matched(row['owners'][receiver], 'in', frame, window))
            for side, endpoint, direction in [('tx', sender, 'out'), ('rx', receiver, 'in')]:
                packet = leg[side]; command_packet(packet, frame, window)
                for fragment in [packet, *packet['fragments']]:
                    if (any(type(fragment[k]) is not int for k in ('bus', 'device', 'handle'))
                            or tuple(fragment[k] for k in ('bus', 'device', 'handle', 'direction'))
                                != (identities[endpoint]['bus'], identities[endpoint]['device'], identities[endpoint]['handle'], direction)):
                        raise CaptureError('original endpoint required on every provider USB fragment')
            if window is app:
                if sender == s and packet_interval(leg['rx'])[1] > callback['observed_wall_ns']:
                    raise CaptureError('original peer request must precede the observed provider callback')
                if sender == t and packet_interval(leg['tx'])[0] < callback['reply_before_wall_ns']:
                    raise CaptureError('dynamic response cannot precede the original provider answer')
            wire.append(leg); credit[sender] += physical_sends(leg['tx'])
    return dict(status=STATUS, sender=s, target=t, api=app['api'], bytes=SIZE, value=value.hex(), wire=wire,
                context=copy.deepcopy(dict(phase=row['phase'], owners=row['owners'], ssap_receipts=row['ssap_receipts'])),
                case=copy.deepcopy(item)), credit


def corroborate(row, matched):
    if row.get('ssap_read_provider_required', False) is not True:
        if any(k in row for k in ('ssap_read_provider_cases', 'ssap_read_provider_version')):
            raise CaptureError('unrequested provider evidence')
        return [], {0: 0, 1: 0}
    if (row.get('ssap_owned_required') is not True or len(row.get('ssap_owned', [])) != 4
            or type(row.get('ssap_read_provider_version')) is not int or row['ssap_read_provider_version'] != VERSION
            or len(row.get('ssap_read_provider_cases', [])) != 2
            or {i['sender'] for i in row['ssap_read_provider_cases']} != {0, 1}):
        raise CaptureError('original Owned baseline and two provider cases required')
    proofs = []; credit = {0: 0, 1: 0}
    for item in row['ssap_read_provider_cases']:
        proof, extra = _case(row, item, matched); proofs.append(proof)
        for endpoint in credit: credit[endpoint] += extra[endpoint]
    if len({p['value'] for p in proofs}) != 2:
        raise CaptureError('distinct original prepared provider values required')
    return proofs, credit


def valid_summary(proof):
    try:
        rows = proof['proofs']; values = set()
        if type(rows) is not list or len(rows) != 2:
            return False
        for phase, row in enumerate(rows):
            items = row['ssap_read_providers']
            if (type(row['phase']) is not int or row['phase'] != phase or len(items) != 2
                    or {i['sender'] for i in items} != {0, 1}):
                return False
            for item in items:
                context, case = item['context'], item['case']
                if (context['phase'] != phase or context['owners'] != row['owners']
                        or item['value'] in values or len(item['wire']) != 4):
                    return False
                packets = [copy.deepcopy(leg[side]) for leg in item['wire'] for side in ('tx', 'rx')]
                def matched(owner, direction, frame, window):
                    wanted = (owner['owner']['bus'], owner['owner']['device'], owner['object']['handle'], direction, frame.hex())
                    found = [p for p in packets if tuple(p[k] for k in ('bus', 'device', 'handle', 'direction', 'data')) == wanted
                             and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
                    if len(found) != 1:
                        raise CaptureError('one original retained provider packet required')
                    packets.remove(found[0]); return found[0]
                rebuilt, _ = _case(context, case, matched)
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
        return (type(record.get('ssap_read_provider_version')) is int and record['ssap_read_provider_version'] == VERSION
                and record.get('ssap_read_provider_acceptance') is True
                and record.get('ssap_owned_acceptance') is True
                and record.get('ordinary_channel_socket_acceptance') is True
                and record.get('status') == 'PASSTHROUGH_SUPPORT_PASS'
                and type(record.get('qemu_exit')) is int and record['qemu_exit'] == 0 and valid_summary(proof))
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
