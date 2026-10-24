# SPDX-License-Identifier: GPL-2.0-only
"""Metadata fixtures and actual local OS children; no kernel, D-Bus or RF proof."""
import copy
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_transport_watch as watch
import ws73_benchmark_ssap as service
from ws73_capture import CaptureError
from test_ws73_session_drain import fixture as drain_fixture


def fixture():
    channel,_=drain_fixture()
    samples=[]
    for i,item in enumerate(channel['session_drain']['samples'][0]['observations']):
        receipt=copy.deepcopy(item['receipt'])
        receipt.update(pid=800+i,reaped=True,outcome='SNAPSHOT_OBSERVED',
            deadline_monotonic_ns=receipt['start_monotonic_ns']+watch.SPEC['query_budget_ns'],
            credentials=dict(uids=[1000]*4,gids=[1000]*4,groups=[],
                             capabilities=dict.fromkeys(watch.CAPABILITIES,'0000000000000000')),
            values=item['values'],stderr='')
        samples.append(dict(pair=0,endpoint=i,planned_monotonic_ns=100,receipt=receipt))
    report=dict(version=1,spec=dict(watch.SPEC),phase=0,samples=samples,missed_pairs=[],unattempted_pairs=[],
        status='BOUNDED_READONLY_OBSERVATION_COMPLETE',thread_joined=True,performance_qualified=False,
        start_wall_ns=10100,start_monotonic_ns=100,stop_wall_ns=10500,stop_monotonic_ns=500,
        end_wall_ns=10600,end_monotonic_ns=600)
    return dict(phase=0,owners=channel['owners'],start_wall_ns=10000,end_wall_ns=10700,
                events=[dict(kind='start',before_wall_ns=10110),dict(kind='quiescent',wall_ns=10400)],
                transport_observation=report)


