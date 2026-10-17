# SPDX-License-Identifier: GPL-2.0-only
"""Verifier fixtures only, no controller/device or qualification produced."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_application_client import corroborate, valid_summary, application_environment
from ws73_capture import CaptureError
from ws73_target import run_exit_code
import ws73_target as target


def fixture():
    rows=[];sdus=[]
    for n in range(2):
        owners=[dict(owner=dict(index=i,generation=10+i,bus=1,device=2+i),object=dict(generation=10+i,lifetime=n+1,handle=i+3)) for i in range(2)]
        request=n.to_bytes(4,'little')+bytes([10+n])*57;reply=n.to_bytes(4,'little')+bytes([20+n])*57
        apps=[]
        for i in [0,1]:
            api=(['c','python'] if n==0 else ['python','c'])[i];owner,obj=owners[i]['owner'],owners[i]['object']
            ready=dict(stage='ready',api=api,index=i,generation=owner['generation'],lifetime=obj['lifetime'],handle=obj['handle'],dup_alive=True,client_closed=True)
            sent,received=(reply,request) if i else (request,reply)
            complete=dict(stage='complete',api=api,sent=sent.hex(),received=received.hex(),last_close_rebind='NotSupported')
            apps.append(dict(position=i,api=api,environment=application_environment(),stdout=json.dumps(ready)+'\n'+json.dumps(complete)+'\n',stderr='',exit=0,credentials=dict(uids=[1000]*4,capabilities={k:'0' for k in ['CapEff','CapPrm','CapAmb','CapInh']})))
        row=dict(phase=n,owners=owners,request=request.hex(),reply=reply.hex(),applications=apps,start_wall_ns=100+n*100,end_wall_ns=199+n*100,status='APPLICATION_CLIENT_EVIDENCE_PENDING')
        rows.append(row)
        for source,target,payload in [(0,1,request),(1,0,reply)]:
            frame=(b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload).hex()
            for i,direction in [(source,'out'),(target,'in')]:
                sdus.append(dict(bus=1,device=2+i,handle=3+i,direction=direction,data=frame,wall_ns=150+n*100))
    return dict(application_clients=rows),sdus


class ApplicationClientEvidence(unittest.TestCase):
    def test_private_image_has_explicit_sdk_path_without_host_native_fallback(self):
        env=application_environment(Path('/private-image'))
        self.assertEqual(env['PYTHONPATH'],'/private-image/usr/share/sparklink/python:/private-image/usr/share/sparklink/tools')
        self.assertEqual(env['LIBSPARKLINK_PATH'],'/private-image/usr/lib/libsparklink.so.0')
        self.assertNotIn('LIBSLK_NATIVE_PATH',env)

    def test_actual_runner_preflight_reaches_verified_profile_before_guest_or_usb(self):
        # Only external identity, prepared-package verification and host inventory
        # are fixtures. Execute the real CLI parser/preflight/final verdict.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared=root/'prepared';prepared.mkdir();(prepared/'manifest.json').write_text('{}')
            output=root/'run'
            argv=['ws73_target.py','run','--prepared',str(prepared),'--output',str(output),'--ports','1-2.1.2','1-2.1.3','--qmp-hotplug','--connection-verify','--connection-advertising','negotiable-t','--application-client-verify']
            with patch.object(sys,'argv',argv),patch('ws73_target.run',target._run),patch('ws73_target.ordinary_identity'),patch('ws73_target.prepared',return_value={}),patch('ws73_target.lab_module',return_value=SimpleNamespace(inventory=lambda:[])),patch('ws73_target.subprocess.Popen') as guest:
                self.assertEqual(target.main(),1)
                guest.assert_not_called()
            result=json.loads((output/'manifest.json').read_text())
            self.assertEqual(result['error'],'application clients require the verified native VM profile')
            self.assertEqual(result['status'],'FAIL')

    def test_explicit_fixture_positive_and_full_terminal_shape(self):
        run,sdus=fixture()
        with patch('ws73_application_client.reassemble_acb',return_value=sdus):proof=corroborate(run,{})
        self.assertTrue(valid_summary(proof))
        record=dict(application_client_verification_requested=True,application_client_acceptance=True,application_client_corroboration=proof,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0)
        self.assertEqual(run_exit_code(record),0)
        for key in ['application_client_verification_requested','application_client_acceptance','application_client_corroboration']:
            bad=copy.deepcopy(record);bad.pop(key)
            with self.subTest(key=key):self.assertEqual(run_exit_code(bad),1)
        bad=copy.deepcopy(record);bad['application_client_corroboration']['proofs'][0]['legs'].pop();self.assertEqual(run_exit_code(bad),1)
        bad=copy.deepcopy(record);bad['qemu_exit']=1;self.assertEqual(run_exit_code(bad),1)

    def test_missing_changed_duplicate_and_wrong_lifetime_rejected(self):
        def mutate(name,run,sdus):
            if name=='missing-peer':sdus.pop()
            elif name=='changed-payload':sdus[0]['data']='00'
            elif name=='duplicate-capture':sdus.append(sdus[0])
            elif name=='stale-handle':sdus[0]['handle']=99
            elif name=='truncated-app':run['application_clients'][0]['applications'][0]['stdout']='{}\n'
            elif name=='wrong-lifetime':
                app=run['application_clients'][0]['applications'][0];parts=app['stdout'].splitlines();ready=json.loads(parts[0]);ready['lifetime']=99;app['stdout']=json.dumps(ready)+'\n'+parts[1]+'\n'
            elif name=='root':run['application_clients'][0]['applications'][0]['credentials']['uids']=[0]*4
            elif name=='inherited-cap':run['application_clients'][0]['applications'][0]['credentials']['capabilities']['CapInh']='1'
            elif name=='diagnostic':run['application_clients'][0]['applications'][0]['stderr']='unexpected warning'
            elif name=='missing-phase':run['application_clients'].pop()
            elif name=='failure':run['application_clients'][0]['applications'][0]['exit']=1
            elif name=='echo':run['application_clients'][0]['reply']=run['application_clients'][0]['request']
        for name in ['missing-peer','changed-payload','duplicate-capture','stale-handle','truncated-app','wrong-lifetime','root','inherited-cap','diagnostic','missing-phase','failure','echo']:
            run,sdus=fixture();mutate(name,run,sdus)
            with self.subTest(name=name),patch('ws73_application_client.reassemble_acb',return_value=sdus),self.assertRaises(CaptureError):corroborate(run,{})
