"""Synthetic evidence negative controls; no hardware or firmware proof."""
import copy
import struct
import unittest

from ws73_capture import CaptureError
from ws73_model_evidence import corroborate_rows
from test_ws73_north_star import command_payload
from test_ws73_platform_capture import allocation


def fixture():
    raw = bytearray(128)
    struct.pack_into('<II', raw, 0, 0, 128)
    raw[64:73] = b'\x19\x09\x20\x00\x10\x00\x01\x00\x00'
    common = dict(bus=1, device=4)
    outgoing = [common | dict(record=10, completion_record=11, raw=raw),
                common | dict(record=20, completion_record=21, raw=command_payload(0x0404))]
    incoming = [common | dict(submit_record=12, record=13, successful=True, raw=allocation())]
    return outgoing, incoming


class ModelEvidenceTests(unittest.TestCase):
    def test_complete_original_order_all_models(self):
        for model in range(3):
            outgoing, incoming = fixture()
            incoming[0]['raw'][108] = model
            proof = corroborate_rows(outgoing, incoming)
            self.assertEqual(proof['observation']['model_id'], model)
            self.assertEqual(proof['observation']['model'], 'WS73' + 'USE'[model])
            self.assertNotIn('raw', proof['observation'])

    def test_missing_and_ambiguous_operations_refused(self):
        for mutation in ['no-request', 'no-response', 'no-dli', 'duplicate-request', 'duplicate-response']:
            outgoing, incoming = fixture()
            if mutation == 'no-request':
                outgoing.pop(0)
            elif mutation == 'no-response':
                incoming.clear()
            elif mutation == 'no-dli':
                outgoing.pop()
            elif mutation == 'duplicate-request':
                outgoing.insert(0, copy.deepcopy(outgoing[0]))
            else:
                incoming.append(copy.deepcopy(incoming[0]))
            with self.subTest(mutation=mutation), self.assertRaises(CaptureError):
                corroborate_rows(outgoing, incoming)

    def test_bad_phase_identity_status_and_lengths_refused(self):
        for mutation in ['old-device', 'before-request', 'after-dli', 'failed-in', 'status',
                         'output-length', 'model', 'bus', 'platform-length', 'request-body', 'subtype', 'truncated']:
            outgoing, incoming = fixture()
            row = incoming[0]
            if mutation == 'old-device': row['device'] += 1
            elif mutation == 'before-request': row['submit_record'] = 9
            elif mutation == 'after-dli': row['record'] = 22
            elif mutation == 'failed-in': row['successful'] = False
            elif mutation == 'status': struct.pack_into('<I', row['raw'], 100, 1)
            elif mutation == 'output-length': struct.pack_into('<I', row['raw'], 104, 1)
            elif mutation == 'model': row['raw'][108] = 3
            elif mutation == 'bus': row['raw'][109] = 1
            elif mutation == 'platform-length': struct.pack_into('<H', row['raw'], 98, 89)
            elif mutation == 'request-body': outgoing[0]['raw'][72] = 1
            elif mutation == 'subtype': row['raw'][92] = 0x10
            else: row['raw'].pop()
            with self.subTest(mutation=mutation), self.assertRaises(CaptureError):
                corroborate_rows(outgoing, incoming)


if __name__ == '__main__':
    unittest.main()
