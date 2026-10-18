# SPDX-License-Identifier: GPL-2.0-only
import copy
import unittest
from test_ws73_management_queued import confirmed_fixture,confirmed_capture
from ws73_management_ready_peer import request,expected_result
from ws73_management_queued import verify_records,corroborate
from sparklink.structs import SleControllerSnapshot,SleManagementQuery,SleDiscoveryResult,SleDiscoverySubmit


def fixture():
    r=confirmed_fixture();r.update(format_version=4,ready_peer=True,synthetic_support=False,status='QUEUED_CONFIRMED_OFF_INITIALIZE_RELEASE_LIVE_PASS',peer_activities=[],peer_releases=[])
    cap=confirmed_capture(r)
    for values in [cap['commands'],cap['complete']]:
        for row in values:row['record']=row['wall_ns']
    for n,c in enumerate(r['cases']):
        index=c['peer_index'];generation=c['peer_generation'];snap=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(r['initial_snapshots'][index]))
        held=bytes(SleManagementQuery(version=1,generation=generation,state=1,mode=1)).hex()
        radio=bytes(SleDiscoveryResult(version=1,generation=generation,dev_index=index,profile=1,radio_adv=1,radio_scan=2)).hex()
        c.update(peer_writer_fd=8,peer_lease=n+10,peer_during_wall_ns=c['critical_start_ns']+1)
        for phase in ['before','during','after']:c['peer_management_'+phase]=held;c['peer_radio_'+phase]=radio
        for phase,op in enumerate([3,4,3,4]):
            start=c['start_wall_ns']-100_000_000 if phase==0 else c['end_wall_ns']+100_000_000+phase*1000
            row=dict(peer_activity=True,index=index,case_index=n,phase=phase,start_wall_ns=start,end_wall_ns=start+20,
                input=bytes(request(snap,2000+n*4+phase,op)).hex(),result=bytes(expected_result(snap,2000+n*4+phase,op)).hex())
            r['peer_activities'].append(row)
            recipe=[(0x1001,'0000010040062003'),(0x1002,'0100')] if op==3 else [(0x1002,'0000')]
            for i,(opcode,params) in enumerate(recipe):
                t=start+i*3
                cap['commands'].append(dict(bus=1,device=index+2,opcode=opcode,params=params,wall_ns=t,record=t,completion=dict(wall_ns=t+1)))
                cap['complete'].append(dict(bus=1,device=index+2,opcode=opcode,value='',status=0,wall_ns=t+2,record=t+2))
        r['peer_releases'].append(dict(peer_release=True,case_index=n,wall_ns=start+30,management=bytes(SleManagementQuery(version=1,generation=generation)).hex()))
    for key in ['commands','complete']:cap[key].sort(key=lambda v:v['wall_ns'])
    return r,cap


class QueueReadyPeerTests(unittest.TestCase):
    def test_both_roles_six_cases_exact_quiet_and_real_activity(self):
        r,w=fixture();verify_records(r);proof=corroborate(r,w)
        self.assertTrue(proof['active_ready_peer_isolation_acceptance'])
        self.assertEqual(len(proof['bootstrap']),10);self.assertEqual(len(proof['ready_peer_activity']['commands']),36)
        self.assertEqual(len(proof['ready_peer_activity']['quiet_intervals']),6)
        self.assertFalse(proof['normal_scheduler_concurrency_acceptance'])
        self.assertFalse(proof['ready_peer_activity']['whole_managed_acceptance'])

    def test_owner_on_role_scope_and_real_operation_cannot_be_faked(self):
        for change in ['owner','on','generation','descriptor','lease','during-time','missing-phase','wrong-phase','wrong-request','failed-start','early-stop','held-release','synthetic','unknown','old-format']:
            r,w=fixture();c=r['cases'][0];a=r['peer_activities'][0]
            if change=='owner':c['peer_management_during']=c['free']
            if change in ['on','generation']:
                v=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(c['peer_radio_after']));setattr(v,'radio_scan' if change=='on' else 'generation',1 if change=='on' else 999);c['peer_radio_after']=bytes(v).hex()
            if change=='descriptor':c['peer_writer_fd']=-1
            if change=='lease':c['peer_lease']=0
            if change=='during-time':c['peer_during_wall_ns']=c['critical_end_ns']
            if change=='missing-phase':r['peer_activities'].pop()
            if change=='wrong-phase':a['phase']=1
            if change=='wrong-request':a['input']=r['peer_activities'][2]['input']
            if change=='failed-start':v=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(a['result']));v.state=4;v.error=-5;a['result']=bytes(v).hex()
            if change=='early-stop':r['peer_activities'][1]['start_wall_ns']=c['start_wall_ns']+1
            if change=='held-release':r['peer_releases'][0]['management']=c['peer_management_after']
            if change=='synthetic':r['synthetic_support']=True
            if change=='unknown':r['confirmed_off']=False
            if change=='old-format':r['format_version']=3
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(r)

    def test_quiet_window_and_gaps_reject_unrecorded_or_failed_traffic(self):
        for change in ['quiet-command','quiet-complete','gap-command','gap-complete','gap-failure','extra-peer-stop','missing-peer-stop','wrong-start-param','failed-peer-reply','wrong-device']:
            r,w=fixture();c=r['cases'][0]
            if change=='quiet-command':w['commands'].append(dict(bus=1,device=2,opcode=0xc02,wall_ns=c['start_wall_ns']+100))
            if change=='quiet-complete':w['complete'].append(dict(bus=1,device=3,opcode=0x1002,wall_ns=c['start_wall_ns']+100))
            if change=='gap-command':w['commands'].append(dict(bus=1,device=2,opcode=0x406,wall_ns=c['end_wall_ns']+20))
            if change=='gap-complete':w['complete'].append(dict(bus=1,device=3,opcode=0x406,status=0,value='',record=c['end_wall_ns']+20,wall_ns=c['end_wall_ns']+20))
            if change=='gap-failure':w['failures'].append(dict(bus=1,device=3,wall_ns=c['end_wall_ns']+20))
            if change=='extra-peer-stop':w['commands'].append(copy.deepcopy(w['commands'][12]))
            if change=='missing-peer-stop':w['commands'].pop(12)
            if change=='wrong-start-param':w['commands'][11]['params']='0200'
            if change=='failed-peer-reply':w['complete'][11]['status']=11
            if change=='wrong-device':w['complete'][11]['device']=2
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(r,w)
