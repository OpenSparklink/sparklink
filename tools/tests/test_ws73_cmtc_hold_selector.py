"""Compile/call the actual test-only C selector; synthetic bytes, no USB I/O.

Not a proof of the QEMU callback, kernel concurrency, firmware or cleanup.
The C caller always supplies the declared readable allocation, including for
negative lengths; invalid C pointers would violate the FFI caller contract.
"""
import ctypes
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest


RESPONSE = bytes.fromhex('0200100002000c00e20000000000fa07ff070101')


def aggregate(payload, *, tag=0xa0, queue=8, extra=b''):
    slot = bytes([tag, queue]) + struct.pack('<H', len(payload)) + payload
    header = bytearray(92)
    struct.pack_into('<II', header, 0, 2, len(header) + len(slot) + len(extra))
    struct.pack_into('<H', header, 12, len(slot))
    return bytes(header) + slot + extra


def frame(handle=0, response=RESPONSE):
    return b'\xa3' + struct.pack('<HH', handle, len(response)) + response


class CmtcHoldSelector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        source = Path(cls.tmp.name) / 'selector.c'
        source.write_text('#include "ws73_cmtc_hold_selector.h"\n'
                          'bool select_reply(const unsigned char *p, size_t n) {\n'
                          'return ws73_test_is_cmtc_capability_reply(p,n);\n}\n')
        lib = source.with_suffix('.so')
        subprocess.run(['/usr/bin/gcc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-pedantic', '-shared', '-fPIC', '-I',
                        str(Path(__file__).resolve().parents[1] / 'lab'),
                        str(source), '-o', str(lib)], check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.select_reply.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        cls.lib.select_reply.restype = ctypes.c_bool

    def selected(self, raw):
        return self.lib.select_reply(ctypes.create_string_buffer(raw), len(raw))

    def test_only_complete_actual_profile_not_identity_authentication(self):
        for handle in [0, 1, 0xfff]:
            raw = aggregate(frame(handle))
            original = bytes(raw)
            self.assertTrue(self.selected(raw))
            self.assertEqual(raw, original)
        for handle in [0x1000, 0x2000, 0x4000, 0x8000]:
            self.assertFalse(self.selected(aggregate(frame(handle))))
        for tag, queue in [(0x50, 10), (0xa1, 8), (0xa0, 9)]:
            self.assertFalse(self.selected(aggregate(frame(), tag=tag, queue=queue)))

    def test_all_truncations_lengths_and_profile_fields_fail_closed(self):
        raw = aggregate(frame())
        for n in range(len(raw)):
            self.assertFalse(self.selected(raw[:n]), n)
        # Preserve the declared total length while mutating every selected
        # profile field. ACB handle is deliberately not an ownership witness.
        for offset in [0, 4, 12, 94, 96, 99, 100, *range(101, len(raw))]:
            bad = bytearray(raw)
            bad[offset] ^= 0x40
            self.assertFalse(self.selected(bytes(bad)), offset)
        self.assertFalse(self.selected(b''))
        self.assertFalse(self.selected(bytes(20481)))

    def test_entire_aggregate_must_be_valid_before_any_match(self):
        raw = aggregate(frame(), extra=b'\0' * 4)
        self.assertFalse(self.selected(raw))  # Unassigned tail.
        for slot, length in [(1, 3), (2, 4), (1, 0xffff)]:
            bad = bytearray(raw)
            struct.pack_into('<H', bad, 12 + 2 * slot, length)
            self.assertFalse(self.selected(bytes(bad)))
        # An unrelated well-formed slot is delivered along with the real
        # retained aggregate, never split or separately synthesized.
        both = bytearray(raw)
        struct.pack_into('<H', both, 14, 4)
        self.assertTrue(self.selected(bytes(both)))
        struct.pack_into('<H', both, len(both) - 2, 1)
        self.assertFalse(self.selected(bytes(both)))

    def test_pattern_in_padding_or_other_protocol_is_not_a_reply(self):
        for raw in [aggregate(RESPONSE), aggregate(b'\xa2' + frame()[1:]),
                    aggregate(b'\0' * 25 + frame()), aggregate(b'\0' * 25, extra=frame())]:
            self.assertFalse(self.selected(raw))
        request = bytes.fromhex('0200080001000400e2000000')
        self.assertFalse(self.selected(aggregate(frame(response=request))))

