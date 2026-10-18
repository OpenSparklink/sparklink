# SPDX-License-Identifier: GPL-2.0-only
"""Request/scope rejection fixtures; never running-kernel or RF acceptance."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_resource_file_gate import announcement, verify_records
from sparklink.structs import SleControllerSnapshot
from ws73_capture import marker_data

class ResourceGateBounds(unittest.TestCase):
    def test_explicit_changed_request_has_real_marker_and_same_identity(self):
        s=SleControllerSnapshot(generation=7,dev_index=0)
        s.address[:]=bytes.fromhex('0001093254f9')
        marker='ab'*16;r=announcement(s,marker)
        self.assertEqual((r.generation,r.request_id,r.operation,r.advertising.mode,r.advertising.gt_role),(7,1,1,3,0))
        self.assertEqual(bytes(r.data[:r.data_len]),marker_data(marker))
        self.assertEqual(bytes(r.advertising.own_address),bytes(s.address))
        self.assertFalse(any(r.data[r.data_len:]))

    def test_incomplete_or_synthetic_claims_do_not_qualify_resource_gate(self):
        for changes in [{},{'status':'PASS'},{'physical_acceptance':True},{'synthetic_support':True},
                        {'initialization_step':True},{'initialization_step':2},{'format_version':True},
                        {'case':'other'},{'selected_domain_cleanup':False}]:
            record=dict(format_version=1,status='RESOURCE_FILE_HELD_REPLY_PASS',resource_recreation=True,
                synthetic_support=False,active_ready_peer=True,daemon_running_during_hold=False,
                physical_acceptance=False,automatic_fault_recovery_acceptance=False,case='release',
                selected_domain_cleanup=True,initialization_step=0)
            record.update(changes)
            with self.subTest(changes=changes), self.assertRaises((ValueError,KeyError)):
                verify_records(record)

class CanonicalResourceRecordTests(unittest.TestCase):
    def setUp(self):
        import json
        self.record=json.loads((Path(__file__).parent/'data/resource_file_remove_record.json').read_text())

    def test_recorded_removed_set_uses_revoking_mode_zero_and_setup_flags(self):
        verify_records(self.record)  # DTO only; original VM100 was not accepted.

    def test_wrong_revoking_mode_and_fake_ready_are_rejected(self):
        import copy
        from ws73_management_setup import decode
        from sparklink.structs import SleManagementQuery,SleControllerSnapshot
        for key,kind,field,value in [('revoking',SleManagementQuery,'mode',1),
                                      ('final_snapshot',SleControllerSnapshot,'flags',1),
                                      ('final_snapshot',SleControllerSnapshot,'flags',0)]:
            changed=copy.deepcopy(self.record);raw=decode(kind,changed[key]);setattr(raw,field,value);changed[key]=bytes(raw).hex()
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):verify_records(changed)

    def test_host_usb_address_cannot_replace_guest_registration(self):
        import copy
        for usb in [dict(port='1-1',bus=1,device=120),dict(port='1-2',bus=1,device=2),
                    dict(port='1-1',bus=True,device=2)]:
            r=copy.deepcopy(self.record);r['target_usb']=usb
            with self.subTest(usb=usb),self.assertRaises(ValueError):verify_records(r)
