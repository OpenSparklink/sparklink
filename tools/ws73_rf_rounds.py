# SPDX-License-Identifier: GPL-2.0-only
"""Shared strict actual RF-round proof; callers retain their lifecycle scope."""
import re
import struct
from ws73_capture import CaptureError, command_reply, marker_data, json_identity


def corroborate_rounds(run, capture, sequence, pairs):
    from ws73_north_star import parse_result, parse_match, parse_scan_window, parse_scan_complete, parse_scan_observed
    rounds = run['rounds']
    if [(r['phase'], r['round']) for r in rounds] != sequence or len({r['marker'] for r in rounds}) != len(sequence):
        raise CaptureError('exact ordered rounds with fresh independent markers required')
    proofs, used = [], set()
    for i, r in enumerate(rounds):
        tx, rx, match = r['tx'], r['rx'], r['match']
        if tx['port'] == rx['port'] or tx['address'] == rx['address']:
            raise CaptureError('distinct physical devices required')
        if i and rounds[i-1]['phase'] == r['phase'] and (tx != rounds[i-1]['rx'] or rx != rounds[i-1]['tx']):
            raise CaptureError('roles did not alternate')
        expected_pair = pairs[r['phase']]
        if {json_identity(tx),json_identity(rx)} != {json_identity(d) for d in expected_pair}:
            raise CaptureError('round uses unrelated physical registrations')
        commands = [run['commands'][j] for j in r['command_indices']]
        radio = []
        if len(commands) != 4:
            raise CaptureError('complete control command references required')
        if any(a['end_monotonic_ns'] > b['start_monotonic_ns'] or a['end_wall_ns'] > b['start_wall_ns'] for a,b in zip(commands,commands[1:])):
            raise CaptureError('radio command windows overlap or are out of order')
        for c, op, owner, words in zip(commands, [1,3,2,4], [tx,rx,tx,rx],
                [['advertise','on'],['scan','on',r['marker'],tx['address']],['advertise','off'],['scan','off']]):
            if c['args'] != [run['slctl']['path'],'--adapter',owner['path'],*words] or c['exit'] != 0:
                raise CaptureError('control command evidence mismatch')
            parse_result(c['stdout'], owner, op)
            opcodes = {1:[0x0c02,0x0c03,0x0c05],3:[0x1001,0x1002],2:[0x0c05],4:[0x1002]}[op]
            recipe = []
            for opcode in opcodes:
                expected = {0x0c03: bytes([0,3,len(marker_data(r['marker']))])+marker_data(r['marker']),
                            0x0c05: bytes([int(op == 1),0,0,0,0]),
                            0x1002: bytes([int(op == 3),0])}.get(opcode)
                step = command_reply(capture, owner, opcode, c['start_wall_ns'], c['end_wall_ns'],
                                     expected, None if opcode == 0x0c02 else '')
                params = bytes.fromhex(step['command']['params'])
                if opcode == 0x0c02 and (len(params) != 49 or params[0] != 0
                        or params[12:18] != bytes.fromhex(owner['address'].replace(':',''))):
                    raise CaptureError('captured advertisement parameters use wrong handle/address')
                if opcode == 0x1001 and (len(params) != 8 or params[2] != 1):
                    raise CaptureError('captured scan parameters use unsupported frame')
                if recipe and recipe[-1]['reply']['wall_ns'] > step['command']['wall_ns']:
                    raise CaptureError('recipe sent next step before previous Complete')
                recipe.append(step)
            radio.extend(recipe)
        accepted = re.findall(r'^NativeAdvertisementAccepted: request=(\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+)$',commands[0]['stdout'],re.M)
        adv_result = parse_result(commands[0]['stdout'],tx,1)
        if radio[0]['reply']['value'] != struct.pack('b', adv_result['selected_power']).hex():
            raise CaptureError('selected power disagrees with raw parameter Complete')
        if (len(accepted) != 1 or int(accepted[0][0]) != adv_result['request']
                or accepted[0][1] != r['marker'] or accepted[0][2] != marker_data(r['marker']).hex()
                or match['marker'] != r['marker']):
            raise CaptureError('admission/marker/result correlation mismatch')
        if parse_match(commands[1]['stdout']) != match:
            raise CaptureError('fresh match disagrees with raw slctl output')
        scan_result = parse_result(commands[1]['stdout'], rx, 3)
        scan_boottime = parse_scan_window(commands[1]['stdout'], rx, scan_result['request'])
        if match['kernel_boottime_ns'] < scan_boottime:
            raise CaptureError('kernel RX predates this scan invocation')
        completed = parse_scan_complete(commands[1]['stdout'], rx, scan_result['request'])
        start_mono, end_mono = commands[1]['start_monotonic_ns'], commands[1]['end_monotonic_ns']
        command=commands[1]
        if not command['start_boottime_ns'] <= scan_boottime <= completed <= command['end_boottime_ns']:
            raise CaptureError('Scan Complete clock outside command observation window')
        observed=parse_scan_observed(commands[1]['stdout'],rx,scan_result['request'])
        if not completed<=match['kernel_boottime_ns']<=observed<=command['end_boottime_ns']:
            raise CaptureError('RX or observation outside correlated boottime interval')
        if match['elapsed_ms']!=(observed-completed)//1_000_000:
            raise CaptureError('elapsed time disagrees with correlated clocks')
        if match['kernel_boottime_ns'] < completed:
            raise CaptureError('kernel RX predates successful Scan Complete')
        if r['scan_window_wall_ns'] != [command['start_wall_ns'],command['end_wall_ns']]:
            raise CaptureError('capture interval disagrees with command timestamps')
        start, end = r['scan_window_wall_ns']
        if (end < start or end_mono < start_mono or match['elapsed_ms'] >= 10000
                or abs((end-start)-(end_mono-start_mono)) > 250_000_000):
            raise CaptureError('inconsistent command clocks or discovery timeout')
        completions=[c for c in capture['complete'] if (c['bus'],c['device'],c['opcode'],c['status']) ==
            (rx['bus'],rx['device'],0x1002,0) and start<=c['wall_ns']<=end]
        if len(completions)!=1 :
            raise CaptureError('one raw successful Scan Complete with post-completion deadline required')
        if (match['generation'] != rx['generation'] or match['address'] != tx['address']
                or match['lost'] or match['seq'] <= r['watermark'] or match['kernel_boottime_ns'] <= 0
                or match['data'] != marker_data(r['marker']).hex()):
            raise CaptureError('invalid fresh selected CLI observation')
        if any(f['bus'] == d['bus'] and f['device'] == d['device'] and start <= f['wall_ns'] <= end
               for f in capture['failures'] for d in [tx,rx]):
            raise CaptureError('failed target URB during accepted discovery')
        rows = [p for p in capture['reports'] if p['bus'] == rx['bus'] and p['device'] == rx['device']
                and completions[0]['wall_ns'] <= p['wall_ns'] <= end and p['wall_ns']-completions[0]['wall_ns'] < 10_000_000_000 and p['address'] == tx['address']
                and p['header'] == r['header'] and p['data'] == match['data'] and p['rssi'] == match['rssi']]
        if not rows:
            raise CaptureError(f"missing full receiver USB/HCC/DLI proof for {r['phase']} round {r['round']}")
        proof = rows[0]
        key = (proof['record'], proof['hcc_offset'])
        if key in used:
            raise CaptureError('raw report reused')
        used.add(key)
        proofs.append({'phase': r['phase'], 'round': r['round'], 'marker': r['marker'],
                       'receiver': rx, 'raw': proof, 'radio_commands': radio})
    return proofs


