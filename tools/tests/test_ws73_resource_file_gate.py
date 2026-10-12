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
