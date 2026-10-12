# SPDX-License-Identifier: GPL-2.0-only
"""Negative reference-byte fixtures only, never hardware/SSAP qualification."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError, read_capture
from ws73_reference_capture import read_reference_capture
from test_ws73_north_star import command_payload, pcap


class ReferenceCaptureTests(unittest.TestCase):
    def acl(self):
        raw = bytearray(command_payload(1, b'\x01\x02\x03'))
        raw[68] = 0xa3
        return raw

    def read(self, raw, completion=True, reader=read_reference_capture):
        rows = [(1, 2, 1000, raw, 'S', 1, -115)]
        if completion:
            rows.append((1, 2, 2000, raw, 'C', 1, 0))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'capture.pcap'
            path.write_bytes(pcap(rows))
            return reader(path, [(1, 2)])

    def test_acl_is_not_a_native_command(self):
        self.assertFalse(self.read(self.acl())['commands'])

    def test_native_reader_remains_strict_before_and_after_reference_read(self):
        for before in [True, False]:
            if not before:
                self.read(self.acl())
            with self.assertRaises(CaptureError):
                self.read(self.acl(), reader=read_capture)

    def test_reference_does_not_hide_malformed_acl(self):
        for offset in [4, 66, 71]:
            raw = self.acl()
            raw[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.read(raw)

    def test_reference_still_requires_paired_out_completion(self):
        with self.assertRaises(ValueError):
            self.read(self.acl(), completion=False)

    def test_reference_native_command_keeps_actual_pair(self):
        row = self.read(command_payload(0x1401, bytes(27)))['commands'][0]
        self.assertEqual(row['opcode'], 0x1401)
        self.assertEqual(row['params'], bytes(27).hex())
        self.assertLess(row['record'], row['completion']['record'])
