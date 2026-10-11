# SPDX-License-Identifier: GPL-2.0-only
"""Reject weak daemon evidence; fixtures never qualify hardware or RF."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from ws73_daemon_hold import Invocation,verify_records,corroborate
from ws73_diagnostic_hold import PROPERTIES


def fixture(case='supersede'):
    a=dict(port='1-1',bus=1,device=2,index=0,generation=1,path='/org/sparklink/slk0_g1',address='00:01:09:32:54:F9',version='016c00a100',features='00'*10)
    b=dict(a,port='1-2',device=3,index=1,generation=2,path='/org/sparklink/slk1_g2',address='00:01:09:30:CE:85')
    def row(owner,i,op,state,opcode,step,count,start,end,words,scan=1):
        error=-125 if state==5 else 0
        text=f"NativeOperationResult: generation={owner['generation']} request={i} operation={op} state={state} errno={error} status=0x00 opcode=0x{opcode:04x} step={step}/{count} power=0 power_valid=0 adv=1 scan={scan} profile=1\n"
        return dict(args=['/bin/slctl','--adapter',owner['path'],*words],stdout=text,stderr='cancelled' if state==5 else '',exit=1 if state==5 else 0,start_wall_ns=start,end_wall_ns=end)
    original=dict(args=['/bin/slctl','--adapter',a['path'],'scan','on'],toggle='on',pid=10,request_id=11,start_wall_ns=1100,marker_wall_ns=1150,stdout='NativeScanRequest: request=11 enable=on\n',stderr='',exit=-9 if case=='caller-exit' else 1,end_wall_ns=1600 if case=='caller-exit' else 2900)
    if case=='caller-exit':original['kill_wall_ns']=1550
    else:original['stdout']+=row(a,11,3,5,0x1001,0,2,0,0,[])['stdout']
    cancel=dict(args=['/bin/slctl','--adapter',a['path'],'cancel-discovery'],toggle='cancel',pid=20,generation=1,start_wall_ns=2200,end_wall_ns=3400,marker_wall_ns=2250,stdout='NativePoliciesCancelRequest: generation=1\nNativePoliciesCancelled: generation=1\n',stderr='',exit=0)
    markers=[dict(hold_phase=p,wall_ns=t) for p,t in [('arm_ready',1000),('wait_held',1200),('release_ready',3000)]]
    acks=[dict(stage=['armed','held','released'][i],request=m,host_wall_ns=m['wall_ns']+1,state=dict(zip(PROPERTIES,[i==0,i==1,int(i>0),int(i==2),0,0,False,0]))) for i,m in enumerate(markers)]
    r=dict(format_version=2,status='DAEMON_HELD_REPLY_CANCEL_EVIDENCE_PENDING',case=case,target=a,peer=b,markers=markers,hold_acknowledgements=acks,
        application_identity=dict(uids=[1000]*4,cap_eff='0',cap_prm='0',cap_amb='0'),daemon_before=dict(pid=100,start_ticks=1),daemon_after=dict(pid=100,start_ticks=1),
        bus_before=dict(owner=':1.1',pid=100,uid=0),bus_after=dict(owner=':1.1',pid=100,uid=0),physical_acceptance=False,automatic_fault_recovery_acceptance=False,
        original_caller=original,cancel_caller=cancel,pending=row(a,11,3,2,0x1001,0,2,1300,1500,['result','11']),
        cancelled=row(a,11,3,5,0x1001,0,2,2300,2500,['result','11']),
        after_drain=row(a,11,3,5,0x1001,0,2,3500,3600,['result','11']),replacement_pending_before_release=True,cancel_observed_wall_ns=2950,
        peer_start=row(b,21,3,3,0x1002,1,2,1800,2100,['scan','on'],2),peer_on_after_drain=row(b,21,3,3,0x1002,1,2,3700,3800,['result','21'],2),
        peer_stop=row(b,22,4,3,0x1002,0,1,3900,4200,['scan','off']),target_after=a,peer_after=b)
    r['cancel_polls']=[r['cancelled']]
    if case=='caller-exit':r['after_caller_exit']=row(a,11,3,2,0x1001,0,2,1650,1700,['result','11'])
    capture=dict(commands=[],complete=[])
    for owner,op,params,start,end,sha in [(a,0x1001,'0000010040062003',1170,3100,'a'*64),(b,0x1001,'0000010040062003',1850,1900,'c'*64),(b,0x1002,'0100',1950,2000,'d'*64),(b,0x1002,'0000',4000,4100,'e'*64)]:
        capture['commands'].append(dict(bus=owner['bus'],device=owner['device'],opcode=op,params=params,wall_ns=start,record=start,completion=dict(wall_ns=start+1)))
        capture['complete'].append(dict(bus=owner['bus'],device=owner['device'],opcode=op,value='',status=0,wall_ns=end,record=end,usb_length=178,usb_sha256=sha))
    for key in ['commands','complete']:capture[key].sort(key=lambda v:v['wall_ns'])
    host=dict(method='QMP_HOLD_ACTUAL_SUCCESSFUL_IN81',complete=True,physical_acceptance=False,automatic_fault_recovery_acceptance=False,observations=acks)
    log='WS73_TEST_RUNTIME_HOLD: dev 1:124 bytes=178 host_status=0 holds=1 sha256='+'a'*64+'\nWS73_TEST_RUNTIME_HOLD_RELEASE: dev 1:124 bytes=178 bounded=0 releases=1\n'
    return r,host,capture,log


class DaemonHoldTests(unittest.TestCase):
    def test_two_cases_require_actual_caller_lifetime_and_unchanged_daemon(self):
        for case in ['supersede','caller-exit']:
            r,h,c,l=fixture(case)
            with self.subTest(case=case):
                verify_records(r);p=corroborate(r,h,c,l,dict(bus=1,address=124))
                self.assertEqual(len(p['target']),1);self.assertEqual(len(p['peer']),3)
                self.assertTrue(p['ordinary_user_daemon_held_cancel_case_acceptance'])
                self.assertFalse(p['whole_managed_acceptance'])

    def test_changed_owner_premature_success_closed_caller_or_old_generation_rejected(self):
        for change in ['uid','caps','daemon','bus','generation','wrong-cancel-generation','premature-stop','succeeded-old','missing-poll','exited-before-admission','caller-exit-success','pending-lost','deadline','peer-off','wrong-affinity']:
            r,h,c,l=fixture('caller-exit')
            if change=='uid':r['application_identity']['uids']=[0]*4
            if change=='caps':r['application_identity']['cap_eff']='1'
            if change=='daemon':r['daemon_after']['pid']=101
            if change=='bus':r['bus_after']['owner']=':1.2'
            if change=='generation':r['target_after']=dict(r['target'],generation=3)
            if change=='wrong-cancel-generation':r['cancel_caller']['generation']=2
            if change=='premature-stop':r['replacement_pending_before_release']=False
            if change=='succeeded-old':r['after_drain']['stdout']=r['after_drain']['stdout'].replace('state=5','state=3').replace('errno=-125','errno=0');r['after_drain']['exit']=0
            if change=='missing-poll':r['cancel_polls']=[]
            if change=='exited-before-admission':r['original_caller']['kill_wall_ns']=1100
            if change=='caller-exit-success':r['original_caller']['exit']=0
            if change=='pending-lost':r['after_caller_exit']['stdout']=r['cancelled']['stdout']
            if change=='deadline':r['markers'][2]['wall_ns']=r['original_caller']['start_wall_ns']+400000000
            if change=='peer-off':r['peer_on_after_drain']['stdout']=r['peer_on_after_drain']['stdout'].replace('scan=2','scan=1')
            if change=='wrong-affinity':r['pending']['args'][2]=r['peer']['path']
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(r)

    def test_missing_extra_failed_or_wrong_host_frame_rejected(self):
        for change in ['hash','early-reply','missing-original','duplicate-start','extra-reply','peer-failed','host-counter']:
            r,h,c,l=fixture()
            if change=='hash':l=l.replace('a'*64,'f'*64)
            if change=='early-reply':next(v for v in c['complete'] if v['device']==2)['wall_ns']=1500
            if change=='missing-original':c['commands']=[v for v in c['commands'] if v['device']!=2]
            if change=='duplicate-start':c['commands'].append(dict(c['commands'][0],opcode=0x1002,params='0100',wall_ns=2000))
            if change=='extra-reply':c['complete'].append(dict(c['complete'][-1],device=2,wall_ns=4000))
            if change=='peer-failed':next(v for v in c['complete'] if v['device']==3)['status']=11
            if change=='host-counter':h['observations'][-1]['state']['test-runtime-in-bounded-releases']=1
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(r,h,c,l,dict(bus=1,address=124))

    def test_live_pipe_collection_reaps_actual_process_without_reading_redirected_file(self):
        # Process/pipe fixture only. No kernel/USB output is generated here.
        script='import time; print("NativeScanRequest: request=7 enable=on",flush=True); time.sleep(.1); print("done",flush=True)'
        p=Invocation([sys.executable,'-c',script],'on')
        self.assertEqual(p.identifier(),7);r=p.finish();self.assertEqual(r['exit'],0);self.assertIn('done',r['stdout'])
        p=Invocation([sys.executable,'-c',script],'on');self.assertEqual(p.identifier(),7);self.assertEqual(p.finish(kill=True)['exit'],-9)
