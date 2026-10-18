# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
import unittest
from test_ws73_management_setup import fixture as setup_fixture
from ws73_management_queued import verify_records, corroborate
from sparklink.structs import SleDiscoveryResult, SleDiscoverySubmit, SleControllerSnapshot
from ws73_management_partial import standby


def fixture():
    record = setup_fixture()
    record['format_version'] = 2
    record['status'] = 'QUEUED_UNKNOWN_SETUP_RELEASE_LIVE_PASS'
    for n, row in enumerate(record['cases']):
        row.update(critical_start_ns=row['start_wall_ns']+1,
                   critical_end_ns=row['start_wall_ns']+1_000_000, scheduler_restored=True)
        for key, state, error in [('queued', 1, 0), ('cancelled', 5, -errno.ECANCELED)]:
            row[key] = [bytes(SleDiscoveryResult(version=1, generation=row['generation'],
                request_id=(n%3)*2+1+i, profile=1, operation=(5, 4)[i], count=(2, 1)[i],
                dev_index=row['index'], state=state, error=error)).hex() for i in [0, 1]]
        row['scan_initialize_rejections'] = []
        for step in [0, 1]:
            command = SleDiscoverySubmit(version=1, generation=row['generation'], profile=1,
                                         request_id=(step+1)*100+n%3, operation=6)
            command.scanning.frame_types = 1
            command.scanning.interval = 1600
            command.scanning.window = 800
            row['scan_initialize_rejections'].append(dict(input=bytes(command).hex(), submit_errno=errno.EBUSY, result_errno=errno.ENOENT))
    return record


class QueuedTests(unittest.TestCase):
    def test_full_canonical_two_domain_six_cases(self):
        record = fixture()
        verify_records(record)
        proof = corroborate(record, {k: [] for k in ['commands', 'complete', 'failures']})
        self.assertFalse(proof['managed_preselection_live_acceptance'])
        self.assertTrue(proof['managed_unknown_setup_preselection_live_acceptance'])
        self.assertFalse(proof['normal_scheduler_concurrency_acceptance'])
        self.assertFalse(proof['partial_initialization_cleanup_acceptance'])
        self.assertFalse(proof['active_ready_peer_isolation_acceptance'])
        self.assertFalse(proof['managed_preselection_synthetic_support_acceptance'])

    def test_synthetic_scope_cannot_claim_live_acceptance(self):
        record = fixture()
        record['synthetic_support'] = True
        record['status'] = 'QUEUED_UNKNOWN_SETUP_RELEASE_SYNTHETIC_SUPPORT_PASS'
        proof = corroborate(record, {k: [] for k in ['commands', 'complete', 'failures']})
        self.assertFalse(proof['managed_preselection_live_acceptance'])
        self.assertTrue(proof['managed_preselection_synthetic_support_acceptance'])
        self.assertFalse(proof['active_ready_peer_isolation_acceptance'])

    def test_scope_status_mismatch_and_non_boolean_rejected(self):
        for synthetic, status in [(True, 'QUEUED_UNKNOWN_SETUP_RELEASE_LIVE_PASS'),
                                  (False, 'QUEUED_UNKNOWN_SETUP_RELEASE_SYNTHETIC_SUPPORT_PASS'),
                                  (1, 'QUEUED_UNKNOWN_SETUP_RELEASE_LIVE_PASS')]:
            record = fixture(); record.update(synthetic_support=synthetic, status=status)
            with self.subTest(synthetic=synthetic, status=status), self.assertRaises(ValueError):
                verify_records(record)

    def test_selected_or_fabricated_result_rejected(self):
        for key in ['queued', 'cancelled']:
            for field, value in [('state', 3), ('opcode', 0xc02), ('step', 1), ('error', 0 if key == 'cancelled' else -125),
                                 ('radio_adv', 1), ('radio_scan', 1), ('power_valid', 1), ('status', 30),
                                 ('request_id', 99), ('generation', 999), ('reserved', (1, 0, 0, 0))]:
                record = fixture()
                result = SleDiscoveryResult.from_buffer_copy(bytes.fromhex(record['cases'][0][key][0]))
                if field == 'reserved': result.reserved[:] = value
                else: setattr(result, field, value)
                record['cases'][0][key][0] = bytes(result).hex()
                with self.subTest(key=key, field=field), self.assertRaises(ValueError): verify_records(record)

    def test_unbounded_or_unrestored_scheduler_rejected(self):
        for field, value in [('scheduler_restored', False), ('scheduler_restored', 1),
                             ('critical_end_ns', 1_050_000_001), ('critical_start_ns', True)]:
            record = fixture(); record['cases'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): verify_records(record)

    def test_traffic_on_either_device_in_gaps_rejected(self):
        for key in ['commands', 'complete', 'failures']:
            capture = {k: [] for k in ['commands', 'complete', 'failures']}
            capture[key] = [{'wall_ns': 1_600_000_000, 'bus': 1, 'device': 3}]
            with self.subTest(key=key), self.assertRaises(ValueError): corroborate(fixture(), capture)

    def test_peer_mutation_and_missing_domain_rejected(self):
        for change in ['peer', 'domain']:
            record = fixture()
            if change == 'peer': record['cases'][0]['peer_after'] = record['initial_snapshots'][0]
            else: record['cases'][0]['cancelled'].pop()
            with self.subTest(change=change), self.assertRaises(ValueError): verify_records(record)

    def test_scan_initialization_cannot_replace_valid_stop_or_be_admitted(self):
        record = fixture()
        result = SleDiscoveryResult.from_buffer_copy(bytes.fromhex(record['cases'][0]['queued'][1]))
        result.operation = 6; result.count = 3
        record['cases'][0]['queued'][1] = bytes(result).hex()
        with self.assertRaises(ValueError): verify_records(record)
        for key, value in [('submit_errno', 0), ('submit_errno', errno.EIO), ('result_errno', 0)]:
            record = fixture(); record['cases'][0]['scan_initialize_rejections'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): verify_records(record)