class WatchContract(unittest.TestCase):
    def test_actual_decoder_reused_without_drain_or_credit_truth(self):
        proof=watch.validate(fixture(),True)
        self.assertEqual(proof['successes'],[1,1])
        self.assertFalse(proof['credit_truth_qualified'])
        self.assertFalse(proof['physical_drain_qualified'])
        self.assertTrue(watch.valid_summary(proof))
        for key in ('credit_truth_qualified','physical_drain_qualified','performance_qualified'):
            bad=copy.deepcopy(proof);bad[key]=True
            self.assertFalse(watch.valid_summary(bad))

    def test_missing_incomplete_identity_budget_and_fabricated_success_fail_closed(self):
        for case in ('missing','unrequested','budget','unjoined','wrong-phase','float-spec','old-generation',
                     'duplicate','wrong-argv','wrong-pid','missing-caps','root','before-armed',
                     'early-stop','renewed-query','overlap','oversize','missing-endpoint','future-values',
                     'lost-unattempted','false-skipped','extended-source-debt'):
            row=fixture();r=row[watch.FIELD];sample=r['samples'][0];receipt=sample['receipt']
            if case=='missing':row.pop(watch.FIELD)
            elif case=='unrequested':pass
            elif case=='budget':r['status']='OBSERVATION_BUDGET_REACHED'
            elif case=='unjoined':r['thread_joined']=False
            elif case=='wrong-phase':r['phase']=1
            elif case=='float-spec':r['spec']['version']=True
            elif case=='old-generation':receipt['stdout']=receipt['stdout'].replace('generation=7','generation=8')
            elif case=='duplicate':r['samples'].append(copy.deepcopy(sample))
            elif case=='wrong-argv':receipt['args'][-1]='/other-lifetime'
            elif case=='wrong-pid':receipt['pid']=True
            elif case=='missing-caps':receipt['credentials']['capabilities']={}
            elif case=='root':receipt['credentials']['uids']=[0]*4
            elif case=='before-armed':r['start_wall_ns']=10111
            elif case=='early-stop':r['stop_wall_ns']=10399
            elif case=='renewed-query':receipt['deadline_monotonic_ns']+=1
            elif case=='overlap':r['samples'][1]['receipt']['start_monotonic_ns']=receipt['start_monotonic_ns']
            elif case=='oversize':receipt['stderr']='x'*8193
            elif case=='missing-endpoint':r['samples'].pop()
            elif case=='future-values':receipt['outcome']='QUERY_TIMEOUT'
            elif case=='lost-unattempted':r['unattempted_pairs']=[1]
            elif case=='false-skipped':r['missed_pairs']=[dict(first=0,stop=1)]
            else:receipt['stdout']=receipt['stdout'].replace('outstanding=0 debt=0','outstanding=6 debt=6')
            with self.subTest(case=case),self.assertRaises((CaptureError,KeyError,ValueError)):
                watch.validate(row,case!='unrequested')

    def test_default_and_observed_profiles_have_separate_boot_and_source_closure(self):
        base=['ws73.socket_benchmark_apps=1','ws73.benchmark_mode=window']
        for paired in(False,True):
            old=service.profile(paired)
            self.assertEqual(service.verifiers(old),service.VERIFIERS)
            self.assertEqual(service.from_boot(base+service.boot(old)),old)
            new=service.profile(paired,observe=True)
            self.assertTrue(service.observing(new))
            self.assertEqual(service.from_boot(base+service.boot(new)),new)
            self.assertTrue(set(watch.VERIFIERS)<=set(service.verifiers(new)))
            bad=copy.deepcopy(new);bad['transport_observation_request']['version']=True
            with self.assertRaises(CaptureError):service.selected({service.FIELD:bad})
            with self.assertRaises(CaptureError):service.from_boot(base+service.boot(new)+service.boot(old))

    def test_failed_query_is_retained_without_zero_or_success_values(self):
        row=fixture();r=row[watch.FIELD];sample=copy.deepcopy(r['samples'][0])
        sample.update(pair=1,planned_monotonic_ns=1_000_000_100)
        receipt=sample['receipt'];receipt.pop('values')
        receipt.update(start_monotonic_ns=1_000_000_200,end_monotonic_ns=2_250_000_201,
                       deadline_monotonic_ns=2_250_000_200,start_wall_ns=1_000_010_200,
                       end_wall_ns=2_250_010_201,exit=-9,outcome='QUERY_TIMEOUT',stdout='')
        r['samples'].append(sample);r.update(stop_monotonic_ns=2_250_000_300,end_monotonic_ns=2_250_000_400,
            stop_wall_ns=2_250_010_300,end_wall_ns=2_250_010_400,unattempted_pairs=[2])
        row['end_wall_ns']=2_250_010_500
        proof=watch.validate(row,True)
        self.assertEqual(proof['failures'],1)
        self.assertEqual(proof['successes'],[1,1])
        receipt['values']=dict(capacity=0,outstanding=0)
        with self.assertRaises(CaptureError):watch.validate(row,True)

    def test_original_failed_role_is_separate_and_never_a_success_summary(self):
        row=fixture();row.update(status='FAIL',error='original fixture failure')
        row['events']=[e for e in row['events'] if e['kind']!='quiescent']
        with self.assertRaises(CaptureError):watch.validate(row,True)
        proof=watch._validate(row,True,failed=True)
        self.assertEqual(proof['status'],'FAILED_ROLE_READONLY_TRANSPORT_OBSERVATIONS_NOT_QUALIFIED')
        self.assertFalse(watch.valid_summary(proof))
        for change in (dict(status='PENDING'),dict(error=''),dict(error=None)):
            with self.subTest(change=change),self.assertRaises(CaptureError):
                watch._validate(row|change,True,failed=True)

    def test_observer_source_contract_cannot_be_missing_stale_or_default(self):
        from ws73_target import HERE,file_record
        from ws73_socket_benchmark import validate_role_sources
        names=['ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py',
               'ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py',
               'ws73_target_guest.py','ws73_target_init.sh','ws73_dynamic_channels.py',*service.VERIFIERS,*watch.VERIFIERS]
        package=dict(socket_benchmark_role_contract_version=1,benchmark_trace_contract_version=1,
                     benchmark_process_resource_contract_version=1,benchmark_ssap_contract_version=2,
                     benchmark_credit_observation_contract_version=1,
                     inputs=[file_record(HERE/n)for n in dict.fromkeys(names)],
                     application_client_tools=dict(sources=[file_record(HERE/n)for n in
                                                          ('testing/application_client/client.c','testing/application_client/client.py')]))
        validate_role_sources(package,dynamic=True,ssap=True,observe=True)
        for case in ('missing','bool','stale-watch','stale-decoder','without-ssap'):
            bad=copy.deepcopy(package)
            if case=='missing':bad.pop('benchmark_credit_observation_contract_version')
            elif case=='bool':bad['benchmark_credit_observation_contract_version']=True
            elif case.startswith('stale'):
                name='ws73_transport_watch.py'if case=='stale-watch'else'ws73_session_drain.py'
                next(v for v in bad['inputs']if v['path'].endswith(name))['sha256']='0'*64
            with self.subTest(case=case),self.assertRaises(ValueError):
                validate_role_sources(bad,dynamic=True,ssap=case!='without-ssap',observe=True)
        # An old plain profile does not acquire observation prerequisites.
        package.pop('benchmark_credit_observation_contract_version')
        validate_role_sources(package,dynamic=True,ssap=True)

    def test_actual_production_guards_with_visible_filesystem_fixtures(self):
        # Execute both real guards/boot parser; only OS identity/file inputs are fixtures.
        def check(tokens,uid=0,vendor='QEMU',scratch=True):
            def read(path,*a,**k):
                return tokens if str(path)=='/proc/cmdline'else vendor
            with patch('os.geteuid',return_value=uid),patch.object(Path,'read_text',read),patch.object(Path,'is_file',return_value=scratch):
                watch.require_environment()
        tokens='ws73.socket_benchmark_apps=1 ws73.session_service=1 ws73.session_service_profile=full-load-v2'
        check(tokens)
        for kwargs in (dict(uid=1000),dict(vendor='host'),dict(scratch=False),
                       dict(tokens=tokens.replace('ws73.socket_benchmark_apps=1','')),
                       dict(tokens=tokens.replace('ws73.session_service=1','')),
                       dict(tokens=tokens.replace('ws73.session_service_profile=full-load-v2','')),
                       dict(tokens=tokens+' ws73.session_service=1'),
                       dict(tokens=tokens+' ws73.session_service_profile=full-load-v2')):
            with self.subTest(kwargs=kwargs),self.assertRaises((CaptureError,ValueError)):
                check(**(dict(tokens=tokens)|kwargs))


