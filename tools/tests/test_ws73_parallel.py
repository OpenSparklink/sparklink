# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic byte/clock fixtures and actual pipes; never real RF evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_ws73_north_star as fixture_module
from test_ws73_north_star import fixture as old_fixture, identity, pcap
from ws73_parallel import EventReader, PREFIX, SEQUENCE, SCOPE, SUCCESS, abort_workers, corroborate, verify_records


def fixture(offset=0):
    def second_owner(generation):
        value = identity(generation)
        index = 3 if generation == 2 else 2
        value.update(port='1-4' if generation == 2 else '1-3', index=index, generation=generation+10,
                     device=generation+11, path=f'/org/sparklink/slk{index}_g{generation+10}',
                     address=f'02:73:00:00:00:{generation+10:02X}', features=f'{generation+10:02x}'*10)
        return value
    runs, records = [], []
    for pair in range(2):
        r, frames = old_fixture(marker_base=pair*100, identity_factory=second_owner if pair else identity)
        r.update(pair=pair, scope=SCOPE, status=SUCCESS, after=copy.deepcopy(r['initial']), barriers=[], advertise_start_offset_ms=offset if pair else 0)
        r['rounds'] = r['rounds'][:20]
        for row in r['rounds']: row['phase'] = 'parallel'
        r['negatives'] = r['negatives'][:1]
        r['negatives'][0]['phase'] = 'parallel'
        r['barriers'].append(dict(pair=pair, phase='ready', round=0, wait_wall_ns=1_500_000_000+pair, owners=r['initial']))
        for row in r['rounds']:
            commands = [r['commands'][i] for i in row['command_indices']]
            r['barriers'].extend([dict(pair=pair, phase='start', round=row['round'], wait_wall_ns=commands[0]['start_wall_ns']-100+pair-offset*1_000_000),
                                  dict(pair=pair, phase='matched', round=row['round'], wait_wall_ns=commands[1]['end_wall_ns']+10+pair)])
        runs.append(r)
        records.extend(frames)
    stages = []
    for i, (phase, number) in enumerate(SEQUENCE):
        waits = [dict(event=copy.deepcopy(r['barriers'][i]), observed_wall_ns=r['barriers'][i]['wait_wall_ns']+1) for r in runs]
        release = max(v['observed_wall_ns'] for v in waits)+1
        stages.append(dict(phase=phase, round=number, waits=waits, release_wall_ns=release))
        for r in runs: r['barriers'][i]['ack_wall_ns'] = release+1
    parent = dict(format_version=1, scope='four real WS73 two-pair parallel RF', status='PARALLEL_RF_EVIDENCE_PENDING',
                  physical_unplug_acceptance=False, automatic_fault_recovery_acceptance=False,
                  application_identity=runs[0]['application_identity'], stages=stages, workers=[], second_pair_start_offset_ms=offset)
    for pair, r in enumerate(runs):
        argv = ['/bin/python3', '/fixture/ws73_parallel.py', 'pair', '--pair', str(pair), '--ports',
                *[o['port'] for o in r['initial']], '--slctl', r['slctl']['path'], '--slkd-pid', '100', '--output', f'/fixture/pair-{pair}', '--start-offset-ms', str(offset if pair else 0)]
        parent['workers'].append(dict(run=r, exit=0, pid=10+pair, args=argv))
    capture = fixture_module.CaptureTests().read(pcap(records), {(1, 2), (1, 3), (1, 12), (1, 13)})
    return parent, capture


