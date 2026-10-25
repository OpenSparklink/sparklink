# SPDX-License-Identifier: GPL-2.0-only
"""Independent literal evidence fixtures; never hardware or kernel qualification."""
import copy
from contextlib import redirect_stdout
import errno
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError, reassemble_acb
import ws73_ssap_provider_owner_exit as gate
import ws73_ssap_owned as owned
from test_ws73_ssap_read_provider import fixture_v2, summary as provider_summary


def swap_fixture_hardware(value):
    """Permute physical identities, not role positions, in independent fixtures."""
    if isinstance(value, list):
        return [swap_fixture_hardware(v) for v in value]
    if isinstance(value, str):
        return (value.replace('/a0', '/TEMP').replace('/a1', '/a0').replace('/TEMP', '/a1')
                .replace('index=0 ', 'index=TEMP ').replace('index=1 ', 'index=0 ').replace('index=TEMP ', 'index=1 ')
                .replace('handle=3 ', 'handle=TEMP ').replace('handle=4 ', 'handle=3 ').replace('handle=TEMP ', 'handle=4 '))
    if not isinstance(value, dict):
        return value
    result = {k:swap_fixture_hardware(v) for k,v in value.items()}
    if 'index' in value: result['index'] = 1-value['index']
    if 'device' in value: result['device'] = 21-value['device']
    if value.get('handle') in (3, 4): result['handle'] = 7-value['handle']
    if 'args' in result:
        args = result['args']
        for mode in ('ssap', 'ssap-error'):
            if mode in args:
                at = args.index(mode)+1
                args[at] = str(1-int(args[at]))
    return result


