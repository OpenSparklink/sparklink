# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import errno
import unittest
from unittest.mock import patch
from ws73_management_partial import verify_records, standby, corroborate
from ws73_diagnostic_hold import PROPERTIES
from sparklink.structs import SleControllerSnapshot, SleManagementQuery, SleDiscoveryResult, SleDiagnosticSubmit, SleDiagnosticResult


def fixture(case='release',domain='advertising'):
    snapshots=[SleControllerSnapshot(version=1,generation=i+1,dev_index=i,flags=2,profile=1,valid_fields=1) for i in [0,1]]
    snapshots[1].address[:]=b'123456'
    markers=[dict(hold_phase=phase,wall_ns=t) for phase,t in [('arm_ready',100),('wait_held',200),('release_ready',400)]]
    ready=SleControllerSnapshot.from_buffer_copy(bytes(snapshots[0]));ready.flags=1
    q=lambda state,mode:bytes(SleManagementQuery(version=1,generation=1,state=state,mode=mode)).hex()
    record=dict(format_version=2,status='MANAGED_PARTIAL_HELD_REPLY_PASS',case=case,domain=domain,preparation=[],
        physical_acceptance=False,automatic_fault_recovery_acceptance=False,daemon_running_during_hold=False,
        initial_snapshots=[bytes(s).hex() for s in snapshots],input=bytes(standby(snapshots[0],1,domain)).hex(),
        before_management=q(1,1),revoking=q(2,0),final_management=q(0,0),final_snapshot=bytes(ready).hex(),
        peer_after=bytes(snapshots[1]).hex(),original_fd=5,duplicate_fd=6 if case=='dup' else -1,lease=1,
        submit_before_wall_ns=150,submit_after_wall_ns=160,release_before_wall_ns=300,release_after_wall_ns=310,
        markers=markers,peer_queries=[],host_hold_acknowledgements=[])
    peer=bytes(SleManagementQuery(version=1,generation=2,state=1,mode=2)).hex()
    record.update(peer_management_before=peer,peer_management_after=peer)
    if domain=='scanning':
        preparation=SleDiscoveryResult(version=1,generation=1,request_id=2,profile=1,
            operation=5,state=3,count=2,step=1,opcode=0xc05,radio_adv=1,power_valid=1,selected_power=6)
        record['preparation']=[dict(input=bytes(standby(snapshots[0],2,'advertising')).hex(),
            result=bytes(preparation).hex(),start_wall_ns=50,end_wall_ns=90)]
    if case!='release':record['original_fd_errno']=errno.EBADF
    if case=='dup':record.update(duplicate_fd_errno=errno.EBADF,after_first_management=q(1,1))
    record['management_observations']=[dict(wall_ns=401,raw=q(2,0)),dict(wall_ns=405,raw=q(0,0))]
    opcode=0xc02 if domain=='advertising' else 0x1001
    for key,state,error in [('pending',2,0),('cancelled',5,-errno.ECANCELED),('final_result',5,-errno.ECANCELED)]:
        record[key]=bytes(SleDiscoveryResult(version=1,generation=1,request_id=1,profile=1,operation=5 if opcode==0xc02 else 6,
            count=2 if opcode==0xc02 else 3,opcode=opcode,state=state,error=error,
            radio_adv=1 if key=='final_result' or domain=='scanning' else 0,
            radio_scan=1 if key=='final_result' else 0)).hex()
    for i,m in enumerate(markers):
        record['host_hold_acknowledgements'].append(dict(stage=['armed','held','released'][i],request=m,
            host_wall_ns=m['wall_ns']+1,state=dict(zip(PROPERTIES,[i==0,i==1,int(i>0),int(i==2),0,0,False,0]))))
    for i in range(3):
        command=SleDiagnosticSubmit(version=1,generation=2,request_id=i+1,seq=i+1,timeout_ms=5000,opcode=0x406,action=1)
        result=SleDiagnosticResult(version=1,generation=2,seq=i+1,state=2,opcode=0x406,data_len=6);result.data[:6]=snapshots[1].address
        record['peer_queries'].append(dict(input=bytes(command).hex(),result=bytes(result).hex(),start_wall_ns=10+i*200,end_wall_ns=20+i*200))
    return record


