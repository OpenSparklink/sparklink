# SPDX-License-Identifier: GPL-2.0-only
"""Real initializer authority/eviction and guest-generation gate, no injection.

Run only through the separate VM passthrough mode. Ordinary D-Bus callers keep
one peer scanning across target handoff and actual result eviction. Closing or
duplicating slkd's private File is not implied by this API-level gate.
"""
import re

from ws73_capture import CaptureError, command_reply, marker_data
from ws73_north_star import parse_result, stable
from ws73_rf_rounds import corroborate_stops

SCOPE = 'real initializer authority eviction and guest generation support'
STATUS = 'INITIALIZER_LIFECYCLE_EVIDENCE_PENDING'
# Pinned Host CAPACITY=64: two initializers followed by 64 genuine business
# operations evict both oldest terminal initializers. No synthetic result fill.
EVICTION_CYCLES = 32


def management(output, owner):
    rows = re.findall(r'^NativeManagementStatus: generation=(\d+) mode=(\d+) state=(\d+) flags=(\d+) errno=(-?\d+) status=0x([0-9a-f]{2}) opcode=0x([0-9a-f]{4})$', output, re.M)
    if rows != [(str(owner['generation']), '1', '1', '1', '0', '00', '0000')] or 'lease=' in output:
        raise ValueError('current owned Managed authority without credential exposure required')


class LifecycleSession:
    def __init__(self, runner):
        self.run = runner
        self.record = runner.data['initialization_lifecycle'] = {
            'version': 1, 'scope': SCOPE, 'status': 'RUNNING', 'eviction_cycles': EVICTION_CYCLES,
            'physical_acceptance': False, 'automatic_recovery_acceptance': False,
            'private_file_close_dup_acceptance': False,
        }

    def ctl(self, owner, *words):
        row = self.run.ctl(owner, *words)
        return len(self.run.data['commands'])-1, row

    def initial(self, owner, domain):
        self.run.confirm_initialization_off(owner, domain)
        return len(self.run.data['commands'])-1

    def rejected(self, owner, *words, reason):
        self.run.check(owner)
        row = self.run.command([str(self.run.args.slctl), '--adapter', owner['path'], *words],
                               15, collection='commands')
        if row['exit'] != 1 or reason not in row['stderr'] or 'NativeOperationResult:' in row['stdout']:
            raise ValueError('exact initializer refusal required; no successful result fallback')
        self.run.check(owner)
        return len(self.run.data['commands'])-1

    def withdrawal(self, target, peer):
        r = self.record['withdrawal'] = {'target': target, 'peer': peer}
        r['initial_queries'] = [self.initial(o, domain) for o in [target, peer] for domain in ['advertise', 'scan']]
        r['peer_scan_on'], row = self.ctl(peer, 'scan', 'on')
        peer_request = parse_result(row['stdout'], peer, 3)['request']
        r['management_before'], row = self.ctl(target, 'management'); management(row['stdout'], target)
        r['cancel'], row = self.ctl(target, 'cancel-discovery')
        expected = [f'NativePoliciesCancelRequest: generation={target["generation"]}',
                    f'NativePoliciesCancelled: generation={target["generation"]}']
        if [line for line in row['stdout'].splitlines() if line.startswith('NativePolicies')] != expected:
            raise ValueError('actual bounded withdrawal/reacquisition acknowledgement required')
        r['invalidated_queries'] = [self.rejected(target, domain, 'initialized-off',
            reason='initializer provenance absent or invalidated') for domain in ['advertise', 'scan']]
        r['historical_queries'] = []
        for index, operation in zip(r['initial_queries'][:2], [5, 6]):
            original = parse_result(self.run.data['commands'][index]['stdout'], target, operation)
            query_index, row = self.ctl(target, 'result', str(original['request']))
            if parse_result(row['stdout'], target, operation)['request'] != original['request']:
                raise ValueError('initializer history must retain its own ID and operation')
            r['historical_queries'].append(query_index)
        r['management_after'], row = self.ctl(target, 'management'); management(row['stdout'], target)
        r['peer_still_on'], row = self.ctl(peer, 'result', str(peer_request)); parse_result(row['stdout'], peer, 3)
        r['peer_untouched_advertising'] = self.initial(peer, 'advertise')
        r['peer_stop'], row = self.ctl(peer, 'scan', 'off'); parse_result(row['stdout'], peer, 4)
        r['peer_after'] = self.run.ready(peer['port'])
        if not stable(peer, r['peer_after']):
            raise ValueError('target handoff changed peer registration')
        self.run.save()

    def replacement_eviction(self, target, peer):
        old = self.record['withdrawal']['target']
        if target['generation'] == old['generation'] or target['path'] == old['path']:
            raise ValueError('fresh generation required before eviction gate')
        r = self.record['replacement_eviction'] = {'target': target, 'peer': peer}
        r['retired_queries'] = []
        for domain in ['advertise', 'scan']:
            row = self.run.command([str(self.run.args.slctl), '--adapter', old['path'], domain, 'initialized-off'],
                                   15, collection='commands')
            if row['exit'] != 1 or 'not a live registration' not in row['stderr'] or 'NativeOperationResult:' in row['stdout']:
                raise ValueError('retired generation selection must stay refused')
            r['retired_queries'].append(len(self.run.data['commands'])-1)
        r['initial_queries'] = [self.initial(target, domain) for domain in ['advertise', 'scan']]
        scan_id = parse_result(self.run.data['commands'][r['initial_queries'][1]]['stdout'], target, 6)['request']
        r['peer_scan_on'], row = self.ctl(peer, 'scan', 'on'); peer_id = parse_result(row['stdout'], peer, 3)['request']
        r['eviction_commands'] = []
        for _ in range(EVICTION_CYCLES):
            for toggle, operation in [('on', 1), ('off', 2)]:
                index, row = self.ctl(target, 'advertise', toggle); parse_result(row['stdout'], target, operation)
                r['eviction_commands'].append(index)
                self.run.save()
        last = parse_result(self.run.data['commands'][r['eviction_commands'][-1]]['stdout'], target, 2)
        r['evicted_initializer_query'] = self.rejected(target, 'scan', 'initialized-off', reason='initializer result absent or evicted')
        r['evicted_general_query'] = self.rejected(target, 'result', str(scan_id), reason='operation absent or evicted')
        r['current_off_query'], row = self.ctl(target, 'result', str(last['request'])); parse_result(row['stdout'], target, 2)
        r['peer_still_on'], row = self.ctl(peer, 'result', str(peer_id)); parse_result(row['stdout'], peer, 3)
        r['peer_stop'], row = self.ctl(peer, 'scan', 'off'); parse_result(row['stdout'], peer, 4)
        r['peer_after'] = self.run.ready(peer['port'])
        if not stable(peer, r['peer_after']):
            raise ValueError('eviction changed peer registration')
        self.record['status'] = STATUS
        self.run.save()