def corroborate_stops(run, capture):
    from ws73_north_star import parse_result
    proofs = []
    for rejection in run.get('initialization_off_rejections', []):
        owner, domain = rejection['identity'], rejection['domain']
        query_index = rejection['query_command']
        query = run['commands'][query_index]
        prefix = [run['slctl']['path'], '--adapter', owner['path']]
        if (domain not in ['advertise', 'scan'] or query['exit'] != 1
                or query['args'] != prefix+[domain, 'initialized-off']
                or 'initializer provenance absent or invalidated' not in query['stderr']
                or 'NativeOperationResult:' in query['stdout']
                or not any(c['args'][:4] == prefix+[domain] and c['args'][4:5] in [['on'], ['off']]
                           for c in run['commands'][:query_index])):
            raise CaptureError('business-used domain must reject old initialization provenance')
    for confirmation in run.get('stop_confirmations', []):
        owner = confirmation['identity']
        domain = confirmation['domain']
        if domain not in ['advertise', 'scan']:
            raise CaptureError('unknown OFF confirmation domain')
        op, opcode, params = (2, 0x0c05, b'\0'*5) if domain == 'advertise' else (4, 0x1002, b'\0'*2)
        source, query = [run['commands'][confirmation[k]] for k in ['source_command', 'query_command']]
        prefix = [run['slctl']['path'], '--adapter', owner['path']]
        result = parse_result(source['stdout'], owner, op)
        observed = parse_result(query['stdout'], owner, op, retained_off=True)
        if (source['exit'] or query['exit'] or source['args'] != prefix+[domain, 'off']
                or query['args'] != prefix+['result', str(result['request'])]
                or observed['request'] != result['request']
                or source['end_wall_ns'] > query['start_wall_ns']):
            raise CaptureError('OFF confirmation differs from retained successful stop')
        if any(c['args'][:4] == prefix+[domain] and c['args'][4:5] in [['on'], ['off']]
               for c in run['commands'][confirmation['source_command']+1:confirmation['query_command']]):
            raise CaptureError('radio operation intervened before OFF confirmation')
        proofs.append(command_reply(capture, owner, opcode, source['start_wall_ns'], source['end_wall_ns'], params, ''))
    for confirmation in run.get('initialization_off_confirmations', []):
        owner, domain = confirmation['identity'], confirmation['domain']
        if domain not in ['advertise', 'scan']:
            raise CaptureError('unknown initializer domain')
        operation = 5 if domain == 'advertise' else 6
        query_index = confirmation['query_command']
        query = run['commands'][query_index]
        prefix = [run['slctl']['path'], '--adapter', owner['path']]
        observed = parse_result(query['stdout'], owner, operation)
        if (query['exit'] or query['args'] != prefix+[domain, 'initialized-off']
                or confirmation['operation'] != operation or confirmation['request'] != observed['request']):
            raise CaptureError('initializer query must retain its own actual operation and ID')
        if any(c['args'][:4] == prefix+[domain] and c['args'][4:5] in [['on'], ['off']]
               for c in run['commands'][:query_index]):
            raise CaptureError('business operation precedes initializer OFF query')
        # This owner/domain must have exactly its initialization recipe before
        # observation. Independent domains may be On. No arbitrary same-opcode
        # reply selection, raw failures or invented wire correlation ID.
        opcodes = [0x0c02, 0x0c05] if operation == 5 else [0x1001, 0x1002, 0x1002]
        rows = [c for c in capture['commands'] if (c['bus'], c['device']) == (owner['bus'], owner['device'])
                and c['opcode'] in (set(opcodes) | ({0x0c03} if operation == 5 else set()))
                and c['wall_ns'] <= query['end_wall_ns']]
        if [c['opcode'] for c in rows] != opcodes:
            raise CaptureError('exact untouched-domain initializer wire sequence required')
        recipe = []
        for index, row in enumerate(rows):
            end = rows[index+1]['wall_ns']-1 if index+1 < len(rows) else query['end_wall_ns']
            params = bytes.fromhex(row['params'])
            if index == 0:
                if len(params) != (49 if operation == 5 else 8):
                    raise CaptureError('complete initializer parameters required')
                value = f'{observed["selected_power"] & 255:02x}' if operation == 5 else ''
            else:
                expected = b'\0'*5 if operation == 5 else bytes([int(index == 1), 0])
                if params != expected:
                    raise CaptureError('initializer enable/OFF parameters disagree')
                value = ''
            recipe.append(command_reply(capture, owner, row['opcode'], row['wall_ns'], end, params, value))
        if recipe[-1]['reply']['wall_ns'] > query['start_wall_ns']:
            raise CaptureError('initializer final Complete must precede its readonly query')
        proofs.append({'identity': owner, 'domain': domain, 'operation': operation,
                       'request': observed['request'], 'query_command': query_index,
                       'initializer_wire_recipe': recipe, 'new_stop_submission': False})
    return proofs
