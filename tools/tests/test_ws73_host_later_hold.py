# SPDX-License-Identifier: GPL-2.0-only
import copy
import unittest
import tempfile
import json
from pathlib import Path
from ws73_diagnostic_hold import PROPERTIES
from test_ws73_management_ready_peer import ready_fixture
from ws73_management_partial import verify_records,corroborate
from ws73_host_later_hold import SELECTORS,verify_selector_rows,LaterHostCoordinator
from sparklink.structs import SleControllerSnapshot,SleDiscoveryResult


def fixture(domain='advertising',step=1,case='release'):
    r,s,cap=ready_fixture(case,domain);r.update(format_version=8,real_later_step=True,initialization_step=step)
    if domain=='scanning':
        r['scan_parameter_cleanup']=False
        value=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(r['final_snapshot']));value.flags=1;r['final_snapshot']=bytes(value).hex()
    else:r['early_selected_power']=6
    for key in ['pending','cancelled','final_result']:
        value=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(r[key]));value.step=step;value.opcode=0xc05 if domain=='advertising' else 0x1002
        if domain=='advertising':value.power_valid=1;value.selected_power=6
        if domain=='scanning' and key=='final_result':value.radio_scan=1
        r[key]=bytes(value).hex()
    r['management_observations'][-1]['wall_ns']=450
    r['ready_peer']['on_after_free']['wall_ns']=515
    for row in r['ready_peer']['after']:
        row['start_wall_ns']+=100;row['end_wall_ns']+=100
    for key in ['commands','complete']:
        for row in cap[key]:
            if row['wall_ns']>=420:
                row['wall_ns']+=100;row['record']+=100
                if key=='commands':row['completion']['wall_ns']+=100
    for i,row in enumerate(r['hold_acknowledgements']):row['state'].update(dict(zip(SELECTORS,[step,step if i==0 else 0,0 if i==0 else step])))
    host=dict(method='QMP_HOLD_LATER_ACTUAL_SUCCESSFUL_IN81',initialization_step=step,complete=True,physical_acceptance=False,automatic_fault_recovery_acceptance=False,observations=r['hold_acknowledgements'])
    def command(op,t,params):return dict(bus=1,device=2,opcode=op,wall_ns=t,record=t,completion=dict(wall_ns=t+1),params=params)
    def reply(op,t,value,sha):return dict(bus=1,device=2,opcode=op,wall_ns=t,record=t,value=value,status=0,usb_length=178,usb_sha256=sha)
    ops=[(0xc02,'00'*49),(0xc05,'00'*5)] if domain=='advertising' else [(0x1001,'0000010040062003'),(0x1002,'0100'),(0x1002,'0000')]
    replies=[]
    for n,(opcode,params) in enumerate(ops):
        cap['commands'].append(command(opcode,155+n*20 if n<=step else 420,params))
        value='06' if opcode==0xc02 else ''
        out=reply(opcode,165+n*20 if n<step else 410 if n==step else 430,value,str(n+1)*64);cap['complete'].append(out);replies.append(out)
    if domain=='scanning':
        cap['commands'] += [command(0xc02,55,'00'*49),command(0xc05,75,'00'*5)]
        cap['complete'] += [reply(0xc02,65,'06','a'*64),reply(0xc05,85,'','b'*64)]
    for key in ['commands','complete']:cap[key].sort(key=lambda v:v['wall_ns'])
    log=''.join(f"WS73_TEST_RUNTIME_SKIP: dev 1:124 bytes=178 host_status=0 skipped={i+1} sha256={v['usb_sha256']}\n" for i,v in enumerate(replies[:step]))
    log+=f"WS73_TEST_RUNTIME_HOLD: dev 1:124 bytes=178 host_status=0 holds=1 sha256={replies[step]['usb_sha256']}\nWS73_TEST_RUNTIME_HOLD_RELEASE: dev 1:124 bytes=178 bounded=0 releases=1\n"
    return r,host,cap,log


