#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline reference Host contrast reader; never Native qualification.

Reference ACL TX is deliberately accepted only in this separate reader. The
production-path verifier remains strict. Both readers retain paired successful
URB completion and full original payload hashes/offsets.
"""
import importlib.util
from pathlib import Path
import struct


def read_reference_capture(path, targets):
    spec = importlib.util.spec_from_file_location(
        '_ws73_reference_capture_reader', Path(__file__).with_name('ws73_capture.py'))
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    native_command = reader.hcc_command

    def reference_command(raw):
        if len(raw) >= 73 and raw[64:66] == bytes([0xa0, 8]) and raw[68] == 0xa3:
            size = struct.unpack_from('<H', raw, 66)[0]
            if (struct.unpack_from('<II', raw) != (0, len(raw)) or size < 5
                    or len(raw) != 64 + max(64, 4 + size)
                    or size != 5 + struct.unpack_from('<H', raw, 71)[0]):
                raise reader.CaptureError('invalid reference ACL HCC/DLI envelope')
            return None  # ACL is not evidence of a command submission.
        return native_command(raw)

    reader.hcc_command = reference_command
    return reader.read_capture(path, targets)
