# SPDX-License-Identifier: GPL-2.0-only
"""Actual profile/report/Root/capture functions on finite fixtures.

Fixtures describe journal bytes,not successful kernel/USB/credit dependencies.
No real EAGAIN,firmware,concurrency or RF qualification is inferred here.
"""
import copy,json,re,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import ws73_socket_benchmark as gate
from ws73_capture import CaptureError
from ws73_benchmark_timeline import check_xhci,valid_trace_summary
from ws73_trace_layout import buffer_kib
import test_ws73_benchmark_role as role_fixture
from test_ws73_benchmark_timeline import modern_trace
from ws73_target import run_exit_code


def trace_fixture(root):
    modern_trace(root)
    for edge in('start','end'):
        p=root/f'benchmark-xhci-{edge}.json';r=json.loads(p.read_text());r['requested_buffer_kb']=16384;r['buffer_kb']=buffer_kib((root/f'benchmark-xhci-header-{edge}.txt').read_text(),16384,r['subbuffer_kb'])[0];p.write_text(json.dumps(r))


def record_fixture(root):
    channel=gate.parallel_channel(pressure=True);run,capture=role_fixture.ClosedBenchmarkRoleFixture().fixture(root,channel,pressure_eagain=True);proof=gate.corroborate(run,capture,root);role=gate.verify_role_artifacts(run,root);trace=root/'trace';trace.mkdir();trace_fixture(trace)
    names=['ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_benchmark_resources.py','ws73_application_role.py','ws73_role_snapshot.py','ws73_dynamic_channels.py','ws73_channel_fairness.py']
    record=dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,socket_benchmark_requested='window',socket_benchmark_window_requested=4,socket_benchmark_acceptance=True,socket_benchmark_corroboration=proof,performance_qualified=False,socket_benchmark_role_contract_version=1,socket_benchmark_apps_acceptance=True,socket_benchmark_role_supervision=role,benchmark_trace_contract_version=1,benchmark_process_resource_contract_version=1,socket_benchmark_xhci_requested='on',socket_benchmark_xhci_observation=check_xhci(trace,'on',pressure=True),benchmark_verifiers=[dict(path=n)for n in names],qemu_args=['ws73.socket_benchmark_apps=1 '+' '.join(gate.channel_boot(channel))],benchmark_channel_request=channel)
    return record,run,capture


