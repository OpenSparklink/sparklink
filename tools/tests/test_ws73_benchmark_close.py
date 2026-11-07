# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic report/USB/credential fixtures; no Native, concurrency or RF claim."""
import copy
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_socket_benchmark as gate
from ws73_capture import CaptureError
import test_ws73_benchmark_role as role_fixture


class CloseProfile(unittest.TestCase):
    def test_finalizer_requires_explicit_close_profile_and_complete_after_proof(self):
        from test_ws73_benchmark_timeline import modern_trace
        from ws73_benchmark_timeline import check_xhci
        from ws73_target import run_exit_code
        helper=role_fixture.ClosedBenchmarkRoleFixture()
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);channel=gate.parallel_channel(close_short=True);run,capture=helper.fixture(root,channel)
            proof=gate.corroborate(run,capture,root);role=gate.verify_role_artifacts(run,root)
            trace=root/'trace';trace.mkdir();modern_trace(trace,'off')
            names=['ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_benchmark_resources.py','ws73_application_role.py','ws73_role_snapshot.py','ws73_dynamic_channels.py','ws73_channel_fairness.py']
            record=dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,
                socket_benchmark_requested='window',socket_benchmark_window_requested=4,
                socket_benchmark_acceptance=True,socket_benchmark_corroboration=proof,performance_qualified=False,
                socket_benchmark_role_contract_version=1,socket_benchmark_apps_acceptance=True,socket_benchmark_role_supervision=role,
                benchmark_trace_contract_version=1,benchmark_process_resource_contract_version=1,
                socket_benchmark_xhci_requested='off',socket_benchmark_xhci_observation=check_xhci(trace,'off'),
                benchmark_verifiers=[dict(path=n)for n in names],qemu_args=['ws73.socket_benchmark_apps=1 '+' '.join(gate.channel_boot(channel))],benchmark_channel_request=channel)
            self.assertEqual(run_exit_code(record),0)
            for kind in ['old-supervision','old-boot','no-close','no-exit','no-after','wrong-count','whole-drain']:
                bad=copy.deepcopy(record);p=bad['socket_benchmark_corroboration'];phase=p['proofs'][0]
                if kind=='old-supervision':bad['socket_benchmark_role_supervision']['version']=2
                elif kind=='old-boot':bad['qemu_args'][0]=bad['qemu_args'][0].replace(' ws73.benchmark_close=short','')
                elif kind=='no-close':phase['channels'][0]['close']=[]
                elif kind=='no-exit':phase['closed_short']=[]
                elif kind=='no-after':phase['close_continuity']['after_reply_sequences']=[]
                elif kind=='wrong-count':p['round_trips']=72
                else:phase['close_continuity']['callback_drain_proved']=True
                with self.subTest(kind=kind):self.assertEqual(run_exit_code(bad),1)

    def test_per_pair_finish_still_requires_both_ends_and_original_resources(self):
        helper=role_fixture.ClosedBenchmarkRoleFixture()
        for kind in ['short-before-peer','missing-long-finish','missing-exit','exit-boolean','long-already-done','resources-before-quiescent']:
            with tempfile.TemporaryDirectory()as directory:
                run,_=helper.fixture(Path(directory),gate.parallel_channel(close_short=True));row=run['socket_benchmark'][0]
                self.assertIsNone(gate.check_supervision(row))
                if kind=='short-before-peer':
                    e=next(e for e in row['events']if e['kind']=='finish'and e['application']==0)
                    e.update(before_wall_ns=1005,wall_ns=1006,before_monotonic_ns=1005,monotonic_ns=1006);row['events'].sort(key=lambda e:e['wall_ns'])
                elif kind=='missing-long-finish':row['events']=[e for e in row['events']if not(e['kind']=='finish'and e['application']==3)]
                elif kind=='missing-exit':row['closed_short'].pop()
                elif kind=='exit-boolean':row['closed_short'][0]['exit']=False
                elif kind=='long-already-done':row['closed_short'][0]['reaped_wall_ns']=row['applications'][0]['end_wall_ns']=8500
                else:row['applications'][2]['process_resources']['after']['begin_mono_ns']=7990
                with self.subTest(kind=kind),self.assertRaises(CaptureError):gate.check_supervision(row)

    def test_explicit_profile_boot_and_per_application_route(self):
        for active in(0,1):
            channel=gate.parallel_channel(active,close_short=True)
            args=SimpleNamespace(channel_benchmark='window',channel_benchmark_parallel=True,channel_benchmark_close_short=True,channel_benchmark_active_endpoint=active)
            self.assertEqual(gate.requested_channel(args),channel)
            self.assertEqual(gate.channel_from_boot(gate.channel_boot(channel),gate.configuration('window')),channel)
            self.assertEqual(gate.parallel_replies(channel),168)
            self.assertEqual(gate.supervision_version(channel),3)
            self.assertEqual([gate.application_config(dict(config=gate.configuration('window'),benchmark_channel_request=channel),i)['count']for i in range(4)],[20,20,64,64])
            for words in [gate.channel_boot(channel)+['ws73.benchmark_close=short'],gate.channel_boot(channel)[:-1]+['ws73.benchmark_close=all']]:
                with self.assertRaises(CaptureError):gate.channel_from_boot(words,gate.configuration('window'))
        for value in [None,1,'true']:
            with self.assertRaises(CaptureError):gate.requested_channel(SimpleNamespace(channel_benchmark_parallel=True,channel_benchmark_close_short=value))
        with self.assertRaises(CaptureError):gate.requested_channel(SimpleNamespace(channel_benchmark_close_short=True))
        legacy=gate.parallel_channel()
        self.assertEqual(gate.supervision_version(legacy),2);self.assertEqual(gate.parallel_replies(legacy),72)
        self.assertNotIn('ws73.benchmark_close=short',gate.channel_boot(legacy))

    def test_actual_production_oracles_close_and_after_peer_reply_fixture(self):
        helper=role_fixture.ClosedBenchmarkRoleFixture()
        for active in(0,1):
            with tempfile.TemporaryDirectory()as directory:
                root=Path(directory);channel=gate.parallel_channel(active,close_short=True);run,capture=helper.fixture(root,channel)
                role=gate.verify_role_artifacts(run,root);self.assertEqual(role['version'],3)
                proof=gate.corroborate(run,capture,root)
                self.assertEqual(proof['round_trips'],168)
                self.assertTrue(proof['channel_close_isolation_acceptance'])
                self.assertTrue(gate.valid_parallel_summary(proof,channel,gate.configuration('window'),role))
                for phase in proof['proofs']:
                    self.assertTrue(phase['close_continuity']['after_reply_sequences'])
                    self.assertTrue(phase['close_continuity']['before_reply_sequences'])
                    self.assertFalse(phase['close_continuity']['callback_drain_proved'])

    def test_close_receipts_and_raw_wire_negatives(self):
        helper=role_fixture.ClosedBenchmarkRoleFixture()
        for kind in ['missing-exit','early-finish','long-already-done','old-profile','missing-close','missing-close-reply','late-close','wrong-close-TCID','late-long-only','early-long-only']:
            with tempfile.TemporaryDirectory()as directory:
                root=Path(directory);channel=gate.parallel_channel(close_short=True);run,capture=helper.fixture(root,channel);row=run['socket_benchmark'][0]
                if kind=='missing-exit':row['closed_short'].pop()
                elif kind=='early-finish':
                    event=next(e for e in row['events']if e['kind']=='finish'and e['application']==0);event['before_wall_ns']=1
                elif kind=='long-already-done':row['closed_short'][1]['reaped_wall_ns']=9000
                elif kind=='old-profile':row[gate.CHANNEL_FIELD]=gate.parallel_channel()
                elif kind in ['missing-close','missing-close-reply','wrong-close-TCID','late-close']:
                    p=next(p for p in capture['acb_packets']if p['direction']=='out'and len(bytes.fromhex(p['data']))in(10,11)and bytes.fromhex(p['data'])[4]==(19 if kind=='missing-close-reply'else 18))
                    if kind.startswith('missing'):capture['acb_packets'].remove(p)
                    elif kind=='wrong-close-TCID':raw=bytearray.fromhex(p['data']);raw[-1]^=1;p['data']=raw.hex()
                    else:p['wall_ns']=8999
                else:
                    for p in capture['acb_packets']:
                        if 200<=p['wall_ns']<1900 and len(bytes.fromhex(p['data']))>11:p['wall_ns']+=(1500 if kind=='late-long-only'else-250)
                with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):gate.corroborate(run,capture,root)

    def test_legacy_global_barrier_is_not_relaxed(self):
        helper=role_fixture.ClosedBenchmarkRoleFixture()
        with tempfile.TemporaryDirectory()as directory:
            run,_=helper.fixture(Path(directory),gate.parallel_channel());row=run['socket_benchmark'][0]
            self.assertIsNone(gate.check_supervision(row))
            event=next(e for e in row['events']if e['kind']=='finish'and e['application']==0)
            event['wall_ns']=999;event['monotonic_ns']=999;row['events'].sort(key=lambda e:e['wall_ns'])
            with self.assertRaises(CaptureError):gate.check_supervision(row)