class PartialTests(unittest.TestCase):
    def test_scan_cleanup_retains_only_previously_proven_off(self):
        record=fixture(domain='scanning')
        record['management_observations']=[dict(wall_ns=440,raw=record['revoking']),dict(wall_ns=450,raw=record['final_management'])]
        record['peer_queries'][2].update(start_wall_ns=490,end_wall_ns=500)
        def command(opcode,t,params='',device=2):return dict(bus=1,device=device,opcode=opcode,wall_ns=t,params=params)
        def reply(opcode,t,value='',device=2):return dict(bus=1,device=device,opcode=opcode,wall_ns=t,value=value,status=0)
        capture=dict(commands=[command(0xc02,55,'00'*49),command(0xc05,75,'00'*5),
            command(0x1001,155),command(0x1002,420,'0000')],
            complete=[reply(0xc02,65,'06'),reply(0xc05,85),reply(0x1001,410),reply(0x1002,430)])
        for row in record['peer_queries']:
            capture['commands'].append(command(0x406,row['start_wall_ns'],device=3))
            capture['complete'].append(reply(0x406,row['end_wall_ns'],'313233343536',device=3))
        # The host hold contract is tested independently. Here exercise exact
        # target capture ordering and refusal to replace prior OFF evidence.
        with patch('ws73_diagnostic_hold.corroborate_host_hold',return_value={}):
            proof=corroborate(record,{},capture,'',{})
            self.assertEqual(proof['retained_advertising_off']['reply']['opcode'],0xc05)
            self.assertEqual([v['opcode'] for v in proof['commands']],[0x1001,0x1002])
            for change in ['missing-off','failed-off','extra-stop','intervening-enable']:
                import copy
                bad=copy.deepcopy(capture)
                if change=='missing-off':bad['complete'].pop(1)
                if change=='failed-off':bad['complete'][1]['status']=30
                if change=='extra-stop':bad['commands'].insert(3,command(0xc05,415,'00'*5))
                if change=='intervening-enable':bad['commands'].insert(2,command(0xc05,120,'0100000000'))
                with self.subTest(change=change),self.assertRaises(ValueError):corroborate(record,{},bad,'',{})

    def test_scan_requires_real_prior_advertising_off_and_no_false_unknown(self):
        for change in ['missing','failed','unknown','wrong-request','reserved','no-power','bad-power','late','bool','pending-radio']:
            record=fixture(domain='scanning');row=record['preparation'][0]
            result=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(row['result']))
            if change=='missing':record['preparation']=[]
            if change=='failed':result.state=4;result.error=-errno.EIO;result.status=30
            if change=='unknown':result.radio_adv=0
            if change=='wrong-request':result.request_id=1
            if change=='reserved':result.reserved[0]=1
            if change=='no-power':result.power_valid=0
            if change=='bad-power':result.selected_power=128
            if change=='late':row['end_wall_ns']=100
            if change=='bool':row['start_wall_ns']=True
            if change=='pending-radio':
                pending=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(record['pending']))
                pending.radio_adv=0;record['pending']=bytes(pending).hex()
            row['result']=bytes(result).hex()
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(record)

    def test_advertising_first_step_cannot_hide_a_prepared_or_old_format_gate(self):
        record=fixture();record['preparation']=fixture(domain='scanning')['preparation']
        with self.assertRaises(ValueError):verify_records(record)
        record=fixture();record['format_version']=1
        with self.assertRaises(ValueError):verify_records(record)

    def test_peer_canonical_result_and_causal_intervals(self):
        for change in ['reserved','tail','repeat-sequence','before-only','during-too-late','after-too-early','boolean']:
            record=fixture();row=record['peer_queries'][1]
            if change in ('reserved','tail'):
                result=SleDiagnosticResult.from_buffer_copy(bytes.fromhex(row['result']))
                if change=='reserved':result._reserved[0]=1
                else:result.data[6]=1
                row['result']=bytes(result).hex()
            if change=='repeat-sequence':row.update(input=record['peer_queries'][0]['input'],result=record['peer_queries'][0]['result'])
            if change=='before-only':row.update(start_wall_ns=10,end_wall_ns=20)
            if change=='during-too-late':row['end_wall_ns']=301
            if change=='after-too-early':record['peer_queries'][2]['start_wall_ns']=405
            if change=='boolean':row['start_wall_ns']=True
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(record)

    def test_unknown_or_incomplete_cleanup_observations(self):
        for change in ['missing','premature-free','wrong-generation','reversed-time','error']:
            record=fixture();rows=record['management_observations']
            if change=='missing':record['management_observations']=[]
            if change=='premature-free':rows[0]['raw']=record['final_management']
            if change=='wrong-generation':rows[0]['raw']=record['peer_management_before']
            if change=='reversed-time':rows[1]['wall_ns']=399
            if change=='error':
                q=SleManagementQuery.from_buffer_copy(bytes.fromhex(rows[0]['raw']));q.error=-errno.EIO;rows[0]['raw']=bytes(q).hex()
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(record)

    def test_six_canonical_partial_cases(self):
        for case in ['release','close','dup']:
            for domain in ['advertising','scanning']:
                with self.subTest(case=case,domain=domain):verify_records(fixture(case,domain))

    def test_fake_success_or_wrong_step_rejected(self):
        for key in ['pending','cancelled','final_result']:
            for field,value in [('state',3),('status',30),('step',1),('opcode',0x406),('power_valid',1)]:
                record=fixture();result=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(record[key]));setattr(result,field,value);record[key]=bytes(result).hex()
                with self.subTest(key=key,field=field),self.assertRaises(ValueError):verify_records(record)

    def test_failure_cleanup_not_normalized(self):
        record=fixture();q=SleManagementQuery.from_buffer_copy(bytes.fromhex(record['final_management']))
        q.state=3;q.error=-errno.EIO;q.status=30;q.opcode=0xc05;q.flags=2;record['final_management']=bytes(q).hex()
        with self.assertRaises(ValueError):verify_records(record)

    def test_dup_and_peer_isolation_rejected(self):
        for change in ['first-close','fd','peer','lease']:
            record=fixture('dup')
            if change=='first-close':record['after_first_management']=record['final_management']
            if change=='fd':record['duplicate_fd']=record['original_fd']
            if change=='peer':record['peer_after']=record['initial_snapshots'][0]
            if change=='lease':record['peer_management_after']=record['final_management']
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(record)

    def test_wrong_ack_and_late_release_rejected(self):
        for change in ['ack','late','inverted','boolean']:
            record=fixture()
            if change=='ack':record['host_hold_acknowledgements'][1]['stage']='released'
            if change=='late':record['release_after_wall_ns']=400_000_151
            if change=='inverted':record['release_after_wall_ns']=250
            if change=='boolean':record['submit_before_wall_ns']=True
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(record)