class ActualProcessBudgets(unittest.TestCase):
    def run_child(self,code,event=None):
        # No uid override: this is an OS-child fixture, never a production query.
        return watch.collect_process([sys.executable,'-c',code],event or threading.Event())

    def assert_reaped(self,receipt):
        self.assertTrue(receipt['reaped'])
        with self.assertRaises(ChildProcessError):os.waitpid(receipt['pid'],os.WNOHANG)

    def test_actual_local_child_outputs_and_reap(self):
        receipt=self.run_child("import time;print('fixture',flush=True);time.sleep(.05)")
        self.assertEqual(receipt['outcome'],'EXITED')
        self.assertEqual(receipt['stdout'],'fixture\n')
        self.assertEqual(receipt['exit'],0)
        self.assertNotIn('values',receipt)
        self.assert_reaped(receipt)

    def test_real_timeout_does_not_renew_with_partial_output(self):
        receipt=self.run_child("import time;[(print('partial',flush=True),time.sleep(.1))for _ in range(100)]")
        self.assertEqual(receipt['outcome'],'QUERY_TIMEOUT')
        self.assertGreaterEqual(receipt['end_monotonic_ns'],receipt['deadline_monotonic_ns'])
        self.assertEqual(receipt['deadline_monotonic_ns']-receipt['start_monotonic_ns'],watch.SPEC['query_budget_ns'])
        self.assert_reaped(receipt)

    def test_output_limit_is_enforced_during_read_not_after_unbounded_capture(self):
        receipt=self.run_child("import os,time;os.write(1,b'x'*100000);time.sleep(60)")
        self.assertEqual(receipt['outcome'],'OUTPUT_BUDGET')
        self.assertLessEqual(len(receipt['stdout']),watch.SPEC['stream_limit_bytes']+1)
        self.assertTrue(receipt['output_incomplete'])
        self.assert_reaped(receipt)

    def test_stop_cancels_and_reaps_only_the_owned_query(self):
        event=threading.Event();result=[]
        thread=threading.Thread(target=lambda:result.append(self.run_child('import time;time.sleep(60)',event)))
        thread.start();time.sleep(.1);event.set();thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]['outcome'],'CANCELLED_OBSERVER_STOP')
        self.assert_reaped(result[0])

    def test_thread_joins_and_does_not_mutate_owners_or_claim_kernel_samples(self):
        row=fixture();owners=copy.deepcopy(row['owners'])
        def local_query(entry,event):return self.run_child("import time;print('OS fixture',flush=True);time.sleep(.05)",event)
        with patch.object(watch,'require_environment'),patch.object(watch,'query',side_effect=local_query):
            observer=watch.Watch(owners,0).start();time.sleep(.1);report=observer.close()
            self.assertIs(observer.close(),report)
        self.assertEqual(owners,row['owners'])
        self.assertFalse(observer.thread.is_alive())
        self.assertTrue(report['thread_joined'])
        self.assertTrue(all(v['receipt']['reaped']for v in report['samples']))
        row[watch.FIELD]=report
        with self.assertRaises(CaptureError):watch.validate(row,True)

    def test_exhausted_finite_observer_is_not_upgraded_by_close(self):
        row=fixture()
        def local_query(entry,event):return self.run_child("import time;print('fixture',flush=True);time.sleep(.05)",event)
        with patch.object(watch,'require_environment'),patch.object(watch,'query',side_effect=local_query),patch.dict(watch.SPEC,max_pairs=1):
            observer=watch.Watch(row['owners'],0).start();observer.thread.join(3)
            self.assertFalse(observer.thread.is_alive())
            report=observer.close()
            self.assertEqual(report['status'],'OBSERVATION_BUDGET_REACHED')
            self.assertLessEqual(len(report['samples']),2)
        row[watch.FIELD]=report
        with self.assertRaises(CaptureError):watch.validate(row,True)
