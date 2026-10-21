# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic diagnostic negatives; never hardware evidence."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError, read_capture
from ws73_rx_gap import distribution, observe, analyze, diagnose_failed, failed_window, frozen_capture_files
from test_ws73_north_star import pcap


def events():
    return [dict(bus=1, device=2, wall_ns=t, record=i + 1, file_offset=24 + i * 80,
                 urb=42, kind=k, status=-115 if k == 'S' else 0,
                 length=20480 if k == 'S' else 0)
            for i, (t, k) in enumerate([(0, 'S'), (2000, 'C'), (3000, 'S'), (5000, 'C'), (7000, 'S')])]


def pending_fixture():
    rows=events()
    other=copy.deepcopy(rows)
    for row in other:row['device']=3
    other.extend([other[-1]|dict(wall_ns=9000,kind='C',status=0,length=0),
                  other[-1]|dict(wall_ns=10000,kind='S')])
    combined=sorted(rows+other,key=lambda r:(r['wall_ns'],r['device']))
    for i,row in enumerate(combined):row.update(record=i+1,file_offset=24+80*i)
    span=dict(version=1,quantum_ns=1000,targets=[[1,2],[1,3]],selected_records=len(combined),
              earliest={k:combined[0][k]for k in('bus','device','wall_ns','record','file_offset')},
              latest={k:combined[-1][k]for k in('bus','device','wall_ns','record','file_offset')})
    return dict(rx_urbs=combined,rx_capture_span=span,packet_count=len(combined)),[dict(owner=dict(bus=1,device=i))for i in(2,3)]


