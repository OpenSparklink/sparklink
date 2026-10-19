# SPDX-License-Identifier: GPL-2.0-only
"""Reject weak daemon evidence; fixtures never qualify hardware or RF."""
import copy
import os
import sys
import subprocess
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
    def test_actual_invocation_forwards_explicit_environment_and_stdin_without_recording_environment(self):
        command=[sys.executable,'-c','import os,sys;print(os.environ["SPARKLINK_TEST_LITERAL"],flush=True);print(sys.stdin.readline().strip(),flush=True)']
        invocation=Invocation(command,'explicit-process-fixture',stdin=subprocess.PIPE,
            env=dict(os.environ,SPARKLINK_TEST_LITERAL='explicit-fixture'))
        try:
            self.assertEqual(invocation.until(rb'^explicit-fixture$',timeout=1,limit=4096),b'explicit-fixture')
            invocation.process.stdin.write(b'original-input\n');invocation.process.stdin.flush()
            record=invocation.finish(timeout=1)
            self.assertEqual(record['exit'],0);self.assertEqual(record['stdout'],'explicit-fixture\noriginal-input\n')
            self.assertEqual(record['stderr'],'');self.assertNotIn('env',record)
        finally:
            if invocation.process.poll()is None:invocation.finish(kill=True)

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

class CancelAuthorTests(unittest.TestCase):
    @staticmethod
    def fixture(case):
        r,h,c,l=fixture();a=r['target'];b=r['peer'];r.update(case=case,format_version=3)
        r['original_caller']['end_wall_ns']=2600
        def management(start,end,state):
            return dict(args=['/bin/slctl','--adapter',a['path'],'management'],stdout=f"NativeManagementStatus: generation=1 mode={int(state==1)} state={state} flags={int(state==1)} errno=0 status=0x00 opcode=0x0000\n",stderr='',exit=0,start_wall_ns=start,end_wall_ns=end)
        r['management_revoking']=management(2650,2700,2)
        r['management_held']=management(3430,3470,1);r['management_polls']=[r['management_held']]
        if case=='cancel-caller-exit':
            r['cancel_caller'].update(exit=-9,kill_wall_ns=2720,end_wall_ns=2750,stdout='NativePoliciesCancelRequest: generation=1\n')
            r['after_cancel_caller_exit']=dict(r['cancelled'],start_wall_ns=2800,end_wall_ns=2830)
            r['management_after_cancel_exit']=management(2900,2930,2)
        else:
            r['busy_cancel']=dict(args=r['cancel_caller']['args'],stdout='NativePoliciesCancelRequest: generation=1\n',stderr='device management admission or handoff busy',exit=1,start_wall_ns=2730,end_wall_ns=2900)
            r['first_cancel_pending_after_busy']=True
        def result(i,op,start,end,scan):
            text=f'NativeOperationResult: generation=1 request={i} operation={op} state=3 errno=0 status=0x00 opcode=0x1002 step={int(op==3)}/{2 if op==3 else 1} power=0 power_valid=0 adv=1 scan={scan} profile=1\n'
            return dict(args=['/bin/slctl','--adapter',a['path'],'scan','on' if op==3 else 'off'],stdout=text,stderr='',exit=0,start_wall_ns=start,end_wall_ns=end)
        r['target_resume']=[result(31,3,3700,4050,2),result(32,4,4080,4150,1)]
        r['peer_on_after_drain'].update(start_wall_ns=4200,end_wall_ns=4300)
        r['peer_stop'].update(start_wall_ns=4400,end_wall_ns=4700)
        for op,params,start,end,sha in [(0x1001,'0000010040062003',3750,3800,'f'*64),(0x1002,'0100',3900,4000,'7'*64),(0x1002,'0000',4100,4130,'8'*64)]:
            c['commands'].append(dict(bus=1,device=2,opcode=op,params=params,wall_ns=start,record=start,completion=dict(wall_ns=start+1)))
            c['complete'].append(dict(bus=1,device=2,opcode=op,value='',status=0,wall_ns=end,record=end,usb_length=178,usb_sha256=sha))
        for key in ['commands','complete']:
            for v in c[key]:
                if v['device']==3 and v['wall_ns']>=4000:
                    v['wall_ns']+=500
                    if key=='commands':v['completion']['wall_ns']+=500
            c[key].sort(key=lambda v:v['wall_ns'])
        return r,h,c,l

    def test_abandoned_cancel_and_busy_handoff_require_real_owned_reacquisition(self):
        for case in ['cancel-caller-exit','cancel-busy']:
            r,h,c,l=self.fixture(case)
            with self.subTest(case=case):
                p=corroborate(r,h,c,l,dict(bus=1,address=124));self.assertEqual(len(p['target']),4);self.assertEqual(len(p['peer']),3)
                self.assertFalse(p['whole_managed_acceptance'])

    def test_wrong_revocation_caller_exit_reacquisition_or_wire_never_pass(self):
        for change in ['false-exit','fake-confirmation','wrong-generation','leaked-token','wrong-owner','early-held','not-revoking','missing-history','wrong-resume','failed-resume','failed-wire','busy-succeeded','busy-no-error','original-handoff-ended']:
            case='cancel-busy' if change.startswith('busy') or change=='original-handoff-ended' else 'cancel-caller-exit'
            r,h,c,l=self.fixture(case)
            if change=='false-exit':r['cancel_caller']['exit']=0
            if change=='fake-confirmation':r['cancel_caller']['stdout']+='NativePoliciesCancelled: generation=1\n'
            if change=='wrong-generation':r['management_held']['stdout']=r['management_held']['stdout'].replace('generation=1','generation=2')
            if change=='leaked-token':r['management_held']['stdout']+='lease=999\n'
            if change=='wrong-owner':r['management_held']['stdout']=r['management_held']['stdout'].replace('flags=1','flags=0')
            if change=='early-held':r['management_held'].update(start_wall_ns=2400,end_wall_ns=2450)
            if change=='not-revoking':r['management_after_cancel_exit']['stdout']=r['management_held']['stdout']
            if change=='missing-history':r['management_polls']=[]
            if change=='wrong-resume':r['target_resume'][0]['args'][2]=r['peer']['path']
            if change=='failed-resume':r['target_resume'][0]['exit']=1
            if change=='failed-wire':next(v for v in c['complete'] if v['device']==2 and v['wall_ns']==4000)['status']=11
            if change=='busy-succeeded':r['busy_cancel']['exit']=0
            if change=='busy-no-error':r['busy_cancel']['stderr']=''
            if change=='original-handoff-ended':r['first_cancel_pending_after_busy']=False
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(r,h,c,l,dict(bus=1,address=124))

