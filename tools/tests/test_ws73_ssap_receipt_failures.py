# SPDX-License-Identifier: GPL-2.0-only
"""Production receipt parser with visible process fixtures, not SDK/VM proof."""
from pathlib import Path
import copy,json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_application_client import application_environment,ssap_receipt
from ws73_capture import CaptureError


def fixture(api='c'):
    path='/org/sparklink/slk0_g1/peer_t00_020000000001/link_0000000000000001'
    entry=dict(owner=dict(index=0,generation=1),object=dict(path=path))
    expected=bytes(range(32)).hex();operation='ssap-read'
    prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    app=dict(environment=application_environment(),exit=0,stderr='',api=api,
        credentials=dict(uids=[1004]*4,gids=[1004]*4,groups=[],capabilities={k:'0'*16 for k in('CapEff','CapPrm','CapAmb','CapInh')}),
        ssap_operation=operation,ssap_path=path,ssap_handle=17,ssap_expected=expected,
        stdout=json.dumps(dict(stage='ssap_start_barrier',api=api,client_closed=True))+'\n'+f'SsapPeerValue: operation={operation} path={path} handle=17 value={expected}\n',
        args=prefix+['ssap','0','1',path,operation,'17',expected])
    return app,entry


class ReceiptFailures(unittest.TestCase):
    def test_original_successful_c_and_python_receipts_remain_strict(self):
        for api in('c','python'):
            app,entry=fixture(api);ssap_receipt(app,entry,expected_uid=1004)
            for change in(dict(stdout='pretend success'),dict(args=app['args'][:-1])):
                with self.subTest(api=api,change=change),self.assertRaises(CaptureError):
                    ssap_receipt(app|change,entry,expected_uid=1004)

    def test_process_errors_do_not_claim_environment_fault_or_edit_receipt(self):
        for code in(1,-9,'timeout','0',False,True,None):
            app,entry=fixture();app.update(exit=code,stderr='retained original remote timeout detail')
            before=copy.deepcopy(app)
            with self.subTest(code=code),self.assertRaisesRegex(CaptureError,'consumer process failed'):
                ssap_receipt(app,entry,expected_uid=1004)
            self.assertEqual(app,before)

    def test_environment_and_stderr_have_distinct_failures(self):
        app,entry=fixture();bad=app|dict(environment={})
        with self.assertRaisesRegex(CaptureError,'SDK environment'):ssap_receipt(bad,entry,expected_uid=1004)
        for stderr in('warning',None,[]):
            with self.subTest(stderr=stderr),self.assertRaisesRegex(CaptureError,'stderr rejected'):
                ssap_receipt(app|dict(stderr=stderr),entry,expected_uid=1004)


if __name__=='__main__':unittest.main()
