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
import secrets
import time

from ws73_capture import CaptureError, packet_interval
from ws73_ssap_read_provider import PROMPT, prompt, _cleanup, _wire

TOKEN = 'ws73.ssap_provider_owner_exit=1'
VERSION = 2  # SDK owners; retained CLI evidence keeps version 1.
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
    from ws73_ssap_sdk_read_provider import validate_inputs as sdk_inputs
    sdk_inputs(package)


def validate_rows(rows, selected, *, version=None):
    if version is not None and (type(version) is not int or version not in (1, 2)):
        raise CaptureError('explicit supported expected owner-exit version required')
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
                or type(row.get(PREFIX+'_version')) is not int or row[PREFIX+'_version'] not in (1, 2)
                or version is not None and row[PREFIX+'_version'] != version
                or row.get('ssap_read_provider_required') is not True or row.get('ssap_read_provider_version') != 2
                or type(row.get(PREFIX+'_tools')) is not dict
                or len(row.get(PREFIX+'_cases', [])) != 1 or len(row.get(PREFIX+'_guards', [])) != 1
                or row[PREFIX+'_cases'][0].get('sender') != 0):
            raise CaptureError('one exit per role and original provider v2 baseline required')
    if selected and len({(row['owners'][1]['owner']['index'], row['owners'][1]['owner']['generation']) for row in rows}) != 2:
        raise CaptureError('both physical Provider receivers must undergo owner exit')
    if selected and len({row[PREFIX+'_version'] for row in rows}) != 1:
        raise CaptureError('one explicit Provider owner-exit evidence version required')


def _sdk_pending(row, item, text, *, writing=False):
    """Validate the original SDK transcript before destructive owner exit.

    This consumes actual SDK observations, never translates them into invented
    CLI prompts/results. The independently validated wire proof remains required.
    """
    from ws73_ssap_sdk_read_provider import json_rows, BOUND, REQUEST, integer
    from ws73_application_client import AUTHORIZATION_CONTEXT_FIELDS, authorization_context
    if type(row['phase']) is not int or row['phase'] not in (0, 1):
        raise CaptureError('one of the two original SDK roles required')
    if writing:
        from ws73_ssap_sdk_write_provider import REQUEST
    prefix = 'SdkWriteProvider' if writing else 'SdkReadProvider'
    contract = 'sdk_write_provider_contract_version' if writing else 'sdk_read_provider_contract_version'
    api = ('python', 'c')[row['phase']]
    bound = json_rows(text, prefix+'Bound', BOUND, 1)[0]
    request = json_rows(text, prefix+'Request', REQUEST, 1)[0]
    approval = json_rows(text, 'SdkAuthorizationDecision',
        AUTHORIZATION_CONTEXT_FIELDS|{'allow','decision_ns','decision_wall_ns'}, 1)[0]
    target = row['owners'][1]
    owner, link = target['owner'], target['object']
    lines = text.splitlines()
    registration = f'SsapOwnedService: start={item["start"]} end={item["end"]} property={item["handle"]}; local registration only'
    if (len(lines) != 5 or lines[:2] != [f'SdkOwnedAPI: api={api} client_closed=true', registration]
            or [v.split(': ', 1)[0] for v in lines[2:]] !=
               [prefix+'Bound','SdkAuthorizationDecision',prefix+'Request']
            or item.get('publisher_api') != api or type(item.get(contract)) is not int
            or item[contract] != 1):
        raise CaptureError('only original SDK registration/bind/approval/pending request allowed')
    if (bound != item['bound'] or bound['api'] != api
            or any(not integer(bound[k], zero=True) for k in ('index','generation','property'))
            or (bound['index'],bound['generation'],bound['property']) != (owner['index'],owner['generation'],item['handle'])
            or any(type(bound[k]) is not int or bound[k] != 0 for k in ('result','notification_result'))
            or bound['notification_ready'] is not True or bound['local_binding_only'] is not True
            or any(not integer(bound[k]) for k in ('started_ns','deadline_ns','returned_ns'))
            or not item['bind_before_monotonic_ns'] <= bound['started_ns'] <= bound['returned_ns'] < bound['deadline_ns']
            or not 0 < bound['deadline_ns']-bound['started_ns'] <= 5_000_000_000):
        raise CaptureError('actual original SDK bind and notification receipt required')
    if (request['api'] != api or any(not integer(request[k], zero=True) for k in REQUEST-({'api','verify','value'} if writing else {'api'}))
            or not all(request[k] for k in ('token','request_id','lifetime','epoch','deadline_ns','property','observed_ns','observed_wall_ns'))
            or tuple(request[k] for k in ('index','generation','lifetime','handle','property')) !=
               (owner['index'],owner['generation'],link['lifetime'],link['handle'],item['handle'])
            or (request['level'],request['local_tcid'],request['remote_tcid'],request['pi']) != (0,10,10,0)
            or not writing and request['maximum_bytes'] != 2042):
        raise CaptureError('original basic-CUTC SDK request identity and budget required')
    if writing and (type(item.get('proposed')) is not str or not re.fullmatch('[0-9a-f]{64}',item['proposed'])
            or item['proposed'] == item['secret'] or request['value'] != item['proposed'] or request['verify'] is not True
            or (request['operation'],request['data_type'],request['offset'],request['value_length']) != (13,0,0,32)):
        raise CaptureError('original complete verified type0 WRITE payload required')
    authorization_context({k:approval[k] for k in AUTHORIZATION_CONTEXT_FIELDS}, api)
    if (approval['allow'] is not True or approval['write'] is not writing or approval['value'] != (item['proposed'] if writing else '')
            or writing and approval['data_type'] != 0
            or any(not integer(approval[k]) for k in ('decision_ns','decision_wall_ns'))
            or any(approval[k] != request[k] for k in ('index','generation','request_id','lifetime','handle','epoch','level','deadline_ns','property','local_tcid','remote_tcid','pi'))
            or not bound['returned_ns'] <= approval['decision_ns'] <= request['observed_ns'] < request['deadline_ns']
            or approval['decision_wall_ns'] > request['observed_wall_ns']):
        raise CaptureError('actual independent approval must precede the same SDK request')
    return request


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