def verify_records(run):
    r = run['initialization_lifecycle']
    if (r.get('version') != 1 or r.get('scope') != SCOPE or r.get('status') != STATUS
            or r.get('eviction_cycles') != EVICTION_CYCLES
            or any(r.get(k) is not False for k in ['physical_acceptance', 'automatic_recovery_acceptance', 'private_file_close_dup_acceptance'])):
        raise CaptureError('separate qualified initializer API lifecycle scope required')
    before, after = r['withdrawal'], r['replacement_eviction']
    if (before['target'] != run['initial'][0] or before['peer'] != run['initial'][1]
            or after['target'] != run['replacement'] or after['peer'] != run['initial'][1]
            or after['target']['generation'] == before['target']['generation']
            or after['target']['path'] == before['target']['path']):
        raise CaptureError('initializer lifecycle must follow the actual selected generations')
    referenced = []

    def row(owner, index, words, *, error=None):
        if type(index) is not int or index < 0 or index >= len(run['commands']):
            raise CaptureError('actual command reference required')
        c = run['commands'][index]
        if c['args'] != [run['slctl']['path'], '--adapter', owner['path'], *words]:
            raise CaptureError('selected command identity differs')
        if error is None:
            if c['exit'] != 0: raise CaptureError('successful actual command required')
        elif c['exit'] != 1 or error not in c['stderr'] or 'NativeOperationResult:' in c['stdout']:
            raise CaptureError('exact refusal without successful result required')
        if c['start_wall_ns'] > c['end_wall_ns'] or c['start_monotonic_ns'] > c['end_monotonic_ns']:
            raise CaptureError('ordered actual observation clocks required')
        referenced.append(index)
        return c

    def initial(owner, index, domain):
        return parse_result(row(owner, index, [domain, 'initialized-off'])['stdout'], owner, 5 if domain == 'advertise' else 6)

    t, p = before['target'], before['peer']
    if len(before['initial_queries']) != 4 or len(before['invalidated_queries']) != 2 or len(before['historical_queries']) != 2:
        raise CaptureError('all initial and withdrawn domains required')
    originals = [initial(o, index, domain) for (o, domain), index in zip(
        [(t, 'advertise'), (t, 'scan'), (p, 'advertise'), (p, 'scan')], before['initial_queries'])]
    scan = row(p, before['peer_scan_on'], ['scan', 'on']); peer_id = parse_result(scan['stdout'], p, 3)['request']
    management(row(t, before['management_before'], ['management'])['stdout'], t)
    cancel = row(t, before['cancel'], ['cancel-discovery'])
    expected = [f'NativePoliciesCancelRequest: generation={t["generation"]}', f'NativePoliciesCancelled: generation={t["generation"]}']
    if ([v for v in cancel['stdout'].splitlines() if v.startswith('NativePolicies')] != expected
            or cancel['end_monotonic_ns']-cancel['start_monotonic_ns'] >= 8_000_000_000):
        raise CaptureError('bounded actual handoff acknowledgement required')
    for domain, index in zip(['advertise', 'scan'], before['invalidated_queries']):
        row(t, index, [domain, 'initialized-off'], error='initializer provenance absent or invalidated')
    for operation, source, index in zip([5, 6], originals, before['historical_queries']):
        observed = parse_result(row(t, index, ['result', str(source['request'])])['stdout'], t, operation)
        if observed != source: raise CaptureError('old initializer history changed or was rewritten as STOP')
    management(row(t, before['management_after'], ['management'])['stdout'], t)
    parse_result(row(p, before['peer_still_on'], ['result', str(peer_id)])['stdout'], p, 3)
    if initial(p, before['peer_untouched_advertising'], 'advertise') != originals[2]:
        raise CaptureError('target withdrawal changed untouched peer initializer')
    parse_result(row(p, before['peer_stop'], ['scan', 'off'])['stdout'], p, 4)
    if not stable(p, before['peer_after']): raise CaptureError('peer changed during handoff')
    withdrawal_order = [*before['initial_queries'], before['peer_scan_on'], before['management_before'], before['cancel'],
        *before['invalidated_queries'], *before['historical_queries'], before['management_after'], before['peer_still_on'],
        before['peer_untouched_advertising'], before['peer_stop']]
    t = after['target']
    if len(after['retired_queries']) != 2 or len(after['initial_queries']) != 2:
        raise CaptureError('retired and fresh initializer domains required')
    for domain, index in zip(['advertise', 'scan'], after['retired_queries']):
        row(before['target'], index, [domain, 'initialized-off'], error='not a live registration')
    initial(t, after['initial_queries'][0], 'advertise')
    scan_id = initial(t, after['initial_queries'][1], 'scan')['request']
    scan = row(p, after['peer_scan_on'], ['scan', 'on']); peer_id = parse_result(scan['stdout'], p, 3)['request']
    commands = after['eviction_commands']
    if len(commands) != EVICTION_CYCLES*2: raise CaptureError('all 64 actual terminal operations required')
    ids, markers = [], []
    for number, index in enumerate(commands):
        op, toggle = (1, 'on') if number % 2 == 0 else (2, 'off')
        c = row(t, index, ['advertise', toggle]); result = parse_result(c['stdout'], t, op); ids.append(result['request'])
        if op == 1:
            values = re.findall(r'^NativeAdvertisementAccepted: request=(\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+)$', c['stdout'], re.M)
            if len(values) != 1 or int(values[0][0]) != result['request'] or values[0][2] != marker_data(values[0][1]).hex():
                raise CaptureError('actual admitted marker/data/result required')
            markers.append(values[0][1])
    if len(set(ids)) != len(ids) or len(set(markers)) != EVICTION_CYCLES:
        raise CaptureError('genuine distinct operations and fresh markers required')
    row(t, after['evicted_initializer_query'], ['scan', 'initialized-off'], error='initializer result absent or evicted')
    row(t, after['evicted_general_query'], ['result', str(scan_id)], error='operation absent or evicted')
    current = parse_result(row(t, after['current_off_query'], ['result', str(ids[-1])])['stdout'], t, 2)
    if current['request'] != ids[-1]: raise CaptureError('current real OFF result required after eviction')
    parse_result(row(p, after['peer_still_on'], ['result', str(peer_id)])['stdout'], p, 3)
    parse_result(row(p, after['peer_stop'], ['scan', 'off'])['stdout'], p, 4)
    if not stable(p, after['peer_after']): raise CaptureError('eviction changed peer')
    eviction_order = [*after['retired_queries'], *after['initial_queries'], after['peer_scan_on'], *commands,
        after['evicted_initializer_query'], after['evicted_general_query'], after['current_off_query'], after['peer_still_on'], after['peer_stop']]
    for order in [withdrawal_order, eviction_order]:
        if order != sorted(order) or len(set(order)) != len(order): raise CaptureError('ordered unique lifecycle references required')
        for a, b in zip(order, order[1:]):
            if run['commands'][a]['end_wall_ns'] > run['commands'][b]['start_wall_ns']:
                raise CaptureError('lifecycle observation windows overlap')
    if max(withdrawal_order) >= run['rounds'][0]['command_indices'][0] or max(eviction_order) >= next(v for v in run['rounds'] if v['phase'] == 'replug')['command_indices'][0]:
        raise CaptureError('each lifecycle gate must precede its real RF phase')
    if len(set(referenced)) != len(referenced): raise CaptureError('lifecycle command evidence reused')
    return r


