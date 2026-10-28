# SPDX-License-Identifier: GPL-2.0-only
"""Actual gate/verdict functions with explicitly synthetic existing USB fixtures."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ws73_application_discovery as old_fixture
from ws73_application_discovery import (corroborate, valid_summary, reader_args, validate_sdk_clients,
                                        SDK_CLIENT_PATHS, boot_case, validate_request)
from ws73_application_client import application_environment
from ws73_capture import CaptureError


def fixture():
    run,capture=old_fixture.fixture()
    clients={name:dict(path=path,sha256='c'*64) for name,path in SDK_CLIENT_PATHS.items()}
    for phase,row in enumerate(run['application_discovery']):
        for source in (row['request'],row['supervision']):source.update(termination='sdk-release',clients=copy.deepcopy(clients))
        for n,app in enumerate(row['supervision']['readers']):
            app['args']=reader_args(row['request'],n);app['environment']=application_environment()
    return run,capture


class DiscoverySdkGate(unittest.TestCase):
    def test_existing_two_role_usb_oracle_accepts_explicit_sdk_case(self):
        run,capture=fixture();proof=corroborate(run,capture)
        self.assertEqual(proof['status'],'SDK_EXPLICIT_RELEASE_TWO_ROLE_USB_CORROBORATED')
        self.assertTrue(valid_summary(proof));self.assertEqual(len(proof['phases']),2)
        self.assertEqual(boot_case(['ws73.application_discovery=1','ws73.application_discovery_case=sdk-release']),'sdk-release')
        for phase,row in enumerate(run['application_discovery']):
            validate_request(row['request'],phase)
            self.assertEqual(reader_args(row['request'],0)[:2],['/bin/ws73-application-client-c','discovery'])
            self.assertEqual(reader_args(row['request'],1)[:2],['/bin/python3',SDK_CLIENT_PATHS['python']])

    def test_arbitrary_binary_missing_sdk_and_other_caller_environment_reject(self):
        original,capture=fixture()
        for case in ['arbitrary','missing','hash','environment','argv','old-case','last-stop']:
            run=copy.deepcopy(original);row=run['application_discovery'][0];source=row['request'];supervisor=row['supervision']
            if case=='arbitrary':source['clients']['c']['path']='/bin/sh';supervisor['clients']=copy.deepcopy(source['clients'])
            elif case=='missing':source['clients'].pop('library');supervisor['clients']=copy.deepcopy(source['clients'])
            elif case=='hash':source['clients']['python']['sha256']='bad';supervisor['clients']=copy.deepcopy(source['clients'])
            elif case=='environment':supervisor['readers'][1]['environment']={}
            elif case=='argv':supervisor['readers'][0]['args'][-1]='000000000000'
            elif case=='old-case':source.pop('termination');supervisor.pop('termination')
            else:supervisor['readers'][1]['stdout']=supervisor['readers'][1]['stdout'].replace('confirmed=true','confirmed=false')
            with self.subTest(case=case),self.assertRaises(CaptureError):corroborate(run,capture)

    def test_fixed_inputs_require_sealed_regular_files(self):
        clients={name:dict(path=p,sha256='a'*64) for name,p in SDK_CLIENT_PATHS.items()}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CaptureError):validate_sdk_clients(clients,Path(tmp),[])
        proof=corroborate(*fixture());proof.pop('clients');self.assertFalse(valid_summary(proof))
        with self.assertRaises(CaptureError):boot_case(['ws73.application_discovery_case=sdk-release'])