def _clock_bounds(item, *, action="kill"):
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
            <= before['monotonic_after_ns'] <= item[action+'_before_monotonic_ns']
            or not item['read']['end_monotonic_ns'] <= after['monotonic_before_ns']
            or not item['callback']['observed_wall_ns'] <= before['realtime_ns'] <= item[action+'_before_wall_ns']
            or not item['read']['end_wall_ns'] <= after['realtime_ns'] <= item['retired_read']['start_wall_ns']):
        raise CaptureError('clock samples must bracket original lifecycle action through SDK completion')
    lower, upper = max(v[0] for v in bounds), min(v[1] for v in bounds)
    if lower > upper:
        raise CaptureError('clock samples contradict the stated stable-offset assumption')
    return lower, upper


def pending_callback(run, row, process, item, app, supervisor_deadline_ns, *, writing=False):
    """Shared actual SDK arrival barrier; does not choose a lifecycle action."""
    from ws73_ssap_owned import wait_text
    item['read'] = app
    run.save()
    sdk_deadline = app['ssap_error_deadline_ns']
    sdk = writing or row.get(PREFIX+'_version', 1) == 2
    pattern = r'^SdkWriteProviderRequest: (.+)$' if writing else r'^SdkReadProviderRequest: (.+)$' if sdk else PROMPT
    _, text = wait_text(process, Path(item['output_files'][0]), pattern,
                        min(sdk_deadline, supervisor_deadline_ns)/1e9, max_count=1)
    observed = time.monotonic_ns()
    data = _sdk_pending(row, item, text, writing=writing) if sdk else prompt(text)
    target = row['owners'][item['target']]
    identity, link = target['owner'], target['object']
    if ((data['index'], data['generation'], data['lifetime'], data['handle'], data['property'])
            != (identity['index'], identity['generation'], link['lifetime'], link['handle'], item['handle'])
            or not observed < data['deadline_ns'] <= observed+5_000_000_000
            or sdk and not data['observed_ns'] <= observed
            or process.poll() is not None):
        raise CaptureError('one live original Provider callback identity and deadline required')
    deadline = min(data['deadline_ns'], sdk_deadline, supervisor_deadline_ns)
    item['callback'] = dict(prompt=data, observed_monotonic_ns=observed, observed_wall_ns=time.time_ns(),
                            publisher_pid=process.pid, supervisor_deadline_ns=supervisor_deadline_ns,
                            exit_deadline_ns=deadline)
    if sdk and data['observed_wall_ns'] > item['callback']['observed_wall_ns']:
        raise CaptureError('SDK arrival wall observation must precede supervisor owner exit')
    run.save()
    _remaining(deadline)
    return deadline


