# SPDX-License-Identifier: GPL-2.0-only
"""Cancel while an original host reply is held, then remove only its VM owner.

This is guest lifecycle support, never physical unplug or autonomous recovery.
No reply is constructed, replayed or changed by this coordinator.
"""
import json
from pathlib import Path
import re
import time

from ws73_daemon_hold import Invocation, observed, management_observed
from ws73_diagnostic_hold import HoldCoordinator, PROPERTIES, write_marker
from ws73_north_star import ordinary_identity, daemon_identity, parse_result, stable


RESET_OPTIONS = ['host-reset', 'kernel-driver-detach', 'guest-reset', 'guest-resets-all']


class RemovalCoordinator(HoldCoordinator):
    def __init__(self, share, record):
        super().__init__(share, record)
        self.folder = Path(share)/'application/passthrough-control/daemon-remove'
        self.record['method'] = 'QMP_REMOVE_ACTUAL_HELD_IN81'

    def poll(self, monitor):
        if self.phase in ['await_remove', 'removed', 'done']:
            return
        super().poll(monitor)
        if self.phase == 'release_ready':
            self.phase = 'await_remove'

    def peer_snapshot(self, monitor):
        peer = HoldCoordinator(self.folder, {})
        peer.path = '/machine/peripheral/ws73_1'
        state = peer.snapshot(monitor)
        options = {key: monitor.execute('qom-get', {'path': peer.path, 'property': key})
                   for key in [*RESET_OPTIONS, 'attached']}
        if state != dict(zip(PROPERTIES, [False, False, 0, 0, 0, 0, False, 0])) or options != dict.fromkeys(RESET_OPTIONS, False) | {'attached': True}:
            raise ValueError('independent attached peer with fresh disabled counters required')
        return dict(state=state, options=options)

    def before_remove(self, monitor):
        expected = dict(zip(PROPERTIES, [False, True, 1, 0, 0, 0, False, 0]))
        if self.phase != 'await_remove' or self.snapshot(monitor) != expected:
            raise ValueError('remove must precede original release/drop/deadline')
        options = {key: monitor.execute('qom-get', {'path': self.path, 'property': key}) for key in RESET_OPTIONS}
        if options != dict.fromkeys(RESET_OPTIONS, False):
            raise ValueError('all target reset/detach opt-outs required')
        self.record.update(before_remove_state=expected, reset_options=options,
                           peer_before_remove=self.peer_snapshot(monitor),
                           removed_id='ws73_0', delete_request_wall_ns=time.time_ns())

    def after_remove(self, monitor):
        self.record['delete_ack_wall_ns'] = time.time_ns()
        self.record['peer_after_remove'] = self.peer_snapshot(monitor)
        self.phase = 'removed'

    def after_readd(self, properties):
        if self.phase != 'removed' or properties.get('id') != 'ws73_0':
            raise ValueError('only the removed owner may be re-added')
        self.record.update(readd_properties=properties, readd_wall_ns=time.time_ns(), complete=True)
        self.phase = 'done'