def confirmed_fixture():
    record=fixture();record.update(format_version=3,confirmed_off=True,synthetic_support=True,status='QUEUED_CONFIRMED_OFF_INITIALIZE_RELEASE_SYNTHETIC_SUPPORT_PASS',bootstrap=[])
    ready=[]
    for index,raw in enumerate(record['initial_snapshots']):
        snap=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(raw));generation=snap.generation
        adv=SleDiscoveryResult(version=1,generation=generation,request_id=1000,profile=1,dev_index=index,operation=5,state=3,count=2,step=1,opcode=0xc05,radio_adv=1,power_valid=1,selected_power=-42)
        scan=SleDiscoveryResult(version=1,generation=generation,request_id=1001,profile=1,dev_index=index,operation=6,state=3,count=3,step=2,opcode=0x1002,radio_adv=1,radio_scan=1)
        prepared=SleControllerSnapshot.from_buffer_copy(bytes(snap));prepared.flags=1;ready.append(bytes(prepared).hex())
        record['bootstrap'].append(dict(bootstrap=True,index=index,start_wall_ns=100_000_000+index*100_000_000,end_wall_ns=150_000_000+index*100_000_000,advertising_input=bytes(standby(snap,1000,'advertising')).hex(),scanning_input=bytes(standby(snap,1001,'scanning')).hex(),advertising_result=bytes(adv).hex(),scanning_result=bytes(scan).hex(),ready_snapshot=ready[-1],radio=bytes(SleDiscoveryResult(version=1,generation=generation,profile=1,dev_index=index,radio_adv=1,radio_scan=1)).hex()))
    for n,row in enumerate(record['cases']):
        i=row['index'];generation=row['generation'];row.update(scan_initialize_rejections=[],snapshot_before=ready[i],snapshot_after=ready[i],peer_before=ready[1-i],peer_after=ready[1-i])
        row['radio_before']=row['radio_after']=bytes(SleDiscoveryResult(version=1,generation=generation,profile=1,dev_index=i,radio_adv=1,radio_scan=1)).hex()
        for key,state,error in [('queued',1,0),('cancelled',5,-errno.ECANCELED)]:
            row[key]=[bytes(SleDiscoveryResult(version=1,generation=generation,request_id=(n%3)*2+1+domain,profile=1,dev_index=i,operation=(5,6)[domain],count=(2,3)[domain],state=state,error=error,radio_adv=1,radio_scan=1)).hex() for domain in [0,1]]
    return record