def _owner_exit(run, row, process, item, app, supervisor_deadline_ns, *, writing=False):
    """After-start hook; no answer, renewed deadline or synthetic Complete."""
    from ws73_ssap_owned import wait_output, await_removed
    deadline = pending_callback(run, row, process, item, app, supervisor_deadline_ns, writing=writing)
    target = row['owners'][item['target']]
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
    from ws73_ssap_sdk_read_provider import tool_records
    if (row.get('ssap_read_provider_required') is not True or row.get('ssap_read_provider_version') != 2
            or len(row.get('ssap_read_provider_cases', [])) != 2):
        raise CaptureError('original provider sequence must finish before owner-exit extension')
    row.update({PREFIX+'_required': True, PREFIX+'_version': VERSION, PREFIX+'_tools': tool_records(),
                PREFIX+'_cases': [], PREFIX+'_guards': []})
    run.save()
    execute_pending_case(run, row, PREFIX, 'provider-owner-exit', _owner_exit)
    row[PREFIX+'_status'] = PENDING; run.save()


def execute_pending_case(run, row, prefix, label, action, *, finish=None, writing=False):
    """Shared SDK/peer/guard orchestration; each action has its own evidence contract."""
    from ws73_application_client import ssap_command, ssap_error_command
    from ws73_ssap_owned import publisher, wait_output, await_removed
    from ws73_ssap_sdk_read_provider import _wait_json, BOUND
    phase = row['phase']
    if type(phase) is not int or phase not in (0, 1):
        raise CaptureError('original two-role phase required')
    # owners are role ordered and reverse physical identities on phase 1.
    # A fixed role position tests each physical Provider receiver once.
    sender = 0
    source, target = row['owners'][sender], row['owners'][1-sender]
    api = ('c', 'python')[phase]
    with publisher(run, row, sender, 'allow', operations=1,
                   collection=prefix+'_guards', label=label+'-guard') as (guard_process, guard):
        guard['registered_wall_ns'] = time.time_ns()
        run.save()
        with publisher(run, row, sender, 'allow', operations=6 if writing else 1,
                       sdk_api=('python', 'c')[phase], read_only=not writing, read_provider=not writing, write_provider=writing,
                       collection=prefix+'_cases', label=label) as (process, item):
            if writing:
                item['proposed'] = secrets.token_hex(32)
            item['guard'] = guard
            item['bind_before_monotonic_ns'] = time.monotonic_ns()
            process.stdin.write('provider\n'); process.stdin.flush()
            item['bound'] = _wait_json(process, item, 'SdkWriteProviderBound' if writing else 'SdkReadProviderBound', BOUND, 1,
                                       item['bind_before_monotonic_ns']+5_000_000_000)
            item['bound_wall_ns'] = time.time_ns(); run.save()
            item['read'] = ssap_error_command(run, row, source,
                (['ssap-write', source['object']['path'], str(item['handle']), item['proposed']] if writing else
                 ['ssap-read', source['object']['path'], str(item['handle'])]), errno.EIO,
                api=api, after_start=lambda app, deadline: action(run, row, process, item, app, deadline))
            item['clock_after'] = _clock_sample()
            run.save()
            item['retired_read'] = run.command([str(run.args.slctl), '--adapter', source['owner']['path'],
                'ssap-read', source['object']['path'], str(item['handle']), '0'], 10, collection=prefix)
            if guard_process.poll() is not None:
                raise CaptureError('independent original guard Owner exited during Provider loss')
            guard['read'] = ssap_command(run, row, source,
                ['ssap-read', source['object']['path'], str(guard['handle'])], bytes.fromhex(guard['secret']), api=api)
            guard['alive_after_read_wall_ns'] = time.time_ns()
            if guard_process.poll() is not None:
                raise CaptureError('independent original guard must survive its actual peer read')
            run.save()
            if finish is not None:
                finish(run, row, process, item)
        guard['quit_wall_ns'] = time.time_ns(); run.save()
        guard_process.stdin.write('quit\n'); guard_process.stdin.flush()
        wait_output(guard_process, 2)
        if guard_process.returncode != 0:
            raise CaptureError('independent guard explicit cleanup failed')
        guard['owner_exit_wall_ns'] = time.time_ns()
        guard['cleanup'] = await_removed(run, target, guard['start'])
        run.save()


