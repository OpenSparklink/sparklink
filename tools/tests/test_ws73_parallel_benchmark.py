# SPDX-License-Identifier: GPL-2.0-only
"""Finite metadata/source/CLI fixtures for the real four-pair coordinator.

These exercise production checks,with synthetic report/wire fixtures and Root
identity declarations. They do NOT execute Root roles,kernel,USB or hardware;
real closed files and peer delivery still require the dedicated VM gate.
No successful controller/Native dependencies are stubbed.
"""
import copy,json,hashlib,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_ws73_parallel_data import fixture as business_fixture
import test_ws73_benchmark_role as role_fixtures
from ws73_capture import CaptureError
from ws73_north_star import file_record
import ws73_parallel_data as gate
import ws73_socket_benchmark as benchmark
from ws73_target import validate_business_mode,require_benchmark_preparation,valid_parallel_benchmark,run_exit_code


def fixture(root):
    control=business_fixture();control.update(scope=gate.BENCHMARK_SCOPE,dynamic_benchmark_mode=True,parallel_benchmark_contract_version=1)
    pairs=[]
    for number,w in enumerate(control['workers']):
        folder=root/str(number);folder.mkdir();r,c=role_fixtures.ClosedBenchmarkRoleFixture().fixture(folder,benchmark.parallel_channel());proof=benchmark._match_payloads(r,c,folder)
        proof.update(parallel_pair=number,**{benchmark.PAIR_FIELD:1})
        child=w['run'];child.update(scope=gate.BENCHMARK_SCOPE,dynamic_benchmark_mode=True,parallel_benchmark_contract_version=1,socket_benchmark=[],connection_control=dict(phases=[]));child.pop('channel_socket');w['args'].insert(-2,'--dynamic-benchmark')
        connections=[]
        for phase in range(2):
            owners=[dict(owner=child['initial'][i],object=dict(generation=child['initial'][i]['generation'],lifetime=11+phase,handle=0))for i in(phase,1-phase)]
            row=dict(phase=phase,status=benchmark.PENDING,owners=owners,config=benchmark.configuration('window'),parallel_pair=number,applications=[dict(pid=2000+8*number+4*phase+i)for i in range(4)],**{benchmark.PAIR_FIELD:1,benchmark.CHANNEL_FIELD:benchmark.parallel_channel()})
            cookie='01234567-89ab-cdef-0123-456789abcdef'
            row['trace_observation']=dict(version=1,mode='on',clock='mono',cookie=cookie,parallel_pair=number,marker=f'SLK_BENCH_PAIR_{number}_PHASE_BEGIN:{cookie}:{phase}',end_marker=f'SLK_BENCH_PAIR_{number}_PHASE_END:{cookie}:{phase}')
            child['socket_benchmark'].append(row);child['connection_control']['phases'].append(dict(typed_objects=owners));proof['proofs'][phase]['owners']=owners
            connections.append(dict(steps=[dict(outcomes=[dict(wall_ns=phase*2000+100)]),dict(outcomes=[dict(wall_ns=phase*2000+1500)])]))
        supervision=dict(status='ACTUAL_ROOT_BENCHMARK_APPS_ONLY_PHASES_CHECKED',version=2,uid=1004,gid=1004,extra_groups=[],role_probes=2,application_processes=8,report_files=8,phases=2,performance_qualified=False,daemon=child['daemon_before'],supervisor=dict(pid=3000+number,start_ticks=77+number),snapshot_files=30,snapshot_bytes=1,parallel_pair=number,**{benchmark.PAIR_FIELD:1,benchmark.CHANNEL_FIELD:benchmark.parallel_channel()})
        pairs.append(dict(channel=proof,benchmark_supervision=supervision,connections=connections))
    proof=dict(status='FOUR_REAL_PARALLEL_DYNAMIC_BENCHMARK_CORROBORATED',parallel_benchmark_contract_version=1,parallel_benchmark_control=control,pairs=pairs,dynamic_benchmark=gate.benchmark_parallel_proof(pairs,control),overlaps=[],controller_count=4,round_trips=144,ordinary_uid=1004,coordinator_uid=1000,dynamic_channel_acceptance=True,fixed_basic_channel_business_acceptance=False,performance_qualified=False,fairness_acceptance=False,controller_credit_correctness_proof=False,fault_isolation_acceptance=False,automatic_fault_recovery_acceptance=False,protected_ssap_acceptance=False,full_goal_complete=False)
    proof['paired_trace']=dict(status='XHCI_CONFIGURATION_AND_SEAL_CORROBORATED',mode='on',trace_contract_version=2,clock='mono',cookie=cookie,phase_intervals=[dict(pair=i,phases=[dict(phase=0,begin_ns=10+i,end_ns=20+i),dict(phase=1,begin_ns=40+i,end_ns=50+i)])for i in(0,1)])
    for n in range(2):
        windows=[[min(v['tx']['wall_ns']for v in p['channel']['proofs'][n]['legs']),max(v['rx']['wall_ns']for v in p['channel']['proofs'][n]['legs'])]for p in pairs]
        proof['overlaps'].append(dict(role_phase=n,business_windows=windows,overlap_wall_ns=gate.overlap_window(windows)))
    return dict(status='FOUR_DEVICE_PARALLEL_DYNAMIC_BENCHMARK_PASS',scope=gate.BENCHMARK_SCOPE,four_dynamic_benchmark_contract_version=1,four_device_dynamic_benchmark_requested=True,four_device_parallel_business=True,four_device_parallel_rf=False,qemu_exit=0,supervisor_exit=0,qemu_args=['-append','ws73.parallel=1 ws73.parallel_business=1 ws73.parallel_benchmark=1 ws73.socket_benchmark_apps=1'],parallel_corroboration=proof)


