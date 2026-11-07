# SPDX-License-Identifier: GPL-2.0-only
"""Finite selector/time/source fixtures,not Native or radio qualification."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from ws73_capture import CaptureError
import ws73_benchmark_ssap as service
import ws73_socket_benchmark as benchmark


def duplex_fixture():
    """SDK-receipt/USB-time input fixtures only,not a Native or peer substitute."""
    from ws73_application_client import application_environment
    owners=[dict(owner=dict(index=s,generation=s+1),object=dict(path=f'/fixture/controller{s}/connection'))for s in(0,1)]
    apps=[];batches=[];values=[]
    for sequence in range(4):
        pair=[dict(sequence=sequence,sender=s,wire=[None]*6,receipts={})for s in(0,1)]
        for step_index,step in enumerate(('read_before','write','read_after')):
            n=sequence*3+step_index;base=1_000_000_000+n*100_000_000
            batch=dict(version=1,index=n,sequence=sequence,step=step,applications=[2*n,2*n+1],start_wall_ns=base,
                       released_wall_ns=base+4_000_000,end_wall_ns=base+20_000_000,wait_deadline_monotonic_ns=base+3_000_000+7_000_000_000,
                       completed_monotonic_ns=base+20_000_000,status='SDK_CALLS_COMPLETE',supervisor_seconds=7)
            batches.append(batch)
            for s in(0,1):
                api='c'if s==0 else'python';value=bytes([sequence+s+1])*32;path=owners[s]['object']['path'];op='ssap-write'if step=='write'else'ssap-read'
                prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
                app=dict(api=api,position=s,environment=application_environment(),exit=0,stderr='',credentials=dict(uids=[1004]*4,gids=[1004]*4,groups=[],capabilities={k:'0'for k in ('CapEff','CapPrm','CapAmb','CapInh')}),
                    ssap_operation=op,ssap_path=path,ssap_handle=17,ssap_expected=value.hex(),args=prefix+['ssap',str(s),str(s+1),path,op,'17',value.hex()]+([value.hex()]if step=='write'else[]),
                    stdout=json.dumps(dict(stage='ssap_start_barrier',api=api,client_closed=True))+'\n'+f'SsapPeerValue: operation={op} path={path} handle=17 value={value.hex()}\n',
                    start_wall_ns=base+s*1_000_000,start_barrier_wall_ns=base+2_000_000+s*1000,ssap_release_before_wall_ns=base+3_000_000+s*100,
                    ssap_released_wall_ns=base+3_000_050+s*100,ssap_release_monotonic_ns=base+3_000_000+s*100,end_wall_ns=base+12_000_000+s*1_000_000,ssap_batch_index=n)
                apps.append(app);pair[s]['receipts'][step]=app
                def packet(t):return dict(wall_ns=t,data='0a00010008')
                request=base+5_000_000+s*500_000;response=base+8_000_000+s*500_000
                pair[s]['wire'][2*step_index:2*step_index+2]=[dict(tx=packet(request),rx=packet(request+100)),dict(tx=packet(response-100),rx=packet(response))]
        values.extend(pair)
    return apps,values,batches,owners,0


def timeline():
    def packet(at,data):return dict(wall_ns=at,data=data)
    def leg(at,data):return dict(tx=packet(at,data),rx=packet(at+1,data))
    channel=dict(legs=[leg(100+10*n+offset,'40000100f1')for n in range(128)for offset in(0,2)])
    ssap=dict(values=[dict(wire=[leg(300+70*n+offset,'0a00010008')for offset in range(6)])for n in range(8)])
    return channel,ssap


class ConcurrentOwned(unittest.TestCase):
    def args(self,**updates):
        return SimpleNamespace(**(dict(channel_benchmark='window',channel_benchmark_window=8,channel_benchmark_count=128,
            channel_benchmark_bytes=2042,channel_benchmark_interval_us=None,channel_benchmark_dynamic=True,
            channel_benchmark_active_endpoint=0,channel_benchmark_ssap_owned=True)|updates))

    def test_explicit_scope_rejects_unbounded_mixed_or_relabelled_workload(self):
        self.assertEqual(service.requested(self.args()),service.profile())
        self.assertIsNone(service.requested(self.args(channel_benchmark_ssap_owned=False)))
        for change in (dict(channel_benchmark_ssap_owned=1),dict(channel_benchmark_count=64),dict(channel_benchmark_bytes=61),
                       dict(channel_benchmark_dynamic=False),dict(channel_benchmark_parallel=True),dict(channel_benchmark='duplex')):
            with self.subTest(change=change),self.assertRaises(CaptureError):service.requested(self.args(**change))
        for value in (None,{},True,service.profile()|dict(version=True),service.profile()|dict(rounds=3),service.profile()|dict(extra=True)):
            with self.subTest(value=value),self.assertRaises(CaptureError):service.selected({service.FIELD:value})

    def test_boot_parent_role_and_single_canonical_token_required(self):
        base=['ws73.socket_benchmark_apps=1','ws73.benchmark_mode=window']
        self.assertIsNone(service.from_boot(base));self.assertEqual(service.from_boot(base+[service.TOKEN]),service.profile())
        for tokens in ([service.TOKEN],base+[service.TOKEN]*2,base+['ws73.benchmark_ssap=other'],['ws73.benchmark_mode=rate',base[0],service.TOKEN]):
            with self.subTest(tokens=tokens),self.assertRaises(CaptureError):service.from_boot(tokens)

    def test_duplex_is_explicit_and_preserves_the_sequential_entry(self):
        args=self.args(channel_benchmark_ssap_duplex=True)
        self.assertEqual(service.requested(args),service.profile(True));self.assertEqual(service.requested(self.args()),service.profile())
        self.assertEqual(service.from_boot(['ws73.socket_benchmark_apps=1','ws73.benchmark_mode=window',service.TOKEN_DUPLEX]),service.profile(True))
        self.assertEqual(service.boot(service.profile()),[service.TOKEN]);self.assertEqual(service.boot(service.profile(True)),[service.TOKEN_DUPLEX])
        for change in (dict(channel_benchmark_ssap_owned=False),dict(channel_benchmark_ssap_duplex=1)):
            with self.subTest(change=change),self.assertRaises(CaptureError):service.requested(self.args(**(dict(channel_benchmark_ssap_duplex=True)|change)))

    def test_paired_call_proof_requires_real_pending_overlap_and_original_budget(self):
        from ws73_application_client import duplex_evidence
        self.assertEqual(len(duplex_evidence(*duplex_fixture())['proofs']),12)
        for kind in ('serialized-wire','late-request-fragment','wrong-TCID','late-release','new-wait-budget','wrong-batch','root-child','missing-batch'):
            a,v,b,o,p=duplex_fixture()
            if kind=='serialized-wire':v[1]['wire'][0]['tx']['wall_ns']=v[0]['wire'][1]['rx']['wall_ns']+1
            elif kind=='late-request-fragment':v[1]['wire'][0]['tx']['fragments']=[dict(wall_ns=1_005_000_000),dict(wall_ns=1_009_000_000)]
            elif kind=='wrong-TCID':v[0]['wire'][0]['tx']['data']='8000010008'
            elif kind=='late-release':a[1]['ssap_released_wall_ns']=a[0]['end_wall_ns']+1
            elif kind=='new-wait-budget':b[0]['wait_deadline_monotonic_ns']+=100
            elif kind=='wrong-batch':a[0]['ssap_batch_index']=1
            elif kind=='root-child':a[0]['credentials']['uids']=[0]*4
            else:b.pop()
            with self.subTest(kind=kind),self.assertRaises(CaptureError):duplex_evidence(a,v,b,o,p)

    def test_pair_cannot_launch_any_child_outside_the_explicit_VM(self):
        from ws73_application_client import ssap_commands
        with patch('subprocess.Popen',side_effect=AssertionError('must not launch')):
            with self.assertRaises(CaptureError):ssap_commands(SimpleNamespace(),{},[(None,None,None)]*2,application_uid=1004,batch=(0,'write'))

    def test_real_wire_window_requires_complete_roundtrips_before_during_after(self):
        channel,ssap=timeline();result=service.progress(channel,ssap)
        self.assertTrue(result['before']and result['during']and result['after'])
        self.assertFalse(result['performance_qualified']);self.assertFalse(result['full_fairness_qualified'])
        for kind in ('only-before','only-after','missing-channel-leg','missing-SSAP-leg','SMTC-alias','untyped-clock'):
            c,s=copy.deepcopy((channel,ssap))
            if kind in ('only-before','only-after'):
                shifted=c['legs']if kind=='only-after'else[leg for v in s['values']for leg in v['wire']]
                for leg in shifted:
                    for p in leg.values():p['wall_ns']+=10000
            elif kind=='missing-channel-leg':c['legs'].pop()
            elif kind=='missing-SSAP-leg':s['values'][0]['wire'].pop()
            elif kind=='SMTC-alias':c['legs'][0]['tx']['data']='0a000100f1'
            else:c['legs'][0]['tx']['wall_ns']=True
            with self.subTest(kind=kind),self.assertRaises(CaptureError):service.progress(c,s)

    def test_complete_fragment_end_not_first_fragment_decides_overlap(self):
        channel,ssap=timeline();first=channel['legs'][50]
        first['rx']['fragments']=[dict(wall_ns=351),dict(wall_ns=5000)]
        result=service.progress(channel,ssap)
        self.assertNotIn(25,result['during']);self.assertEqual(service.packet_times(first['rx']),(351,5000))
        with self.assertRaises(CaptureError):service.packet_times(dict(fragments=[]))

    def test_new_service_source_closure_includes_the_actual_C_and_Python_inputs(self):
        from ws73_target import HERE,file_record
        names=['ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py',
               'ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh','ws73_dynamic_channels.py',*service.VERIFIERS]
        package=dict(socket_benchmark_role_contract_version=1,benchmark_trace_contract_version=1,benchmark_process_resource_contract_version=1,
            benchmark_ssap_contract_version=2,inputs=[file_record(HERE/n)for n in dict.fromkeys(names)],
            application_client_tools=dict(sources=[file_record(HERE/n)for n in('testing/application_client/client.c','testing/application_client/client.py')]))
        benchmark.validate_role_sources(package,dynamic=True,ssap=True)
        for kind in ('marker','helper','C-source'):
            bad=copy.deepcopy(package)
            if kind=='marker':bad['benchmark_ssap_contract_version']=True
            elif kind=='helper':next(x for x in bad['inputs']if x['path'].endswith('ws73_benchmark_ssap.py'))['sha256']='0'*64
            else:bad['application_client_tools']['sources'][0]['sha256']='0'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):benchmark.validate_role_sources(bad,dynamic=True,ssap=True)
        # The original plain benchmark doesnot gain an SDK-consumer prerequisite.
        package.pop('application_client_tools');benchmark.validate_role_sources(package,dynamic=True)

    def test_missing_source_or_outside_VM_never_calls_the_SSAP_loop(self):
        run=SimpleNamespace();row={service.FIELD:service.profile()}
        with patch('ws73_application_role.require_vm',side_effect=CaptureError('outside VM')):
            with patch('ws73_application_client.ssap_phase',side_effect=AssertionError('must not call')):
                with self.assertRaises(CaptureError):service.execute(run,row)
        with self.assertRaises(CaptureError):service.streams({service.SOURCE:{}})
        for value in (None,{},dict(ssap={})):self.assertFalse(service.valid_summary(value))
        from ws73_application_client import corroborate_ssap
        with self.assertRaises(CaptureError):corroborate_ssap([dict(phase=0)],{})


if __name__=='__main__':unittest.main()
