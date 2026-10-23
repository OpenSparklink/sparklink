# SPDX-License-Identifier: GPL-2.0-only
"""Offline File-gate ABI/authorization checks; no device or RF acceptance."""
import ctypes
import copy
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_connected_file_gate import duplicate_result, verify_records, connection, stop, bound_disconnect, mutate_reference, ConnectedHoldCoordinator, ConnectedOutcomeCoordinator, announcement
from ws73_diagnostic_hold import PROPERTIES
from ws73_host_later_hold import SELECTORS
from sparklink.structs import SleConnectionResult, SleControllerSnapshot, SleDiscoverySubmit, SleManagementQuery, SleLinkInfo, SleConnectionSubmit


class ConnectedFileGate(unittest.TestCase):
    def test_existing_announcement_already_uses_negotiable_t_without_new_wire_path(self):
        snapshot=SleControllerSnapshot(generation=7)
        snapshot.address[:]=bytes.fromhex('a67b7310e001')
        value=announcement(snapshot,'00112233445566778899aabbccddeeff')
        self.assertEqual((value.version,value.operation,value.generation),(1,1,7))
        p=value.advertising
        self.assertEqual((p.mode,p.gt_role,p.max_requests,p.conn_interval_min,p.conn_interval_max),(3,0,1,100,100))
        self.assertEqual(bytes(p.own_address),bytes(snapshot.address))
        self.assertEqual((p.interval_min,p.interval_max,p.channel_map,p.tx_power,p.supervision_timeout),(1200,1200,7,127,200))

    def test_disconnect_reference_uses_full_v2_tuple_and_bounded_mutations(self):
        snapshot=SleControllerSnapshot(generation=7)
        link=SleLinkInfo(lifetime=3,handle=12,role=1,address_type=0)
        link.address[:]=bytes.fromhex('0001093254f9')
        value=bound_disconnect(snapshot,link,901)
        self.assertEqual(ctypes.sizeof(value),128)
        self.assertEqual((value.version,value.operation,value.generation,value.handle,value.expected_lifetime,value.expected_role,value.expected_address_type,value.reason),(2,2,7,12,3,1,0,0x10))
        self.assertEqual(bound_disconnect(snapshot,link,901,reason=0x13).reason,0x13)
        for invalid in [True,False,0,0x11,256,'16']:
            with self.subTest(reason=invalid),self.assertRaises(ValueError):bound_disconnect(snapshot,link,901,reason=invalid)
        self.assertEqual(bytes(value.expected_address),bytes(link.address))
        self.assertEqual(bytes(value.parameters),bytes(ctypes.sizeof(value.parameters)))
        for mutation in ['lifetime','type','address','role','zero','generation','version']:
            changed=SleConnectionSubmit.from_buffer_copy(bytes(value));mutate_reference(changed,mutation)
            self.assertNotEqual(bytes(changed),bytes(value))
        with self.assertRaises(ValueError):mutate_reference(value,'success')

    def test_coordinator_targets_selected_real_owner_not_global_first_device(self):
        for n in [0,1]:
            for cls in [ConnectedHoldCoordinator,ConnectedOutcomeCoordinator]:
                coordinator=cls('/evidence',{},n)
                self.assertEqual(coordinator.path,f'/machine/peripheral/ws73_{n}')
                self.assertEqual(coordinator.folder,Path('/evidence/connected-file'))

    def test_offline_inflight_cancel_cannot_become_success_or_invent_outcome(self):
        original=json.loads((Path(__file__).parent/'data/connected_file_record.json').read_text())
        for phase,state,flags in [('status',2,0),('outcome',3,1)]:
            r=copy.deepcopy(original);r.update(status='INFLIGHT_FILE_PASS',reply_hold=phase)
            if phase=='status':
                snapshot=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(r['before_snapshots'][0]));snapshot.command_credits=0;r['before_snapshots'][0]=bytes(snapshot).hex()
            value=SleConnectionResult.from_buffer_copy(bytes.fromhex(r.pop('connected')));value.state=state;value.flags=flags;value.handle=0
            r['pending']=bytes(value).hex();value.state=6;value.error=-errno.ECANCELED;r['cancelled']=bytes(value).hex()
            value.flags=7;value.handle=int.from_bytes(bytes.fromhex(r['up'][0]['params'])[1:3],'little');r['author_result_after_release']=bytes(value).hex()
            q=SleManagementQuery.from_buffer_copy(bytes.fromhex(r['free']));q.state=2;r['revoking']=bytes(q).hex()
            r['markers']=[dict(hold_phase=k,wall_ns=t) for k,t in zip(['arm_ready','wait_held','release_ready'],
                [r['connect_before_wall_ns']-1,(r['connect_before_wall_ns']+r['release_before_wall_ns'])//2,r['release_after_wall_ns']+1])]
            r['hold_acknowledgements']=[]
            for n,marker in enumerate(r['markers']):
                q=dict(zip(PROPERTIES,[n==0,n==1,int(n>0),int(n==2),0,0,False,0]))
                if phase=='outcome':q.update(dict(zip(SELECTORS,[1,1 if n==0 else 0,0 if n==0 else 1])))
                r['hold_acknowledgements'].append(dict(stage=['armed','held','released'][n],request=marker,state=q,host_wall_ns=marker['wall_ns']+1))
            self.assertEqual(len(verify_records(r)),2)
            for field in ['cancelled','author_result_after_release']:
                bad=copy.deepcopy(r);v=SleConnectionResult.from_buffer_copy(bytes.fromhex(bad[field]));v.state=4;v.error=0;bad[field]=bytes(v).hex()
                with self.subTest(phase=phase,field=field),self.assertRaises(ValueError):verify_records(bad)
            bad=copy.deepcopy(r);bad['hold_acknowledgements'][1]['state']['test-runtime-in-hold-drops']=1
            with self.assertRaises(ValueError):verify_records(bad)

    def test_recorded_uapi_fixture_is_only_offline_verification(self):
        r=json.loads((Path(__file__).parent/'data/connected_file_record.json').read_text())
        self.assertEqual(r['fixture_scope'],'ADAPTED_V2_UAPI_UNIT_FIXTURE_NOT_LIVE_ACCEPTANCE')
        self.assertEqual(len(verify_records(r)),2)
        changes=[('connected','00'*64),('peer_after','00'*48),('free','00'*48),
            ('author_result_after_release',None),('case','dup'),('scan_match',dict(r['scan_match'],elapsed_ms=10000)),
            ('discovery',r['discovery'][:-1]),('after_snapshots',r['initial_snapshots'])]
        for key,value in changes:
            bad=copy.deepcopy(r);bad[key]=value
            with self.subTest(key=key),self.assertRaises((ValueError,KeyError)):verify_records(bad)
        for key in ['up','down']:
            bad=copy.deepcopy(r);bad[key][0]['lost']=1
            with self.subTest(key=key),self.assertRaises(ValueError):verify_records(bad)

    def test_stop_has_no_unrelated_scanning_or_advertising_fields(self):
        s=SleControllerSnapshot(generation=7)
        for operation in [2,4]:
            value=stop(s,104,operation)
            self.assertEqual(bytes(value),bytes(SleDiscoverySubmit(version=1,profile=1,generation=7,request_id=104,operation=operation)))
        with self.assertRaises(ValueError):stop(s,104,3)

    def test_duplicate_result_matches_canonical_kernel_ioctl(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'abi.c';binary=Path(folder)/'abi'
            source.write_text('#include <stdio.h>\n#include <linux/sparklink_ioctl.h>\nint main(void){printf("%lu",(unsigned long)SL_IOCTL_CONNECTION_RESULT);}\n')
            kernel=Path(os.environ.get('SPARKLINK_KERNEL_SOURCE',Path(__file__).resolve().parents[3]/'linux'))
            subprocess.run(['cc','-I',str(kernel/'include/uapi'),str(source),'-o',str(binary)],check=True,capture_output=True)
            expected=int(subprocess.check_output([str(binary)]))
            def ioctl(fd,number,raw,mutable):
                self.assertEqual((fd,number,mutable),(123,expected,True))
                value=SleConnectionResult.from_buffer_copy(raw)
                self.assertEqual((value.version,value.generation,value.request_id),(1,7,900))
                value.state=4;raw[:]=bytes(value)
            with patch('ws73_connected_file_gate.fcntl.ioctl',side_effect=ioctl):
                self.assertEqual(duplicate_result(123,7,900).state,4)

    def test_dev_null_does_not_become_success(self):
        fd=os.open('/dev/null',os.O_RDONLY)
        try:
            with self.assertRaises(OSError) as caught:duplicate_result(fd,7,900)
            self.assertEqual(caught.exception.errno,errno.ENOTTY)
        finally:os.close(fd)

    def test_incomplete_synthetic_or_daemon_claim_rejected(self):
        for changes in [{},{'index':True},{'format_version':True},{'daemon_running':True},
                {'physical_acceptance':True},{'automatic_recovery_acceptance':True},{'synthetic_support':True}]:
            r=dict(format_version=1,status='CONNECTED_FILE_PASS',case='release',index=0,daemon_running=False,
                synthetic_support=False,physical_acceptance=False,automatic_recovery_acceptance=False)
            r.update(changes)
            with self.assertRaises((ValueError,KeyError)):verify_records(r)

    def test_real_typed_create_is_not_test_key_or_event_injection(self):
        a=SleControllerSnapshot(generation=7);b=SleControllerSnapshot(generation=8)
        b.address[:]=bytes.fromhex('0001093254f9');request=connection(a,b)
        self.assertEqual((request.version,request.profile,request.operation,request.generation,request.request_id,request.timeout_ms),(2,1,1,7,900,10000))
        self.assertEqual(bytes(request.parameters.peer_address),bytes(b.address))
        self.assertEqual((request.parameters.gt_negotiate,request.parameters.frame),(1,1))
        self.assertEqual(ctypes.sizeof(SleConnectionResult),64)


if __name__=='__main__':unittest.main()