class RemovalSession:
    def __init__(self, run):
        self.run = run
        self.callers = []

    def begin(self):
        run = self.run
        a, b = run.data['initial']
        folder = run.output/'daemon-remove'
        folder.mkdir(exist_ok=False)
        r = dict(format_version=1, status='RUNNING', target=a, peer=b, markers=[], hold_acknowledgements=[],
                 acknowledgement_observed_wall_ns=[],
                 application_identity=ordinary_identity(), daemon_before=daemon_identity(run.args.slkd_pid),
                 bus_before=run.bus_identity(), cancel_polls=[], physical_acceptance=False,
                 automatic_fault_recovery_acceptance=False)
        self.record = r
        run.data['daemon_removal'] = r
        run.save()

        def stage(phase, ack):
            marker = dict(hold_phase=phase, wall_ns=time.time_ns())
            r['markers'].append(marker)
            run.save()
            write_marker(folder/f'hold-{phase}.json', marker)
            deadline = time.monotonic()+6
            while not (folder/f'hold-{ack}-ack.json').exists():
                run.alive()
                if time.monotonic() > deadline:
                    raise TimeoutError('actual held-removal host acknowledgement')
                time.sleep(.002)
            value = json.loads((folder/f'hold-{ack}-ack.json').read_text())
            if value['stage'] != ack or value['request'] != marker:
                raise ValueError('wrong held-removal acknowledgement')
            r['hold_acknowledgements'].append(value)
            r['acknowledgement_observed_wall_ns'].append(time.time_ns())
            run.save()

        prefix = [str(run.args.slctl), '--adapter', a['path']]
        stage('arm_ready', 'armed')
        original = Invocation(prefix+['scan', 'on'], 'on')
        self.callers.append(original)
        r['original_caller'] = original.row
        old = original.identifier()
        stage('wait_held', 'held')
        r['pending'] = run.command(prefix+['result', str(old)], 3, field='removal_pending')
        observed(r['pending'], a, old, 3, 2, 0x1001, 0, 2)
        r['peer_start'] = run.command([str(run.args.slctl), '--adapter', b['path'], 'scan', 'on'], 3, field='removal_peer_start')
        parse_result(r['peer_start']['stdout'], b, 3)
        cancel = Invocation(prefix+['cancel-discovery'], 'cancel')
        self.callers.append(cancel)
        r['cancel_caller'] = cancel.row
        if cancel.identifier() != a['generation']:
            raise ValueError('wrong selected cancellation generation')
        deadline = time.monotonic()+.1
        while True:
            row = run.command(prefix+['result', str(old)], 3, field='removal_cancelled')
            r['cancel_polls'].append(row)
            r['cancelled'] = row
            run.save()
            try:
                observed(row, a, old, 3, 5, 0x1001, 0, 2)
                break
            except ValueError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.001)
        original.finish()
        r['management_revoking'] = run.command(prefix+['management'], 3, field='removal_management')
        management_observed(r['management_revoking'], a, 2)
        r['cancel_pending_before_remove'] = cancel.process.poll() is None
        if not r['cancel_pending_before_remove']:
            raise ValueError('cancel completed before held owner removal')
        r['remove_ready_wall_ns'] = time.time_ns()
        run.save()

    def removed(self):
        run, r = self.run, self.record
        a, b = r['target'], r['peer']
        self.callers[-1].finish()
        cancel = r['cancel_caller']
        if not cancel['exit'] or 'NativePoliciesCancelled:' in cancel['stdout']:
            raise ValueError('removed owner must return actual cancellation RPC failure')
        req = parse_result(r['peer_start']['stdout'], b, 3)['request']
        r['peer_on_after_remove'] = run.command([str(run.args.slctl), '--adapter', b['path'], 'result', str(req)], 3, field='removal_peer_on')
        parse_result(r['peer_on_after_remove']['stdout'], b, 3)
        r['peer_stop'] = run.command([str(run.args.slctl), '--adapter', b['path'], 'scan', 'off'], 3, field='removal_peer_stop')
        parse_result(r['peer_stop']['stdout'], b, 4)
        r['peer_after'] = run.ready(b['port'])
        if not stable(b, r['peer_after']):
            raise ValueError('target removal changed peer registration')
        r['retirement_polls'] = []
        deadline = time.monotonic()+3
        while True:
            row = run.command([str(run.args.slctl), '--adapter', a['path'], 'show'], 3, field='removal_retired')
            r['retirement_polls'].append(row)
            run.save()
            if row['exit'] and 'not a live registration' in row['stderr']:
                r['retired_selection'] = row
                break
            if time.monotonic() > deadline:
                raise TimeoutError('old registration retirement')
            time.sleep(.002)
        r['daemon_after'] = daemon_identity(run.args.slkd_pid)
        r['bus_after'] = run.bus_identity()
        r['status'] = 'DAEMON_CANCEL_REMOVAL_EVIDENCE_PENDING'
        verify_records(r)
        run.save()

    def close(self):
        for caller in self.callers:
            if caller.process.poll() is None:
                caller.finish(kill=True)
        self.run.save()