class RxGap(unittest.TestCase):
    def test_same_device_pairs_and_partial_final_window(self):
        rows = events()
        result = observe(rows, dict(bus=1, device=2), 1000, 8000)
        self.assertEqual(result['gap']['samples'], 2)
        self.assertEqual(result['gap']['p50_ns'], 1000)
        self.assertEqual(result['gap']['max_ns'], 2000)
        self.assertEqual(result['peak_observed_outstanding'], 1)
        result = observe(rows, dict(bus=1, device=2), 1000, 6000)
        self.assertEqual(result['right_censored_completions'], 1)
        self.assertEqual(result['gap']['samples'], 1)
        self.assertEqual(result['sum_gap_ns'],1000)
        self.assertEqual(result['window_fraction_without_submitted_rx'],.2)

    def test_invalid_pairing_order_error_overlap_and_empty_rejected(self):
        for kind in ['missing', 'identity', 'different-device', 'error', 'duplicate', 'parallel', 'order', 'size', 'empty']:
            rows = copy.deepcopy(events())
            if kind == 'missing': rows.pop(0)
            if kind == 'identity': rows[2]['urb'] = 43
            if kind == 'different-device': rows[2]['device'] = 3
            if kind == 'error': rows[1]['status'] = -32
            if kind == 'duplicate': rows[3]['kind'] = 'S'
            if kind == 'parallel':
                rows[1]['kind'] = 'S'; rows[1]['urb'] = 43
            if kind == 'order': rows[2]['wall_ns'] = 1000
            if kind == 'size': rows[1]['length'] = 20481
            if kind == 'empty': rows = []
            with self.subTest(kind=kind), self.assertRaises(CaptureError):
                observe(rows, dict(bus=1, device=2), 1000, 8000)
        with self.assertRaises(CaptureError): distribution([])

    def test_opt_in_usb_metadata_does_not_change_default_receipts(self):
        raw = pcap([(1, 2, 1000, b'', 'S', 0x81, -115),
                    (1, 2, 2000, b'', 'C', 0x81, 0),
                    (1, 2, 3000, b'', 'S', 0x81, -115)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.pcap'; path.write_bytes(raw)
            default = read_capture(path, [(1, 2)])
            diagnostic = read_capture(path, [(1, 2)], observe_rx=True)
            rows = diagnostic.pop('rx_urbs')
            self.assertEqual(default, diagnostic)
            self.assertEqual([r['kind'] for r in rows], ['S', 'C', 'S'])
            malformed = bytearray(raw)
            struct.pack_into('<I', malformed, 24 + 16 + 36, 1)
            path.write_bytes(malformed)
            with self.assertRaises(CaptureError): read_capture(path, [(1, 2)], observe_rx=True)

    def test_failure_export_validation_never_accepts_a_qualified_snapshot(self):
        from ws73_role_snapshot import publish,verify,verify_failed
        # File-export fixtures only, no Native/device/daemon success substitute.
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory)
            for success in (True,False):
                source=root/('source-'+str(success));source.mkdir();(source/'run.json').write_text('{"fixture":"closed bytes"}')
                dest=root/('export-'+str(success));publish(source,dest,phase=0,success=success,kind='benchmark')
                accept=verify if success else verify_failed;reject=verify_failed if success else verify
                self.assertEqual(accept(dest,phase=0,runtime_root=source,kind='benchmark')['success'],success)
                with self.assertRaises(CaptureError):reject(dest,phase=0,runtime_root=source,kind='benchmark')
                (dest/'run.json').write_text('changed')
                with self.assertRaises(CaptureError):accept(dest,phase=0,runtime_root=source,kind='benchmark')

    def test_failed_entry_requires_terminal_failure_and_never_relabels_success(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);control=root/'guest-output/application/passthrough-control';control.mkdir(parents=True)
            (control/'run.json').write_text(json.dumps(dict(status='FAIL')))
            for status,qemu in [('FAIL',None),('FAIL',1),('PASSTHROUGH_SUPPORT_PASS',0)]:
                (root/'manifest.json').write_text(json.dumps(dict(status=status,qemu_exit=qemu)))
                with self.subTest(status=status,qemu=qemu),self.assertRaises(CaptureError):diagnose_failed(root,0)
            (root/'manifest.json').write_text(json.dumps(dict(status='FAIL',qemu_exit=0)))
            with self.assertRaises(CaptureError):analyze(root)
            for phase in (True,-1,2,None):
                with self.subTest(phase=phase),self.assertRaises(CaptureError):diagnose_failed(root,phase)

    def test_pending_tail_requires_explicit_validated_complete_capture(self):
        capture,owners=pending_fixture()
        with self.assertRaises(CaptureError):failed_window(capture,owners,1000,8000)
        windows,proof=failed_window(capture,owners,1000,8000,pending_rx_tail=True)
        self.assertEqual(len(windows),2)
        self.assertEqual(proof[0]['mode'],'CAPTURE_SPAN_PENDING_RX_TAIL')
        self.assertEqual(proof[0]['end_tail_ns'],1000)
        self.assertEqual(proof[1]['mode'],'ENDPOINT_EVENTS_BRACKET')
        self.assertEqual(windows[0]['gap']['samples'],2)
        self.assertNotIn('qualified',proof[0])

    def test_pending_tail_rejects_span_source_order_error_and_nonpending_end(self):
        for case in ('missing-span','old-span','bool-version','wrong-target','missing-capture-start',
                     'missing-capture-end','wrong-count','wrong-order','outside-target','wrong-clock',
                     'no-original-submission','no-pending-end','wrong-URB','bad-pending-status',
                     'bad-pending-length','inside-error','duplicate-submission'):
            capture,owners=pending_fixture();span=capture['rx_capture_span']
            endpoint=[e for e in capture['rx_urbs']if e['device']==2]
            if case=='missing-span':capture.pop('rx_capture_span')
            elif case=='old-span':span['version']=0
            elif case=='bool-version':span['version']=True
            elif case=='wrong-target':span['targets']=[[1,2]]
            elif case=='missing-capture-start':span['earliest']['wall_ns']=1000
            elif case=='missing-capture-end':span['latest']['wall_ns']=8000
            elif case=='wrong-count':span['selected_records']=capture['packet_count']+1
            elif case=='wrong-order':span['latest']['record']=1
            elif case=='outside-target':span['latest']['device']=4
            elif case=='wrong-clock':span['quantum_ns']=1
            elif case=='no-original-submission':capture['rx_urbs'].remove(endpoint[0])
            elif case=='no-pending-end':capture['rx_urbs'].remove(endpoint[-1])
            elif case=='wrong-URB':endpoint[-1]['urb']=43
            elif case=='bad-pending-status':endpoint[-1]['status']=0
            elif case=='bad-pending-length':endpoint[-1]['length']=0
            elif case=='inside-error':endpoint[1]['status']=-110
            else:endpoint[1]['kind']='S'
            with self.subTest(case=case),self.assertRaises(CaptureError):
                failed_window(capture,owners,1000,8000,pending_rx_tail=True)

    def test_span_parser_is_opt_in_and_default_rx_receipts_unchanged(self):
        raw=pcap([(1,2,1000,b'','S',0x81,-115),(1,2,2000,b'','C',0x81,0),
                  (1,2,3000,b'','S',0x81,-115),(1,3,10000,b'','C',0x81,0)])
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'fixture.pcap';path.write_bytes(raw)
            original=read_capture(path,[(1,2)],observe_rx=True)
            extra=read_capture(path,[(1,2)],observe_rx=True,observe_rx_span=True)
            span=extra.pop('rx_capture_span')
            self.assertEqual(extra,original)
            self.assertEqual(span['earliest']['wall_ns'],1000)
            self.assertEqual(span['latest']['wall_ns'],3000) # Unrelated device cannot extend the span.
            self.assertEqual(span['selected_records'],3)
            with self.assertRaises(CaptureError):read_capture(path,[(1,2)],observe_rx_span=True)
            path.write_bytes(raw[:-1])
            with self.assertRaises(CaptureError):read_capture(path,[(1,2)],observe_rx=True,observe_rx_span=True)

    def test_new_capture_materials_bind_fixed_files_without_opening_manifest_paths(self):
        import hashlib
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);p=root/'guest-output/ws73.pcap';p.parent.mkdir();p.write_bytes(b'not a capture: hash fixture only')
            record=dict(path='/original-run/guest-output/ws73.pcap',sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            manifest=dict(guest_files=[record])
            self.assertEqual(frozen_capture_files(root,manifest,[p])[0]['sha256'],record['sha256'])
            for case in ('missing','duplicate','tampered'):
                m=copy.deepcopy(manifest)
                if case=='missing':m['guest_files']=[]
                elif case=='duplicate':m['guest_files'].append(record)
                else:m['guest_files'][0]['sha256']='0'*64
                with self.subTest(case=case),self.assertRaises(CaptureError):frozen_capture_files(root,m,[p])


if __name__ == '__main__': unittest.main()
