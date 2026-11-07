"""Current runner receipt checks only; actual ioctl tests execute in the VM."""
from pathlib import Path
import unittest

from ws73_channel_socket import verify_retired_uapi_receipt
from ws73_capture import CaptureError


class RetiredUapiReceipt(unittest.TestCase):
    def setUp(self):
        self.good = dict(exit=0, stderr='', stdout=(
            'RETIRED_UAPI_ENOTTY_PASS: uid=1000 cases=103 unchanged=103 '
            'checks=309 invalid_user_address=1 mixed_stats=ENOTTY\n'))

    def test_current_receipt(self):
        verify_retired_uapi_receipt(self.good)

    def test_incomplete_or_historical_receipt(self):
        variants = [dict(self.good, exit=1), dict(self.good, exit=False),
                    dict(self.good, stderr='RETIRED_UAPI_FAIL'), {}]
        for old, new in [('uid=1000', 'uid=0'), ('cases=103', 'cases=83'),
                         ('unchanged=103', 'unchanged=100'), ('checks=309', 'checks=1'),
                         ('invalid_user_address=1', 'invalid_user_address=0'),
                         ('mixed_stats=ENOTTY', 'mixed_stats=EOPNOTSUPP')]:
            variants.append(dict(self.good, stdout=self.good['stdout'].replace(old, new)))
        variants.append(dict(self.good, stdout=self.good['stdout'] * 2))
        variants.append(dict(self.good, stdout=self.good['stdout'].replace('=103', '=101').replace('checks=309', 'checks=303')))
        for row in variants:
            with self.subTest(row=row), self.assertRaises(CaptureError):
                verify_retired_uapi_receipt(row)

    def test_current_builder_and_caller_use_one_probe(self):
        root = Path(__file__).resolve().parents[1]
        for name in ['ws73_target.py', 'ws73_channel_socket.py']:
            source = (root / name).read_text()
            self.assertNotIn('protocol-state-probe', source)
            self.assertNotIn('protocol_state_unsupported_test.c', source)
            self.assertIn('retired-uapi-probe', source)
        builder = (root / 'ws73_target.py').read_text()
        for dependency in ['retired_uapi_test.c', 'retired_ioctl_cases.h',
                           'retired_ioctl_numbers.h', 'file_affinity_probe.h']:
            self.assertIn(dependency, builder)


if __name__ == '__main__':
    unittest.main()