def verify_records(r):
    if (r.get('format_version') != 1 or r.get('status') != 'DAEMON_CANCEL_REMOVAL_EVIDENCE_PENDING'
            or r.get('physical_acceptance') is not False or r.get('automatic_fault_recovery_acceptance') is not False):
        raise ValueError('explicit limited cancel/removal records required')
    a, b = r['target'], r['peer']
    if any(a[k] == b[k] for k in ['generation', 'path', 'address', 'port']):
        raise ValueError('independent registrations required')
    app = r['application_identity']
    if app['uids'] != [1000]*4 or any(int(app[k], 16) for k in ['cap_eff', 'cap_prm', 'cap_amb']):
        raise ValueError('ordinary caller without capabilities required')
    if r['daemon_before'] != r['daemon_after'] or r['bus_before'] != r['bus_after'] or r['bus_before']['pid'] != r['daemon_before']['pid']:
        raise ValueError('unchanged running daemon and authenticated owner required')
    if not stable(b, r['peer_after']) or r.get('cancel_pending_before_remove') is not True:
        raise ValueError('independent peer and actual pending cancel required')
    original, cancel = r['original_caller'], r['cancel_caller']
    old = original['request_id']
    prefix = [original['args'][0], '--adapter', a['path']]
    if (not old or original['pid'] == cancel['pid'] or original['args'] != prefix+['scan', 'on']
            or cancel['args'] != prefix+['cancel-discovery'] or cancel['generation'] != a['generation']
            or original['toggle'] != 'on' or cancel['toggle'] != 'cancel'):
        raise ValueError('distinct actual callers and exact selected affinity required')
    if re.findall(r'^NativeScanRequest: request=(\d+) enable=on$', original['stdout'], re.M) != [str(old)]:
        raise ValueError('actual original request marker required')
    observed(original, a, old, 3, 5, 0x1001, 0, 2)
    for key, state in [('pending', 2), ('cancelled', 5)]:
        if r[key]['args'] != prefix+['result', str(old)]:
            raise ValueError('old result query affinity required')
        observed(r[key], a, old, 3, state, 0x1001, 0, 2)
    management_observed(r['management_revoking'], a, 2)
    if r['management_revoking']['args'] != prefix+['management']:
        raise ValueError('Revoking query affinity required')
    if (type(cancel['exit']) is not int or cancel['exit'] <= 0 or 'NativePoliciesCancelled:' in cancel['stdout']
            or re.findall(r'^NativePoliciesCancelRequest: generation=(\d+)$', cancel['stdout'], re.M) != [str(a['generation'])]
            or not any(word in cancel['stderr'].lower() for word in ['no such device', 'removed', 'enodev'])):
        raise ValueError('actual removed-device RPC error, no successful confirmation required')
    markers, acks = r['markers'], r['hold_acknowledgements']
    if len(markers) != 2 or [v['hold_phase'] for v in markers] != ['arm_ready', 'wait_held'] or [v['stage'] for v in acks] != ['armed', 'held'] or [v['request'] for v in acks] != markers:
        raise ValueError('arm/hold only; no explicit release permitted')
    times = [markers[0]['wall_ns'], original['start_wall_ns'], original['marker_wall_ns'], markers[1]['wall_ns'], r['pending']['start_wall_ns'], r['pending']['end_wall_ns'], r['peer_start']['start_wall_ns'], r['peer_start']['end_wall_ns'], cancel['start_wall_ns'], cancel['marker_wall_ns'], r['cancelled']['start_wall_ns'], r['cancelled']['end_wall_ns'], original['end_wall_ns'], r['management_revoking']['start_wall_ns'], r['management_revoking']['end_wall_ns'], r['remove_ready_wall_ns'], cancel['end_wall_ns'], r['peer_on_after_remove']['start_wall_ns'], r['peer_on_after_remove']['end_wall_ns'], r['peer_stop']['start_wall_ns'], r['peer_stop']['end_wall_ns'], r['retired_selection']['start_wall_ns'], r['retired_selection']['end_wall_ns']]
    if any(type(t) is not int or t <= 0 for t in times) or times != sorted(times) or r['remove_ready_wall_ns']-original['start_wall_ns'] >= 400_000_000:
        raise ValueError('actual cancellation-before-removal within original500ms deadline required')
    if not r['remove_ready_wall_ns'] <= r['remove_ack_observed_wall_ns'] <= cancel['end_wall_ns']:
        raise ValueError('actual delete acknowledgement must precede collecting RPC failure')
    if not r['cancel_polls'] or r['cancel_polls'][-1] != r['cancelled']:
        raise ValueError('actual Pending-to-Cancelled history required')
    previous = cancel['marker_wall_ns']
    for i, row in enumerate(r['cancel_polls']):
        observed(row, a, old, 3, 5 if i == len(r['cancel_polls'])-1 else 2, 0x1001, 0, 2)
        if row['args'] != prefix+['result', str(old)] or not previous <= row['start_wall_ns'] <= row['end_wall_ns']:
            raise ValueError('ordered cancellation queries required')
        previous = row['end_wall_ns']
    peer_req = parse_result(r['peer_start']['stdout'], b, 3)['request']
    for key, words, op in [('peer_start', ['scan', 'on'], 3), ('peer_on_after_remove', ['result', str(peer_req)], 3), ('peer_stop', ['scan', 'off'], 4)]:
        row = r[key]
        if row['exit'] or row['args'] != [prefix[0], '--adapter', b['path'], *words]:
            raise ValueError('successful actual peer control required')
        parse_result(row['stdout'], b, op)
    retired = r['retired_selection']
    if retired['args'] != prefix+['show'] or not retired['exit'] or 'not a live registration' not in retired['stderr'] or not r['retirement_polls'] or r['retirement_polls'][-1] != retired:
        raise ValueError('old registration must reject new work')


