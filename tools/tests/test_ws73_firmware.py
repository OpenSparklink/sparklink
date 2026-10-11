# SPDX-License-Identifier: GPL-2.0-only
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_firmware import export_combined, split_combined, NAMES


def image(payload):
    return hashlib.sha256(payload).hexdigest().encode() + payload


class FirmwareImport(unittest.TestCase):
    def setUp(self):
        # Different sizes and a fake inner header must not affect section bounds.
        self.images = [image(b'firmware' + b'a' * 64 + b'payload'),
                       image(bytes(range(256))), image(b'calibration')]
        self.blob = b''.join(self.images)

    def test_unchanged_headers_payloads_and_order(self):
        self.assertEqual(list(split_combined(self.blob).values()), self.images)

    def test_truncation_tampering_extra_image_and_trailing_bytes(self):
        for bad in [self.blob[:-1], self.blob[:66] + b'X' + self.blob[67:],
                    self.blob + image(b'extra'), self.blob + b'\0',
                    b''.join(self.images[:2]), b'']:
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                split_combined(bad)

    def test_invalid_header_and_empty_payload(self):
        for bad in [self.images[0][:64].upper() + self.blob[64:],
                    b'g' + self.blob[1:], image(b'') + b''.join(self.images[1:])]:
            with self.assertRaises(ValueError):
                split_combined(bad)

    def test_hash_refusal_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'combined.bin'; source.write_bytes(self.blob)
            output = root / 'output'
            with self.assertRaises(ValueError):
                export_combined(source, output, '0' * 64)
            self.assertFalse(output.exists())

    def test_later_bad_image_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'combined.bin'
            blob = self.blob[:-1]; source.write_bytes(blob); output = root / 'output'
            with self.assertRaises(ValueError):
                export_combined(source, output, hashlib.sha256(blob).hexdigest())
            self.assertFalse(output.exists())

    def test_export_receipt_and_refuse_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'combined.bin'; source.write_bytes(self.blob)
            output = root / 'output'; digest = hashlib.sha256(self.blob).hexdigest()
            receipt = export_combined(source, output, digest)
            self.assertEqual(receipt['combined_sha256'], digest)
            self.assertEqual(b''.join((output / n).read_bytes() for n in NAMES), self.blob)
            with self.assertRaises(FileExistsError):
                export_combined(source, output, digest)


if __name__ == '__main__':
    unittest.main()
