"""Verifier negative controls only; fabricated records do not qualify hardware."""
import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_security_agent import ssap_refusals
from ws73_channel_socket import protected_ssap_wire
from ws73_capture import CaptureError
from ws73_target import run_exit_code


def fixture():
    owners=[dict(owner=dict(bus=1,device=n+2,index=n),object=dict(path=f'/test/link{n}',generation=n+1,lifetime=13,handle=1)) for n in range(2)]
    phase=dict(typed_objects=owners)
    stages=dict(current_security_before=[],allocated=[],protected_ssap_refusal=[])
    for entry in owners:
        obj=entry['object'];path=obj['path']
        stages['current_security_before'].append(dict(path=path,wall_ns=10))
        stages['allocated'].append(dict(path=path,start_wall_ns=30))
        stages['protected_ssap_refusal'].append(dict(path=path,wall_ns=20,identity=[obj[k] for k in ['generation','lifetime','handle']],required=2,configured=2,error='org.freedesktop.DBus.Error.Failed',detail='native channel bind: Permission denied (os error 13)'))
    row=dict(mode='numeric-approve',ssap_security_requirement=2,owners=owners,session_start_wall_ns=1,end_wall_ns=100)
    capture=dict(native_events=[dict(bus=1,device=n+2,event=0x11,params='00010001',wall_ns=40,record=n) for n in range(2)])
    packets=[dict(bus=1,device=n+2,handle=1,direction=direction,data='0a0002000203',wall_ns=50) for n in range(2) for direction in ['in','out']]
    return row,phase,stages,capture,packets


class ProtectedSsapEvidence(unittest.TestCase):
    def test_same_frozen_policy_and_both_actual_refusal_shapes(self):
        row,phase,stages,_,_=fixture()
        self.assertEqual(ssap_refusals(row,phase,stages),2)
        for kind in ['missing','duplicate','identity','configured','grade','errno','late','unsupported']:
            r,p,s=copy.deepcopy((row,phase,stages))
            if kind=='missing':s['protected_ssap_refusal'].pop()
            elif kind=='duplicate':s['protected_ssap_refusal'][1]=copy.deepcopy(s['protected_ssap_refusal'][0])
            elif kind=='identity':s['protected_ssap_refusal'][0]['identity'][1]+=1
            elif kind=='configured':s['protected_ssap_refusal'][0]['configured']=0
            elif kind=='grade':r['mode']='approve'
            elif kind=='errno':s['protected_ssap_refusal'][0]['detail']='other failure'
            elif kind=='late':s['protected_ssap_refusal'][0]['wall_ns']=31
            else:r['ssap_security_requirement']=3
            with self.subTest(kind=kind),self.assertRaises(CaptureError):ssap_refusals(r,p,s)

    def test_smtc_wire_requires_real_install_before_each_direction(self):
        row,_,_,capture,packets=fixture()
        proof=protected_ssap_wire(row,capture,packets)
        self.assertEqual(proof['packets'],4)
        for kind in ['missing-install','duplicate-install','wrong-handle','early-rx','early-tx','only-out','other-generation-window','unknown-grade']:
            r,c,p=copy.deepcopy((row,capture,packets))
            if kind=='missing-install':c['native_events'].pop()
            elif kind=='duplicate-install':c['native_events'].append(copy.deepcopy(c['native_events'][0]))
            elif kind=='wrong-handle':c['native_events'][0]['params']='00020001'
            elif kind=='early-rx':p[0]['wall_ns']=39
            elif kind=='early-tx':p[1]['wall_ns']=39
            elif kind=='only-out':p=[v for v in p if v['direction']=='out']
            elif kind=='other-generation-window':r['session_start_wall_ns']=41
            else:r['ssap_security_requirement']=3
            with self.subTest(kind=kind),self.assertRaises(CaptureError):protected_ssap_wire(r,c,p)

    def test_parent_cannot_strip_protected_ssap_business(self):
        record=dict(supervisor_exit=0,status='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS',live_security_agent_requested='numeric-approve',live_ssap_security_requirement=2,
            security_agent_corroboration=dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',phases=[dict(mode='numeric-approve',ssap_security_requirement=2) for _ in range(2)],business_round_trips=8),
            channel_socket_corroboration=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8,proofs=[dict(protected_ssap=dict(required=2,controllers=[{},{}]),ssap_values=[{}],ssap_discovery=[{}]) for _ in range(2)]),ordinary_channel_socket_acceptance=True,qemu_exit=0)
        self.assertEqual(run_exit_code(record),0)
        for kind in ['missing-policy','basic-fallback','missing-values','missing-discovery','one-controller','failed-vm','missing-required-input']:
            r=copy.deepcopy(record)
            if kind=='missing-policy':r['security_agent_corroboration']['phases'][0].pop('ssap_security_requirement')
            elif kind=='basic-fallback':r['channel_socket_corroboration']['proofs'][0]['protected_ssap']['required']=0
            elif kind=='missing-values':r['channel_socket_corroboration']['proofs'][1]['ssap_values']=[]
            elif kind=='missing-discovery':r['channel_socket_corroboration']['proofs'][0]['ssap_discovery']=[]
            elif kind=='one-controller':r['channel_socket_corroboration']['proofs'][0]['protected_ssap']['controllers'].pop()
            elif kind=='missing-required-input':r.pop('live_ssap_security_requirement')
            else:r['qemu_exit']=1
            with self.subTest(kind=kind):self.assertEqual(run_exit_code(r),1)