class BusinessAdmissionTests(unittest.TestCase):
    @staticmethod
    def fixture():
        r,h,c,l=CancelAuthorTests.fixture('cancel-admission')
        r['format_version']=4;r['busy_cancel']['end_wall_ns']=2740
        r['admission_refusals']=[]
        for number,words in enumerate([('advertise','on'),('advertise','off'),('scan','on'),('scan','off'),('advertise','initialized-off'),('scan','initialized-off')]):
            identifier=51+number
            text=(f'NativeAdvertisementRequest: request={identifier} marker='+ 'a'*32+'\n' if number==0 else
                  f'NativeStopAdvertisingRequest: request={identifier}\n' if number==1 else
                  f'NativeScanRequest: request={identifier} enable={words[1]}\n' if number<4 else '')
            r['admission_refusals'].append(dict(args=['/bin/slctl','--adapter',r['target']['path'],*words],
                exit=1,stdout=text,stderr='device management admission or handoff busy',start_wall_ns=2741+number*3,end_wall_ns=2743+number*3))
        r['still_cancelled']=dict(r['cancelled'],start_wall_ns=2760,end_wall_ns=2762)
        r['peer_on_during_handoff']=dict(r['peer_on_after_drain'],start_wall_ns=2764,end_wall_ns=2766)
        r['first_cancel_pending_after_admission']=True
        return r,h,c,l

    def test_actual_busy_refusals_preserve_queries_and_peer_without_extra_wire(self):
        r,h,c,l=self.fixture();p=corroborate(r,h,c,l,dict(bus=1,address=124))
        self.assertTrue(p['busy_business_initializer_admission_acceptance'])
        self.assertFalse(p['whole_managed_acceptance'])

    def test_admission_delay_success_wrong_domain_result_alias_or_extra_wire_rejected(self):
        for change in ['missing','success','delay','wrong-domain','missing-request','old-id','accepted','result','wrong-error','false-pending','original-success','peer-off','extra-wire','old-format']:
            r,h,c,l=self.fixture();row=r['admission_refusals'][0]
            if change=='missing':r['admission_refusals'].pop()
            if change=='success':row['exit']=0
            if change=='delay':row['end_wall_ns']=row['start_wall_ns']+100_000_000
            if change=='wrong-domain':row['args'][2]=r['peer']['path']
            if change=='missing-request':row['stdout']=''
            if change=='old-id':row['stdout']=row['stdout'].replace('request=51','request=11')
            if change=='accepted':row['stdout']+='NativeAdvertisementAccepted: request=51 marker=x data=y\n'
            if change=='result':row['stdout']+=r['target_resume'][0]['stdout']
            if change=='wrong-error':row['stderr']='initializer provenance absent or invalidated'
            if change=='false-pending':r['first_cancel_pending_after_admission']=False
            if change=='original-success':r['still_cancelled']['exit']=0
            if change=='peer-off':r['peer_on_during_handoff']['stdout']=r['peer_on_during_handoff']['stdout'].replace('scan=2','scan=1')
            if change=='extra-wire':c['commands'].append(dict(c['commands'][0],opcode=0x0c02,wall_ns=2750))
            if change=='old-format':r['format_version']=3
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(r,h,c,l,dict(bus=1,address=124))