class FourDynamicBenchmark(unittest.TestCase):
    def test_dedicated_typed_contract_rejects_mixed_modes(self):
        args=SimpleNamespace(command='run',four_device_dynamic_benchmark=True)
        validate_business_mode(args)
        for extra in ['four_device_burst','four_device_owned','channel_benchmark_parallel','qmp_hotplug']:
            with self.subTest(extra=extra),self.assertRaises(ValueError):validate_business_mode(SimpleNamespace(**vars(args),**{extra:True}))
        for r in [dict(dynamic_benchmark_mode=1),dict(parallel_benchmark_contract_version=1),dict(dynamic_benchmark_mode=True,parallel_benchmark_contract_version=True),dict(dynamic_benchmark_mode=True)]:
            with self.assertRaises(CaptureError):gate.benchmark_mode(r)

    def test_prepare_uses_actual_copied_sources_and_executable_init(self):
        here=Path(gate.__file__).parent
        names=['ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh','ws73_dynamic_channels.py','ws73_channel_fairness.py','ws73_parallel_data.py','ws73_parallel.py','ws73_connection_control.py']
        package=dict(four_dynamic_benchmark_contract_version=1,socket_benchmark_role_contract_version=1,benchmark_trace_contract_version=1,benchmark_process_resource_contract_version=1,inputs=[file_record(here/n)for n in names])
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp);dest=path/'root/usr/share/sparklink/tools';dest.mkdir(parents=True)
            for n in names:(dest/n).write_bytes((here/n).read_bytes())
            init=path/'root/init';init.write_bytes((here/'ws73_target_init.sh').read_bytes());init.chmod(0o755)
            require_benchmark_preparation(package,path)
            (dest/'ws73_parallel_data.py').write_text('# stale source\n')
            with self.assertRaisesRegex(ValueError,'source mismatch'):require_benchmark_preparation(package,path)
            (dest/'ws73_parallel_data.py').write_bytes((here/'ws73_parallel_data.py').read_bytes());init.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'executable VM init'):require_benchmark_preparation(package,path)
        for value in (None,True,2):
            wrong=dict(package,four_dynamic_benchmark_contract_version=value)
            with self.assertRaises(ValueError):require_benchmark_preparation(wrong,Path('/missing'))

    def test_metadata_aggregation_checks_existing_dynamic_wire_summary_and_ownership(self):
        with tempfile.TemporaryDirectory()as tmp:r=fixture(Path(tmp))
        p=r['parallel_corroboration'];gate.verify_records(p['parallel_benchmark_control']);self.assertTrue(valid_parallel_benchmark(r));self.assertEqual(run_exit_code(r),0)
        self.assertEqual(p['dynamic_benchmark']['application_processes'],16)
        mutations=['halfcount','pair','Rootpair','sameRoot','daemon','pid','missingphase','owner','roles','onechannel','smalllong','missingwireleg','nooverlap','extra-mode','boot-missing','boot-duplicate','boot-conflict','performance','fairness','credittruth','downgradestatus','unrequested','missing-trace','wrong-trace-root','legacy-trace','wrong-trace-pair']
        for kind in mutations:
            bad=copy.deepcopy(r);proof=bad['parallel_corroboration'];pair=proof['pairs'][1];child=proof['parallel_benchmark_control']['workers'][1]['run']
            if kind=='halfcount':proof['round_trips']=72
            elif kind=='pair':pair['channel']['parallel_pair']=0
            elif kind=='Rootpair':pair['benchmark_supervision']['parallel_pair']=0
            elif kind=='sameRoot':pair['benchmark_supervision']['supervisor']=proof['pairs'][0]['benchmark_supervision']['supervisor']
            elif kind=='daemon':pair['benchmark_supervision']['daemon']=dict(pid=33,start_ticks=44)
            elif kind=='pid':child['socket_benchmark'][0]['applications'][0]['pid']=proof['parallel_benchmark_control']['workers'][0]['run']['socket_benchmark'][0]['applications'][0]['pid']
            elif kind=='missingphase':child['socket_benchmark'].pop()
            elif kind=='owner':pair['channel']['proofs'][0]['owners']=[]
            elif kind=='roles':child['socket_benchmark'][0]['owners'].reverse()
            elif kind=='onechannel':pair['channel'][benchmark.CHANNEL_FIELD]=pair['channel'][benchmark.CHANNEL_FIELD]['channels'][0]['route']
            elif kind=='smalllong':pair['channel']['proofs'][0]['channels'][1]['config']['bytes']=61
            elif kind=='missingwireleg':pair['channel']['proofs'][0]['legs'].pop()
            elif kind=='nooverlap':proof['overlaps'][0]['overlap_wall_ns']=[1,1]
            elif kind=='extra-mode':bad['four_device_burst_requested']=True
            elif kind=='boot-missing':bad['qemu_args'][-1]=bad['qemu_args'][-1].replace('ws73.parallel_benchmark=1','')
            elif kind=='boot-duplicate':bad['qemu_args'][-1]+=' ws73.parallel_benchmark=1'
            elif kind=='boot-conflict':bad['qemu_args'][-1]+=' ws73.parallel_burst=1'
            elif kind=='performance':proof['performance_qualified']=True
            elif kind=='fairness':proof['fairness_acceptance']=True
            elif kind=='credittruth':proof['controller_credit_correctness_proof']=True
            elif kind=='downgradestatus':bad['status']='FOUR_DEVICE_PARALLEL_BUSINESS_PASS'
            elif kind=='missing-trace':proof.pop('paired_trace')
            elif kind=='wrong-trace-root':child['socket_benchmark'][0]['trace_observation']['parallel_pair']=0
            elif kind=='legacy-trace':proof['paired_trace']['trace_contract_version']=1
            elif kind=='wrong-trace-pair':proof['paired_trace']['phase_intervals'][1]['pair']=0
            else:bad['four_device_dynamic_benchmark_requested']=False
            with self.subTest(kind=kind):self.assertFalse(valid_parallel_benchmark(bad));self.assertEqual(run_exit_code(bad),1)

    def test_real_cli_exposes_one_mode_and_barrier_is_existing_pair_coordination(self):
        here=Path(gate.__file__).parent
        for script,extra in [('ws73_target.py',['run','--help']),('ws73_parallel_data.py',['--help'])]:
            p=subprocess.run([sys.executable,str(here/script),*extra],capture_output=True,text=True);self.assertEqual(p.returncode,0);self.assertIn('--four-device-dynamic-benchmark'if script=='ws73_target.py'else'--dynamic-benchmark',p.stdout)
        seen=[];run=SimpleNamespace(benchmark=True,barrier=lambda *v:seen.append(v));gate.BusinessPair.benchmark_barrier(run,dict(phase=1));self.assertEqual(seen,[('business-ready',1)])
        run.benchmark=False
        with self.assertRaises(CaptureError):gate.BusinessPair.benchmark_barrier(run,dict(phase=0))


if __name__=='__main__':unittest.main()
