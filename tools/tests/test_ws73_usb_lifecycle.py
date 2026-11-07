# SPDX-License-Identifier: GPL-2.0-only
"""Visible QEMU metadata fixtures only; no real callback, USB or drain proof."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_usb_lifecycle as life
from ws73_capture import CaptureError


def trace(*events):
    return ''.join(f'1@1.{i:06d}:{event}\n'for i,event in enumerate(events,1))


DATA='usb_host_req_data dev 1:18, packet 0x1, in 1, ep 1, size 20480'
COMPLETE='usb_host_req_complete dev 1:18, packet 0x1, status 0, length 178'
CANCEL='usb_host_req_canceled dev 1:18, packet 0x1'
CONTROL='usb_host_req_control dev 1:18, packet 0x1, req 0x5, value 2, index 0'
EMULATED='usb_host_req_emulated dev 1:18, packet 0x1, status 0'
TARGET={(1,18)}


class Lifecycle(unittest.TestCase):
    def test_data_complete_and_cancel_are_distinct_from_physical_drain(self):
        proof=life.parse(trace(DATA,COMPLETE,DATA,CANCEL),TARGET)
        self.assertEqual(proof['status'],'LOGICAL_USB_REQUESTS_CLOSED')
        self.assertEqual(proof['terminal_counts'],dict(QEMU_COMPLETION=1,LOGICAL_CANCEL=1))
        self.assertEqual(len(proof['requests']),2)
        self.assertFalse(proof['physical_drain_qualified'])
        self.assertFalse(proof['credit_truth_qualified'])
        self.assertTrue(all(r['terminal']['physical_obligation_closed']is False for r in proof['requests']))

    def test_control_emulation_and_data_pointer_reuse_have_typed_incarnations(self):
        proof=life.parse(trace(CONTROL,EMULATED,DATA,CANCEL,CONTROL,EMULATED,DATA,COMPLETE),TARGET)
        self.assertEqual([r['kind']for r in proof['requests']],['CONTROL','DATA','CONTROL','DATA'])
        self.assertEqual(proof['terminal_counts']['EMULATED_CONTROL_RETURN'],2)
        self.assertEqual(proof['endpoint_logical_peaks'][0]['peak'],1)
        self.assertEqual(proof['status'],'LOGICAL_USB_REQUESTS_CLOSED')
        with self.assertRaises(CaptureError):life.parse(trace(DATA,EMULATED),TARGET)

    def test_missing_cancel_cannot_silently_overwrite_a_live_pointer(self):
        with self.assertRaises(CaptureError):life.parse(trace(DATA,DATA,COMPLETE),TARGET)
        proof=life.parse(trace(DATA),TARGET)
        self.assertEqual(proof['pending'],1)
        self.assertTrue(proof['status'].startswith('INCOMPLETE'))

    def test_late_or_duplicate_terminal_remains_unknown_not_control_success(self):
        for extra in(CANCEL,COMPLETE,EMULATED):
            with self.subTest(extra=extra):
                proof=life.parse(trace(DATA,COMPLETE,extra),TARGET)
                self.assertTrue(proof['status'].startswith('INCOMPLETE'))
                self.assertEqual(sum(proof['unmapped_without_observed_request'].values()),1)
                self.assertEqual(proof['terminal_counts']['QEMU_COMPLETION'],1)

    def test_error_return_is_not_success_and_two_devices_are_separate(self):
        second=DATA.replace('1:18','1:19')
        failure=COMPLETE.replace('status 0, length 178','status -1, length 0')
        proof=life.parse(trace(DATA,second,failure,CANCEL.replace('1:18','1:19')),{(1,18),(1,19)})
        self.assertEqual(proof['requests'][0]['terminal']['status'],-1)
        self.assertEqual(proof['requests'][1]['terminal']['kind'],'LOGICAL_CANCEL')
        self.assertEqual(proof['pending'],0)

    def test_malformed_truncated_wrong_identity_and_budget_fail_closed(self):
        for text in(trace(DATA)[:-1],trace(DATA.replace('packet 0x1','packet 0x0')),
                    trace(DATA.replace('size 20480','size 0')),trace(DATA.replace('ep 1','ep 0')),
                    trace(DATA.replace('dev 1:18','dev 1:19')),trace(DATA,COMPLETE.replace('length 178','length 20481')),
                    trace(DATA,COMPLETE.replace('status 0','status 1')),'not-a-trace\n'):
            with self.subTest(text=text),self.assertRaises(CaptureError):life.parse(text,TARGET)
        for field,value in(('BYTE_LIMIT',2),('LINE_LIMIT',1),('REQUEST_LIMIT',1),('PENDING_LIMIT',1),('REPORT_LIMIT',1)):
            with self.subTest(field=field),patch.object(life,field,value),self.assertRaises(CaptureError):
                life.parse(trace(DATA,COMPLETE,DATA.replace('0x1','0x2'),DATA),TARGET)

    def test_existing_collector_must_include_independent_control_cancel_markers(self):
        from ws73_target import USB_LIFECYCLE_EVENTS,lifecycle_trace
        expected={'usb_host_req_control','usb_host_req_emulated','usb_host_req_canceled'}
        self.assertTrue(expected<=set(USB_LIFECYCLE_EVENTS))
        with tempfile.TemporaryDirectory()as directory:
            for missing in expected:
                available='\n'.join(e for e in USB_LIFECYCLE_EVENTS if e!=missing)
                with self.subTest(missing=missing),patch('subprocess.check_output',return_value=available),self.assertRaises(ValueError):
                    lifecycle_trace(Path('/fixture/qemu'),Path(directory))

    def test_actual_file_reader_manifest_and_event_closure_without_a_VM_stub(self):
        import hashlib,json
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);events=root/'usb-lifecycle.events';log=root/'usb-lifecycle.log'
            events.write_text('\n'.join(sorted(life.REQUIRED))+'\n');log.write_text(trace(CONTROL,EMULATED,DATA,CANCEL))
            manifest=dict(status='FAIL',qemu_exit=0,native_vm=dict(fixture='metadata only'),
                synthetic_empty_bulk=False,synthetic_hotplug=False,synthetic_warm=False,
                artificial_guest_transport_fault=False,early_bootstrap_fault_requested=False,
                physical_resource_allocation=dict(selected_ports=['fixture-leaf']),
                inventory_before={'fixture-leaf':dict(bus=1,address=18)},
                host_lifecycle_files=[dict(path='/original/'+p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())for p in(events,log)])
            (root/'manifest.json').write_text(json.dumps(manifest))
            proof=life.analyze(root)
            self.assertFalse(proof['original_gate_qualified'])
            self.assertEqual(proof['logical']['status'],'LOGICAL_USB_REQUESTS_CLOSED')
            for field,value in(('qemu_exit',False),('qemu_exit',None),('synthetic_warm',True),('native_vm',None)):
                bad=manifest|{field:value};(root/'manifest.json').write_text(json.dumps(bad))
                with self.subTest(field=field,value=value),self.assertRaises(CaptureError):life.analyze(root)
            (root/'manifest.json').write_text(json.dumps(manifest));events.write_text('usb_host_req_data\nusb_host_req_complete\n')
            manifest['host_lifecycle_files'][0]['sha256']=hashlib.sha256(events.read_bytes()).hexdigest()
            (root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(CaptureError,'event contract'):life.analyze(root)

    def test_result_budget_covers_real_pretty_output_not_only_compact_json(self):
        import json
        value={'requests':[{'kind':'DATA','nested':{'result':'pending'}}for _ in range(8)]}
        compact=len(json.dumps(value).encode())
        actual=(json.dumps(value,indent=2)+'\n').encode()
        self.assertGreater(len(actual),compact)
        with patch.object(life,'REPORT_LIMIT',compact+1),self.assertRaises(CaptureError):life.encoded_report(value)
        with patch.object(life,'REPORT_LIMIT',len(actual)):
            self.assertEqual(life.encoded_report(value).encode(),actual)
        with patch.object(life,'REPORT_LIMIT',len(actual)-1),self.assertRaises(CaptureError):life.encoded_report(value)
