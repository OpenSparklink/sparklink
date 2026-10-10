# SPDX-License-Identifier: GPL-2.0-only
"""Firmware file-selection guards; no board/hardware qualification."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_native_service_bundle import firmware_files
from ws73_firmware import NAMES


class NativeFirmwareInputs(unittest.TestCase):
    def test_combined_selection_cannot_mix_or_corrupt_individual_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            images = {}
            for name in NAMES:
                payload = ('synthetic file validation: ' + name).encode()
                blob = hashlib.sha256(payload).hexdigest().encode() + payload
                images[name] = blob
                (root / name).write_bytes(blob)
            selected = hashlib.sha256(b''.join(images[name] for name in NAMES)).hexdigest()
            self.assertEqual(firmware_files(root, selected), images)
            with self.assertRaises(ValueError): firmware_files(root, '0' * 64)
            (root / NAMES[0]).write_bytes(images[NAMES[0]][:-1] + b'X')
            with self.assertRaises(ValueError): firmware_files(root, selected)
            (root / NAMES[0]).write_bytes(images[NAMES[0]])
            # Every individual hash can be valid while the three files belong
            # to another selected release/order: the combined guard is needed.
            (root / NAMES[1]).write_bytes(images[NAMES[2]])
            (root / NAMES[2]).write_bytes(images[NAMES[1]])
            with self.assertRaises(ValueError): firmware_files(root, selected)

    def test_header_only_and_wrong_header_form_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for invalid in [b'0' * 64, b'Z' * 64 + b'payload', b'0' * 63 + b'payload']:
                (root / NAMES[0]).write_bytes(invalid)
                with self.assertRaises(ValueError): firmware_files(root, '0' * 64)


if __name__ == '__main__':
    unittest.main()
