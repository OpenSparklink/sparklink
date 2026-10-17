"""Independent capture decoder, not firmware or real-device qualification."""
import struct
import unittest

from ws73_capture import CaptureError, hcc_receive


def allocation(tag=0x19, queue=9, advertised=96):
    raw = bytearray(188)
    struct.pack_into('<II', raw, 0, 2, len(raw))
    struct.pack_into('<H', raw, 12, 96)
    struct.pack_into('<BBH', raw, 92, tag, queue, advertised)
    # Actual E110 response envelope; deliberately nonzero allocation padding.
    raw[96:] = bytes([0xa5]) * 92
    struct.pack_into('<HHII', raw, 96, 10, 88, 0, 2)
    raw[108:110] = bytes([2, 0])
    return raw


class PlatformCaptureTests(unittest.TestCase):
    def test_actual_e110_allocation_shape(self):
        slots = hcc_receive(allocation())
        self.assertEqual(len(slots), 1)
        service, queue, offset, payload = slots[0]
        self.assertEqual((service, queue, offset, len(payload)), (1, 9, 92, 92))
        self.assertEqual(struct.unpack_from('<HHII', payload), (10, 88, 0, 2))
        self.assertEqual(payload[12:14], b'\x02\x00')

    def test_payload_only_platform_unchanged(self):
        self.assertEqual(len(hcc_receive(allocation(advertised=14))[0][3]), 14)
        with self.assertRaises(CaptureError):
            hcc_receive(allocation(tag=0x10, advertised=14))

    def test_no_relaxation_for_other_routes(self):
        for tag, queue in [(0xa0, 8), (0x50, 10), (0x10, 9), (0x19, 8)]:
            with self.subTest(tag=tag, queue=queue), self.assertRaises(CaptureError):
                hcc_receive(allocation(tag, queue))

    def test_oversized_and_nearby_lengths_rejected(self):
        for n in [93, 94, 95, 97, 65535]:
            with self.subTest(length=n), self.assertRaises(CaptureError):
                hcc_receive(allocation(advertised=n))

    def test_truncated_or_extra_slot_rejected(self):
        raw = allocation()
        for n in [91, 96, 110, 187]:
            with self.subTest(size=n), self.assertRaises(CaptureError):
                hcc_receive(raw[:n])
        struct.pack_into('<H', raw, 14, 64)
        with self.assertRaises(CaptureError):
            hcc_receive(raw)


if __name__ == '__main__':
    unittest.main()