def corroborate_wire(r, capture):
    from ws73_capture import command_reply
    verify_records(r)
    a, b = r['target'], r['peer']
    start, end = r['original_caller']['start_wall_ns'], r['peer_stop']['end_wall_ns']
    rows = lambda key, owner: [v for v in capture[key] if (v['bus'], v['device']) == (owner['bus'], owner['device']) and start <= v['wall_ns'] <= end]
    target = rows('commands', a)
    if (len(target) != 1 or target[0]['opcode'] != 0x1001 or target[0]['params'] != '0000010040062003'
            or not start <= target[0]['wall_ns'] <= target[0]['completion']['wall_ns'] <= r['pending']['end_wall_ns']
            or rows('complete', a)):
        raise ValueError('one actual original OUT; zero delivered old Complete/START/STOP required')
    failures = rows('failures', a)
    if not any(v['endpoint'] == 0x81 and v['status'] != 0 and r['remove_ready_wall_ns'] <= v['wall_ns'] <= end for v in failures) or rows('failures', b):
        raise ValueError('actual target IN retirement and no peer USB failure required')
    peer = []
    for opcode, params in [(0x1001, bytes.fromhex('0000010040062003')), (0x1002, b'\1\0')]:
        peer.append(command_reply(capture, b, opcode, r['peer_start']['start_wall_ns'], r['peer_start']['end_wall_ns'], params, ''))
    peer.append(command_reply(capture, b, 0x1002, r['peer_stop']['start_wall_ns'], end, b'\0\0', ''))
    if peer[0]['reply']['wall_ns'] > peer[1]['command']['wall_ns']:
        raise ValueError('peer scan parameters must complete before START')
    for key, item in [('commands', 'command'), ('complete', 'reply')]:
        if rows(key, b) != [v[item] for v in peer]:
            raise ValueError('extra peer commands/replies in complete removal interval')
    return dict(target_command=target[0], target_usb_retirement=failures, peer=peer)


def corroborate_clocks(r, host):
    """Bound host-minus-guest offset by atomic marker/ack round trips.

    Raw wall clocks are never assumed equal. All deadline durations use one
    clock per subtraction, with a conservative upper bound across the hold.
    """
    guest_acks = r['acknowledgement_observed_wall_ns']
    if len(guest_acks) != 2:
        raise ValueError('two actual guest ack observations required')
    bounds = []
    for marker, ack, guest_end in zip(r['markers'], host['observations'], guest_acks):
        if type(guest_end) is not int or not marker['wall_ns'] <= guest_end:
            raise ValueError('ordered atomic marker/ack observations required')
        bounds.append((ack['host_wall_ns']-guest_end, ack['host_wall_ns']-marker['wall_ns']))
    for begin, end, event in [(r['remove_ready_wall_ns'], r['remove_ack_observed_wall_ns'], host['delete_ack_wall_ns']),
                              (r['readd_ready_wall_ns'], r['readd_ack_observed_wall_ns'], host['readd_wall_ns'])]:
        if not begin <= end:
            raise ValueError('ordered lifecycle acknowledgements required')
        bounds.append((event-end, event-begin))
    lower, upper = max(v[0] for v in bounds), min(v[1] for v in bounds)
    if lower > upper:
        raise ValueError('host/guest clock bounds do not intersect')
    held_host = host['observations'][1]['host_wall_ns']
    held_guest = guest_acks[1]
    if not r['markers'][1]['wall_ns'] <= held_guest <= r['pending']['start_wall_ns']:
        raise ValueError('held ack must precede actual Pending query')
    if not held_host <= host['delete_request_wall_ns'] <= host['delete_ack_wall_ns'] <= host['readd_wall_ns']:
        raise ValueError('host-only held/delete/re-add clock order required')
    bound = held_guest-r['original_caller']['start_wall_ns'] + host['delete_request_wall_ns']-held_host
    if not 0 <= bound < 400_000_000:
        raise ValueError('conservative hold-to-delete bound exceeds original deadline')
    return dict(method='ATOMIC_MARKER_ACK_OFFSET_INTERVAL', host_minus_guest_ns=[lower, upper],
                original_to_delete_upper_bound_ns=bound, raw_wall_clocks_assumed_equal=False)