def _ordinary(item):
    from ws73_ssap_owned import verify_output
    verify_output(item)
    credentials = item['credentials']
    if (credentials['uids'] != [1000]*4
            or set(credentials['capabilities']) != {'CapEff', 'CapPrm', 'CapAmb', 'CapInh'}
            or any(int(v, 16) for v in credentials['capabilities'].values()) or item['stderr']):
        raise CaptureError('original cap-zero owner and complete output required')


def _registration(row, item, *, sdk=False, writing=False):
    if writing and not sdk: raise CaptureError('WRITE registration requires actual SDK caller')
    _ordinary(item)
    target = row['owners'][item['target']]
    if sdk:
        from ws73_application_client import owned_arguments, application_environment
        api = ('python', 'c')[row['phase']]
        args = owned_arguments(api, target, item['service'], item['uuid'], item['secret'], 'allow',
                               read_only=not writing, read_provider=not writing, write_provider=writing)
        selected = f'SdkOwnedAPI: api={api} client_closed=true'
        if item.get('environment') != application_environment() or item.get('publisher_api') != api:
            raise CaptureError('exact SDK caller argv/environment required')
    else:
        args = [row['ssap_receipts'][0]['args'][0], '--adapter', target['owner']['path'],
                'ssap-serve', item['service'], item['uuid'], '1', '36', item['secret'], 'allow']
        selected = f'Selected {target["owner"]["path"]}'
    if (type(item['sender']) is not int or item['sender'] != 0 or type(item['target']) is not int or item['target'] != 1
            or any(type(item[k]) is not int for k in ('start', 'end', 'handle', 'pid', 'operations'))
            or not 0 < item['start'] < item['handle'] == item['end'] < 65535 or item['pid'] <= 0
            or item['operations'] != (6 if writing else 1) or item['policy'] != 'allow'
            or item['args'] != args
            or any(not re.fullmatch('[0-9a-f]{32}', item[k]) for k in ('service', 'uuid'))
            or not re.fullmatch('[0-9a-f]{64}', item['secret'])):
        raise CaptureError('one original READ-only allow publisher with full identity required')
    registration = f'SsapOwnedService: start={item["start"]} end={item["end"]} property={item["handle"]}; local registration only'
    lines = item['stdout'].splitlines()
    if (lines[:2] != [selected, registration]
            or sum(l.startswith(('Selected ', 'SdkOwnedAPI:')) for l in lines) != 1
            or sum(l.startswith('SsapOwnedService:') for l in lines) != 1):
        raise CaptureError('one selected target followed by its original registration required')
    return registration


def _response(row, item, packets, *, writing=False):
    """Select exactly one actual paired READ_RSP; EIO never selects its code."""
    s, t = item['sender'], item['target']
    window = item['read']
    chosen = []
    if writing:
        h = item['handle'].to_bytes(2,'little')
        allowed = [(b'\x0a\0\x06\0\x0e\x07\x01'+h+bytes([e])).hex() for e in (175,4)]
    else:
        allowed = ('0a000400090baf00','0a000400090b0400')
    for endpoint, direction in ((t, 'out'), (s, 'in')):
        owner, link = row['owners'][endpoint]['owner'], row['owners'][endpoint]['object']
        found = [p for p in packets if (p['bus'], p['device'], p['handle'], p['direction'])
                 == (owner['bus'], owner['device'], link['handle'], direction)
                 and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']
                 and bytes.fromhex(p['data'])[:2] == b'\x0a\0']
        if len(found) != 1 or found[0]['data'] not in allowed:
            raise CaptureError('one actual AF/4 READ_RSP on each original endpoint required')
        chosen.append(bytes.fromhex(found[0]['data'])[4:])
    if chosen[0] != chosen[1]:
        raise CaptureError('original Provider exit wire response must match at both ends')
    return chosen[0]