def corroborate_wire(run, capture):
    r = verify_records(run)
    initializers = corroborate_stops(run, capture)
    if len([v for v in initializers if 'initializer_wire_recipe' in v]) != 7:
        raise CaptureError('all seven actual initializer query recipes required')
    peers, business = [], []
    for section in ['withdrawal', 'replacement_eviction']:
        record = r[section]; peer = record['peer']
        start, stop = [run['commands'][record[k]] for k in ['peer_scan_on', 'peer_stop']]
        peers.append({'section': section, 'on': [command_reply(capture, peer, opcode, start['start_wall_ns'], start['end_wall_ns'], None if opcode == 0x1001 else b'\1\0', '') for opcode in [0x1001, 0x1002]],
                      'off': command_reply(capture, peer, 0x1002, stop['start_wall_ns'], stop['end_wall_ns'], b'\0\0', '')})
        # No peer control may intervene while its own real scanning state is
        # inspected. Target activity cannot make the peer's old START look new.
        if any((c['bus'], c['device'], c['opcode']) == (peer['bus'], peer['device'], 0x1002)
               and start['end_wall_ns'] < c['wall_ns'] < stop['start_wall_ns'] for c in capture['commands']):
            raise CaptureError('peer scan control changed during target lifecycle')
    target = r['withdrawal']['target'];cancel = run['commands'][r['withdrawal']['cancel']]
    if any((c['bus'], c['device']) == (target['bus'], target['device']) and c['opcode'] in [0x0c02,0x0c03,0x0c05,0x1001,0x1002]
           and cancel['start_wall_ns'] <= c['wall_ns'] <= cancel['end_wall_ns'] for c in capture['commands']):
        raise CaptureError('initialized-Off handoff must not resubmit a redundant radio command')
    target = r['replacement_eviction']['target']
    for number, index in enumerate(r['replacement_eviction']['eviction_commands']):
        c = run['commands'][index]; operation = 1 if number % 2 == 0 else 2
        typed = parse_result(c['stdout'], target, operation)
        marker = re.findall(r'^NativeAdvertisementAccepted: request=\d+ marker=([0-9a-f]{32}) data=[0-9a-f]+$',c['stdout'],re.M)[0] if operation == 1 else None
        recipe = []
        for opcode in ([0x0c02,0x0c03,0x0c05] if operation == 1 else [0x0c05]):
            params = bytes([0,3,43])+marker_data(marker) if opcode == 0x0c03 else bytes([int(operation == 1),0,0,0,0]) if opcode == 0x0c05 else None
            value = f'{typed["selected_power"] & 255:02x}' if opcode == 0x0c02 else ''
            proof = command_reply(capture,target,opcode,c['start_wall_ns'],c['end_wall_ns'],params,value)
            if opcode == 0x0c02:
                encoded = bytes.fromhex(proof['command']['params'])
                if len(encoded)!=49 or encoded[12:18]!=bytes.fromhex(target['address'].replace(':','')):
                    raise CaptureError('eviction business must use its actual selected address')
            if recipe and recipe[-1]['reply']['wall_ns'] > proof['command']['wall_ns']:
                raise CaptureError('eviction recipe step precedes its previous Complete')
            recipe.append(proof)
        business.append({'operation':operation,'request':typed['request'],'wire':recipe})
    return {'status':'REAL_INITIALIZER_AUTHORITY_EVICTION_GUEST_GENERATION_CORROBORATED',
            'initializer_queries':initializers,'peer_scanning':peers,'real_eviction_business_operations':business,
            'withdrawal_target_redundant_radio_commands':0,'private_file_close_dup_acceptance':False,
            'physical_acceptance':False,'automatic_recovery_acceptance':False}
