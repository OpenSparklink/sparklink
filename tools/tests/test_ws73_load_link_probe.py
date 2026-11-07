# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic receipts plus real local child/thread tests;not D-Bus/kernel/RF proof."""
import copy
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
import ws73_link_measurement as link
import ws73_benchmark_ssap as service
import ws73_transport_watch as transport
from ws73_capture import CaptureError
from test_ws73_link_measurement import fixture as initial


def fixture():
    origin=1_000_000_000;bias=1_000_000_000_000;owners=[];samples=[]
    capture=dict(commands=[],complete=[])
    for endpoint in (0,1):
        entry,raw=initial(endpoint);owners.append(entry)
        start=origin+link.LOAD_SPEC['offset_ns']+100+endpoint*1000;end=start+100
        receipt=copy.deepcopy(entry['link_measurements']['queries'][0]['command'])
        value=copy.deepcopy(entry['link_measurements']['queries'][0]['observation'])
        value.update(request_id=100+endpoint,deadline_monotonic_ns=start+5_000_000_000)
        receipt.update(args=link.load_command(entry),start_monotonic_ns=start,end_monotonic_ns=end,
            start_wall_ns=bias+start,end_wall_ns=bias+end,
            deadline_monotonic_ns=start+link.LOAD_SPEC['child_budget_ns'],
            stdout='NativeLinkMeasurement: '+json.dumps(value)+'\n',
            pid=800+endpoint,reaped=True,outcome='LINK_REPLY_OBSERVED',observation=value,
            credentials=dict(uids=[1000]*4,gids=[1000]*4,groups=[],
                capabilities=dict.fromkeys(transport.CAPABILITIES,'0')))
        samples.append(dict(endpoint=endpoint,receipt=receipt))
        command=copy.deepcopy(raw['commands'][0]);reply=copy.deepcopy(raw['complete'][0])
        command.update(wall_ns=bias+start+10,completion=dict(wall_ns=bias+start+11))
        reply.update(wall_ns=bias+start+12)
        capture['commands'].append(command);capture['complete'].append(reply)
    finish=samples[-1]['receipt']['end_monotonic_ns']+100
    report=dict(version=1,spec=dict(link.LOAD_SPEC),phase=0,samples=samples,
        barrier_monotonic_ns=origin,planned_monotonic_ns=origin+link.LOAD_SPEC['offset_ns'],
        start_wall_ns=bias+origin+10,start_monotonic_ns=origin+10,
        worker_end_wall_ns=bias+finish,worker_end_monotonic_ns=finish,
        stop_wall_ns=bias+finish+100,stop_monotonic_ns=finish+100,
        end_wall_ns=bias+finish+200,end_monotonic_ns=finish+200,
        status='COLLECTED_NOT_QUALIFIED',thread_joined=True,unattempted_endpoints=[],
        performance_qualified=False,physical_drain_qualified=False,application_delivery_qualified=False)
    return dict(phase=0,owners=owners,start_wall_ns=bias+origin-100,end_wall_ns=bias+finish+300,
        events=[dict(kind='start',application=0,monotonic_ns=origin-1,wall_ns=bias+origin-1),
                dict(kind='start',application=1,monotonic_ns=origin,wall_ns=bias+origin)],load_link_probe=report),capture