def _case(row, item, matched, packets, *, writing=False):
    prefix, status = PREFIX, STATUS
    if writing:
        from ws73_ssap_write_owner_exit import PREFIX as prefix, STATUS as status
    from ws73_application_client import ssap_receipt, ssap_error_receipt
    from ws73_ssap_command import _identity
    version = row.get(prefix+'_version', 1)
    if type(version) is not int or version not in ((1,) if writing else (1, 2)):
        raise CaptureError('explicit supported owner-exit version required')
    sdk = writing or version == 2
    if sdk:
        from ws73_ssap_update_delivery import TOOLS
        from ws73_ssap_sdk_read_provider import EXTRA_TOOLS, integer
        if writing:
            from ws73_ssap_write_owner_exit import EXTRA_TOOLS
        records = row[prefix+'_tools']
        if (type(records) is not dict or set(records) != set(TOOLS)|set(EXTRA_TOOLS)
                or any(type(v) is not dict or set(v) != {'sha256','bytes'} or not integer(v['bytes'])
                       or type(v['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',v['sha256'])
                       for v in records.values())):
            raise CaptureError('exact SDK owner tools must be retained with version 2')
    registration = _registration(row, item, sdk=sdk, writing=writing)
    guard = item['guard']; guard_registration = _registration(row, guard)
    identities = [_identity(owner) for owner in row['owners']]
    if (len({(i['index'], i['generation']) for i in identities}) != 2
            or len({(i['bus'], i['device']) for i in identities}) != 2):
        raise CaptureError('two original physical controller identities required')
    s, t, h = item['sender'], item['target'], item['handle']
    source, target = row['owners'][s], row['owners'][t]
    app, callback = item['read'], item['callback']
    data = _sdk_pending(row, item, item['stdout'], writing=writing) if sdk else prompt(item['stdout'])
    if (any(k in item for k in ('reply_command', 'quit_wall_ns', 'steps'))
            or type(item['exit']) is not int or item['exit'] != -9 or type(item['owner_exit']) is not int or item['owner_exit'] != -9
            or callback['prompt'] != data or callback['publisher_pid'] != item['pid']
            or (data['index'], data['generation'], data['lifetime'], data['handle'], data['property'])
                != (identities[t]['index'], identities[t]['generation'], identities[t]['lifetime'], identities[t]['handle'], h)
            or guard['pid'] == item['pid'] or guard['handle'] == h
            or guard['service'] == item['service'] or guard['uuid'] == item['uuid'] or guard['secret'] == item['secret']):
        raise CaptureError('actual distinct guard and killed pending provider identity required')
    if sdk and (not data['observed_ns'] <= callback['observed_monotonic_ns']
                or data['observed_wall_ns'] > callback['observed_wall_ns']):
        raise CaptureError('SDK arrival observation must precede supervisor owner exit')
    sdk_prefix = 'SdkWriteProvider' if writing else 'SdkReadProvider'
    lines = item['stdout'].splitlines()
    bound = next(l for l in lines if l.startswith(sdk_prefix+'Bound:')) if sdk else f'SsapReadProviderBound: handle={h}; stored value discarded, no rebind or fallback'
    decision = next(l for l in lines if l.startswith('SdkAuthorizationDecision:')) if sdk else f'SsapAuthorizationDecision: request={data["request"]} property={h} data_type=0 write=false security=0 approved=true; local policy only'
    prompt_line = next(l for l in lines if l.startswith(sdk_prefix+'Request:' if sdk else 'SsapReadProviderPrompt:'))
    if (lines.count(bound) != 1 or lines.count(decision) != 1
            or sum(l.startswith(sdk_prefix+'Bound:' if sdk else 'SsapReadProviderBound:') for l in lines) != 1
            or sum(l.startswith('SdkAuthorizationDecision:' if sdk else 'SsapAuthorizationDecision:') for l in lines) != 1
            or any(l.startswith(('SsapReadProviderResult:', 'SsapReadProviderInput:')) for l in lines)
            or [lines.index(v) for v in (registration, bound, decision, prompt_line)] != sorted(lines.index(v) for v in (registration, bound, decision, prompt_line))):
        raise CaptureError('approved actual pending provider prompt without an application answer required')
    receipt = ssap_error_receipt(app, source, expected_errno=errno.EIO)
    if (app['api'] != ('c', 'python')[row['phase']] or app['ssap_operation'] != ('ssap-write' if writing else 'ssap-read') or app['ssap_handle'] != h
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
    response, wire, credit = corroborate_peer_guard(row, item, matched, packets, receipt,
        deadline, offset_lower, item['kill_before_wall_ns'], writing=writing)
    context = dict(phase=row['phase'], owners=row['owners'], ssap_receipts=row['ssap_receipts'])
    if sdk:
        context[prefix+'_version'] = version
        context[prefix+'_tools'] = row[prefix+'_tools']
    return dict(status=status, version=version, sender=s, target=t, api=app['api'],
                sdk_errno=receipt['errno'], peer_error=response[-1] if writing else response[2], wire=wire,
                context=copy.deepcopy(context),
                case=copy.deepcopy(item)), credit


def corroborate_peer_guard(row, item, matched, packets, receipt, deadline, offset_lower, action_wall_ns, *, writing=False):
    """Same paired wire and independent guard checks for distinct lifecycle actions."""
    from ws73_application_client import ssap_receipt
    guard, app, callback = item['guard'], item['read'], item['callback']
    source, target = row['owners'][item['sender']], row['owners'][item['target']]
    guard_registration = _registration(row, guard)
    _cleanup(row, item)
    if (type(guard['exit']) is not int or guard['exit'] != 0 or 'SsapReadProvider' in guard['stdout']
            or guard['stdout'].splitlines()[1] != guard_registration):
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
    response = _response(row, item, packets, writing=writing)
    # The barrier precedes the real lifecycle action, never a fabricated reply
    # command or wait() completion time.
    requests = None
    if writing:
        h = item['handle'].to_bytes(2,'little')
        requests = [b'\x0d\x23'+h+b'\0'+bytes.fromhex(item['proposed']),b'\x08\x03'+h+b'\0']
    wire, credit = _wire(row, item, matched, [
        (app, response, dict(observed_wall_ns=callback['observed_wall_ns'], reply_before_wall_ns=action_wall_ns)),
        (item['retired_read'], b'\x09\x0b\x04\0', None)],requests=requests)
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
    return response, wire, credit


def corroborate(row, matched, packets):
    if row.get(PREFIX+'_required', False) is not True:
        if any(k.startswith(PREFIX+'_') for k in row if k != PREFIX+'_required'):
            raise CaptureError('unrequested owner-exit evidence')
        return [], {0: 0, 1: 0}
    if (type(row.get(PREFIX+'_version')) is not int or row[PREFIX+'_version'] not in (1, 2)
            or row.get('ssap_read_provider_required') is not True or row.get('ssap_read_provider_version') != 2
            or len(row.get(PREFIX+'_cases', [])) != 1 or len(row.get(PREFIX+'_guards', [])) != 1
            or row[PREFIX+'_cases'][0]['guard'] != row[PREFIX+'_guards'][0]):
        raise CaptureError('one original guard/case and provider v2 required')
    result, credit = _case(row, row[PREFIX+'_cases'][0], matched, packets)
    return [result], credit


def valid_summary(proof, *, version=None, writing=False):
    prefix = PREFIX
    allowed = (1,) if writing else (1, 2)
    if writing:
        from ws73_ssap_write_owner_exit import PREFIX as prefix, verify_business_after
    try:
        if version is not None and (type(version) is not int or version not in allowed):
            return False
        rows = proof['proofs']
        if type(rows) is not list or len(rows) != 2:
            return False
        receivers, versions = set(), set()
        for phase, row in enumerate(rows):
            items = row[prefix]
            if type(row['phase']) is not int or row['phase'] != phase or len(items) != 1:
                return False
            item = items[0]; context, case = item['context'], item['case']
            if type(item.get('version')) is not int or item['version'] not in allowed or version is not None and item['version'] != version:
                return False
            versions.add(item['version'])
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
            if writing:
                verify_business_after(case, row['legs'])
            rebuilt, _ = _case(context, case, matched, packets, writing=writing)
            if packets or json.dumps(rebuilt, sort_keys=True) != json.dumps(item, sort_keys=True):
                return False
        return len(receivers) == 2 and len(versions) == 1
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
        return (type(record.get(PREFIX+'_version')) is int and record[PREFIX+'_version'] in (1, 2)
                and record.get(PREFIX+'_acceptance') is True and record.get('ssap_read_provider_version') == 2
                and provider_manifest(record) and valid_summary(proof, version=record[PREFIX+'_version']))
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
