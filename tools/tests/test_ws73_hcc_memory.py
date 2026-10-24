# SPDX-License-Identifier: GPL-2.0-only
"""Actual parser/collector and local children; sysfs/USB/kernel concurrency not run."""
import copy
import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_hcc_memory as hcc
import ws73_benchmark_ssap as service
import ws73_transport_watch as watch
from ws73_capture import CaptureError
from test_ws73_transport_watch import fixture as old_fixture


def data(entry, start, end, *, uid=0, disabled=0, error=None, raw=123):
    row=dict(path=hcc.path_for(entry),uid=uid,mode=0o400,disabled_errno=disabled,
             start_ns=start,end_ns=end)
    if disabled:row.update(status='SKIPPED_AFTER_ERROR',errno=disabled)
    elif error is not None:row.update(status='ERROR',errno=error)
    else:
        o=entry['owner']
        row.update(status='READ',data=f"source=SDK_USB_CLASS_5 id={o['index']} generation={o['generation']} raw_le32={raw} start_ns={start} end_ns={end} semantics_verified=0\n")
    return json.dumps(row)+'\n'


def fixture():
    row=old_fixture();row[hcc.FIELD]=row.pop(watch.FIELD)
    for i,(entry,sample)in enumerate(zip(row['owners'],row[hcc.FIELD]['samples'])):
        entry['owner']['port']=f'1-{i+1}'
        r=sample['receipt'];r.pop('values');r['outcome']='EXITED'
        r['args']=hcc.command(entry);r['credentials']['uids']=[0]*4;r['credentials']['gids']=[0]*4
        r['stdout']=data(entry,r['start_monotonic_ns']+1,r['end_monotonic_ns']-1)
        probe=copy.deepcopy(r);probe.update(start_monotonic_ns=r['start_monotonic_ns']-10,
                end_monotonic_ns=r['start_monotonic_ns']-1,pid=r['pid']+10,
                deadline_monotonic_ns=r['start_monotonic_ns']-10+watch.SPEC['query_budget_ns'],exit=1)
        probe['credentials']['uids']=[1000]*4;probe['credentials']['gids']=[1000]*4
        probe['stdout']=data(entry,probe['start_monotonic_ns']+1,probe['end_monotonic_ns']-1,uid=1000,error=errno.EACCES)
        r['access_probe']=probe
    return row


