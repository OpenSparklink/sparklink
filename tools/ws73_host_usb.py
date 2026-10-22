# SPDX-License-Identifier: GPL-2.0-only
"""Read-only QEMU host USB request observations, never a delivery verdict.

The packet pointer identifies only one pending host request. Cancellation and
emulation are distinct terminals; pointer reuse after a terminal is allowed.
Integer intervals stay in the host trace clock. No host/guest clock subtraction.
"""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re

from ws73_capture import CaptureError

MAX_BYTES = 64 * 1024 * 1024
MAX_LINES = 500_000
MAX_REQUESTS = 100_000
LINE = re.compile(r'\d+@(\d+)\.(\d{6}):(\w+) (.+)')
IDENTITY = r'dev (\d+):(\d+), packet (0x[0-9a-f]+)'
REQUESTS = {
    'usb_host_req_data': re.compile(IDENTITY + r', in ([01]), ep (\d+), size (\d+)'),
    'usb_host_req_control': re.compile(IDENTITY + r', req (0x[0-9a-f]+), value (\d+), index (\d+)'),
    'usb_host_req_complete': re.compile(IDENTITY + r', status (-?\d+), length (\d+)'),
    'usb_host_req_canceled': re.compile(IDENTITY),
    'usb_host_req_emulated': re.compile(IDENTITY + r', status (-?\d+)'),
}


def request_ledger(lines, devices):
    """Require a closed original trace; an unclosed request is not drain proof."""
    if (not isinstance(devices, (list, tuple, set)) or not devices
            or any(type(v) is not tuple or len(v) != 2
                   or any(type(n) is not int or n <= 0 for n in v) for v in devices)
            or len(set(devices)) != len(devices)):
        raise CaptureError('explicit distinct original host USB identities required')
    devices = set(devices)
    pending, closed, counts, halts, releases = {}, [], Counter(), [], []
    for number, line in enumerate(lines, 1):
        if number > MAX_LINES:
            raise CaptureError('host trace line budget exceeded')
        match = LINE.fullmatch(line)
        if not match:
            raise CaptureError('malformed host trace line')
        seconds, micros, name, body = match.groups()
        stamp = int(seconds) * 1_000_000_000 + int(micros) * 1000
        counts[name] += 1
        if name not in REQUESTS:
            if name.startswith('usb_host_req_'):
                raise CaptureError('unknown host request transition')
            if name == 'usb_xhci_ep_state' and body.endswith(' -> halted'):
                halts.append(dict(line=number, wall_ns=stamp, body=body))
            if name == 'usb_host_release_interface':
                m = re.fullmatch(r'dev (\d+):(\d+), if (\d+)', body)
                if not m or tuple(map(int, m.groups()[:2])) not in devices:
                    raise CaptureError('malformed release identity')
                releases.append(dict(line=number, wall_ns=stamp, body=body))
            continue
        match = REQUESTS[name].fullmatch(body)
        if not match:
            raise CaptureError('malformed host request transition')
        bus, device, pointer, *tail = match.groups()
        key = int(bus), int(device), pointer
        if key[:2] not in devices:
            raise CaptureError('original host device identity mismatch')
        if name in ('usb_host_req_data', 'usb_host_req_control'):
            if key in pending:
                raise CaptureError('duplicate pending host packet')
            if len(closed) + len(pending) >= MAX_REQUESTS:
                raise CaptureError('host request budget exceeded')
            row = dict(host_bus=key[0], host_device=key[1], packet=pointer,
                       type='data' if name.endswith('_data') else 'control',
                       submit_line=number, submit_wall_ns=stamp)
            if row['type'] == 'data':
                row.update(direction=int(tail[0]), endpoint=int(tail[1]), requested=int(tail[2]))
                if not 1 <= row['endpoint'] <= 15 or not 0 <= row['requested'] <= 1 << 20:
                    raise CaptureError('host endpoint/transfer budget exceeded')
            else:
                row.update(request=int(tail[0], 16), value=int(tail[1]), index=int(tail[2]))
                if any(not 0 <= row[k] <= 65535 for k in ('request', 'value', 'index')):
                    raise CaptureError('host control field out of range')
            pending[key] = row
            continue
        row = pending.pop(key, None)
        if row is None:
            raise CaptureError('completion/cancel/emulation without unique request')
        if stamp < row['submit_wall_ns']:
            raise CaptureError('completion precedes request in host clock')
        row.update(terminal=name.removeprefix('usb_host_req_'), terminal_line=number,
                   terminal_wall_ns=stamp, interval_ns=stamp - row['submit_wall_ns'])
        if name == 'usb_host_req_complete':
            row.update(status=int(tail[0]), length=int(tail[1]))
            if row['type'] == 'data' and not 0 <= row['length'] <= row['requested']:
                raise CaptureError('host complete exceeds original buffer')
        if name == 'usb_host_req_emulated':
            if row['type'] != 'control':
                raise CaptureError('data must not be emulated')
            row['status'] = int(tail[0])
        closed.append(row)
    if not closed or pending:
        raise CaptureError('empty or unclosed host request trace')
    return dict(closed=closed, counts=dict(counts), halts=halts, releases=releases)


