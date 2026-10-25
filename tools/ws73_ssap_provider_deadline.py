# SPDX-License-Identifier: GPL-2.0-only
"""Original Provider deadline, then a rejected late application answer.

Opt-in VM gate reusing the actual SDK supervisor, Owned pipes, terminal
observer and ordinary CUTC runner. Scoped execution evidence and independent
audit remain necessary; installing this tool creates no hardware qualification.
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
from ws73_ssap_read_provider import PROMPT, prompt
from ws73_ssap_provider_owner_exit import CLOCK_CONTRACT, _clock_sample, _registration
from ws73_ssap_command_deadline import info_arguments, terminal_receipt, verify_business
from ws73_ssap_command_policy import need, packet_key, window_packets

PREFIX = 'ssap_provider_deadline'
TOKEN = 'ws73.ssap_provider_deadline=1'
VERSION = 1
COLLECTION = PREFIX + '_cases'
PENDING = 'PROVIDER_ORIGINAL_DEADLINE_PENDING_PAIRED_USB'
REJECTED = 'SsapReadProviderInput: rejected stale token, expired request or invalid value/status'
DESTRUCTIVE = ('ssap_write_command_deadline_verify', 'ssap_update_lifecycle_verify',
               'ssap_requester_lifecycle_verify', 'ssap_owner_lifecycle_verify',
               'ssap_sender_deadline_verify')


def requested(args, *, passthrough=None):
    from ws73_ssap_provider_owner_exit import requested as owner_exit_requested
    selected = getattr(args, PREFIX + '_verify', False)
    if type(selected) is not bool:
        raise ValueError('explicit Provider deadline selector boolean required')
    if selected and (not owner_exit_requested(args, passthrough=passthrough)
                     or any(getattr(args, name, False) for name in DESTRUCTIVE)):
        raise ValueError('Provider deadline requires the dedicated Owner-exit/Provider-v2 ordinary baseline')
    return selected


def boot_requested(tokens):
    from ws73_ssap_provider_owner_exit import boot_requested as owner_exit_boot
    if type(tokens) not in (list, tuple) or any(type(t) is not str for t in tokens):
        raise ValueError('original tokenized boot arguments required')
    selected = [t for t in tokens if t == TOKEN.split('=')[0]
                or t.startswith(TOKEN.split('=')[0] + '=')]
    if selected not in ([], [TOKEN]) or selected and not owner_exit_boot(tokens):
        raise ValueError('one exact Provider deadline selector and original Provider dependency required')
    return bool(selected)


def validate_inputs(package):
    from ws73_ssap_provider_owner_exit import validate_inputs as owner_exit_inputs
    owner_exit_inputs(package)
    directory = Path(__file__).resolve().parent
    for name in ('ws73_ssap_provider_deadline.py', 'ws73_ssap_command_deadline.py',
                 'ws73_ssap_command_policy.py'):
        path = directory/name
        matches = [r for r in package.get('inputs', []) if Path(r['path']).resolve() == path]
        need(len(matches) == 1 and matches[0]['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest(),
             'fresh exact Provider deadline input required: ' + name)


def validate_rows(rows, selected):
    from ws73_ssap_provider_owner_exit import validate_rows as owner_exit_rows
    need(type(selected) is bool and type(rows) is list, 'typed selection and rows required')
    if selected:
        owner_exit_rows(rows, True)
        need(len(rows) == 2, 'two original connection roles required')
    for phase, row in enumerate(rows):
        need(type(row.get(PREFIX+'_required', False)) is bool
             and row.get(PREFIX+'_required', False) == selected, 'Provider deadline selection/row mismatch')
        if not selected:
            need(not any(k.startswith(PREFIX+'_') and k != PREFIX+'_required' for k in row),
                 'unrequested Provider deadline evidence')
            continue
        need(type(row.get(PREFIX+'_version')) is int and row[PREFIX+'_version'] == VERSION
             and row['ssap_read_provider_version'] == 2
             and len(row.get(COLLECTION, [])) == 1 and row['phase'] == phase,
             'one deadline after the exact retained Provider-v2 baseline required')
    if selected:
        need(len({(r['owners'][1]['owner']['index'], r['owners'][1]['owner']['generation'])
                  for r in rows}) == 2, 'both physical Provider receivers required')


def observe_prompt(run, row, process, item, app, supervisor_deadline_ns):
    """Only the actual value callback is a barrier; return without answering."""
    from ws73_ssap_owned import wait_text
    item['read'] = app; run.save()
    _, text = wait_text(process, Path(item['output_files'][0]), PROMPT,
                        min(app['ssap_error_deadline_ns'], supervisor_deadline_ns)/1e9, max_count=1)
    observed = time.monotonic_ns(); data = prompt(text)
    target = row['owners'][1]; controller, link = target['owner'], target['object']
    need((data['index'], data['generation'], data['lifetime'], data['handle'], data['property'])
         == (controller['index'], controller['generation'], link['lifetime'], link['handle'], item['handle'])
         and observed < data['deadline_ns'] <= observed+5_000_000_000
         and observed < app['ssap_error_deadline_ns'] < supervisor_deadline_ns
         and data['deadline_ns'] <= supervisor_deadline_ns and process.poll() is None,
         'one live original Provider prompt before SDK deadline required')
    decision = (f'SsapAuthorizationDecision: request={data["request"]} property={item["handle"]} '
                'data_type=0 write=false security=0 approved=true; local policy only')
    need(text.splitlines().count(decision) == 1, 'Provider prompt must follow actual authorization')
    item['callback'] = dict(prompt=data, observed_monotonic_ns=observed,
        observed_wall_ns=time.time_ns(), publisher_pid=process.pid,
        supervisor_deadline_ns=supervisor_deadline_ns)
    run.save()
    # No wait through expiry: ssap_error_command records its end after this hook.


def observe_terminal(run, entry, deadline_ns):
    """One finite observation budget; never renew an expired protocol request."""
    attempts = []
    for _ in range(16):
        remaining = (deadline_ns-time.monotonic_ns())/1e9
        need(remaining > 0, 'original terminal observation budget expired')
        receipt = run.command(info_arguments(str(run.args.slctl), entry), remaining,
                              collection=PREFIX+'_terminal')
        attempts.append(receipt); run.save()
        try:
            return attempts, terminal_receipt(receipt, str(run.args.slctl), entry)
        except CaptureError:
            need(receipt['exit'] != 0 and 'SsapExchangeInfo:' not in receipt['stdout'],
                 'expired receiver must not remain negotiated')
            time.sleep(.02)
    raise CaptureError('finite terminal observation count exhausted')


def requester_outcome(receipt, original, program, source):
    """One actual observation, not a promise of health or completed physical drain."""
    need(receipt['args'] == original['args'] == info_arguments(program,source)
         and type(receipt['exit']) is int
         and receipt['start_monotonic_ns'] <= receipt['end_monotonic_ns']
         <= receipt['start_monotonic_ns']+2_000_000_000,
         'same original requester identity and finite observation required')
    if receipt['exit'] == 0:
        need(original['exit'] == 0 and not original['stderr'] and not receipt['stderr']
             and receipt['stdout'] == original['stdout'], 'exact retained requester negotiated observation required')
        return dict(state='original-negotiated-observation',physical_drain_proven=False)
    reason = terminal_receipt(receipt,program,source)
    return dict(state='original-deadline-terminal',reason=reason,physical_drain_proven=False)


def execute(run, row, business):
    from ws73_application_client import ssap_error_command, ssap_error_receipt
    from ws73_ssap_owned import publisher, wait_text, output_text, wait_output, await_removed
    from ws73_ssap_update_delivery import tool_records
    need(callable(business) and row.get('ssap_read_provider_required') is True
         and row.get('ssap_read_provider_version') == 2 and len(row.get('ssap_read_provider_cases', [])) == 2
         and row.get('ssap_provider_owner_exit_required') is True
         and row.get('ssap_provider_owner_exit_version') == 1
         and row.get('ssap_provider_owner_exit_status') == 'PROVIDER_OWNER_EXIT_PENDING_PAIRED_USB'
         and len(row.get('ssap_provider_owner_exit_cases', [])) == len(row.get('ssap_provider_owner_exit_guards', [])) == 1
         and type(row['phase']) is int and row['phase'] in (0, 1), 'completed Provider-v2 baseline required')
    row.update({PREFIX+'_required': True, PREFIX+'_version': VERSION,
                PREFIX+'_tools': tool_records(), COLLECTION: []})
    source, target = row['owners']; api = ('c', 'python')[row['phase']]
    with publisher(run, row, 0, 'allow', operations=1, collection=COLLECTION,
                   label='provider-original-deadline') as (process, item):
        item.update(api=api, late_value=secrets.token_hex(32), status='RUNNING')
        need(item['late_value'] != item['secret'], 'late value must differ from discarded stored bytes')
        process.stdin.write('provider\n'); process.stdin.flush()
        bound, _ = wait_text(process, Path(item['output_files'][0]),
            r'^SsapReadProviderBound: handle=(\d+); stored value discarded, no rebind or fallback$',
            time.monotonic()+5, max_count=1)
        need(bound == [str(item['handle'])], 'actual same-handle Provider binding required')
        item['bound_wall_ns'] = time.time_ns()
        item['clock_contract'] = copy.deepcopy(CLOCK_CONTRACT)
        item['clock_before'] = _clock_sample(); run.save()
        item['read'] = ssap_error_command(run, row, source,
            ['ssap-read', source['object']['path'], str(item['handle'])], errno.ETIMEDOUT, api=api,
            after_start=lambda app, deadline: observe_prompt(run, row, process, item, app, deadline))
        receipt = ssap_error_receipt(item['read'], source, expected_errno=errno.ETIMEDOUT)
        need(receipt['returned_ns'] >= receipt['deadline_ns'], 'SDK must actually reach its original deadline')
        original = item['callback']['prompt']['deadline_ns']
        while time.monotonic_ns() < original:
            output_text(process, Path(item['output_files'][0]))
            need(process.poll() is None, 'Owner exited before original Provider deadline')
            time.sleep(max(0, min(.02, (original-time.monotonic_ns())/1e9)))
        item['provider_deadline_observed_ns'] = time.monotonic_ns()
        # This is an observation budget, not another SSAP request deadline.
        item['terminal_observation_deadline_ns'] = original+2_000_000_000
        item['terminal_attempts'], item['terminal'] = observe_terminal(
            run, target, item['terminal_observation_deadline_ns'])
        need(process.poll() is None, 'Provider Owner must survive original callback expiry')
        item['late_input'] = dict(text=f'provide p{item["callback"]["prompt"]["token"]} {item["late_value"]}',
            wall_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())
        process.stdin.write(item['late_input']['text']+'\n'); process.stdin.flush()
        matches, _ = wait_text(process, Path(item['output_files'][0]), '^'+re.escape(REJECTED)+'$',
                              time.monotonic()+2, max_count=1)
        need(matches == [REJECTED], 'one actual expired-token rejection required')
        item['late_input'].update(completed_wall_ns=time.time_ns(), completed_monotonic_ns=time.monotonic_ns())
        item['business_window'] = dict(start_wall_ns=time.time_ns(), start_monotonic_ns=time.monotonic_ns())
        run.save()
        business(time.monotonic()+30)
        item['business_window'].update(end_wall_ns=time.time_ns(), end_monotonic_ns=time.monotonic_ns())
        item['requester_observation'] = run.command(info_arguments(str(run.args.slctl),source),2,
                                                   collection=PREFIX+'_requester')
        item['requester_outcome'] = requester_outcome(item['requester_observation'],row['ssap_receipts'][0],
                                                     str(run.args.slctl),source)
        item['terminal_after_business'] = run.command(info_arguments(str(run.args.slctl), target), 2,
                                                       collection=PREFIX+'_terminal')
        need(terminal_receipt(item['terminal_after_business'], str(run.args.slctl), target) == item['terminal'],
             'expired receiver must retain its original terminal after CUTC business')
        need(process.poll() is None, 'Owner must remain alive until explicit withdrawal')
        item['owner_alive_after_business_ns'] = time.monotonic_ns()
        item['quit_wall_ns'] = time.time_ns()
        process.stdin.write('quit\n'); process.stdin.flush()
        need(wait_output(process, 2) == 0, 'actual explicit Owner withdrawal must succeed')
        item['owner_exit_wall_ns'] = time.time_ns()
        item['cleanup'] = await_removed(run, target, item['start'])
        item['clock_after'] = _clock_sample()
        item['status'] = PENDING; run.save()
    row[PREFIX+'_status'] = PENDING; run.save()


def clock_bounds(item):
    need(item['clock_contract'] == CLOCK_CONTRACT
         and type(item['clock_contract']['version']) is int
         and type(item['clock_contract']['usbmon_quantization_ns']) is int,
         'explicit same-guest stable-offset clock scope required')
    bounds = []
    for name in ('clock_before', 'clock_after'):
        sample = item[name]
        need(type(sample) is dict and set(sample) == {'monotonic_before_ns','realtime_ns','monotonic_after_ns'}
             and all(type(v) is int and v > 0 for v in sample.values())
             and sample['monotonic_before_ns'] <= sample['monotonic_after_ns'], 'ordered original clock bracket required')
        bounds.append((sample['realtime_ns']-sample['monotonic_after_ns'],
                       sample['realtime_ns']-sample['monotonic_before_ns']))
    before, after = item['clock_before'], item['clock_after']
    need(before['monotonic_after_ns'] <= item['read']['start_monotonic_ns']
         <= item['read']['end_monotonic_ns'] <= after['monotonic_before_ns']
         and item['bound_wall_ns'] <= before['realtime_ns'] <= item['read']['start_wall_ns']
         and item['cleanup']['end_wall_ns'] <= after['realtime_ns'] <= item['end_wall_ns'],
         'clock samples must bracket the original request through withdrawal')
    lower, upper = max(b[0] for b in bounds), min(b[1] for b in bounds)
    need(lower <= upper, 'clock samples contradict no-adjustment assumption')
    return lower, upper


def timing_contract(item, sdk):
    """Different original deadlines remain different; no renewed late timeout."""
    app, callback = item['read'], item['callback']; data = callback['prompt']
    stamps = [callback['observed_monotonic_ns'],callback['observed_wall_ns'],callback['supervisor_deadline_ns'],
              item['provider_deadline_observed_ns'],item['terminal_observation_deadline_ns'],item['owner_alive_after_business_ns']]
    for record in [item['late_input'],item['business_window'],item['requester_observation'],item['terminal_after_business'],*item['terminal_attempts']]:
        stamps.extend(v for k,v in record.items() if k.endswith('_ns'))
    need(all(type(v) is int and 0 < v < 2**64 for v in stamps), 'original bounded integer clock observations required')
    need(callback['supervisor_deadline_ns'] == app['ssap_supervisor_deadline_ns']
         and app['start_monotonic_ns'] <= sdk['call_ns'] <= callback['observed_monotonic_ns']
         < sdk['deadline_ns'] <= sdk['returned_ns'] <= app['end_monotonic_ns']
         and 0 < data['deadline_ns']-callback['observed_monotonic_ns'] <= 5_000_000_000
         and data['deadline_ns'] <= callback['supervisor_deadline_ns'], 'unchanged SDK and Provider original deadlines required')
    need(data['deadline_ns'] <= item['provider_deadline_observed_ns']
         and app['end_monotonic_ns'] <= item['provider_deadline_observed_ns']
         and item['terminal_observation_deadline_ns'] == data['deadline_ns']+2_000_000_000,
         'finite post-original-deadline observation only')
    previous = max(data['deadline_ns'], app['end_monotonic_ns'], item['provider_deadline_observed_ns'])
    attempts = item['terminal_attempts']
    need(type(attempts) is list and 1 <= len(attempts) <= 16, 'bounded actor observations required')
    for receipt in attempts:
        need(previous <= receipt['start_monotonic_ns'] <= receipt['end_monotonic_ns']
             <= item['terminal_observation_deadline_ns'], 'ordered original terminal observations required')
        previous = receipt['end_monotonic_ns']
    late, window = item['late_input'], item['business_window']
    need(previous <= late['monotonic_ns'] <= late['completed_monotonic_ns']
         <= late['monotonic_ns']+2_000_000_000
         and late['completed_monotonic_ns'] <= window['start_monotonic_ns']
         <= window['end_monotonic_ns'] <= window['start_monotonic_ns']+31_000_000_000
         and window['end_monotonic_ns'] <= item['requester_observation']['start_monotonic_ns']
         <= item['requester_observation']['end_monotonic_ns'] <= item['terminal_after_business']['start_monotonic_ns']
         <= item['terminal_after_business']['end_monotonic_ns'] <= item['owner_alive_after_business_ns'],
         'late rejection, independent business and persistent terminal ordering required')


def sdk_inventory(row, item):
    """Retain the selected earlier calls; this scenario adds exactly one call."""
    owners = row['ssap_read_provider_cases']
    need(len(owners) == 2 and all(len(owner['steps']) == 3 for owner in owners), 'original six Provider calls required')
    prior = [step['read'] for owner in owners for step in owner['steps']]
    end = max(owner['end_wall_ns'] for owner in owners)
    need(row.get('ssap_provider_owner_exit_required') is True
         and type(row.get('ssap_provider_owner_exit_version')) is int and row['ssap_provider_owner_exit_version'] == 1
         and len(row['ssap_provider_owner_exit_cases']) == len(row['ssap_provider_owner_exit_guards']) == 1,
         'required exact original owner-exit baseline required')
    owner, guard = row['ssap_provider_owner_exit_cases'][0], row['ssap_provider_owner_exit_guards'][0]
    need(owner['guard'] == guard, 'original owner-exit guard correspondence required')
    prior.extend([owner['read'], guard['read']]); end = max(end,owner['end_wall_ns'],guard['end_wall_ns'])
    expected = prior+[item['read']]; actual = row['ssap_language_clients']
    need(actual == expected and len(actual) == 9
         and all(type(app['pid']) is int and app['pid'] > 0 for app in actual)
         and len({app['pid'] for app in actual}) == len(actual)
         and end < item['start_wall_ns'], 'exact selected SDK inventory and last-SSAP ordering required')


def case_contract(row, item):
    from ws73_application_client import ssap_error_receipt
    registration = _registration(row, item)
    source, target = row['owners']; program = row['ssap_receipts'][0]['args'][0]
    app, callback = item['read'], item['callback']; data = prompt(item['stdout'])
    need(type(row['phase']) is int and row['phase'] in (0, 1)
         and item['status'] == PENDING and type(item['exit']) is int and item['exit'] == 0
         and item['api'] == app['api'] == ('c','python')[row['phase']]
         and app['ssap_operation'] == 'ssap-read' and app['ssap_handle'] == item['handle']
         and callback['publisher_pid'] == item['pid'] and callback['prompt'] == data
         and all(type(v) is int for v in callback['prompt'].values())
         and not any(k in item for k in ('kill_before_wall_ns','owner_exit','reply_command','retired_read','steps')),
         'actual same-owner SDK timeout and explicit successful withdrawal required')
    identity, link = target['owner'], target['object']
    need((data['index'],data['generation'],data['lifetime'],data['handle'],data['property'])
         == (identity['index'],identity['generation'],link['lifetime'],link['handle'],item['handle']),
         'original full Provider callback identity required')
    bound = f'SsapReadProviderBound: handle={item["handle"]}; stored value discarded, no rebind or fallback'
    decision = (f'SsapAuthorizationDecision: request={data["request"]} property={item["handle"]} '
                'data_type=0 write=false security=0 approved=true; local policy only')
    lines = item['stdout'].splitlines(); prompt_line = next(l for l in lines if l.startswith('SsapReadProviderPrompt:'))
    need(lines == [f'Selected {target["owner"]["path"]}', registration, bound, decision, prompt_line, REJECTED],
         'exact approved pending Provider transcript followed by one rejected late input required')
    need(re.fullmatch('[0-9a-f]{64}', item['late_value']) and item['late_value'] != item['secret']
         and item['late_input']['text'] == f'provide p{data["token"]} {item["late_value"]}',
         'one distinct late value against the expired original token required')
    sdk = ssap_error_receipt(app, source, expected_errno=errno.ETIMEDOUT)
    sdk_inventory(row, item)
    timing_contract(item, sdk)
    for receipt in item['terminal_attempts']:
        need(receipt['args'] == info_arguments(program,target) and receipt['exit'] != 0
             and 'SsapExchangeInfo:' not in receipt['stdout'], 'no successful renegotiation before terminal')
    need(terminal_receipt(item['terminal_attempts'][-1], program, target) == item['terminal']
         == terminal_receipt(item['terminal_after_business'], program, target), 'same original actor terminal required')
    need(item['requester_outcome'] == requester_outcome(item['requester_observation'],row['ssap_receipts'][0],program,source)
         and item['requester_outcome']['physical_drain_proven'] is False,
         'actual requester observation cannot assert physical drain or revived actor')
    cleanup = item['cleanup']; lists = re.findall(r'^SsapLocalServices: (.+)$',cleanup['stdout'],re.M)
    need(cleanup['args'] == [program,'--adapter',target['owner']['path'],'ssap-list']
         and cleanup['exit'] == 0 and not cleanup['stderr'] and len(lists) == 1
         and not any(v[0] == item['start'] for v in json.loads(lists[0])), 'actual registration removal required')
    late, window = item['late_input'], item['business_window']
    stamps = [item['start_wall_ns'],item['bound_wall_ns'],app['start_wall_ns'],callback['observed_wall_ns'],
        app['end_wall_ns'],item['terminal_attempts'][0]['start_wall_ns'],item['terminal_attempts'][-1]['end_wall_ns'],
        late['wall_ns'],late['completed_wall_ns'],window['start_wall_ns'],window['end_wall_ns'],
        item['requester_observation']['start_wall_ns'],item['requester_observation']['end_wall_ns'],
        item['terminal_after_business']['start_wall_ns'],item['terminal_after_business']['end_wall_ns'],
        item['quit_wall_ns'],item['owner_exit_wall_ns'],cleanup['start_wall_ns'],cleanup['end_wall_ns'],item['end_wall_ns']]
    need(all(type(v) is int and v > 0 for v in stamps) and stamps == sorted(stamps), 'original wall chronology required')
    need(len(row['applications']) == 2 and all(a['exit'] == 0 and window['start_wall_ns'] <= a['start_wall_ns']
         <= a['end_wall_ns'] <= window['end_wall_ns'] for a in row['applications']), 'original ordinary business after terminal required')
    clock_bounds(item)
    return sdk


def corroborate(row, matched, sdus):
    """One request pair; no post-deadline response is required or accepted."""
    from ws73_ssap_value import pair_wire, command_packet, physical_sends
    need(type(row.get(PREFIX+'_required', False)) is bool, 'typed explicit Provider deadline selection required')
    if not row.get(PREFIX+'_required', False):
        need(not any(k.startswith(PREFIX+'_') and k != PREFIX+'_required' for k in row), 'unrequested deadline evidence')
        return [], {0:0, 1:0}
    need(type(row[PREFIX+'_version']) is int and row[PREFIX+'_version'] == VERSION
         and row['ssap_read_provider_version'] == 2 and len(row[COLLECTION]) == 1,
         'one new deadline case preserving original Provider-v2 required')
    item = row[COLLECTION][0]; sdk = case_contract(row, item)
    window = dict(start_wall_ns=item['read']['start_wall_ns'], end_wall_ns=item['end_wall_ns'])
    inventory = window_packets(row, window, sdus)
    pdu = b'\x08\x03'+item['handle'].to_bytes(2,'little')+b'\0'
    wire = pair_wire(row, matched, row['owners'][0], row['owners'][1], pdu, window)
    frame = b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
    offset_lower, offset_upper = clock_bounds(item)
    for side, index, direction in (('tx',0,'out'),('rx',1,'in')):
        packet = wire[side]; identity, link = row['owners'][index]['owner'], row['owners'][index]['object']
        need('ssap_fragments' not in packet, 'short READ only')
        command_packet(packet, frame, window)
        need(all(type(p['wall_ns']) is int and p['wall_ns'] > 0 and p['wall_ns'] % 1000 == 0
                 for p in [packet,*packet['fragments']]), 'original usbmon microsecond timestamp precision required')
        need(all((p['bus'],p['device'],p['handle'],p['direction'])
                 == (identity['bus'],identity['device'],link['handle'],direction)
                 for p in [packet,*packet['fragments']]), 'every request fragment belongs to the original endpoint')
        need(packet_interval(packet)[0]-offset_upper >= sdk['call_ns'], 'whole request must follow actual SDK call')
        need(packet_interval(packet)[1]+999-offset_lower < item['callback']['observed_monotonic_ns'],
             'whole request must precede its actual Provider callback with clock uncertainty included')
    need(packet_interval(wire['tx'])[1]+999 < packet_interval(wire['rx'])[0], 'whole request TX must precede opposite RX')
    need(sorted(inventory,key=packet_key) == sorted([wire['tx'],wire['rx']],key=packet_key),
         'exact full window: no peer response, fallback, late value or duplicate request')
    context = {k:copy.deepcopy(row[k]) for k in ('phase','owners','ssap_receipts','applications','application_tool',
        'rounds','message_bytes','channel_info_required','tx_status_required','message_security_required',
        'tx_constraint_required','security_requirement','dtap_limits_version','cmtc_local_capability',
        'ssap_read_provider_cases','ssap_language_clients')}
    for key in ('ssap_provider_owner_exit_required','ssap_provider_owner_exit_version',
                'ssap_provider_owner_exit_cases','ssap_provider_owner_exit_guards'):
        if key in row:context[key] = copy.deepcopy(row[key])
    return [dict(version=VERSION, case=copy.deepcopy(item), sdk=sdk, wire=wire,
        window_packets=copy.deepcopy(inventory), context=context, bounded_absence_only=True,
        same_actor_recovery=False, automatic_recovery_qualification=False)], {0:physical_sends(wire['tx']),1:0}


def verify_business_evidence(row, proof, legs):
    need(len(proof) == 1, 'one deadline scope per physical lifetime required')
    verify_business(row, proof[0]['case'], legs)


def valid_summary(summary):
    """Bounded local recheck; outer retained gates and raw auditor remain mandatory."""
    try:
        from ws73_ssap_provider_owner_exit import valid_summary as owner_exit_summary
        from ws73_ssap_read_provider import valid_summary as provider_summary
        need(owner_exit_summary(summary), 'original retained Owner-exit paired summary required')
        need(provider_summary(summary, version=2), 'original retained Provider-v2 paired summary required')
        rows = summary['proofs']; need(len(rows) == 2, 'two physical roles required')
        receivers = set()
        for phase, row in enumerate(rows):
            item, = row[PREFIX]; context = item['context']; case = item['case']
            need(type(item['version']) is int and item['version'] == VERSION
                 and item['bounded_absence_only'] is True and item['same_actor_recovery'] is False
                 and item['automatic_recovery_qualification'] is False
                 and type(row['phase']) is int and type(context['phase']) is int
                 and context['phase'] == row['phase'] == phase and context['owners'] == row['owners'],
                 'original phase context and bounded proof scope required')
            # These retained calls must be the same evidence that the outer
            # Provider/Owner-exit validators just replayed, not an independently
            # self-consistent second copy inside the deadline context.
            retained_providers = [proof['case'] for proof in row['ssap_read_providers']]
            retained_exits = [proof['case'] for proof in row['ssap_provider_owner_exit']]
            need(context['ssap_read_provider_cases'] == retained_providers
                 and context['ssap_provider_owner_exit_cases'] == retained_exits
                 and context['ssap_provider_owner_exit_guards'] == [case['guard'] for case in retained_exits],
                 'deadline inventory must bind the same-phase retained Provider and Owner-exit proofs')
            receiver = row['owners'][1]['owner']; receivers.add((receiver['index'],receiver['generation']))
            packets = copy.deepcopy(item['window_packets'])
            def matched(entry, direction, frame, window):
                key = (entry['owner']['bus'],entry['owner']['device'],entry['object']['handle'],direction,frame.hex())
                found = [p for p in packets if tuple(p[k] for k in ('bus','device','handle','direction','data')) == key
                         and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
                need(len(found) == 1, 'one exact retained request packet required')
                packets.remove(found[0]); return found[0]
            context = dict(context, **{PREFIX+'_required':True, PREFIX+'_version':VERSION,
                'ssap_read_provider_version':2, COLLECTION:[case]})
            rebuilt, _ = corroborate(context, matched, packets)
            need(not packets and rebuilt == [item], 'exact retained deadline proof reconstruction required')
            verify_business_evidence(context, rebuilt, row['legs'])
        return len(receivers) == 2
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, StopIteration):
        return False


def valid_manifest(record):
    try:
        selected = record.get(PREFIX+'_requested', False)
        need(type(selected) is bool and boot_requested([t for arg in record.get('qemu_args', []) for t in arg.split()]) == selected,
             'original Provider deadline boot/manifest selection required')
        proof = record.get('channel_socket_corroboration', {})
        if not selected:
            return (record.get(PREFIX+'_acceptance', False) is False and PREFIX+'_version' not in record
                    and not any(PREFIX in row for row in proof.get('proofs', [])))
        from ws73_ssap_provider_owner_exit import valid_manifest as owner_exit_manifest
        verifier = record[PREFIX+'_verifier']
        return (type(record.get(PREFIX+'_version')) is int and record[PREFIX+'_version'] == VERSION
                and record.get(PREFIX+'_acceptance') is True and owner_exit_manifest(record)
                and type(verifier) is dict and Path(verifier['path']).name == Path(__file__).name
                and re.fullmatch('[0-9a-f]{64}',verifier['sha256']) is not None
                and valid_summary(proof))
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, StopIteration):
        return False
