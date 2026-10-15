# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic transformation tests, not redistributable SDK or hardware proof."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_relay_firmware_extension as extension


class RelayFirmwareExtension(unittest.TestCase):
    def payload(self):
        b=bytearray(extension.PAYLOAD_SIZE)
        # Distinct row contents make preservation assertions cover every entry.
        for offset,count,stride in [extension.PACKETS,extension.DISPATCH]:
            for n in range(count):
                row=struct.pack('<H',n)+bytes([n+1])*(stride-2)
                b[offset+n*stride:offset+(n+1)*stride]=row
        for offset,data in [(0x1790a,'9307c0021ea11f05d4c041008280'),(0x1cfa4,'4a003c00accd4100'),
                            (0x7168,'b7054300'),(0x1c1d6,'46010a1f0100'),(0x1cf2c,'46010600a4a64100')]:
            raw=bytes.fromhex(data);b[offset:offset+len(raw)]=raw
        return bytes(b)

    def test_all_original_rows_and_type146_preserved_in_both_locations(self):
        original=self.payload();new,r=extension._extend_payload(original)
        for (offset,count,stride),key in [(extension.PACKETS,'packet_table'),(extension.DISPATCH,'dispatch_table')]:
            old=original[offset:offset+count*stride];relocated=r[key]['address']-extension.BASE
            self.assertEqual(new[offset:offset+len(old)],old)
            self.assertEqual(new[relocated:relocated+len(old)],old)
            self.assertEqual(r[key]['new_count'],count+1)
        self.assertEqual(new[0x1c1d6:0x1c1dc],bytes.fromhex('46010a1f0100'))
        self.assertEqual(new[0x1cf2c:0x1cf34],bytes.fromhex('46010600a4a64100'))

    def test_runtime_layout_arithmetic_is_not_boot_upload_safety(self):
        b,r=extension._extend_payload(self.payload())
        self.assertEqual(r['reservation']['bytes'],4096)
        self.assertEqual(r['reservation']['original_pool_bytes']-r['reservation']['new_pool_bytes'],4096)
        self.assertEqual(r['packet_table']['address'],extension.RESERVED)
        self.assertEqual(r['dispatch_table']['address']%4,0)
        self.assertLessEqual(extension.BASE+len(b),extension.POOL_END)
        self.assertLessEqual(len(b),204736)
        self.assertEqual(b[0x5700:0x5754],self.payload()[0x5700:0x5754])
        self.assertFalse(r['hardware_qualified'])
        self.assertFalse(r['production_default_changed'])
        self.assertFalse(r['safe_to_upload'])

    def test_exact_new_type_and_only_declared_old_bytes_change(self):
        old=self.payload();new,r=extension._extend_payload(old)
        p=r['packet_table']['address']-extension.BASE+44*6
        q=r['dispatch_table']['address']-extension.BASE+60*8
        self.assertEqual(new[p:p+6],bytes.fromhex('ff01041f0100'))
        self.assertEqual(new[q:q+8],bytes.fromhex('ff010600a4a64100'))
        allowed={x['address']-extension.BASE+j for x in r['patches'] for j in range(len(bytes.fromhex(x['after'])))}
        self.assertTrue(all(n in allowed for n,(a,b) in enumerate(zip(old,new)) if a!=b))
        self.assertEqual(struct.unpack_from('<I',new,0x7168)[0],0x0042f5b7)

    def test_different_preimages_sizes_or_existing_alias_rejected(self):
        original=self.payload()
        for offset in [0x1790a,0x1cfa4,0x7168,0x1c1d6,0x1cf2c]:
            bad=bytearray(original);bad[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(ValueError): extension._extend_payload(bad)
        for b in [original[:-1],original+b'\0']:
            with self.assertRaises(ValueError): extension._extend_payload(b)
        bad=bytearray(original);bad[extension.PACKETS[0]:extension.PACKETS[0]+2]=b'\xff\1'
        with self.assertRaises(ValueError): extension._extend_payload(bad)

    def test_public_entry_rejects_synthetic_or_unknown_firmware(self):
        # Internal structural tests do not bypass the public pinned-image guard.
        payload=self.payload()
        with self.assertRaisesRegex(ValueError,'pinned original'): extension.plan(extension.digest(payload).encode()+payload)

    def test_public_audit_returns_no_image_and_retains_real_failure(self):
        payload=self.payload();image=extension.digest(payload).encode()+payload
        with patch.object(extension,'STOCK_SHA256',extension.digest(image)):
            report=extension.plan(image)
        self.assertIsInstance(report,dict)
        self.assertEqual(report['status'],'RETIRED_CONTIGUOUS_PLAN_BOOT_FAILURE')
        self.assertFalse(report['safe_to_upload'])
        self.assertFalse(report['hardware_qualified'])
        self.assertIn('enumeration failed',report['retirement_reason'])
