"""Actual canonical C helpers, Rust library semantics and Python operations.

The expected bits come from T/XS 20001-2025 table32; compiled languages are not
allowed to agree on an incorrect permission table. No kernel or RF claim.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sparklink.adapter import Adapter

from sparklink import SsapOperations as Ops

ROOT = Path(__file__).resolve().parents[3]
HEADER = Path(os.environ.get('SPARKLINK_KERNEL_UAPI', ROOT.parent / 'linux/include/uapi/linux/sparklink_ioctl.h')).resolve()
NAMES = ['READ', 'WRITE_NO_RSP', 'WRITE_WITH_RSP', 'NOTIFY', 'INDICATE', 'BROADCAST', 'DESC_WRITABLE', 'CLIENT_CFG_WR', 'SERVER_CFG_WR']
STANDARD = [1, 2, 4, 8, 16, 32, 256, 512, 1024]
VALUES = [*range(2048), 65535, 65536, 0x80000000, 0xFFFFFFFF]


def run(command):
    return subprocess.check_output(command, text=True)


class OperationsConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HEADER.is_file():
            raise AssertionError('matching kernel UAPI required; no fixture fallback')
        temporary = tempfile.TemporaryDirectory(prefix='sparklink-ssap-ops-')
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        c = ['#include <stdio.h>', f'#include {json.dumps(str(HEADER))}', 'int main(void) {',
             'const unsigned flags[] = {' + ','.join('SL_SSAP_OP_' + n for n in NAMES) + '};',
             'for (unsigned i=0;i<9;i++) { printf("%u ",flags[i]); } puts("");',
             'const unsigned values[] = {' + ','.join(str(v)+'U' for v in VALUES) + '};',
             'for (unsigned i=0;i<sizeof(values)/sizeof(values[0]);i++) { unsigned v=values[i];',
             'printf("%u %d %d",v,sl_ssap_ops_valid(v),sl_ssap_ops_fits_legacy(v));',
             'for (unsigned j=0;j<9;j++) { printf(" %d",sl_ssap_ops_allows(v,flags[j])); } puts(""); }',
             # Unknown required bits must not accidentally grant permission.
             'if (sl_ssap_ops_allows(0x73fU,0x40U)) { return 1; } return 0; }']
        (root/'test.c').write_text('\n'.join(c))
        subprocess.run(shlex.split(os.environ.get('CC', 'cc')) + ['-std=c11', '-Wall', '-Wextra', '-Werror', str(root/'test.c'), '-o', str(root/'c-test')], check=True)
        cls.c_lines = run([str(root/'c-test')]).splitlines()
        rust = [f'#[expect(dead_code, reason="independent actual ABI declarations for permission tests")] #[path={json.dumps(str(ROOT / "crates/slk-protocol/src/types.rs"))}] mod types;',
                'pub use types::SsapAddProperty;',
                f'#[path={json.dumps(str(ROOT / "crates/slk-protocol/src/ssap.rs"))}] mod ssap;',
                'use ssap::*; fn main() {',
                'let flags = [' + ','.join('SsapOperations::'+n for n in NAMES) + '];',
                'for flag in flags {print!("{} ",flag.bits());} println!();',
                'for v in [' + ','.join(str(v)+'u32' for v in VALUES) + '] {',
                'let ops=SsapOperations::from_bits(v); print!("{} {} {}",v,ops.is_ok() as u8,ops.is_ok_and(|o|o.to_legacy_bits().is_ok()) as u8);',
                'for flag in flags {print!(" {}",ops.is_ok_and(|o|o.contains(flag)) as u8);} println!(); }',
                'let mut p=SsapAddProperty::for_legacy_staging(1,SsapOperations::READ,&[0;248]).unwrap(); p.validate_legacy_staging().unwrap();',
                'p.ops=0x40; assert!(p.validate_legacy_staging().is_err()); p.ops=1; p.value_len=249; assert!(p.validate_legacy_staging().is_err());',
                'p.value_len=1; p._reserved=[1,0]; assert!(p.validate_legacy_staging().is_err()); }']
        (root/'test.rs').write_text('\n'.join(rust))
        subprocess.run(shlex.split(os.environ.get('RUSTC', 'rustc')) + ['--edition=2024', '-D', 'warnings', str(root/'test.rs'), '-o', str(root/'rust-test')], check=True)
        cls.rust_lines = run([str(root/'rust-test')]).splitlines()

    def test_constants_match_standard_table_not_just_each_other(self):
        self.assertEqual(list(map(int, self.c_lines[0].split())), STANDARD)
        self.assertEqual(list(map(int, self.rust_lines[0].split())), STANDARD)
        self.assertEqual([getattr(Ops, n).bits for n in NAMES], STANDARD)

    def test_exhaustive_permissions_and_legacy_narrowing(self):
        self.assertEqual(len(self.c_lines), len(VALUES)+1)
        self.assertEqual(len(self.rust_lines), len(VALUES)+1)
        for v, c, rust in zip(VALUES, self.c_lines[1:], self.rust_lines[1:]):
            valid = v & ~0x73F == 0
            expected = [v, int(valid), int(valid and v <= 255), *[int(valid and v & flag == flag) for flag in STANDARD]]
            self.assertEqual(list(map(int, c.split())), expected, v)
            self.assertEqual(list(map(int, rust.split())), expected, v)
            if valid:
                ops = Ops(v)
                self.assertEqual([int(ops.contains(getattr(Ops, n))) for n in NAMES], expected[3:])
                if v <= 255:
                    self.assertEqual(ops.to_legacy_bits(), v)
                else:
                    with self.assertRaises(ValueError): ops.to_legacy_bits()
            else:
                with self.assertRaises(ValueError): Ops(v)

    def test_python_negative_oversize_bool_and_unvalidated_required_reject(self):
        for v in [-1, 1 << 32]:
            with self.assertRaises(ValueError): Ops(v)
        for v in [True, 1.5, '9']:
            with self.assertRaises(TypeError): Ops(v)
        with self.assertRaises(TypeError): Ops.READ.contains(0x40)
        self.assertFalse((Ops.READ | Ops.NOTIFY).contains(Ops.WRITE_NO_RSP))
        self.assertFalse((Ops.READ | Ops.NOTIFY).contains(Ops.WRITE_WITH_RSP))


class LegacyWriteBoundary(unittest.TestCase):
    def test_oversize_write_cannot_wrap_u16_length_or_reach_ffi(self):
        adapter = object.__new__(Adapter)
        adapter._handle = None
        with patch('sparklink.adapter._get_lib', side_effect=AssertionError('FFI must not be reached')):
            for size in [253, 65535, 65536]:
                with self.assertRaises(ValueError):
                    adapter.ssap_write(1, bytes(size))
