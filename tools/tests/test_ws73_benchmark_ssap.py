# SPDX-License-Identifier: GPL-2.0-only
"""Finite selector/time/source fixtures,not Native or radio qualification."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from ws73_capture import CaptureError
import ws73_benchmark_ssap as service
import ws73_socket_benchmark as benchmark


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
            benchmark_ssap_contract_version=1,inputs=[file_record(HERE/n)for n in dict.fromkeys(names)],
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
