# SPDX-License-Identifier: GPL-2.0-only
import copy
import ctypes
import errno
import json
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ws73_active_deadline import ActiveDeadlineCoordinator, corroborate, verify_records
from ws73_diagnostic_hold import PROPERTIES
from sparklink.structs import SleControllerSnapshot, SleDiagnosticResult, SleDiagnosticSubmit
from test_ws73_diagnostic_hold import Monitor


def fixture():
    target = SleControllerSnapshot(version=1, generation=1, flags=1, profile=1, valid_fields=1)
    peer = SleControllerSnapshot(version=1, generation=2, flags=1, profile=1, valid_fields=1, dev_index=1)
    peer.address[:] = b'123456'
    command = SleDiagnosticSubmit(version=1, generation=1, request_id=1, timeout_ms=500, opcode=0x0406, action=1)
    original = bytes(command).hex(); command.seq = 1
    pending = SleDiagnosticResult(version=1, generation=1, seq=1, state=1, opcode=0x0406)
    markers = [{'hold_phase': phase, 'wall_ns': stamp} for phase, stamp in
               [('arm_ready',100),('wait_held',200),('abort_ready',300)]]
    acks = []
    for i, marker in enumerate(markers):
        acks.append({'stage':['armed','held','aborted'][i], 'request':marker,
                     'host_wall_ns':marker['wall_ns']+1010,
                     'state':dict(zip(PROPERTIES,[i==0,i==1,int(i>0),0,0,int(i==2),False,0]))})
    queries = []
    for i, (start, end) in enumerate([(10,90),(320,400)]):
        output = SleDiagnosticSubmit(version=1, generation=2, request_id=i+1, timeout_ms=5000,
                                     opcode=0x0406, seq=i+1, action=1)
        result = SleDiagnosticResult(version=1, generation=2, seq=i+1, state=2, opcode=0x0406, data_len=6)
        result.data[:6] = peer.address
        queries.append({'output':bytes(output).hex(),'result':bytes(result).hex(),'start_wall_ns':start,'end_wall_ns':end})
    return {'format_version':1,'status':'ACTIVE_DEADLINE_PRE_DAEMON_PASS','physical_acceptance':False,
            'automatic_fault_recovery_acceptance':False,'daemon_running_during_hold':False,
            'target_snapshot':bytes(target).hex(),'peer_snapshots':[bytes(peer).hex()]*2,
            'input':original,'output':bytes(command).hex(),'initial_result':bytes(pending).hex(),
            'submit_before_monotonic_ns':1_000_000_000,'submit_after_monotonic_ns':1_001_000_000,
            'quiet_before_monotonic_ns':1_020_000_000,'quiet_after_monotonic_ns':1_550_000_000,
            'submit_before_wall_ns':150,'submit_after_wall_ns':160,
            'host_hold_acknowledgements':acks,'markers':markers,'peer_queries':queries,
            'guest_ack_receipts':[{'stage':stage,'wall_ns':wall,'monotonic_ns':mono} for stage,wall,mono in
                                  [('armed',110,900_000_000),('held',210,1_010_000_000),('aborted',310,1_549_000_000)]],
            'retired_result_errno':errno.ENODEV,'retired_submit_errno':errno.ENODEV}


