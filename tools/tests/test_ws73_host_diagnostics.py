# SPDX-License-Identifier: GPL-2.0-only
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_host_diagnostics import classify, journal_port, snapshot, usb_journal


class HostDiagnosis(unittest.TestCase):
    def test_controller_errors_are_retained_without_inventing_port_owner(self):
        row={'MESSAGE':'xhci_hcd 0000:c5:00.3: Timeout while waiting for setup device command',
             '__REALTIME_TIMESTAMP':'9','__MONOTONIC_TIMESTAMP':'3'}
        self.assertEqual(usb_journal(json.dumps(row),['1-2.1.4']),[])
        records=usb_journal(json.dumps(row),['1-2.1.4'],['0000:c5:00.3'])
        self.assertEqual(records[0]['ports'],[])
        self.assertEqual(records[0]['controllers'],['0000:c5:00.3'])

    def test_exact_device_and_hub_port_ownership(self):
        self.assertTrue(journal_port('usb 1-2.1.4: device not accepting address 93, error -62', '1-2.1.4'))
        self.assertTrue(journal_port('usb 1-2.1-port4: unable to enumerate USB device', '1-2.1.4'))
        for message in ['usb 1-2.1.40: disconnect', 'usb 1-2.1.4.1: disconnect', 'usb 1-2.1-port40: failed', 'usb 1-2.1.3: disconnect']:
            self.assertFalse(journal_port(message, '1-2.1.4'))

    def test_journal_timestamps_and_ownership(self):
        row={'MESSAGE': 'usb 1-2.1-port4: unable to enumerate USB device', '__REALTIME_TIMESTAMP': '9', '__MONOTONIC_TIMESTAMP': '3', '_BOOT_ID':'a'}
        self.assertEqual(usb_journal(json.dumps(row), ['1-2.1.4'])[0]['wall_us'], 9)
        self.assertEqual(usb_journal(json.dumps(row), ['1-2.1.3']), [])
        row.pop('__MONOTONIC_TIMESTAMP')
        with self.assertRaises(ValueError): usb_journal(json.dumps(row), ['1-2.1.4'])

    def test_failure_does_not_invent_electrical_root_cause(self):
        rows=[{'ports':['1-2.1.4'],'wall_us':1,'message':'usb 1-2.1-port4: unable to enumerate USB device'}]
        self.assertEqual(classify('1-2.1.4', {'present':False}, rows, True), 'ABSENT_LAST_ENUMERATION_FAILED_BEFORE_DRIVER')
        self.assertEqual(classify('1-2.1.4', {'present':False}, rows, False), 'ABSENT_CAUSE_UNOBSERVED')
        self.assertEqual(classify('1-2.1.3', {'present':False}, rows, True), 'ABSENT_CAUSE_UNOBSERVED')

    def test_later_enumeration_supersedes_old_failure(self):
        rows=[{'ports':['1-2.1.4'],'wall_us':1,'message':'unable to enumerate USB device'},
              {'ports':['1-2.1.4'],'wall_us':2,'message':'New USB device found'}]
        self.assertEqual(classify('1-2.1.4', {'present':False}, rows, True), 'ABSENT_CAUSE_UNOBSERVED')

    def test_presence_is_not_ready_and_foreign_device_not_ws73(self):
        row={'present':True,'idVendor':'ffff','idProduct':'3733','interfaces':[{'driver':None}]}
        self.assertEqual(classify('1-2.1.4',row,[],False),'WS73_PRESENT_UNBOUND')
        row['interfaces'][0]['driver']='sparklink_ws73_usb'
        self.assertEqual(classify('1-2.1.4',row,[],False),'WS73_PRESENT_DRIVER_BOUND')
        row['idVendor']='0000'
        self.assertEqual(classify('1-2.1.4',row,[],True),'PRESENT_OTHER_DEVICE')

    def test_snapshot_preserves_hub_state_without_device(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);p=root/'1-2.1:1.0/1-2.1-port4';p.mkdir(parents=True)
            (p/'state').write_text('default\n');(p/'over_current_count').write_text('0\n')
            row=snapshot('1-2.1.4',root)
            self.assertFalse(row['present']);self.assertEqual(row['hub_port_state'],'default')
            self.assertEqual(row['hub_port_over_current_count'],'0');self.assertTrue(row['errors'])
        with self.assertRaises(ValueError): snapshot('../other')
