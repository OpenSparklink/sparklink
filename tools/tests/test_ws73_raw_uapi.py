"""Actual receipt-validator entry, synthetic JSON and byte-file dependencies."""
from pathlib import Path
import tempfile
import unittest

from ws73_raw_uapi import verify, verify_binary


class RawUapi(unittest.TestCase):
    def setUp(self):
        self.record = dict(channel_socket=[dict(start_wall_ns=1, end_wall_ns=4,
            owners=[dict(owner=dict(index=2))])], retired_uapi_refusals=[dict(exit=0,
            stderr='', args=['/bin/retired-uapi-probe', '2'], pid=100,
            start_wall_ns=2, end_wall_ns=3, stdout=(
                'RETIRED_UAPI_ENOTTY_PASS: uid=1000 cases=103 unchanged=103 '
                'checks=309 invalid_user_address=1 mixed_stats=ENOTTY'))])

    def test_complete_receipt_only(self):
        self.assertEqual(verify(self.record)['receipts'], 1)

    def test_empty_and_legacy_are_rejected(self):
        self.record['retired_uapi_refusals'] = []
        with self.assertRaises(ValueError): verify(self.record)

    def test_invalid_values_not_coerced(self):
        for key in ['pid', 'start_wall_ns', 'end_wall_ns']:
            saved = self.record['retired_uapi_refusals'][0][key]
            for value in [True, 0, -1, '2']:
                self.record['retired_uapi_refusals'][0][key] = value
                with self.assertRaises(ValueError): verify(self.record)
            self.record['retired_uapi_refusals'][0][key] = saved

    def test_missing_and_changed_binary_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'root/bin/retired-uapi-probe'
            with self.assertRaises(ValueError): verify_binary(root, dict(guest_files=[]))
            entry = dict(path=str(path), sha256='0' * 64)
            with self.assertRaises(OSError): verify_binary(root, dict(guest_files=[entry]))
            path.parent.mkdir(parents=True)
            path.write_bytes(b'not-an-ELF: this test only checks byte identity')
            with self.assertRaises(ValueError): verify_binary(root, dict(guest_files=[entry]))
            with self.assertRaises(ValueError): verify_binary(root, dict(guest_files=[entry, entry]))


if __name__ == '__main__':
    unittest.main()