class ParallelTests(unittest.TestCase):
    def test_two_pairs_require_forty_independent_reports_and_twenty_raw_overlaps(self):
        r, c = fixture()
        p = corroborate(r, c)
        self.assertEqual([len(v) for v in p['pairs']], [20, 20])
        self.assertEqual(len(p['overlaps']), 20)
        self.assertTrue(p['four_device_two_pair_rf_acceptance'])
        self.assertFalse(p['physical_unplug_acceptance'])
        self.assertFalse(p['automatic_fault_recovery_acceptance'])
        self.assertFalse(p['full_goal_complete'])
        self.assertTrue(p['default_parallel_gate_acceptance'])
        self.assertFalse(p['whole_concurrency_acceptance'])

    def test_explicit_offset_contrast_never_certifies_default_parallel_gate(self):
        r,c=fixture(offset=37)
        proof=corroborate(r,c)
        self.assertTrue(proof['parallel_offset_contrast_acceptance'])
        self.assertFalse(proof['default_parallel_gate_acceptance'])
        self.assertFalse(proof['whole_concurrency_acceptance'])
        for change in ['negative','excessive','worker-offset','argv-offset','actual-too-early']:
            r,c=fixture(offset=37)
            if change=='negative':r['second_pair_start_offset_ms']=-1
            if change=='excessive':r['second_pair_start_offset_ms']=126
            if change=='worker-offset':r['workers'][1]['run']['advertise_start_offset_ms']=0
            if change=='argv-offset':r['workers'][1]['args'][-1]='0'
            if change=='actual-too-early':
                child=r['workers'][1]['run']
                child['barriers'][1]['ack_wall_ns']=child['commands'][child['rounds'][0]['command_indices'][0]]['start_wall_ns']-10
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(r)

    def test_missing_barrier_early_off_wrong_owner_and_reused_markers_rejected(self):
        for change in ['worker-failed', 'aborted', 'same-pid', 'wrong-argv', 'root', 'caps', 'other-daemon', 'same-controller', 'same-marker', 'not-ready', 'missing-stage', 'missing-child', 'wrong-ack', 'early-off', 'wrong-round', 'missing-cleanup', 'synthetic']:
            r, c = fixture()
            a, b = [w['run'] for w in r['workers']]
            if change == 'worker-failed': r['workers'][1]['exit'] = 1
            if change == 'aborted': r['failure_shutdown'] = [dict(pid=10, forced_kill=False)]
            if change == 'same-pid': r['workers'][1]['pid'] = r['workers'][0]['pid']
            if change == 'wrong-argv': r['workers'][1]['args'][6] = '1-1'
            if change == 'root': r['application_identity']['uids'] = [0]*4
            if change == 'caps': r['application_identity']['cap_eff'] = '1'
            if change == 'other-daemon': b['bus_before']['owner'] = ':1.9'; b['bus_after']['owner'] = ':1.9'
            if change == 'same-controller': b['initial'][0]['index'] = a['initial'][0]['index']
            if change == 'same-marker': b['rounds'][0]['marker'] = a['rounds'][0]['marker']
            if change == 'not-ready': b['after'][0]['generation'] += 1
            if change == 'missing-stage': r['stages'].pop()
            if change == 'missing-child': b['barriers'].pop()
            if change == 'wrong-ack': b['barriers'][2]['ack_wall_ns'] = 1
            if change == 'early-off': a['barriers'][2]['ack_wall_ns'] = a['commands'][2]['start_wall_ns']+1
            if change == 'wrong-round': a['rounds'][0]['round'] = 2
            if change == 'missing-cleanup': b['cleanup'].pop()
            if change == 'synthetic': b['initial'][0]['descriptors']['product'] = 'synthetic fixture'
            with self.subTest(change=change), self.assertRaises(ValueError): verify_records(r)

    def test_bad_metadata_reply_report_negative_and_sequential_windows_rejected(self):
        for change in ['bad-metadata', 'failed-scan', 'wrong-address', 'wrong-data', 'no-report', 'no-negative', 'short-negative', 'extra-negative-tx', 'nonoverlap']:
            r, c = fixture()
            a, b = [w['run'] for w in r['workers']]
            if change == 'bad-metadata': c['commands'] = [v for v in c['commands'] if not (v['device'] == 12 and v['opcode'] == 0x0406)]
            if change == 'failed-scan': next(v for v in c['complete'] if v['device'] == 13 and v['opcode'] == 0x1002 and v['wall_ns'] > 1_000_000_000)['status'] = 11
            if change == 'wrong-address': b['rounds'][0]['match']['address'] = a['initial'][0]['address']
            if change == 'wrong-data': b['rounds'][0]['match']['data'] = a['rounds'][0]['match']['data']
            if change == 'no-report': c['reports'] = [v for v in c['reports'] if v['device'] != 13]
            if change == 'no-negative': b['negatives'] = []
            if change == 'short-negative': b['negatives'][0]['window_wall_ns'][1] -= 1
            if change == 'extra-negative-tx': b['negatives'][0]['transmitter_addresses'] = []
            if change == 'nonoverlap':
                # Keep each pair internally valid but move the second full
                # trace to a later time; an uncoordinated replay cannot pass.
                with patch('ws73_parallel.verify_records', return_value=[]):
                    for v in c['commands']+c['complete']+c['reports']:
                        if v['device'] in [12, 13]:
                            v['wall_ns'] += 20_000_000_000
                            if 'completion' in v: v['completion']['wall_ns'] += 20_000_000_000
                    for row in b['commands']:
                        for key in ['start_wall_ns', 'end_wall_ns', 'start_monotonic_ns', 'end_monotonic_ns']: row[key] += 20_000_000_000
                    for row in b['rounds']: row['scan_window_wall_ns'] = [v+20_000_000_000 for v in row['scan_window_wall_ns']]
                    for owner in b['initial']: owner['observed_wall_ns'] += 20_000_000_000
                    for row in b['negatives']:
                        for key in ['window_wall_ns', 'scan_window_wall_ns', 'stop_window_wall_ns']: row[key] = [v+20_000_000_000 for v in row[key]]
                    with self.assertRaisesRegex(ValueError, 'did not overlap'): corroborate(r, c)
                continue
            with self.subTest(change=change), self.assertRaises(ValueError): corroborate(r, c)

    def test_actual_child_pipes_are_reaped_and_event_order_checked(self):
        for bad in [False, True]:
            processes, rows = [], []
            reader = None
            try:
                for pair in range(2):
                    phase = 'matched' if bad and pair == 1 else 'ready'
                    program = f'import json,time,sys; print({PREFIX!r}+json.dumps(dict(pair={pair},phase={phase!r},round=0,wait_wall_ns=time.time_ns())),flush=True); print("ack="+sys.stdin.readline().strip(),flush=True)'
                    processes.append(subprocess.Popen([sys.executable, '-c', program], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                    rows.append(dict(stdout='', stderr=''))
                reader = EventReader(processes, rows)
                if bad:
                    with self.assertRaises(ValueError): reader.waits(processes, 'ready', 0)
                else:
                    self.assertEqual(len(reader.waits(processes, 'ready', 0)), 2)
                    for p in processes: p.stdin.write(b'parallel-ready-0\n'); p.stdin.flush()
                    for p in processes: p.wait(timeout=3)
                    while reader.watch.get_map(): reader.pump(.01)
                    self.assertTrue(all('ack=parallel-ready-0' in r['stdout'] for r in rows))
            finally:
                for p in processes:
                    if p.poll() is None: p.kill()
                    p.wait()
                    for pipe in [p.stdin, p.stdout, p.stderr]: pipe.close()
                if reader: reader.watch.close()

    def test_vm_modes_reject_shared_injection_and_hotplug_before_output(self):
        import ws73_target
        for changes in [dict(command='support'), dict(qmp_hotplug=True), dict(fault_recovery=True), dict(daemon_cancel_remove=True), dict(setup_release_verify=True), dict(hotplug=True), dict(warm=True), dict(empty_bulk=True)]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)/'never-created'
                fields = dict(command='run', output=output, parallel_pairs=True)
                fields.update(changes)
                with patch.object(ws73_target, 'ordinary_identity'), self.assertRaisesRegex(ValueError, 'four-device parallel RF requires'):
                    ws73_target._run(SimpleNamespace(**fields))
                self.assertFalse(output.exists())

    def test_actual_peer_abort_is_graceful_with_bounded_forced_kill(self):
        for stuck in [False, True]:
            processes, rows = [], []
            reader = None
            try:
                for pair in range(2):
                    ending = 'time.sleep(60)' if stuck else 'print(sys.stdin.readline().strip(),flush=True); sys.exit(7)'
                    program = f'import json,time,sys; print({PREFIX!r}+json.dumps(dict(pair={pair},phase="ready",round=0,wait_wall_ns=time.time_ns())),flush=True); {ending}'
                    processes.append(subprocess.Popen([sys.executable, '-c', program], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                    rows.append(dict(stdout='', stderr=''))
                reader = EventReader(processes, rows)
                reader.waits(processes, 'ready', 0)
                shutdown = abort_workers(processes, reader, timeout=.05 if stuck else 2)
                for p in processes: p.wait(timeout=3)
                while reader.watch.get_map(): reader.pump(.01)
                self.assertTrue(all(r['sent'] for r in shutdown))
                self.assertTrue(all(r['forced_kill'] == stuck for r in shutdown))
                self.assertTrue(all(p.returncode == (-9 if stuck else 7) for p in processes))
                if not stuck: self.assertTrue(all('parallel-abort' in r['stdout'] for r in rows))
            finally:
                for p in processes:
                    if p.poll() is None: p.kill()
                    p.wait()
                    for pipe in [p.stdin, p.stdout, p.stderr]: pipe.close()
                if reader: reader.watch.close()