class LoadLinkProbeTests(unittest.TestCase):
    def test_success_requires_real_raw_complete_and_preserves_non_delivery_scope(self):
        row,raw=fixture();proof=link.validate_load(row,raw,True)
        self.assertTrue(link.valid_load_summary(proof))
        self.assertFalse(link.valid_load_summary(link.validate_load(row,None,True)))
        self.assertFalse(proof['application_delivery_qualified'])
        self.assertFalse(proof['physical_drain_qualified'])

    def test_identity_schedule_attempts_budget_and_raw_negatives(self):
        for case in ('unrequested','missing','duplicate','early','renew','unjoined','root','old-life',
                     'old-author','missing-complete','wrong-params','wrong-data','fake-drain',
                     'false-skip','bool-spec','empty','extra-output','killed-with-value'):
            row,raw=fixture();p=row[link.LOAD_FIELD];r=p['samples'][0]['receipt']
            if case=='missing':row.pop(link.LOAD_FIELD)
            elif case=='duplicate':p['samples'].append(copy.deepcopy(p['samples'][0]))
            elif case=='early':r['start_monotonic_ns']=p['planned_monotonic_ns']-1
            elif case=='renew':r['deadline_monotonic_ns']+=1
            elif case=='unjoined':p['thread_joined']=False
            elif case=='root':r['credentials']['uids']=[0]*4
            elif case=='old-life':row['owners'][0]['object']['lifetime']+=1
            elif case=='old-author':
                r['observation']['request_id']=1;r['stdout']='NativeLinkMeasurement: '+json.dumps(r['observation'])+'\n'
            elif case=='missing-complete':raw['complete'].pop()
            elif case=='wrong-params':raw['commands'][0]['params']='3512'
            elif case=='wrong-data':raw['complete'][0]['value']='341200'
            elif case=='fake-drain':p['physical_drain_qualified']=True
            elif case=='false-skip':p['unattempted_endpoints']=[1]
            elif case=='bool-spec':p['spec']['version']=True
            elif case=='empty':p['samples']=[];p['unattempted_endpoints']=[0,1]
            elif case=='extra-output':r['stdout']+='extra\n'
            elif case=='killed-with-value':r['outcome']='CANCELLED_OBSERVER_STOP'
            with self.subTest(case=case),self.assertRaises((CaptureError,KeyError,TypeError)):
                link.validate_load(row,raw,case!='unrequested')

    def test_actual_failed_attempt_and_unattempted_are_not_zero_or_success(self):
        row,raw=fixture();row.update(status='FAIL',error='original business fault')
        p=row[link.LOAD_FIELD];p['samples']=p['samples'][:1];p['unattempted_endpoints']=[1]
        raw['commands']=raw['commands'][:1];raw['complete']=raw['complete'][:1]
        r=p['samples'][0]['receipt'];r.pop('observation');r.update(outcome='LINK_QUERY_NOT_SUCCESSFUL',exit=1,stdout='',stderr='original deadline')
        proof=link.validate_load(row,raw,True,failed=True)
        self.assertEqual((proof['attempts'],proof['successful_replies'],proof['unattempted_endpoints']),(1,0,[1]))
        self.assertFalse(link.valid_load_summary(proof))
        self.assertEqual(len(proof['raw_completion_candidates'][0]['candidates']),1)
        with self.assertRaises(CaptureError):link.validate_load(row,raw,True)

    def test_downgrading_scope_or_repeating_wire_queries_is_rejected(self):
        row,raw=fixture();row.pop(link.LOAD_FIELD)
        with self.assertRaises(CaptureError):link.validate_load(row,raw,False)
        row,raw=fixture();raw['commands'].append(copy.deepcopy(raw['commands'][0]))
        with self.assertRaises(CaptureError):link.validate_load(row,raw,True)

    def test_final_metadata_rejects_missing_raw_and_scope_upgrades(self):
        row,raw=fixture();p=link.validate_load(row,raw,True)
        for case in ('no-raw','missing-end','bad-data','bool-status','drain','delivery','failed-role'):
            bad=copy.deepcopy(p)
            if case=='no-raw':bad['queries'][0]['real_DLI']=None
            elif case=='missing-end':bad['queries'].pop()
            elif case=='bad-data':bad['queries'][0]['real_DLI']['reply']['value']='341200'
            elif case=='bool-status':bad['queries'][0]['real_DLI']['reply']['status']=False
            elif case=='drain':bad['physical_drain_qualified']=True
            elif case=='delivery':bad['application_delivery_qualified']=True
            else:bad['original_role_qualified']=False
            with self.subTest(case=case):self.assertFalse(link.valid_load_summary(bad))

    def test_explicit_profile_boot_and_original_profiles_unchanged(self):
        base=['ws73.socket_benchmark_apps=1','ws73.benchmark_mode=window','ws73.link_measurements=1']
        for paired in (False,True):
            old=service.profile(paired,observe=True,hcc=True)
            self.assertNotIn(link.LOAD_REQUEST,old)
            new=service.profile(paired,observe=True,hcc=True,link_probe=True)
            self.assertEqual(service.from_boot(base+service.boot(new)),new)
            self.assertIn('ws73_link_measurement.py',service.verifiers(new))
            self.assertNotIn('ws73_link_measurement.py',service.verifiers(old))
            for words in (base+service.boot(new)+[link.LOAD_TOKEN],base+[link.LOAD_TOKEN],
                          base[:-1]+service.boot(new)):
                with self.assertRaises(CaptureError):service.from_boot(words)
            bad=copy.deepcopy(new);bad[link.LOAD_REQUEST]['offset_ns']+=1
            with self.assertRaises(CaptureError):service.selected({service.FIELD:bad})
        with self.assertRaises(CaptureError):service.profile(link_probe=True)

    def test_independent_fixed_contract_and_real_selector(self):
        self.assertEqual(link.LOAD_SPEC,dict(version=1,offset_ns=6_000_000_000,max_queries=2,
            kind=1,timeout_ms=5000,child_budget_ns=7_000_000_000))
        args=dict(channel_benchmark='window',channel_benchmark_window=8,channel_benchmark_count=128,
            channel_benchmark_bytes=2042,channel_benchmark_interval_us=None,channel_benchmark_dynamic=True,
            channel_benchmark_active_endpoint=0,channel_benchmark_ssap_owned=True,
            channel_benchmark_credit_observe=True,channel_benchmark_link_probe=True,link_measurements=True)
        self.assertTrue(service.probing_link(service.requested(SimpleNamespace(**args))))
        for change in [dict(channel_benchmark_link_probe=1),dict(link_measurements=False),
                       dict(channel_benchmark_credit_observe=False),dict(channel_benchmark_count=127),
                       dict(channel_benchmark_window=4),dict(channel_benchmark_ssap_owned=False)]:
            with self.subTest(change=change),self.assertRaises(CaptureError):
                service.requested(SimpleNamespace(**(args|change)))

    def test_actual_source_closure_requires_probe_helper_and_explicit_version(self):
        import ws73_socket_benchmark as benchmark
        from ws73_target import HERE,file_record
        names=['ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py',
               'ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py',
               'ws73_target_guest.py','ws73_target_init.sh','ws73_dynamic_channels.py',
               *service.VERIFIERS,*transport.VERIFIERS,'ws73_link_measurement.py']
        package=dict(socket_benchmark_role_contract_version=1,benchmark_trace_contract_version=1,
            benchmark_process_resource_contract_version=1,benchmark_ssap_contract_version=2,
            benchmark_credit_observation_contract_version=1,benchmark_link_probe_contract_version=1,
            inputs=[file_record(HERE/n)for n in dict.fromkeys(names)],application_client_tools=dict(
                sources=[file_record(HERE/n)for n in ('testing/application_client/client.c','testing/application_client/client.py')]))
        benchmark.validate_role_sources(package,dynamic=True,ssap=True,observe=True,link_probe=True)
        for case in ('no-version','bool-version','no-helper','changed-helper','changed-C-source'):
            bad=copy.deepcopy(package)
            if case=='no-version':bad.pop('benchmark_link_probe_contract_version')
            elif case=='bool-version':bad['benchmark_link_probe_contract_version']=True
            elif case=='no-helper':bad['inputs']=[r for r in bad['inputs']if not r['path'].endswith('ws73_link_measurement.py')]
            elif case=='changed-helper':next(r for r in bad['inputs']if r['path'].endswith('ws73_link_measurement.py'))['sha256']='0'*64
            else:bad['application_client_tools']['sources'][0]['sha256']='0'*64
            with self.subTest(case=case),self.assertRaises(ValueError):
                benchmark.validate_role_sources(bad,dynamic=True,ssap=True,observe=True,link_probe=True)

    def test_real_collector_optional_budget_reaps_timeout_without_renewal(self):
        row=transport.collect_process([sys.executable,'-c','import time;time.sleep(10)'],threading.Event(),budget_ns=20_000_000)
        self.assertEqual(row['deadline_monotonic_ns'],row['start_monotonic_ns']+20_000_000)
        self.assertEqual(row['outcome'],'QUERY_TIMEOUT');self.assertTrue(row['reaped'])
        for invalid in (0,True,-1,7_000_000_001):
            with patch.object(transport.subprocess,'Popen')as spawn:
                with self.assertRaises(CaptureError):transport.collect_process([],threading.Event(),budget_ns=invalid)
                spawn.assert_not_called()

    def test_stop_before_due_never_spawns_and_thread_is_joined(self):
        owners=[initial(i)[0]for i in (0,1)]
        with patch('ws73_transport_watch.require_environment'),patch.object(Path,'read_text',return_value=' '.join([
                'ws73.socket_benchmark_apps=1','ws73.benchmark_mode=window','ws73.link_measurements=1',
                *service.boot(service.profile(observe=True,link_probe=True))])):
            def forbidden(*args):raise AssertionError('no query before fixed original due')
            probe=link.LoadProbe(owners,0,time.monotonic_ns(),query_fn=forbidden).start()
            report=probe.close()
        self.assertFalse(probe.thread.is_alive());self.assertTrue(report['thread_joined'])
        self.assertEqual(report['samples'],[]);self.assertEqual(report['unattempted_endpoints'],[0,1])
        self.assertIs(probe.close(),report);self.assertFalse(report['physical_drain_qualified'])

    def test_actual_child_stop_is_not_physical_drain(self):
        stop=threading.Event();timer=threading.Timer(.05,stop.set);timer.start()
        try:row=transport.collect_process([sys.executable,'-c','import time;time.sleep(10)'],stop,budget_ns=7_000_000_000)
        finally:timer.cancel();timer.join()
        self.assertEqual(row['outcome'],'CANCELLED_OBSERVER_STOP');self.assertTrue(row['reaped'])
        self.assertNotIn('observation',row);self.assertNotIn('physical_drain_qualified',row)

    def test_worker_stop_during_actual_child_reaps_and_prevents_second_attempt(self):
        owners=[initial(i)[0]for i in (0,1)];started=threading.Event();calls=[]
        actual_spawn=transport.subprocess.Popen
        def spawn(*args,**kwargs):
            proc=actual_spawn(*args,**kwargs);started.set();return proc
        def query(entry,stop):
            calls.append(entry)
            return transport.collect_process([sys.executable,'-c','import time;time.sleep(10)'],stop,budget_ns=7_000_000_000)
        tokens=['ws73.socket_benchmark_apps=1','ws73.benchmark_mode=window','ws73.link_measurements=1',
                *service.boot(service.profile(observe=True,link_probe=True))]
        actual_read=Path.read_text
        def read(path,*args,**kwargs):
            return ' '.join(tokens)if str(path)=='/proc/cmdline'else actual_read(path,*args,**kwargs)
        with patch('ws73_transport_watch.require_environment'),patch.object(Path,'read_text',read),patch.object(transport.subprocess,'Popen',side_effect=spawn):
            probe=link.LoadProbe(owners,0,time.monotonic_ns()-6_000_000_000,query_fn=query).start()
            try:self.assertTrue(started.wait(1))
            finally:report=probe.close()
        self.assertEqual(len(calls),1);self.assertEqual(report['unattempted_endpoints'],[1])
        self.assertTrue(report['thread_joined']);self.assertFalse(probe.thread.is_alive())
        self.assertEqual(report['samples'][0]['receipt']['outcome'],'CANCELLED_OBSERVER_STOP')
        self.assertTrue(report['samples'][0]['receipt']['reaped']);self.assertFalse(report['physical_drain_qualified'])


if __name__=='__main__':unittest.main()