def confirmed_capture(record):
    cap={k:[] for k in ['commands','complete','failures']}
    for index,row in enumerate(record['bootstrap']):
        snap=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(record['initial_snapshots'][index]));adv=bytearray(49);adv[12:18]=bytes(snap.address)
        for n,(opcode,params) in enumerate([(0xc02,adv.hex()),(0xc05,'0000000000'),(0x1001,'0000010040062003'),(0x1002,'0100'),(0x1002,'0000')]):
            wall=row['start_wall_ns']+n*1000+1;cmd=dict(bus=1,device=index+2,opcode=opcode,params=params,wall_ns=wall,completion=dict(wall_ns=wall+1));cap['commands'].append(cmd)
            cap['complete'].append(dict(bus=1,device=index+2,opcode=opcode,status=0,value='d6' if n==0 else '',wall_ns=wall+2))
    return cap


class ConfirmedOffTests(unittest.TestCase):
    def test_full_initialization_queue_two_roles_all_fd_cases_and_wire(self):
        record=confirmed_fixture();verify_records(record);proof=corroborate(record,confirmed_capture(record))
        self.assertTrue(proof['confirmed_off']);self.assertEqual(len(proof['bootstrap']),10)
        self.assertFalse(proof['managed_preselection_live_acceptance']);self.assertFalse(proof['managed_unknown_setup_preselection_live_acceptance'])
        self.assertFalse(proof['active_ready_peer_isolation_acceptance']);self.assertFalse(proof['normal_scheduler_concurrency_acceptance'])

    def test_missing_failed_or_fabricated_bootstrap_is_rejected(self):
        for change in ['missing','failed','ready','radio','scanstop','time','scope','format']:
            r=confirmed_fixture()
            if change=='missing':r['bootstrap'].pop()
            if change=='failed':
                v=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(r['bootstrap'][0]['scanning_result']));v.status=11;r['bootstrap'][0]['scanning_result']=bytes(v).hex()
            if change=='ready':r['bootstrap'][0]['ready_snapshot']=r['initial_snapshots'][0]
            if change=='radio':r['bootstrap'][0]['radio']=r['cases'][1]['queued'][0]
            if change=='scanstop':
                v=SleDiscoveryResult.from_buffer_copy(bytes.fromhex(r['cases'][0]['queued'][1]));v.operation=4;v.count=1;r['cases'][0]['queued'][1]=bytes(v).hex()
            if change=='time':r['bootstrap'][0]['end_wall_ns']=r['cases'][0]['start_wall_ns']+1
            if change=='scope':r['confirmed_off']=1
            if change=='format':r['format_version']=2
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(r)

    def test_original_start_stop_reply_order_and_payload_are_required(self):
        for change in ['missing','status','start','duplicate','power','gap','bootstrap-gap','extra-reply','failed-transfer']:
            r=confirmed_fixture();cap=confirmed_capture(r)
            if change=='missing':cap['complete'].pop(3)
            if change=='status':cap['complete'][4]['status']=11
            if change=='start':cap['commands'][3]['params']='0000'
            if change=='duplicate':cap['complete'].append(dict(cap['complete'][4]))
            if change=='power':cap['complete'][0]['value']='00'
            if change=='extra-reply':cap['complete'].append(dict(cap['complete'][0],opcode=0x406))
            if change=='failed-transfer':cap['failures'].append(dict(cap['complete'][0],status=-5))
            if change=='bootstrap-gap':cap['commands'].append(dict(cap['commands'][0],wall_ns=r['bootstrap'][0]['end_wall_ns']+1))
            if change=='gap':cap['commands'].append(dict(cap['commands'][0],wall_ns=r['cases'][1]['start_wall_ns']-1))
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(r,cap)