class RawObservationContract(unittest.TestCase):
    def test_original_fixed_query_only_and_zero_is_raw_not_credit(self):
        row=fixture();proof=hcc.validate(row,True)
        self.assertTrue(hcc.valid_summary(proof))
        self.assertEqual([s['reads']for s in proof['endpoints']],[1,1])
        for raw in (0,2**32-1):
            r=row[hcc.FIELD]['samples'][0]['receipt']
            r['stdout']=data(row['owners'][0],301,309,raw=raw)
            value=hcc.decoded(r,row['owners'][0])['raw_observation']
            self.assertEqual(value['raw_le32'],raw)
            self.assertFalse(value['semantics_verified'])
        for key in ('semantics_verified','credit_truth_qualified','physical_drain_qualified','performance_qualified'):
            bad=copy.deepcopy(proof);bad[key]=True
            self.assertFalse(hcc.valid_summary(bad))

    def test_first_error_and_later_real_skip_without_second_read(self):
        row=fixture();report=row[hcc.FIELD];r=report['samples'][0]['receipt']
        r['stdout']=data(row['owners'][0],301,309,error=errno.EPIPE);r['exit']=1
        sample=copy.deepcopy(report['samples'][0]);sample.update(pair=1,planned_monotonic_ns=1_000_000_100)
        receipt=sample['receipt'];receipt.pop('access_probe')
        receipt.update(start_monotonic_ns=1_000_000_200,end_monotonic_ns=1_000_000_210,
                       deadline_monotonic_ns=2_250_000_200,start_wall_ns=1_000_010_200,
                       end_wall_ns=1_000_010_210,exit=0,args=hcc.command(row['owners'][0],errno.EPIPE),
                       stdout=data(row['owners'][0],1_000_000_201,1_000_000_209,disabled=errno.EPIPE))
        report['samples'].append(sample);report.update(stop_monotonic_ns=1_000_000_300,
            end_monotonic_ns=1_000_000_400,stop_wall_ns=1_000_010_300,end_wall_ns=1_000_010_400)
        row['end_wall_ns']=1_000_010_500
        proof=hcc.validate(row,True)
        self.assertEqual(proof['endpoints'][0],dict(disabled=errno.EPIPE,reads=0,errors=1,skipped=1,probed=True))
        self.assertTrue(hcc.valid_summary(proof))
        # A successful retry after the original error is forbidden, even if
        # it reports a plausible raw word and the business path later passes.
        receipt.update(args=hcc.command(row['owners'][0]),stdout=data(row['owners'][0],1_000_000_201,1_000_000_209))
        with self.assertRaises(CaptureError):hcc.validate(row,True)

    def test_negative_identities_permissions_raw_and_collection(self):
        cases=('unrequested','missing','root','groups','probe-missing','probe-success','probe-late','probe-unreaped',
               'wrong-path','short','new-generation','out-of-range','verified','future-clock','error-with-data',
               'zero-error','timeout','float-mode','unjoined','oldphase','changed-spec','lost-slot')
        for case in cases:
            row=fixture();report=row[hcc.FIELD];r=report['samples'][0]['receipt'];entry=row['owners'][0]
            raw=json.loads(r['stdout'])
            if case=='missing':row.pop(hcc.FIELD)
            elif case=='root':r['credentials']['uids']=[1000]*4
            elif case=='groups':r['credentials']['groups']=[10]
            elif case=='probe-missing':r.pop('access_probe')
            elif case=='probe-success':r['access_probe']['stdout']=data(entry,291,299,uid=1000)
            elif case=='probe-late':r['access_probe']['end_monotonic_ns']=301
            elif case=='probe-unreaped':r['access_probe']['reaped']=False
            elif case=='wrong-path':r['args'][-2]='/sys/bus/usb/devices/1-3:1.0/hcc_memory_observation'
            elif case=='short':raw['data']='0000'
            elif case=='new-generation':raw['data']=raw['data'].replace('generation=7','generation=8')
            elif case=='out-of-range':raw['data']=raw['data'].replace('raw_le32=123','raw_le32=4294967296')
            elif case=='verified':raw['data']=raw['data'].replace('semantics_verified=0','semantics_verified=1')
            elif case=='future-clock':raw['end_ns']=311
            elif case=='error-with-data':raw.update(status='ERROR',errno=errno.EPIPE);r['exit']=1
            elif case=='zero-error':raw.pop('data');raw.update(status='ERROR',errno=0);r['exit']=1
            elif case=='timeout':r['outcome']='QUERY_TIMEOUT'
            elif case=='float-mode':raw['mode']=256.0
            elif case=='unjoined':report['thread_joined']=False
            elif case=='oldphase':report['phase']=1
            elif case=='changed-spec':report['spec']['max_pairs']=1
            elif case=='lost-slot':report['unattempted_pairs']=[0]
            r['stdout']=json.dumps(raw)+'\n'
            with self.subTest(case=case),self.assertRaises((CaptureError,KeyError,ValueError)):
                hcc.validate(row,case!='unrequested')

    def test_failed_role_never_gets_normal_summary(self):
        row=fixture();row.update(status='FAIL',error='original failure')
        with self.assertRaises(CaptureError):hcc.validate(row,True)
        proof=hcc.validate(row,True,failed=True)
        self.assertFalse(hcc.valid_summary(proof))

    def test_profile_and_boot_cannot_enable_implicitly(self):
        base=['ws73.socket_benchmark_apps=1','ws73.benchmark_mode=window']
        for duplex in (False,True):
            old=service.profile(duplex,observe=True)
            self.assertNotIn(hcc.TOKEN,service.boot(old))
            new=service.profile(duplex,observe=True,hcc=True)
            self.assertEqual(service.from_boot(base+service.boot(new)),new)
            self.assertTrue(set(hcc.VERIFIERS)<=set(service.verifiers(new)))
            bad=copy.deepcopy(new);bad[hcc.REQUEST]['semantics_verified']=False
            with self.assertRaises(CaptureError):service.selected({service.FIELD:bad})
        for words in (base+[hcc.TOKEN],base+[service.TOKEN,hcc.TOKEN],
                      base+[service.TOKEN+'-credit',hcc.TOKEN,hcc.TOKEN]):
            with self.subTest(words=words),self.assertRaises(CaptureError):service.from_boot(words)

    def test_actual_reader_does_not_open_disabled_file(self):
        # Local owned regular-file fixture, never a host USB/sysfs access.
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'counter';path.write_text('fixture');path.chmod(0o400)
            for disabled in (0,errno.EPIPE):
                r=watch.collect_process([sys.executable,'-c',hcc.READER,str(path),str(disabled)],threading.Event())
                self.assertTrue(r['reaped']);self.assertEqual(r['exit'],0)
                actual=json.loads(r['stdout'])
                if disabled:self.assertEqual(actual['status'],'SKIPPED_AFTER_ERROR');self.assertNotIn('data',actual)
                else:self.assertEqual(actual['data'],'fixture')
            path.chmod(0o444)
            r=watch.collect_process([sys.executable,'-c',hcc.READER,str(path),'0'],threading.Event())
            self.assertEqual(r['exit'],1);self.assertNotIn('data',json.loads(r['stdout']))

    def test_actual_observer_selector_and_first_error_disable_following_query(self):
        row=fixture();entry=row['owners'][0];root=copy.deepcopy(row[hcc.FIELD]['samples'][0]['receipt'])
        denied=root.pop('access_probe')
        root.update(exit=1,stdout=data(entry,301,309,error=errno.EPIPE))
        skipped=copy.deepcopy(root)
        skipped.update(exit=0,args=hcc.command(entry,errno.EPIPE),stdout=data(entry,301,309,disabled=errno.EPIPE))
        tokens='ws73.socket_benchmark_apps=1 ws73.benchmark_mode=window '+service.TOKEN+'-credit '+hcc.TOKEN
        fake=SimpleNamespace(start=lambda:None)
        with patch.object(hcc,'require_environment'),patch.object(Path,'read_text',return_value=tokens),\
             patch.object(hcc,'Watch',return_value=fake)as make,\
             patch.object(hcc,'collect_process',side_effect=[denied,root,skipped])as collect:
            hcc.observer(row['owners'],0)
            query=make.call_args.kwargs['query_fn']
            self.assertEqual(query(entry,threading.Event())['exit'],1)
            self.assertEqual(query(entry,threading.Event())['exit'],0)
            self.assertEqual([call.args[0][-1]for call in collect.call_args_list],['0','0',str(errno.EPIPE)])
            self.assertIs(collect.call_args_list[1].kwargs['identity_reader'],hcc.root_identity)
        for words in (tokens.replace(hcc.TOKEN,''),tokens.replace(service.TOKEN+'-credit','')):
            with patch.object(hcc,'require_environment'),patch.object(Path,'read_text',return_value=words),\
                 patch.object(hcc,'Watch')as make,self.assertRaises(CaptureError):
                hcc.observer(row['owners'],0)
            make.assert_not_called()

    def test_fresh_prepared_contract_and_source_hash_are_required(self):
        from ws73_target import HERE,file_record
        from ws73_socket_benchmark import validate_role_sources
        names=('ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py',
               'ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py',
               'ws73_target_guest.py','ws73_target_init.sh','ws73_dynamic_channels.py',*service.VERIFIERS,*watch.VERIFIERS,*hcc.VERIFIERS)
        package=dict(socket_benchmark_role_contract_version=1,benchmark_trace_contract_version=1,
                     benchmark_process_resource_contract_version=1,benchmark_ssap_contract_version=2,
                     benchmark_credit_observation_contract_version=1,benchmark_hcc_observation_contract_version=1,
                     inputs=[file_record(HERE/n)for n in dict.fromkeys(names)],
                     application_client_tools=dict(sources=[file_record(HERE/n)for n in
                                                          ('testing/application_client/client.c','testing/application_client/client.py')]))
        validate_role_sources(package,dynamic=True,ssap=True,observe=True,hcc=True)
        for kind in ('missing','bool','stale','no-observe'):
            bad=copy.deepcopy(package)
            if kind=='missing':bad.pop('benchmark_hcc_observation_contract_version')
            elif kind=='bool':bad['benchmark_hcc_observation_contract_version']=True
            elif kind=='stale':next(v for v in bad['inputs']if v['path'].endswith('ws73_hcc_memory.py'))['sha256']='0'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                validate_role_sources(bad,dynamic=True,ssap=True,observe=kind!='no-observe',hcc=True)
        args=SimpleNamespace(channel_benchmark_ssap_owned=False,channel_benchmark_hcc_memory_observe=True)
        with self.assertRaises(CaptureError):service.requested(args)


if __name__=='__main__':unittest.main()
