# SPDX-License-Identifier: GPL-2.0-only
"""Reject plausible metadata when the active peer wire/state proof is absent."""
import copy
import unittest
from unittest.mock import patch
from test_ws73_management_partial import fixture
from ws73_management_partial import verify_records, corroborate as corroborate_partial
from ws73_management_ready_peer import request,expected_result,ready_bytes,verify,corroborate
from ws73_capture import partial_metadata_bounds,CaptureError
from sparklink.structs import SleControllerSnapshot,SleManagementQuery,SleDiscoveryResult,SleDiscoverySubmit


def ready_fixture(case='release',domain='advertising'):
    r=fixture(case,domain);r.update(format_version=7,selected_domain_cleanup=True,active_ready_peer=True,peer_queries=[])
    if domain=='scanning':r['scan_parameter_cleanup']=True
    s=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(r['final_snapshot']));s.flags=2;r['final_snapshot']=bytes(s).hex()
    result=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(r['final_result']));result.radio_scan=0;r['final_result']=bytes(result).hex()
    peer=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(r['initial_snapshots'][1]));ready=ready_bytes(peer)
    owner=bytes(SleManagementQuery(version=1,generation=2,state=1,mode=1)).hex()
    r.update(peer_after=ready,peer_management_before=owner,peer_management_after=owner)
    activity=dict(ready_snapshot=ready,released_management=bytes(SleManagementQuery(version=1,generation=2)).hex())
    for key,items in [('bootstrap',[(101,5,1,8),(102,6,9,20)]),('before',[(201,3,21,30),(202,4,31,35)]),
                      ('during',[(203,3,210,240)]),('after',[(204,4,420,430),(205,3,440,450),(206,4,460,470)])]:
        activity[key]=[dict(input=bytes(request(peer,i,op)).hex(),result=bytes(expected_result(peer,i,op,6 if op==5 else 0)).hex(),start_wall_ns=a,end_wall_ns=b) for i,op,a,b in items]
    for key,t in [('on_before_cancel',250),('on_after_free',415)]:
        activity[key]=dict(wall_ns=t,snapshot=ready,management=owner,result=activity['during'][0]['result'])
    r['ready_peer']=activity
    wire=dict(commands=[],complete=[])
    for phase in ['bootstrap','before','during','after']:
        for row in activity[phase]:
            inp=SleDiscoverySubmit.from_buffer_copy(bytes.fromhex(row['input']));op=inp.operation
            adv=bytearray(49);adv[12:18]=bytes(peer.address)
            recipe=[(0xc02,adv.hex(),'06'),(0xc05,'00'*5,'')] if op==5 else [(0x1001,'0000010040062003',''),(0x1002,'0100','')]+([(0x1002,'0000','')] if op==6 else []) if op==3 or op==6 else [(0x1002,'0000','')]
            for index,(opcode,params,value) in enumerate(recipe):
                t=row['start_wall_ns']+index*3
                wire['commands'].append(dict(bus=1,device=3,opcode=opcode,params=params,wall_ns=t,record=t,completion=dict(wall_ns=t+1)))
                wire['complete'].append(dict(bus=1,device=3,opcode=opcode,value=value,status=0,wall_ns=t+2,record=t+2))
    return r,peer,wire


class ReadyPeerTests(unittest.TestCase):
    def test_six_canonical_cases_and_fourteen_actual_commands(self):
        for case in ['release','close','dup']:
            for domain in ['advertising','scanning']:
                r,s,wire=ready_fixture(case,domain)
                with self.subTest(case=case,domain=domain):
                    verify_records(r);proof=corroborate(r,s,wire)
                    self.assertEqual(len(proof['proofs']),14)
                    self.assertTrue(proof['active_ready_peer_isolation_case_acceptance'])
                    self.assertFalse(proof['whole_managed_acceptance'])

    def test_metadata_cannot_replace_active_ownership_and_current_on(self):
        for change in ['setup','generation','owner','off-before','off-after','too-early','too-late','diagnostic','missing-release','failed-operation','duplicate-phase','synthetic','old-format']:
            r,s,wire=ready_fixture();p=r['ready_peer']
            if change=='setup':p['ready_snapshot']=r['initial_snapshots'][1]
            if change=='generation':r['peer_after']=r['initial_snapshots'][0]
            if change=='owner':r['peer_management_after']=r['final_management']
            if change.startswith('off-'):
                k='on_before_cancel' if change=='off-before' else 'on_after_free';v=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(p[k]['result']));v.radio_scan=1;p[k]['result']=bytes(v).hex()
            if change=='too-early':p['on_after_free']['wall_ns']=400
            if change=='too-late':p['on_before_cancel']['wall_ns']=300
            if change=='diagnostic':r['peer_queries']=fixture()['peer_queries']
            if change=='missing-release':p['released_management']=r['peer_management_before']
            if change=='failed-operation':p['after'][-1]['result']=r['cancelled']
            if change=='duplicate-phase':p['during'].append(copy.deepcopy(p['during'][0]))
            if change=='synthetic':r['synthetic_support']=True
            if change=='old-format':r['format_version']=6
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(r)

    def test_missing_extra_failed_or_misdirected_wire_is_rejected(self):
        for change in ['missing-stop','extra-stop','failed-reply','wrong-address','unmatched-reply','bad-start','other-device']:
            r,s,w=ready_fixture()
            if change=='missing-stop':w['commands'].pop()
            if change=='extra-stop':w['commands'].insert(8,dict(w['commands'][7],wall_ns=350,record=350,completion=dict(wall_ns=351)))
            if change=='failed-reply':w['complete'][8]['status']=11
            if change=='wrong-address':w['commands'][0]['params']='00'*49
            if change=='unmatched-reply':w['complete'].insert(8,dict(w['complete'][7],wall_ns=350,record=350))
            if change=='bad-start':w['commands'][7]['params']='0200'
            if change=='other-device':w['complete'][8]['device']=2
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(r,s,w)

    def test_bootstrap_metadata_window_and_unrecorded_query(self):
        r,s,w=ready_fixture();identities=[dict(port=f'1-2.1.{4-i}',index=i,generation=i+1,address='00:00:00:00:00:00' if i==0 else '31:32:33:34:35:36',bus=1,device=i+2,observed_wall_ns=600) for i in [0,1]]
        bounds,proofs=partial_metadata_bounds(dict(initial=identities),w,r)
        self.assertEqual(set(bounds.values()),{1});self.assertEqual(len(proofs[0]['proofs']),14)
        for key in ['commands','complete']:
            bad=copy.deepcopy(w);bad[key].append(dict(bus=1,device=2,opcode=0x406,wall_ns=500))
            with self.subTest(key=key),self.assertRaises(CaptureError):partial_metadata_bounds(dict(initial=identities),bad,r)