class PressureProfile(unittest.TestCase):
    def test_explicit_profile_uses_original_args_and_rejects_implicit_or_combined_scope(self):
        for active in(0,1):
            channel=gate.parallel_channel(active,pressure=True);args=SimpleNamespace(channel_benchmark='window',channel_benchmark_parallel=True,channel_benchmark_pressure=True,channel_benchmark_active_endpoint=active)
            self.assertEqual(gate.requested_channel(args),channel);self.assertEqual(gate.channel_from_boot(gate.channel_boot(channel),gate.configuration('window')),channel)
            self.assertEqual(gate.parallel_replies(channel),168);self.assertEqual([g['config']['window']for g in channel['channels']],[4,16])
            for words in [gate.channel_boot(channel)+['ws73.benchmark_pressure=1'],gate.channel_boot(channel)[:-1]+['ws73.benchmark_pressure=0'],gate.channel_boot(channel)+['ws73.benchmark_close=short']]:
                with self.assertRaises(CaptureError):gate.channel_from_boot(words,gate.configuration('window'))
        for values in [dict(channel_benchmark_pressure=1),dict(channel_benchmark_pressure=True),dict(channel_benchmark_pressure=True,channel_benchmark_parallel=True,channel_benchmark_close_short=True)]:
            with self.assertRaises(CaptureError):gate.requested_channel(SimpleNamespace(channel_benchmark='window',**values))
        self.assertEqual(gate.parallel_channel()['version'],2);self.assertEqual(gate.parallel_channel(close_short=True)['version'],3)
        for name,extra in [('ws73_target.py',['run','--help']),('ws73_target_control.py',['--help'])]:
            result=subprocess.run([sys.executable,str(Path(gate.__file__).with_name(name)),*extra],capture_output=True,text=True)
            self.assertEqual(result.returncode,0);self.assertIn('--channel-benchmark-pressure',result.stdout)

    def test_existing_closed_root_wire_and_original_deadline_oracle_requires_recovered_eagain(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);record,run,capture=record_fixture(root);proof=record['socket_benchmark_corroboration'];channel=gate.row_channel(record)
            self.assertEqual(run_exit_code(record),0);self.assertTrue(gate.valid_parallel_summary(proof,channel,gate.configuration('window'),record['socket_benchmark_role_supervision']));self.assertEqual(proof['round_trips'],168)
            self.assertTrue(proof['software_backpressure_acceptance'])
            for phase in proof['proofs']:
                group=phase['channels'][1];gate.check_pressure_recovery(group,phase['owners'][0]);self.assertGreater(group['application']['backpressure_recovery']['would_block_calls'],0)
            for mutation in ['no-recovery','counter','boolcounter','deadline','payload','lifetime','missing-leg','old-profile','no-acceptance','credit-truth','default-trace','orphan-boot']:
                bad=copy.deepcopy(record);p=bad['socket_benchmark_corroboration'];phase=p['proofs'][0];group=phase['channels'][1];item=group['application']['backpressure_recovery']['records'][0]
                if mutation=='no-recovery':group['application']['backpressure_recovery']['records']=[]
                elif mutation=='counter':item['send_attempts']=1
                elif mutation=='boolcounter':item['would_block']=True
                elif mutation=='deadline':item['deadline_ns']+=1
                elif mutation=='payload':item['frame_sha256']='0'*64
                elif mutation=='lifetime':group['application']['backpressure_recovery']['source_identity']['lifetime']+=1
                elif mutation=='missing-leg':group['legs'].pop()
                elif mutation=='old-profile':bad[gate.CHANNEL_FIELD]=gate.parallel_channel()
                elif mutation=='no-acceptance':p.pop('software_backpressure_acceptance')
                elif mutation=='credit-truth':group['application']['backpressure_recovery']['controller_credit_truth']=True
                elif mutation=='default-trace':bad['socket_benchmark_xhci_observation']['requested_buffer_kb']=1024
                else:bad['qemu_args'][0]=bad['qemu_args'][0].replace('ws73.benchmark_pressure=1','')
                with self.subTest(mutation=mutation):self.assertEqual(run_exit_code(bad),1)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);run,capture=role_fixture.ClosedBenchmarkRoleFixture().fixture(root,gate.parallel_channel(pressure=True))
            with self.assertRaisesRegex(CaptureError,'actual send EAGAIN'):gate.corroborate(run,capture,root)

    def test_exact_trace_profile_and_actual_init_budget_do_not_weaken_zero_loss(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);trace_fixture(root);proof=check_xhci(root,'on',pressure=True);self.assertTrue(valid_trace_summary(proof,'on',pressure=True))
            with self.assertRaises(CaptureError):check_xhci(root,'on')
            with self.assertRaises(CaptureError):check_xhci(root,'off',pressure=True)
            with self.assertRaises(CaptureError):check_xhci(root,'on',parallel=True,pressure=True)
            (root/'xhci-trace-stats.txt').write_text((root/'xhci-trace-stats.txt').read_text().replace('overrun: 0','overrun: 1',1))
            with self.assertRaises(CaptureError):check_xhci(root,'on',pressure=True)
        text=Path(gate.__file__).with_name('ws73_target_init.sh').read_text();body=re.search(r'^benchmark_trace_buffer_kb\(\) \{.*?^\}',text,re.M|re.S).group()
        for words,result in [([], '1024'),(['ws73.parallel_benchmark=1'],'8192'),(['ws73.benchmark_pressure=1'],'16384')]:
            p=subprocess.run(['sh','-c',body+'\nbenchmark_trace_buffer_kb "$@"','fixture',*words],capture_output=True,text=True);self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,result)


if __name__=='__main__':unittest.main()