def corroborate(r, host, capture, stderr, identity):
    wire = corroborate_wire(r, capture)
    if (host.get('method') != 'QMP_REMOVE_ACTUAL_HELD_IN81' or host.get('complete') is not True
            or host.get('physical_acceptance') is not False or host.get('automatic_fault_recovery_acceptance') is not False
            or host['observations'] != r['hold_acknowledgements'] or host['removed_id'] != 'ws73_0'):
        raise ValueError('actual selected host removal and guest handshake required')
    for i, row in enumerate(host['observations']):
        expected = dict(zip(PROPERTIES, [i == 0, i == 1, int(i > 0), 0, 0, 0, False, 0]))
        if row['state'] != expected or any(type(row['state'][k]) is not type(v) for k, v in expected.items()) or type(row['host_wall_ns']) is not int or row['host_wall_ns'] <= 0:
            raise ValueError('exact fresh arm/held states required')
    if host['before_remove_state'] != host['observations'][1]['state'] or host['reset_options'] != dict.fromkeys(RESET_OPTIONS, False) or host['peer_before_remove'] != host['peer_after_remove']:
        raise ValueError('no release/reset/drop or peer change before deletion required')
    expected_peer = dict(state=dict(zip(PROPERTIES, [False, False, 0, 0, 0, 0, False, 0])), options=dict.fromkeys(RESET_OPTIONS, False) | {'attached': True})
    if host['peer_after_remove'] != expected_peer:
        raise ValueError('independent peer remains attached with no injected behavior')
    props = host['readd_properties']
    if props.get('driver') != 'usb-host' or props.get('id') != 'ws73_0' or props.get('hostport') != identity['path'].split('-', 1)[1] or props.get('hostbus') != identity['bus'] or props.get('port') != '1' or any(props.get(k) is not False for k in RESET_OPTIONS):
        raise ValueError('same physical target only, all reset opt-outs on re-add required')
    clocks = corroborate_clocks(r, host)
    replacement, retired = r['replacement'], r['retired_after_readd']
    if (replacement['port'] != r['target']['port'] or replacement['address'] != r['target']['address']
            or replacement['generation'] == r['target']['generation'] or replacement['path'] == r['target']['path']
            or retired['args'] != r['retired_selection']['args'] or not retired['exit'] or 'not a live registration' not in retired['stderr']
            or not r['cancel_caller']['end_wall_ns'] <= r['readd_ready_wall_ns'] <= r['readd_ack_observed_wall_ns'] <= retired['start_wall_ns'] <= retired['end_wall_ns']):
        raise ValueError('new generation and old selection rejection after actual re-add required')
    holds = re.findall(r'WS73_TEST_RUNTIME_HOLD: dev (\d+):(\d+) bytes=(\d+) host_status=0 holds=(\d+) sha256=([0-9a-f]{64})', stderr)
    drops = re.findall(r'WS73_TEST_RUNTIME_HOLD_DROP: dev (\d+):(\d+) bytes=(\d+) drops=(\d+) sha256=([0-9a-f]{64})', stderr)
    if len(holds) != 1 or holds != drops or holds[0][3] != '1' or tuple(map(int, holds[0][:2])) != (identity['bus'], identity['address']) or int(holds[0][2]) <= 0 or 'WS73_TEST_RUNTIME_HOLD_RELEASE:' in stderr:
        raise ValueError('exact original successful host-only bytes dropped once; no delivery/replay')
    return dict(status='DAEMON_CANCEL_REMOVAL_CORROBORATED', **wire, clocks=clocks, host_transfer_sha256=holds[0][4], host_transfer_bytes=int(holds[0][2]),
                guest_cancel_removal_support_acceptance=True, whole_managed_acceptance=False,
                physical_acceptance=False, automatic_fault_recovery_acceptance=False, natural_fault_root_cause_closed=False)