def fixture(phase=0, peer_error=175):
    row, _, _ = fixture_v2(phase)
    if phase == 1: row = swap_fixture_hardware(row)
    item = copy.deepcopy(row['ssap_read_provider_cases'][0])
    sender, target = 0, 1
    source, dest = row['owners'][sender], row['owners'][target]
    base = 1_000_000_000_000 + phase*1_000_000_000_000
    stamp = lambda n: base+n*1_000_000
    app = copy.deepcopy(item['steps'][0]['read'])
    app['api'] = ('c', 'python')[phase]
    prefix = ['/bin/ws73-application-client-c'] if phase == 0 else ['/bin/python3', '/usr/share/sparklink/tools/ws73-application-client.py']
    app.update(args=prefix+['ssap-error', str(source['owner']['index']), '4', source['object']['path'], 'ssap-read', '17', str(errno.EIO)],
        start_wall_ns=stamp(10), end_wall_ns=stamp(20), start_monotonic_ns=stamp(10), end_monotonic_ns=stamp(20),
        ssap_error_deadline_ns=stamp(5010), ssap_supervisor_deadline_ns=stamp(7010))
    call = dict(stage='ssap_call', api=app['api'], deadline_ns=stamp(5010), call_ns=stamp(11), client_closed=True)
    result = dict(stage='ssap_error', api=app['api'], errno=errno.EIO, operation_success=False,
                  deadline_ns=stamp(5010), returned_ns=stamp(14))
    app['stdout'] = json.dumps(call)+'\n'+json.dumps(result)+'\n'
    callback = copy.deepcopy(item['steps'][0]['callback'])
    callback['prompt']['deadline_ns'] = stamp(4900)
    callback = dict(prompt=callback['prompt'], publisher_pid=item['pid'], observed_monotonic_ns=stamp(12),
                    observed_wall_ns=stamp(12), supervisor_deadline_ns=stamp(7010), exit_deadline_ns=stamp(4900))
    for key in ('steps', 'prepared_wall_ns', 'quit_wall_ns'):
        del item[key]
    item.update(read=app, callback=callback, start_wall_ns=stamp(2), bound_wall_ns=stamp(3),
                kill_before_wall_ns=stamp(13), kill_before_monotonic_ns=stamp(13),
                kill_returned_wall_ns=stamp(13)+1000, kill_returned_monotonic_ns=stamp(13)+1000,
                owner_exit_wall_ns=stamp(15), owner_exit_monotonic_ns=stamp(15), owner_exit=-9, exit=-9,
                cleanup_completed_monotonic_ns=stamp(17), end_wall_ns=stamp(60),
                clock_contract=dict(version=1, domain='same-guest', offset_assumption='no-clock-adjustment-between-samples', usbmon_quantization_ns=1000),
                clock_before=dict(monotonic_before_ns=stamp(12)+1000, realtime_ns=stamp(12)+1100, monotonic_after_ns=stamp(12)+1200),
                clock_after=dict(monotonic_before_ns=stamp(20)+1000, realtime_ns=stamp(20)+1100, monotonic_after_ns=stamp(20)+1200))
    d = callback['prompt']
    item['stdout'] = '\n'.join([
        'SsapOwnedService: start=16 end=17 property=17; local registration only',
        'SsapReadProviderBound: handle=17; stored value discarded, no rebind or fallback',
        'SsapAuthorizationDecision: request=9 property=17 data_type=0 write=false security=0 approved=true; local policy only',
        f'SsapReadProviderPrompt: token=p1 request=9 index={dest["owner"]["index"]} generation=4 lifetime={d["lifetime"]} handle={d["handle"]} epoch=41 security=0 local_tcid=10 remote_tcid=10 pi=0 property=17 deadline_ns={d["deadline_ns"]} maximum_bytes=2042; answer \'provide p1 HEX\' (\'-\' for empty) or \'provider-error p1 AF..FF\'',
    ])+'\n'
    item['captured_bytes']['stdout'] = len(item['stdout'].encode())
    item['cleanup'].update(start_wall_ns=stamp(16), end_wall_ns=stamp(17))
    item['retired_read'].update(start_wall_ns=stamp(30), end_wall_ns=stamp(35))
    guard = {k:copy.deepcopy(item[k]) for k in ('sender', 'target', 'policy', 'operations', 'credentials', 'output_collection')}
    guard.update(start=32, end=33, handle=33, pid=item['pid']+100, service='d1'*16, uuid='d2'*16,
                 secret='d3'*32, exit=0, stderr='', start_wall_ns=stamp(1), registered_wall_ns=stamp(1)+1, alive_after_read_wall_ns=stamp(51),
                 quit_wall_ns=stamp(70), owner_exit_wall_ns=stamp(71), end_wall_ns=stamp(80))
    guard['args'] = ['slctl', '--adapter', dest['owner']['path'], 'ssap-serve', guard['service'], guard['uuid'], '1', '36', guard['secret'], 'allow']
    guard['stdout'] = ('SsapOwnedService: start=32 end=33 property=33; local registration only\n'
                       'SsapAuthorizationDecision: request=10 property=33 data_type=0 write=false security=0 approved=true; local policy only\n')
    guard['captured_bytes'] = dict(stdout=len(guard['stdout'].encode()), stderr=0)
    guard['cleanup'] = dict(item['cleanup'], start_wall_ns=stamp(72), end_wall_ns=stamp(73))
    guard['read'] = dict(api=app['api'], args=prefix+['ssap', str(source['owner']['index']), '4', source['object']['path'], 'ssap-read', '33', guard['secret']],
                        exit=0, stderr='', environment=app['environment'], credentials=copy.deepcopy(app['credentials']),
                        ssap_operation='ssap-read', ssap_path=source['object']['path'], ssap_handle=33, ssap_expected=guard['secret'],
                        start_wall_ns=stamp(40), ssap_released_wall_ns=stamp(41), ssap_release_monotonic_ns=stamp(41), end_wall_ns=stamp(50),
                        stdout=json.dumps(dict(stage='ssap_start_barrier', api=app['api'], client_closed=True))+'\n'
                               +f'SsapPeerValue: operation=ssap-read path={source["object"]["path"]} handle=33 value={guard["secret"]}\n')
    item['guard'] = guard
    row.update(ssap_provider_owner_exit_required=True, ssap_provider_owner_exit_version=1,
               ssap_provider_owner_exit_cases=[item], ssap_provider_owner_exit_guards=[guard], ssap_provider_owner_exit_tools={})
    capture = dict(acb_packets=[], native_events=[])
    for window, handle, response in [(app, 17, b'\x09\x0b'+bytes([peer_error, 0])),
                                     (item['retired_read'], 17, b'\x09\x0b\x04\0'),
                                     (guard['read'], 33, b'\x09\x03'+bytes.fromhex(guard['secret']))]:
        for a, b, pdu in [(sender, target, b'\x08\x03'+handle.to_bytes(2, 'little')+b'\0'), (target, sender, response)]:
            frame = b'\x0a\0'+len(pdu).to_bytes(2, 'little')+pdu
            for endpoint, direction in [(a, 'out'), (b, 'in')]:
                offset = (1_100_000 if a == sender else 3_500_000)+(100_000 if direction == 'in' else 0)
                capture['acb_packets'].append(dict(bus=1, device=row['owners'][endpoint]['owner']['device'], handle=row['owners'][endpoint]['object']['handle'], direction=direction,
                    data=frame.hex(), boundary=0, record=len(capture['acb_packets'])+1, wall_ns=window['start_wall_ns']+offset))
    packets = reassemble_acb(capture)
    def matched(owner, direction, frame, window):
        key = (owner['owner']['bus'], owner['owner']['device'], owner['object']['handle'], direction, frame.hex())
        found = [p for p in packets if tuple(p[k] for k in ('bus', 'device', 'handle', 'direction', 'data')) == key
                 and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
        if len(found) != 1:
            raise CaptureError('one exact independent fixture leg required')
        packets.remove(found[0]); return found[0]
    return row, matched, packets


def summary():
    result = provider_summary(version=2)
    result['proofs'][1] = swap_fixture_hardware(result['proofs'][1])
    for phase, proof in enumerate(result['proofs']):
        row, match, packets = fixture(phase, (175, 4)[phase])
        items, credit = gate.corroborate(row, match, packets)
        assert not packets and credit == {0:3, 1:3}
        proof[gate.PREFIX] = items
    return result


class OwnerExitEvidence(unittest.TestCase):
    def test_explicit_opt_in_and_dependency(self):
        good = dict(ssap_provider_owner_exit_verify=True, ssap_read_provider_verify=True, ssap_owned_verify=True,
                    channel_socket_verify=True, channel_socket_rounds=4, channel_socket_bytes=61, passthrough=True)
        self.assertTrue(gate.requested(SimpleNamespace(**good)))
        self.assertFalse(gate.requested(SimpleNamespace()))
        for key, value in [('ssap_provider_owner_exit_verify', 1), ('ssap_read_provider_verify', False),
                           ('ssap_owned_verify', False), ('channel_socket_rounds', 5), ('passthrough', False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.requested(SimpleNamespace(**dict(good, **{key:value})))
        tokens = [gate.TOKEN, 'ws73.ssap_read_provider=1', 'ws73.ssap_owned=1']
        self.assertTrue(gate.boot_requested(tokens))
        self.assertFalse(gate.boot_requested([]))
        for bad in [tokens+[gate.TOKEN], tokens[:-1], [gate.TOKEN], ['ws73.ssap_provider_owner_exit=0'], [1]]:
            with self.subTest(tokens=bad), self.assertRaises(ValueError): gate.boot_requested(bad)

    def test_two_roles_c_then_python_and_both_possible_wire_errors(self):
        proof = summary()
        self.assertTrue(gate.valid_summary(proof))
        self.assertEqual([p[gate.PREFIX][0]['api'] for p in proof['proofs']], ['c', 'python'])
        self.assertEqual([p[gate.PREFIX][0]['peer_error'] for p in proof['proofs']], [175, 4])
        self.assertEqual([p[gate.PREFIX][0]['sender'] for p in proof['proofs']], [0, 0])
        self.assertEqual([p['owners'][1]['owner']['index'] for p in proof['proofs']], [1, 0])
        for p in proof['proofs']:
            case = p[gate.PREFIX][0]['case']
            # A response before wait() completes is intentionally admissible.
            self.assertLess(json.loads(case['read']['stdout'].splitlines()[1])['returned_ns'], case['owner_exit_monotonic_ns'])

    def test_no_grant_from_old_publisher_gate(self):
        rows = [fixture(n)[0] for n in (0, 1)]
        gate.validate_rows(rows, True)
        for key, value in [('ssap_provider_owner_exit_version', True), ('phase', True),
                           ('ssap_read_provider_version', 1), ('ssap_provider_owner_exit_cases', [])]:
            bad = copy.deepcopy(rows); bad[0][key] = value
            with self.subTest(key=key), self.assertRaises(CaptureError): gate.validate_rows(bad, True)
        with self.assertRaises(CaptureError): gate.validate_rows(rows, False)
        with self.assertRaises(CaptureError): gate.validate_rows(rows[:1], True)
        rows[1] = swap_fixture_hardware(rows[1])
        with self.assertRaises(CaptureError): gate.validate_rows(rows, True)

    def test_fail_closed_evidence_mutations(self):
        def change_result(item, key, value):
            rows = [json.loads(l) for l in item['read']['stdout'].splitlines()]
            rows[1][key] = value
            item['read']['stdout'] = '\n'.join(json.dumps(v) for v in rows)+'\n'
        mutations = {
            'not killed': lambda r,i,p: i.update(exit=0),
            'wrong wait': lambda r,i,p: i.update(owner_exit=0),
            'no prompt': lambda r,i,p: i.update(stdout=''),
            'answer sent': lambda r,i,p: i.update(reply_command='provide p1 00'),
            'quit sent': lambda r,i,p: i.update(quit_wall_ns=i['kill_before_wall_ns']),
            'wrong lifetime': lambda r,i,p: i['callback']['prompt'].update(lifetime=999),
            'wrong pid': lambda r,i,p: i['callback'].update(publisher_pid=1),
            'renewed deadline': lambda r,i,p: i['callback'].update(exit_deadline_ns=i['callback']['exit_deadline_ns']+1),
            'late cleanup': lambda r,i,p: i.update(cleanup_completed_monotonic_ns=i['callback']['exit_deadline_ns']),
            'late response': lambda r,i,p: change_result(i,'returned_ns',i['callback']['exit_deadline_ns']),
            'response before kill': lambda r,i,p: change_result(i,'returned_ns',i['kill_before_monotonic_ns']-1),
            'timeout': lambda r,i,p: change_result(i,'errno',errno.ETIMEDOUT),
            'operation success': lambda r,i,p: change_result(i,'operation_success',True),
            'guard pid reused': lambda r,i,p: i['guard'].update(pid=i['pid']),
            'guard old handle': lambda r,i,p: i['guard'].update(handle=i['handle']),
            'guard died': lambda r,i,p: i['guard'].update(exit=-9),
            'guard registered after loss': lambda r,i,p: i['guard'].update(registered_wall_ns=i['owner_exit_wall_ns']),
            'guard corruption': lambda r,i,p: i['guard']['read'].update(ssap_expected='00'*32),
            'retired accepted': lambda r,i,p: i['retired_read'].update(exit=0),
            'old owner remains': lambda r,i,p: i['cleanup'].update(stdout='SsapLocalServices: [[16]]\n'),
            'truncated pipes': lambda r,i,p: i['output_collection'].update(complete=False),
            'inheritable cap': lambda r,i,p: i['credentials']['capabilities'].update(CapInh='1'),
            'missing leg': lambda r,i,p: p.pop(),
            'duplicate response': lambda r,i,p: p.append(copy.deepcopy(p[2])),
            'wrong peer response': lambda r,i,p: p[3].update(data='0a000400090b0400'),
            'response before kill wire': lambda r,i,p: p[2].update(wall_ns=i['kill_before_wall_ns']-1),
            'wrong generation': lambda r,i,p: r['owners'][0]['object'].update(generation=3),
            'wrong fragment handle': lambda r,i,p: p[0]['fragments'][0].update(handle=99),
        }
        for name, mutate in mutations.items():
            row, match, packets = fixture()
            mutate(row, row[gate.PREFIX+'_cases'][0], packets)
            with self.subTest(case=name), self.assertRaises((CaptureError, KeyError, ValueError)):
                gate.corroborate(row, match, packets)
        for code in (0, 9, 255):
            row, match, packets = fixture(peer_error=code)
            with self.subTest(error=code), self.assertRaises(CaptureError): gate.corroborate(row, match, packets)

    def test_summary_and_manifest_do_not_promote_missing_baseline(self):
        proof = summary()
        record = dict(ssap_provider_owner_exit_requested=True, ssap_provider_owner_exit_version=1,
            ssap_provider_owner_exit_acceptance=True, ssap_read_provider_requested=True, ssap_read_provider_version=2,
            ssap_read_provider_acceptance=True, ssap_owned_acceptance=True, ordinary_channel_socket_acceptance=True,
            status='PASSTHROUGH_SUPPORT_PASS', qemu_exit=0,
            qemu_args=[gate.TOKEN+' ws73.ssap_read_provider=1 ws73.ssap_owned=1'], channel_socket_corroboration=proof)
        self.assertTrue(gate.valid_manifest(record))
        self.assertTrue(gate.valid_manifest({}))
        for key, value in [('qemu_exit', 1), ('status', 'FAIL'), ('ssap_read_provider_acceptance', False),
                           ('ssap_owned_acceptance', False), ('ssap_provider_owner_exit_version', True),
                           ('ssap_provider_owner_exit_requested', False), ('ssap_provider_owner_exit_acceptance', False),
                           ('ordinary_channel_socket_acceptance', False), ('ssap_read_provider_version', 1)]:
            with self.subTest(key=key): self.assertFalse(gate.valid_manifest(dict(record, **{key:value})))
        bad = copy.deepcopy(proof); bad['proofs'][0][gate.PREFIX][0]['wire'].pop()
        self.assertFalse(gate.valid_summary(bad))
        bad = copy.deepcopy(proof); bad['proofs'][1][gate.PREFIX][0]['api'] = 'c'
        self.assertFalse(gate.valid_summary(bad))
        bad = copy.deepcopy(proof); bad['proofs'][1][gate.PREFIX][0]['peer_error'] = 9
        self.assertFalse(gate.valid_summary(bad))
        bad = copy.deepcopy(proof); bad['proofs'][1] = swap_fixture_hardware(bad['proofs'][1])
        self.assertFalse(gate.valid_summary(bad))

    def test_late_wire_counterexample_and_clock_uncertainty_fail_closed(self):
        def wire_at(packets, stamps):
            for packet, stamp in zip(packets[2:4], stamps, strict=True):
                packet['wall_ns'] = stamp
                for fragment in packet['fragments']: fragment['wall_ns'] = stamp
        mutations = {
            # Original reviewer counterexample: the SDK has already returned,
            # although both physical legs fit the supervisor's later end.
            'wire after actual SDK return': lambda i,p: wire_at(p, [i['read']['end_wall_ns']-2000, i['read']['end_wall_ns']-1000]),
            'wire after original Provider deadline': lambda i,p: wire_at(p, [i['callback']['prompt']['deadline_ns']+1000, i['callback']['prompt']['deadline_ns']+2000]),
            'wire after original SDK deadline': lambda i,p: wire_at(p, [i['read']['ssap_error_deadline_ns']+1000, i['read']['ssap_error_deadline_ns']+2000]),
            # A microsecond-truncated sample is not known to finish before the
            # bound merely because its stored lower endpoint precedes it.
            'quantization overlaps SDK return': lambda i,p: wire_at(p, [json.loads(i['read']['stdout'].splitlines()[1])['returned_ns']-2000, json.loads(i['read']['stdout'].splitlines()[1])['returned_ns']-1000]),
            'no contract': lambda i,p: i.pop('clock_contract'),
            'wrong contract version type': lambda i,p: i['clock_contract'].update(version=True),
            'host guest domain': lambda i,p: i['clock_contract'].update(domain='host-guest'),
            'unrecorded offset assumption': lambda i,p: i['clock_contract'].pop('offset_assumption'),
            'missing bracket': lambda i,p: i.pop('clock_before'),
            'wrong bracket type': lambda i,p: i['clock_before'].update(monotonic_before_ns=True),
            'inverted bracket': lambda i,p: i['clock_before'].update(monotonic_before_ns=i['clock_before']['monotonic_after_ns']+1),
            'contradictory offsets': lambda i,p: i['clock_after'].update(realtime_ns=i['clock_after']['realtime_ns']+1000),
            'before sampled after kill': lambda i,p: i['clock_before'].update(monotonic_before_ns=i['kill_before_monotonic_ns']+1000,monotonic_after_ns=i['kill_before_monotonic_ns']+1200),
            'after sampled before SDK observation': lambda i,p: i['clock_after'].update(monotonic_before_ns=i['read']['end_monotonic_ns']-1000,monotonic_after_ns=i['read']['end_monotonic_ns']-800),
        }
        for name, mutate in mutations.items():
            row, matched, packets = fixture(); item = row[gate.PREFIX+'_cases'][0]
            mutate(item, packets)
            with self.subTest(case=name), self.assertRaises((CaptureError, KeyError, ValueError)):
                gate.corroborate(row, matched, packets)

    def test_explicit_nonzero_same_guest_offset_and_sample_overlap(self):
        row, matched, packets = fixture()
        item = row[gate.PREFIX+'_cases'][0]
        # Keep realtime/USB intact and move all original monotonic observations
        # by a fixed amount. The relation must not assume numeric equality.
        offset = 987_654_321
        for key in ('start_monotonic_ns', 'end_monotonic_ns', 'ssap_error_deadline_ns', 'ssap_supervisor_deadline_ns'):
            item['read'][key] -= offset
        receipts = [json.loads(l) for l in item['read']['stdout'].splitlines()]
        for receipt in receipts:
            for key in ('deadline_ns', 'call_ns', 'returned_ns'):
                if key in receipt: receipt[key] -= offset
        item['read']['stdout'] = '\n'.join(json.dumps(v) for v in receipts)+'\n'
        for key in ('observed_monotonic_ns', 'supervisor_deadline_ns', 'exit_deadline_ns'):
            item['callback'][key] -= offset
        old_deadline = item['callback']['prompt']['deadline_ns']
        item['callback']['prompt']['deadline_ns'] -= offset
        item['stdout'] = item['stdout'].replace(f'deadline_ns={old_deadline}',f'deadline_ns={old_deadline-offset}')
        item['captured_bytes']['stdout'] = len(item['stdout'].encode())
        for key in ('kill_before_monotonic_ns', 'kill_returned_monotonic_ns', 'owner_exit_monotonic_ns', 'cleanup_completed_monotonic_ns'):
            item[key] -= offset
        for name in ('clock_before', 'clock_after'):
            for key in ('monotonic_before_ns', 'monotonic_after_ns'): item[name][key] -= offset
        self.assertEqual(gate._clock_bounds(item), (offset-100, offset+100))
        result, _ = gate.corroborate(row, matched, packets)
        self.assertEqual(result[0]['peer_error'], 175)
        self.assertFalse(packets)


class OriginalDeadline(unittest.TestCase):
    def test_after_start_kills_only_the_prompt_owner_and_keeps_original_budget(self):
        row, _, _ = fixture()
        item = row[gate.PREFIX+'_cases'][0]
        transcript = item['stdout']
        item['output_files'] = ['/unused/original.stdout', '/unused/original.stderr']
        process = Mock(pid=item['pid'], returncode=-9)
        process.poll.return_value = None
        run = SimpleNamespace(save=Mock())
        observed = item['callback']['observed_monotonic_ns']
        with patch.object(owned, 'wait_text', return_value=([], transcript)), \
             patch.object(owned, 'wait_output') as wait, \
             patch.object(owned, 'await_removed', return_value=item['cleanup']) as removed, \
             patch.object(gate.time, 'monotonic_ns', return_value=observed), \
             patch.object(gate.time, 'time_ns', return_value=observed):
            gate._owner_exit(run, row, process, item, item['read'], item['read']['ssap_supervisor_deadline_ns'])
        process.kill.assert_called_once_with()
        process.stdin.write.assert_not_called()
        wait.assert_called_once_with(process, (item['callback']['exit_deadline_ns']-observed)/1e9)
        self.assertEqual(removed.call_args.kwargs, dict(deadline_ns=item['callback']['exit_deadline_ns']))
        self.assertEqual(item['owner_exit'], -9)

    def test_expired_prompt_or_wrong_identity_does_not_kill_owner(self):
        for mutate in ('expired', 'identity'):
            row, _, _ = fixture(); item = row[gate.PREFIX+'_cases'][0]
            item['output_files'] = ['/unused/original.stdout', '/unused/original.stderr']
            transcript = item['stdout']
            observed = item['callback']['observed_monotonic_ns']
            if mutate == 'expired': observed = item['callback']['prompt']['deadline_ns']
            else: transcript = transcript.replace('lifetime=101', 'lifetime=999')
            process = Mock(pid=item['pid']); process.poll.return_value = None
            with patch.object(owned, 'wait_text', return_value=([], transcript)), \
                 patch.object(gate.time, 'monotonic_ns', return_value=observed):
                with self.subTest(kind=mutate), self.assertRaises(CaptureError):
                    gate._owner_exit(SimpleNamespace(save=Mock()), row, process, item, item['read'], item['read']['ssap_supervisor_deadline_ns'])
            process.kill.assert_not_called()

    def test_optional_cleanup_never_extends_original_budget(self):
        run = SimpleNamespace(args=SimpleNamespace(slctl='slctl'), command=Mock(return_value=dict(exit=0, stdout='SsapLocalServices: []\n')))
        target = dict(owner=dict(path='/a1'))
        with patch.object(owned.time, 'monotonic', return_value=10):
            owned.await_removed(run, target, 16, deadline_ns=10_500_000_000)
        self.assertEqual(run.command.call_args.args[1], .5)
        with patch.object(owned.time, 'monotonic', return_value=10):
            owned.await_removed(run, target, 16)
        self.assertEqual(run.command.call_args.args[1], 2)
        run.command.reset_mock()
        with patch.object(owned.time, 'monotonic', return_value=10):
            with self.assertRaises(CaptureError): owned.await_removed(run, target, 16, deadline_ns=10_000_000_000)
        run.command.assert_not_called()
        for deadline in (True, 0, '10'):
            with self.subTest(deadline=deadline), self.assertRaises(CaptureError): owned.await_removed(run, target, 16, deadline_ns=deadline)

    def test_remaining_rejects_expired_without_new_wait(self):
        with patch.object(gate.time, 'monotonic_ns', return_value=10):
            self.assertEqual(gate._remaining(20), 10/1e9)
            with self.assertRaises(CaptureError): gate._remaining(10)
            with self.assertRaises(CaptureError): gate._remaining(9)


class RealRunnerInputValidation(unittest.TestCase):
    def test_actual_cli_and_host_reject_stale_owner_exit_verifier_before_launch(self):
        # Actual parser/_run and validators, with only artifact/read-only host
        # observations replaced. No fixture supplies a successful VM result.
        import ws73_target as host
        names = list(TOOLS.glob('*.py'))+[TOOLS/'ws73_target_init.sh']
        good = dict(inputs=[host.file_record(p) for p in names],
                    application_client_tools=dict(sources=[host.file_record(TOOLS/n) for n in
                        ('testing/application_client/client.c', 'testing/application_client/client.py')]),
                    ssap_exchange_contract_version=False)
        for changed in (True, False):
            package = copy.deepcopy(good)
            if changed:
                next(r for r in package['inputs'] if Path(r['path']).name == 'ws73_ssap_provider_owner_exit.py')['sha256'] = '0'*64
            with self.subTest(stale=changed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); prepared = root/'prepared'; prepared.mkdir()
                (prepared/'manifest.json').write_text(json.dumps(package))
                output = root/'output'
                argv = ['ws73_target.py', 'run', '--prepared', str(prepared), '--output', str(output),
                        '--ports', '1-1.1.1', '1-1.1.2', '--qmp-hotplug', '--firmware-evidence', 'runtime-observation',
                        '--connection-verify', '--connection-advertising', 'negotiable-t', '--channel-socket-verify',
                        '--ssap-owned-verify', '--ssap-read-provider-verify', '--ssap-provider-owner-exit-verify']
                with patch.object(sys, 'argv', argv), patch.object(host, 'run', side_effect=lambda args: args):
                    args = host.main()
                with redirect_stdout(io.StringIO()), patch.object(host, 'ordinary_identity'), \
                     patch.object(host, 'prepared', return_value=package), \
                     patch.object(host, 'lab_module', return_value=SimpleNamespace(inventory=lambda: [])), \
                     patch.object(gate, 'validate_inputs', wraps=gate.validate_inputs) as checked, \
                     patch.object(host.subprocess, 'Popen', side_effect=AssertionError('must not launch')) as launch:
                    self.assertEqual(host._run(args), 1)
                checked.assert_called_once_with(package)
                launch.assert_not_called()
                record = json.loads((output/'manifest.json').read_text())
                expected = 'fresh exact Provider owner-exit verifier' if changed else 'explicit known SSAP exchange artifact contract required'
                self.assertIn(expected, record['error'])
                self.assertIs(record['ssap_provider_owner_exit_acceptance'], False)
                self.assertIs(record['physical_acceptance'], False)
                self.assertNotIn('qemu_args', record)


if __name__ == '__main__':
    unittest.main()
