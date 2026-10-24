"""Independent capture negative controls; fixtures are not firmware truth."""
import copy
import struct
import unittest

from ws73_address_source_evidence import corroborate_rows
from ws73_capture import CaptureError
from test_ws73_model_evidence import fixture as chip_fixture


def fixture():
    outgoing, incoming = chip_fixture()
    outgoing[0]['raw'][68:74] = b'\x0b\x00\x02\x00\x7d\x06'
    struct.pack_into('<HHII', incoming[0]['raw'], 96, 5, 88, 0, 6)
    incoming[0]['raw'][108:114] = bytes(6)
    return outgoing, incoming


class AddressSourceEvidenceTests(unittest.TestCase):
    def test_zero_is_observation_only_and_padding_is_not_data(self):
        outgoing, incoming = fixture()
        result = corroborate_rows(outgoing, incoming)
        self.assertEqual(result['observation']['bytes'], '000000000000')
        self.assertFalse(result['address_validated'])
        incoming[0]['raw'][108:114] = b'\x42' * 6
        self.assertEqual(corroborate_rows(outgoing, incoming)['observation']['bytes'], '42' * 6)

    def test_failed_firmware_output_is_withheld(self):
        for size in [0, 6]:
            outgoing, incoming = fixture()
            struct.pack_into('<II', incoming[0]['raw'], 100, 0x80001390, size)
            incoming[0]['raw'][108:114] = b'\xa5' * 6
            result = corroborate_rows(outgoing, incoming)['observation']
            self.assertIsNone(result['bytes'])
            self.assertEqual((result['status'], result['length']), (0x80001390, size))

    def test_identity_order_missing_and_duplicate_rejected(self):
        for case in ['no-request', 'no-response', 'no-dli', 'duplicate-request', 'duplicate-response',
                     'old-device', 'before-request', 'after-dli', 'failed-in']:
            outgoing, incoming = fixture()
            if case == 'no-request': outgoing.pop(0)
            elif case == 'no-response': incoming.clear()
            elif case == 'no-dli': outgoing.pop()
            elif case == 'duplicate-request': outgoing.append(copy.deepcopy(outgoing[0]))
            elif case == 'duplicate-response': incoming.append(copy.deepcopy(incoming[0]))
            elif case == 'old-device': incoming[0]['device'] += 1
            elif case == 'before-request': incoming[0]['submit_record'] = 9
            elif case == 'after-dli': incoming[0]['record'] = 22
            else: incoming[0]['successful'] = False
            with self.subTest(case=case), self.assertRaises(CaptureError):
                corroborate_rows(outgoing, incoming)

    def test_lengths_fixed_field_and_mutating_operation_rejected(self):
        for case in ['output7', 'output0', 'short-allocation', 'oversize-allocation',
                     'request-field', 'request-length', 'request-padding', 'wrong-reply', 'truncated', 'write']:
            outgoing, incoming = fixture()
            if case == 'output7': struct.pack_into('<I', incoming[0]['raw'], 104, 7)
            elif case == 'output0': struct.pack_into('<I', incoming[0]['raw'], 104, 0)
            elif case == 'short-allocation': struct.pack_into('<H', incoming[0]['raw'], 98, 8)
            elif case == 'oversize-allocation': struct.pack_into('<H', incoming[0]['raw'], 98, 89)
            elif case == 'request-field': outgoing[0]['raw'][72] = 124
            elif case == 'request-length': outgoing[0]['raw'][70] = 3
            elif case == 'request-padding': outgoing[0]['raw'][74] = 1
            elif case == 'wrong-reply': struct.pack_into('<H', incoming[0]['raw'], 96, 10)
            elif case == 'truncated': incoming[0]['raw'].pop()
            else:
                row = copy.deepcopy(outgoing[0]); row['raw'][68] = 10
                row.update(record=8, completion_record=9); outgoing.insert(0, row)
            with self.subTest(case=case), self.assertRaises(CaptureError):
                corroborate_rows(outgoing, incoming)


if __name__ == '__main__':
    unittest.main()