class LaterHostTests(unittest.TestCase):
    def test_three_steps_three_fd_cases_actual_frame_contract(self):
        for domain,step in [('advertising',1),('scanning',1),('scanning',2)]:
            for case in ['release','close','dup']:
                r,h,w,log=fixture(domain,step,case)
                with self.subTest(domain=domain,step=step,case=case):
                    verify_records(r);p=corroborate(r,h,w,log,dict(bus=1,address=124))
                    self.assertEqual(len(p['host_hold']['skipped_original_frames']),step)
                    self.assertTrue(p['active_ready_peer_isolation_acceptance'])
                    self.assertFalse(p['full_cleanup_acceptance'])
                    self.assertEqual(p['retained_original_final_stop'] is not None,domain=='advertising' or step==2)

    def test_wrong_count_type_hash_identity_or_extra_frame_is_rejected(self):
        for change in ['budget','count','boolean','hash','identity','extra','drop','no-peer','model','old-format','duplicate-stop','missing-earlier','failed-earlier']:
            r,h,w,log=fixture('scanning',2)
            if change=='budget':h['observations'][0]['state'][SELECTORS[1]]=1
            if change=='count':h['observations'][1]['state'][SELECTORS[2]]=1
            if change=='boolean':h['observations'][1]['state'][SELECTORS[2]]=True
            if change=='hash':log=log.replace('1'*64,'f'*64)
            if change=='identity':log=log.replace('dev 1:124','dev 1:125',1)
            if change=='extra':log='WS73_TEST_RUNTIME_SKIP: dev 1:124 bytes=178 host_status=0 skipped=1 sha256='+'c'*64+'\n'+log
            if change=='drop':h['observations'][2]['state']['test-runtime-in-hold-drops']=1
            if change=='no-peer':r['active_ready_peer']=False
            if change=='model':r['synthetic_support']=True
            if change=='old-format':r['format_version']=7
            if change=='duplicate-stop':w['commands'].append(dict(bus=1,device=2,opcode=0x1002,wall_ns=420,params='0000'))
            if change=='missing-earlier':w['complete']=[v for v in w['complete'] if not(v['device']==2 and v['wall_ns']==165)]
            if change=='failed-earlier':next(v for v in w['complete'] if v['device']==2 and v['wall_ns']==185)['status']=11
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(r,h,w,log,dict(bus=1,address=124))

    def test_old_model_or_unbounded_selector_is_not_a_real_host_gate(self):
        for count in [False,0,3,-1]:
            with self.subTest(count=count),self.assertRaises(ValueError):LaterHostCoordinator('/tmp',{},count)
        r,h,w,log=fixture()
        self.assertEqual(len(h['observations'][0]['state']),11)


class CoordinatorTests(unittest.TestCase):
    def test_fixture_qmp_handshake_progress_and_explicit_release(self):
        # QMP readback fixture only; C callback and live USB evidence are separate.
        for step in [1,2]:
            with self.subTest(step=step),tempfile.TemporaryDirectory() as tmp:
                record={};c=LaterHostCoordinator(tmp,record,step);c.folder.mkdir()
                state=dict(zip(PROPERTIES,[False,False,0,0,0,0,False,0]));state.update(dict.fromkeys(SELECTORS,0))
                class Monitor:
                    def execute(self,method,arguments):
                        key=arguments['property']
                        if method=='qom-get':return True if key=='attached' else state.get(key,False)
                        if key.startswith('test-runtime-in-skip-'):state[SELECTORS[0]]=step
                        elif key==PROPERTIES[0]:state[key]=True;state[SELECTORS[1]]=step
                        elif key=='test-runtime-in-release':state[PROPERTIES[1]]=False;state[PROPERTIES[3]]=1
                        else:raise AssertionError(key)
                m=Monitor()
                def marker(phase,t):(c.folder/f'hold-{phase}.json').write_text(json.dumps(dict(hold_phase=phase,wall_ns=t)))
                marker('arm_ready',1);c.poll(m);self.assertEqual(c.phase,'wait_held')
                marker('wait_held',2);c.poll(m);self.assertEqual(len(record['observations']),1)
                if step==2:
                    state[SELECTORS[1]]=1;state[SELECTORS[2]]=1;c.poll(m);self.assertEqual(len(record['observations']),1)
                state[SELECTORS[1]]=0;state[SELECTORS[2]]=step;state[PROPERTIES[0]]=False;state[PROPERTIES[1]]=True;state[PROPERTIES[2]]=1
                c.poll(m);self.assertEqual(c.phase,'release_ready');marker('release_ready',3);c.poll(m)
                self.assertTrue(record['complete']);verify_selector_rows(record['observations'],step)

    def test_selector_state_boolean_or_budget_drift_is_rejected(self):
        for change in ['boolean','remaining','drops']:
            r,h,w,log=fixture('scanning',2);rows=h['observations']
            if change=='boolean':rows[0]['state'][SELECTORS[0]]=True
            if change=='remaining':rows[2]['state'][SELECTORS[1]]=1
            if change=='drops':rows[1]['state'][PROPERTIES[5]]=1
            with self.subTest(change=change),self.assertRaises(ValueError):verify_selector_rows(rows,2)
