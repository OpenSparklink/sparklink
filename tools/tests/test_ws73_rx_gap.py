# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic diagnostic negatives; never hardware evidence."""
import copy
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError, read_capture
from ws73_rx_gap import distribution, observe
from test_ws73_north_star import pcap


def events():
    return [dict(bus=1, device=2, wall_ns=t, record=i + 1, file_offset=24 + i * 80,
                 urb=42, kind=k, status=-115 if k == 'S' else 0,
                 length=20480 if k == 'S' else 0)
            for i, (t, k) in enumerate([(0, 'S'), (2000, 'C'), (3000, 'S'), (5000, 'C'), (7000, 'S')])]


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


if __name__ == '__main__': unittest.main()
