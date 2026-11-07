# SPDX-License-Identifier: GPL-2.0-only
"""Collector budgets/receipt fixtures; no kernel concurrency or WS73 proof."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ws73_session_service import fixture
from ws73_session_service import FULL_LOAD_PROFILE,PROFILE_TOKEN,collector_boot,collector_limits,trace_bytes,parse,summary
from ws73_trace_layout import buffer_kib


def full_fixture():
    text,row,owners,capture=fixture()
    row.update(collector_contract_version=2,collector_profile=dict(FULL_LOAD_PROFILE),requested_buffer_kb=8192)
    row['readbacks']['buffer_size_kb']=str(buffer_kib(row['header_page'],8192,4)[0])
    return text,row,owners,capture


class SessionCollectorProfile(unittest.TestCase):
    def test_explicit_profile_preserves_legacy_and_carries_exact_summary(self):
        text,row,_,_=fixture();self.assertNotIn('collector_profile',parse(text,row))
        self.assertEqual(collector_limits(row)['requested_buffer_kb'],2048)
        text,row,_,_=full_fixture();p=parse(text,row)
        self.assertEqual(summary(p)['collector_profile'],FULL_LOAD_PROFILE)
        self.assertEqual(collector_boot([PROFILE_TOKEN+'full-load-v2']),FULL_LOAD_PROFILE)
        self.assertIsNone(collector_boot(['unrelated=1']))

    def test_profile_cannot_reclassify_or_hide_losses_and_budget_failure(self):
        text,row,_,_=full_fixture()
        for kind in ['version','missing-profile','missing-version','old-buffer','changed-text-limit','unknown','loss','truncated','budget-type','events']:
            r=copy.deepcopy(row)
            if kind=='version':r['collector_contract_version']=True
            elif kind=='missing-profile':r.pop('collector_profile')
            elif kind=='missing-version':r.pop('collector_contract_version')
            elif kind=='old-buffer':r['requested_buffer_kb']=2048
            elif kind=='changed-text-limit':r['collector_profile']['text_limit_bytes']+=1
            elif kind=='unknown':r['collector_profile']['name']='unknown'
            elif kind=='loss':r['stats']['cpu0']=r['stats']['cpu0'].replace('overrun: 0','overrun: 1',1)
            elif kind=='truncated':r['trace_budget_exceeded']=True
            elif kind=='budget-type':r['trace_budget_exceeded']=0
            else:r['stats']['cpu0']=r['stats']['cpu0'].replace('entries: 10','entries: 100003')
            with self.subTest(kind=kind),self.assertRaises(ValueError):parse(text,r)
        for values in [[PROFILE_TOKEN+'unknown'],[PROFILE_TOKEN+'full-load-v2']*2,[PROFILE_TOKEN+'']]:
            with self.subTest(boot=values),self.assertRaises(ValueError):collector_boot(values)

    def test_actual_file_read_is_bounded_before_hash_or_parser(self):
        _,row,_,_=full_fixture();limit=FULL_LOAD_PROFILE['text_limit_bytes']
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'trace'
            with path.open('wb')as stream:stream.truncate(limit+1)
            with self.assertRaisesRegex(ValueError,'byte budget'):trace_bytes(path,row)
            path.write_bytes(b'actual bounded bytes')
            self.assertEqual(trace_bytes(path,row),path.read_bytes())
        class Stream:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,count):
                self.count=count
                return b''
        stream=Stream()
        with patch.object(Path,'open',return_value=stream):self.assertEqual(trace_bytes(Path('fixture'),row),b'')
        self.assertEqual(stream.count,limit+1)

    def test_finalizer_requires_matching_requested_boot_and_observed_profile(self):
        from ws73_target import run_exit_code
        good=dict(status='PASSTHROUGH_SUPPORT_PASS',supervisor_exit=0,qemu_exit=0,
            session_service_observation_requested=True,session_service_acceptance=True,
            session_service_collector_contract_version=2,session_service_collector_profile=dict(FULL_LOAD_PROFILE),
            qemu_args=[PROFILE_TOKEN+'full-load-v2'],session_service_observation=dict(
                status='REAL_SESSION_SERVICE_AND_USB_SUBMITS_CORROBORATED',services=2,attempts=2,
                accepted_usb_packets=2,operations=2,collector_contract_version=2,collector_profile=dict(FULL_LOAD_PROFILE)))
        self.assertEqual(run_exit_code(good),0)
        for kind in ['request','version','proof','proof-version','boot','duplicate-boot','not-observing','requested-type','changed-profile']:
            r=copy.deepcopy(good)
            if kind=='request':r.pop('session_service_collector_contract_version')
            elif kind=='version':r['session_service_collector_contract_version']=True
            elif kind=='proof':r['session_service_observation'].pop('collector_profile')
            elif kind=='proof-version':r['session_service_observation']['collector_contract_version']=True
            elif kind=='boot':r['qemu_args']=[]
            elif kind=='duplicate-boot':r['qemu_args']*=2
            elif kind=='not-observing':r['session_service_observation_requested']=False
            elif kind=='requested-type':r['session_service_observation_requested']=1
            else:r['session_service_collector_profile']['event_limit']=100001
            with self.subTest(kind=kind):self.assertEqual(run_exit_code(r),1)

    def test_invalid_request_is_rejected_before_preparation_and_devices(self):
        import ws73_target
        for fields in [dict(),dict(session_service_observe=True,session_service_profile='unknown')]:
            with tempfile.TemporaryDirectory()as directory:
                args=SimpleNamespace(command='run',output=Path(directory)/'absent',**(dict(session_service_profile='full-load-v2')|fields))
                with patch.object(ws73_target,'ordinary_identity'),patch.object(ws73_target,'prepared')as prepare,self.assertRaisesRegex(ValueError,'Session service profile'):
                    ws73_target._run(args)
                prepare.assert_not_called();self.assertFalse(args.output.exists())