class ActiveDeadlineTests(unittest.TestCase):
    def test_exact_fixture_is_only_record_validation(self):
        verify_records(fixture())
        self.assertEqual(ctypes.sizeof(SleDiagnosticResult),104)

    def test_old_release_downgrade_or_bounded_release_is_rejected(self):
        for field, value in [('test-runtime-in-releases',1),('test-runtime-in-bounded-releases',1),
                             ('test-runtime-in-hold-drops',0),('test-runtime-in-hold-drops',2),
                             ('test-runtime-in-holds',2),('test-runtime-in-errors',1)]:
            with self.subTest(field=field,value=value):
                record=fixture();record['host_hold_acknowledgements'][-1]['state'][field]=value
                with self.assertRaises(ValueError):verify_records(record)

    def test_wrong_original_request_pending_and_stale_retry_fail(self):
        for field in ['input','output','initial_result','peer_snapshots']:
            record=fixture()
            if field=='peer_snapshots':record[field][1]='00'*ctypes.sizeof(SleControllerSnapshot)
            else:record[field]='00'*(len(record[field])//2)
            with self.subTest(field=field),self.assertRaises(ValueError):verify_records(record)
        for field in ['retired_result_errno','retired_submit_errno']:
            record=fixture();record[field]=errno.EBUSY
            with self.subTest(field=field),self.assertRaises(ValueError):verify_records(record)

    def test_causal_clocks_real_hold_and_peer_intervals_are_required(self):
        mutations=[('quiet_after_monotonic_ns',1_010_000_000),('quiet_after_monotonic_ns',4_000_000_000),
                   ('quiet_before_monotonic_ns',1_500_000_000),('submit_after_wall_ns',210),
                   ('format_version',True),('daemon_running_during_hold',True)]
        for field,value in mutations:
            record=fixture();record[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify_records(record)
        record=fixture();record['peer_queries'][1]['start_wall_ns']=305
        with self.assertRaises(ValueError):verify_records(record)
        record=fixture();record['host_hold_acknowledgements'][2]['state'][PROPERTIES[5]]=True
        with self.assertRaises(ValueError):verify_records(record)

    def setup_hold(self, temporary):
        hold=ActiveDeadlineCoordinator(temporary,{});monitor=Monitor();hold.folder.mkdir()
        for phase,stamp in [('arm_ready',100),('wait_held',200)]:
            (hold.folder/f'hold-{phase}.json').write_text(json.dumps({'hold_phase':phase,'wall_ns':stamp}))
            if phase=='wait_held':monitor.state.update({'test-runtime-in-hold-once':False,'test-runtime-in-held':True,'test-runtime-in-holds':1})
            hold.poll(monitor)
        (hold.folder/'hold-abort_ready.json').write_text(json.dumps({'hold_phase':'abort_ready','wall_ns':300}))
        return hold,monitor

    def test_coordinator_waits_for_actual_abort_without_releasing(self):
        with tempfile.TemporaryDirectory() as temporary:
            hold,monitor=self.setup_hold(temporary);hold.poll(monitor)
            self.assertFalse(hold.record['complete']);self.assertEqual(hold.phase,'abort_ready')
            monitor.state.update({'test-runtime-in-held':False,'test-runtime-in-hold-drops':1})
            hold.poll(monitor);hold.poll(monitor)
            self.assertTrue(hold.record['complete']);self.assertEqual(len(monitor.sets),1)
            self.assertEqual([v['stage'] for v in hold.record['observations']],['armed','held','aborted'])

    def test_coordinator_rejects_release_extra_drop_or_detach(self):
        for field,value in [('test-runtime-in-releases',1),('test-runtime-in-bounded-releases',1),
                            ('test-runtime-in-hold-drops',2),('attached',False)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temporary:
                hold,monitor=self.setup_hold(temporary)
                monitor.state.update({'test-runtime-in-held':False,'test-runtime-in-hold-drops':1})
                (monitor.options if field=='attached' else monitor.state)[field]=value
                with self.assertRaises(ValueError):hold.poll(monitor)
                self.assertEqual(len(monitor.sets),1)

    def test_records_and_counters_alone_cannot_qualify_a_live_abort(self):
        record=fixture();host={'method':'QMP_HOLD_ACTUAL_IN81_UNTIL_NATIVE_RETIREMENT','complete':True,
                               'observations':copy.deepcopy(record['host_hold_acknowledgements'])}
        capture={'commands':[],'reports':[],'complete':[]}
        with self.assertRaises(ValueError):corroborate(record,host,capture,'','',{'bus':1,'device':1},{'bus':1,'device':2},{'bus':9,'address':101})

    def test_wire_verifier_requires_single_target_out_peer_pairs_and_no_late_payload(self):
        record=fixture();host={'method':'QMP_HOLD_ACTUAL_IN81_UNTIL_NATIVE_RETIREMENT','complete':True,
                               'observations':copy.deepcopy(record['host_hold_acknowledgements'])}
        capture={'commands':[],'reports':[],'complete':[]}
        for device,start,finish,ordinal in [(1,180,185,3),(2,30,40,1),(2,330,340,5)]:
            capture['commands'].append({'bus':1,'device':device,'opcode':0x0406,'params':'',
                                        'wall_ns':start,'record':ordinal,'completion':{'wall_ns':finish}})
            if device==2:capture['complete'].append({'bus':1,'device':2,'opcode':0x0406,'status':0,
                                                    'wall_ns':finish+10,'record':ordinal+1,'value':b'123456'.hex()})
        stderr='WS73_TEST_RUNTIME_HOLD: dev 9:101 bytes=178 host_status=0 holds=1 sha256='+('a'*64)
        kernel='[1.500000] sparklink: sle0 USB command Host timed out\n[1.540000] sparklink_ws73_usb 1-1:1.0: native RX stopped: -110\n'
        args=(record,host,capture,stderr,kernel,{'bus':1,'device':1,'index':0,'generation':3},
              {'bus':1,'device':2,'index':1,'generation':2},{'bus':9,'address':101})
        self.assertFalse(corroborate(*args)['daemon_continuity_during_hold_qualified'])
        for mutation in ['no_peer_reply','duplicate_target','late_payload','early_reply','release','missing_retirement','host_identity','peer_replaced','target_not_replaced']:
            values=copy.deepcopy(args)
            if mutation=='no_peer_reply':values[2]['complete'].pop()
            elif mutation=='duplicate_target':values[2]['commands'].append(copy.deepcopy(values[2]['commands'][0]))
            elif mutation in ['late_payload','early_reply']:
                values[2]['complete'].append({'bus':1,'device':1,'opcode':0x0406,'status':0,'wall_ns':1000 if mutation=='late_payload' else 190,
                                             'record':7,'usb_sha256':'a'*64 if mutation=='late_payload' else 'b'*64})
            elif mutation=='release':values=(*values[:3],values[3]+'\nWS73_TEST_RUNTIME_HOLD_RELEASE:',*values[4:])
            elif mutation=='host_identity':values[-1]['address']=1
            elif mutation=='peer_replaced':values[-2]['generation']=4
            elif mutation=='target_not_replaced':values[-3]['generation']=1
            else:values=(*values[:4],'',*values[5:])
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):corroborate(*values)


if __name__=='__main__':unittest.main()