def bounded_bytes(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise CaptureError('host trace byte budget exceeded')
    with path.open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CaptureError('host trace grew beyond byte budget')
    return raw


def decode_lines(raw):
    try:
        return raw.decode('ascii').splitlines()
    except UnicodeError as error:
        raise CaptureError('host trace must be ASCII') from error


def read_requests(path, devices):
    return request_ledger(decode_lines(bounded_bytes(path)), devices)


def completion_candidates(ledger, bulk, host, guest, direction):
    """Unique ordered length-sequence candidates, not a cross-clock identity.

    The host trace has no payload or guest URB id. This association assumes
    complete ordered observations of the selected single-request stream.
    Ambiguity is refused; identical-length missing/duplicate pairs cannot be
    excluded by this trace and remain an explicit limitation.
    """
    if type(direction) is not int or direction not in (0, 1):
        raise CaptureError('explicit bulk direction required')
    source = [r for r in ledger['closed'] if r['type'] == 'data'
              and (r['host_bus'], r['host_device']) == host
              and r['endpoint'] == 1 and r['direction'] == direction
              and r['terminal'] == 'complete' and r['status'] == 0]
    target = [r for r in bulk if (r['bus'], r['device']) == guest
              and r['endpoint'] == (0x81 if direction else 1)
              and r['kind'] == 'C' and r['status'] == 0]
    if (not source or not target or any(a['terminal_wall_ns'] > b['submit_wall_ns']
            for a, b in zip(source, source[1:]))
            or any(a['record'] >= b['record'] for a, b in zip(target, target[1:]))):
        raise CaptureError('nonempty ordered single-request streams required')
    left, right = [r['length'] for r in source], [r['length'] for r in target]
    starts = [i for i in range(len(left) - len(right) + 1)
              if left[i:i+len(right)] == right]
    if len(starts) != 1:
        raise CaptureError('host/guest completion length sequence absent or ambiguous')
    start = starts[0]
    return {r['record']: source[start+i] for i, r in enumerate(target)}


def original_mapping(manifest, messages, owners):
    """Captured QMP attachment only; never discover/select/open a live device."""
    selected = manifest['physical_resource_allocation']['selected_ports']
    adds = [m['arguments'] for m in messages if m.get('execute') == 'device_add']
    if (manifest.get('qmp_guest_hotplug') is not True or len(owners) != 2
            or len(selected) != 2 or len(set(selected)) != 2 or len(adds) != 2
            or any(m.get('execute') in ('device_del','qom-set','system_reset') for m in messages)):
        raise CaptureError('original explicit two-device QMP attachment required')
    mapping = []
    for entry in owners:
        owner = entry['owner']
        matches = [a for a in adds if owner['port'] == f'{owner["bus"]}-{a.get("port")}']
        if len(matches) != 1:
            raise CaptureError('one original guest port attachment required')
        config = matches[0]
        host_port = f'{config.get("hostbus")}-{config.get("hostport")}'
        # Connection-role exchange reverses the application owners, not the
        # original QMP attachment. Join by the captured guest port and require
        # the complete explicit allocation below; never use list position as
        # device identity.
        if (config.get('driver') != 'usb-host' or host_port not in selected
                or any(config.get(k) is not False for k in
                       ('guest-reset','guest-resets-all','kernel-driver-detach','host-reset'))
                or any('test' in k for k in config)):
            raise CaptureError('captured leaf port/no-reset boundary mismatch')
        original = manifest['inventory_before'][host_port]
        if original['bus'] != config['hostbus'] or original['path'] != host_port:
            raise CaptureError('original host inventory disagrees with QMP')
        mapping.append(dict(host_port=host_port, host=(original['bus'], original['address']),
                            guest=(owner['bus'], owner['device']),
                            controller=owner['index'], generation=owner['generation']))
    if (len({r['host'] for r in mapping}) != 2 or len({r['guest'] for r in mapping}) != 2
            or {r['host_port'] for r in mapping} != set(selected)):
        raise CaptureError('distinct captured host/guest identities required')
    return mapping


def observe_failed(root, manifest, row, reports, application, capture, timings, parsed):
    """Opt-in addition after the existing complete failed-window oracle.

    Host trace hashes are checked at fixed paths. QMP bytes are separately
    recorded for an outer evidence seal; this function cannot authenticate
    a mutable manifest or its claimed original identities.
    """
    from ws73_benchmark_progress import business_legs, observed_link_window

    root = Path(root)
    trace, events, qmp = [root / n for n in ('usb-lifecycle.log','usb-lifecycle.events','qmp.jsonl')]
    raw = {p: bounded_bytes(p) for p in (trace,events,qmp)}
    for path in (trace, events):
        expected = [r for r in manifest['host_lifecycle_files'] if Path(r['path']).name == path.name]
        if len(expected) != 1 or hashlib.sha256(raw[path]).hexdigest() != expected[0]['sha256']:
            raise CaptureError('original host lifecycle material hash required')
    messages = [v['message'] for line in decode_lines(raw[qmp])
                if (v := json.loads(line))['direction'] == 'tx']
    mapping = original_mapping(manifest, messages, row['owners'])
    ledger = request_ledger(decode_lines(raw[trace]), [r['host'] for r in mapping])
    bulk = capture['bulk_urbs']
    candidates = {}
    sequences = []
    for endpoint, identity in enumerate(mapping):
        for direction in (0, 1):
            paired = completion_candidates(ledger, bulk, identity['host'], identity['guest'], direction)
            candidates[endpoint, direction] = paired
            sequences.append(dict(endpoint=endpoint, direction=direction, candidate_completions=len(paired),
                                  first_guest_record=min(paired), last_guest_record=max(paired)))
    # A3 OUT receipts point at submissions; sequence candidates use completions.
    pending, submissions = {}, {}
    for point in bulk:
        if point['endpoint'] != 1:
            continue
        key = point['bus'], point['device'], point['urb']
        if point['kind'] == 'S':
            if key in pending:
                raise CaptureError('duplicate OUT submission in bulk metadata')
            pending[key] = point['record']
        else:
            submitted = pending.pop(key, None)
            if submitted is None:
                raise CaptureError('OUT completion missing original bulk metadata')
            if point['kind'] == 'C' and point['status'] == 0:
                submissions[submitted] = point['record']
    if pending:
        raise CaptureError('OUT metadata has an unfinished request')
    anchor = min(e['before_wall_ns'] for e in row['events'] if e['kind'] == 'start')
    scoped, windows = observed_link_window(capture, row['owners'], anchor)
    legs = business_legs(scoped, reports, application, row['owners'], timings)
    for leg in legs:
        direction = int(leg['direction'] == 'in')
        keys = leg['fragment_records'] if direction else [submissions[r] for r in leg['fragment_records']]
        paired = candidates[leg['endpoint'], direction]
        if any(r not in paired for r in keys):
            raise CaptureError('business fragment lacks a host completion candidate')
        requests = [paired[k] for k in dict.fromkeys(keys)]
        leg['host_candidates'] = dict(requests=len(requests),
            first_submit_line=requests[0]['submit_line'], last_terminal_line=requests[-1]['terminal_line'],
            first_submit_wall_ns=requests[0]['submit_wall_ns'],
            last_terminal_wall_ns=requests[-1]['terminal_wall_ns'],
            max_request_interval_ns=max(r['interval_ns'] for r in requests))
        if direction:
            from ws73_rx_gap import observe
            stream = list(paired.values())
            lo, hi = requests[0]['submit_wall_ns'], requests[-1]['terminal_wall_ns']
            gaps = [b['submit_wall_ns'] - a['terminal_wall_ns'] for a, b in zip(stream, stream[1:])
                    if lo <= a['terminal_wall_ns'] <= b['submit_wall_ns'] <= hi]
            leg['host_candidates']['resubmit_gaps'] = dict(samples=len(gaps),
                max_ns=max(gaps,default=None),sum_ns=sum(gaps),
                scope='Fully observed adjacent endpoint-1 host requests in this PDU interval, including nonbusiness input. Edges censored; not callback CPU time, RF delay or a performance verdict.')
            if len(set(keys)) > 1:
                guest_gap = observe(capture['rx_urbs'],
                    dict(bus=mapping[leg['endpoint']]['guest'][0],device=mapping[leg['endpoint']]['guest'][1]),
                    leg['first_wall_ns'],leg['last_wall_ns']+1)
                leg['guest_resubmit_gaps'] = {k:guest_gap[k] for k in ('gap','sum_gap_ns',
                    'right_censored_completions','peak_observed_outstanding')}
            else:
                leg['guest_resubmit_gaps'] = dict(status='INSUFFICIENT_PAIRED_COMPLETIONS')
    errors = [r for r in parsed['rows'] if r['event'] == 'work' and r['stage'] == 1 and r['error']]
    if not errors:
        raise CaptureError('original trace has no software fault to locate')
    first = min(errors, key=lambda r: r['mono_ns'])
    start = min(e['before_wall_ns'] for e in row['events'] if e['kind'] == 'start')
    lo, hi = parsed['offset_ns']
    quantum = parsed['quantum_ns']
    downs = []
    for endpoint, owner in enumerate(row['owners']):
        identity = reports[endpoint]['channel_identity']
        for event in capture['native_events']:
            params = bytes.fromhex(event['params'])
            if ((event['bus'],event['device']) != mapping[endpoint]['guest']
                    or event['event'] not in (5,0x1405) or event['wall_ns'] < start):
                continue
            if len(params) != 4 or params[0] != 0 or int.from_bytes(params[1:3], 'little') != identity['handle']:
                raise CaptureError('original successful Down has a different handle/shape')
            downs.append(dict(endpoint=endpoint, record=event['record'], reason=params[3],
                guest_wall_ns=event['wall_ns'],
                after_first_software_fault_lower_ns=event['wall_ns']-hi-quantum-first['mono_ns'],
                after_first_software_fault_upper_ns=event['wall_ns']-lo+quantum-first['mono_ns']))
    if len(downs) != 2 or {r['endpoint'] for r in downs} != {0,1}:
        raise CaptureError('both original physical Down observations required')
    end = max(r['guest_wall_ns'] for r in downs)
    disconnects = [r['record'] for r in capture['commands'] if r['opcode'] == 0x1403 and start <= r['wall_ns'] <= end]
    failures = [r for r in ledger['closed'] if r['type'] == 'data'
                and r['terminal'] == 'complete' and r['status']]
    return dict(status='FAILED_BUSINESS_AND_HOST_LENGTH_CANDIDATES_NOT_QUALIFIED',
        observed_link_windows=windows,
        original_result='FAIL', original_gate_qualified=False, mapping=mapping,
        materials=[dict(path=str(p),bytes=len(raw[p]),sha256=hashlib.sha256(raw[p]).hexdigest())
                   for p in (trace,events,qmp)],
        host_request_count=len(ledger['closed']), host_event_counts=ledger['counts'],
        sequences=sequences, business_legs=legs,
        first_unanswered_application_index=min(application['unanswered_indices'],default=None),
        first_software_fault={k:first[k] for k in ('ctl','gen','life','service','mono_ns','error')},
        physical_Down=downs, captured_disconnect_commands=disconnects,
        host_nonzero_data_completions=failures, host_halts=ledger['halts'], host_releases=ledger['releases'],
        scope=['Original failed artifacts only. Random payload/fragment and Session-operation joins do not turn the whole failure into business qualification.',
               'Host association is a unique ordered length candidate, assuming complete ordered streams. Host trace has no payload/guest URB ID; identical-length missing/duplicate pairs are not independently excluded.',
               'Guest wall/trace-mono comparison uses original validated guest anchors and quantization. Host intervals stay separate; no host/guest clock mapping, one-way RF latency or callback CPU-time claim.',
               'Raw Down reason and software timeout are different observations, not a firmware/RF/root-cause proof. NOCP does not prove peer delivery; no credit refunds or deadline/load changes.',
               'Final host nonzero completions/halts/releases are retained, not called the first business failure or natural recovery. No new hardware run, drain proof or current-image qualification.'])
