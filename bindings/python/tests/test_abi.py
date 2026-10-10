"""Compare live C/Rust declarations with ctypes, without copying ABI constants.

Requires a C compiler, rustc and the matching kernel UAPI header. The kernel
checkout beside this repository is used by default; SPARKLINK_KERNEL_UAPI can
select a header from a different checkout. Missing inputs fail the suite.
"""

import ctypes
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from sparklink import structs


WORKSPACE = Path(__file__).resolve().parents[3]
KERNEL_HEADER = Path(os.environ.get(
    "SPARKLINK_KERNEL_UAPI",
    WORKSPACE.parent / "linux/include/uapi/linux/sparklink_ioctl.h",
)).resolve()
PUBLIC_HEADER = WORKSPACE / "crates/libsparklink/include/sparklink.h"
RUST_TYPES = WORKSPACE / "crates/slk-protocol/src/types.rs"

# These are name mappings only. Fields, sizes, alignments and offsets come from
# the actual declarations/compiler output, never from a second ABI definition.
STRUCT_NAMES = {
    "SciDevInfo": "sci_dev_info",
    "SleScanParams": "sle_scan_params",
    "SleConnectParams": "sle_connect_params",
    "SleConnInfo": "sle_conn_info",
    "SleSecInfo": "sle_sec_info",
    "SlePairParams": "sle_pair_params",
    "SsapSummary": "ssap_summary",
    "SsapReadWrite": "ssap_read_write",
    "SleDliEvent": "sle_dli_event",
    "SleDliInfo": "sle_dli_info",
    "SlePhyInfo": "sle_phy_info",
    "SleControllerSnapshot": "sle_controller_snapshot",
    "SleManagementQuery": "sle_management_query",
    "SleControllerEvent": "sle_controller_event",
    "SleControllerEventQuery": "sle_controller_event_query",
    "SleSnoopRecord": "sle_snoop_record",
    "SleSnoopQuery": "sle_snoop_query",
    "SleDiscoveryAdvConfig": "sle_discovery_adv_config",
    "SleDiscoveryScanConfig": "sle_discovery_scan_config",
    "SleDiscoverySubmit": "sle_discovery_submit",
    "SleDiscoveryResult": "sle_discovery_result",
    "SleDiscoveryTiming": "sle_discovery_timing",
}


def c_fields(source, name):
    """Get all member names from the selected flat UAPI struct declaration."""
    match = re.search(r"\bstruct\s+(?:SPARKLINK_ALIGN\(\d+\)\s+)?" + re.escape(name) + r"\s*\{([^}]+)\}", source)
    if not match:
        raise AssertionError(f"missing C struct declaration: {name}")
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", match.group(1), flags=re.S)
    fields = []
    for declaration in body.split(";"):
        if not declaration.strip():
            continue
        for part in declaration.split(","):
            member = re.search(r"\b([A-Za-z_]\w*)\s*(?:\[\s*\w+\s*\])?\s*$", part)
            if not member:
                raise AssertionError(f"unsupported C member in {name}: {declaration}")
            fields.append(member.group(1))
    return fields


def rust_fields(source, name):
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\s*\{([^}]+)\}", source)
    if not match:
        raise AssertionError(f"missing Rust struct declaration: {name}")
    return re.findall(r"\bpub\s+(\w+)\s*:", match.group(1))


def run(command):
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {shlex.join(command)}\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout


def parse_layout(output):
    layouts = {}
    for line in output.splitlines():
        kind, name, member, size, alignment_or_offset = line.split()
        key = (kind, name)
        if member == "STRUCT":
            layouts[key] = {
                "size": int(size), "alignment": int(alignment_or_offset), "fields": {},
            }
        else:
            layouts[key]["fields"][member] = (int(size), int(alignment_or_offset))
    return layouts


class TestAbiConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not KERNEL_HEADER.is_file():
            raise AssertionError(
                f"canonical kernel UAPI not found: {KERNEL_HEADER}; set "
                "SPARKLINK_KERNEL_UAPI to include/uapi/linux/sparklink_ioctl.h"
            )
        cls.kernel_source = KERNEL_HEADER.read_text()
        cls.public_source = PUBLIC_HEADER.read_text()
        cls.rust_source = RUST_TYPES.read_text()
        cls.fields = {
            name: c_fields(cls.kernel_source, kernel_name)
            for name, kernel_name in STRUCT_NAMES.items()
        }

        directory = tempfile.TemporaryDirectory(prefix="sparklink-abi-")
        cls.addClassCleanup(directory.cleanup)
        path = Path(directory.name)
        c_source = [
            "#include <stddef.h>", "#include <stdio.h>",
            f"#include {json.dumps(str(KERNEL_HEADER))}",
            f"#include {json.dumps(str(PUBLIC_HEADER))}",
            "int main(void) {",
        ]
        for name, kernel_name in STRUCT_NAMES.items():
            for kind, c_type in (("kernel", "struct " + kernel_name), ("public", name)):
                c_source.append(
                    f'printf("{kind} {name} STRUCT %zu %zu\\n", '
                    f"sizeof({c_type}), _Alignof({c_type}));"
                )
                for field in cls.fields[name]:
                    c_source.append(
                        f'printf("{kind} {name} {field} %zu %zu\\n", '
                        f"sizeof((({c_type} *)0)->{field}), offsetof({c_type}, {field}));"
                    )
        c_source.append("return 0; }")
        c_file = path / "layout.c"
        c_file.write_text("\n".join(c_source))
        compiler = shlex.split(os.environ.get("CC", "cc"))
        run(compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror", str(c_file), "-o", str(path / "c-layout")])
        cls.layouts = parse_layout(run([str(path / "c-layout")]))

        rust_source = [
            "#![allow(dead_code)]",
            f"#[path = {json.dumps(str(RUST_TYPES))}] mod types;",
            "use types::*;",
            "use std::mem::{align_of, offset_of, size_of, size_of_val};",
            "fn main() {",
        ]
        for name in STRUCT_NAMES:
            rust_source.extend([
                f'println!("rust {name} STRUCT {{}} {{}}", size_of::<{name}>(), align_of::<{name}>());',
                # Selected structs contain only integer/array POD fields.
                f"let value: {name} = unsafe {{ std::mem::zeroed() }};",
            ])
            for field in cls.fields[name]:
                rust_source.append(
                    f'println!("rust {name} {field} {{}} {{}}", '
                    f"size_of_val(&value.{field}), offset_of!({name}, {field}));"
                )
        rust_source.append("}")
        rust_file = path / "layout.rs"
        rust_file.write_text("\n".join(rust_source))
        run(shlex.split(os.environ.get("RUSTC", "rustc")) + [
            "--edition=2024", "-Dwarnings", str(rust_file), "-o", str(path / "rust-layout"),
        ])
        cls.layouts.update(parse_layout(run([str(path / "rust-layout")])))

        # Compare generated C against canonical UAPI on i386 as well, without
        # requiring a 32-bit libc/runtime. Native UAPI keeps explicit align(8).
        assertions = ["#include <stddef.h>",
                      f"#include {json.dumps(str(KERNEL_HEADER))}",
                      f"#include {json.dumps(str(PUBLIC_HEADER))}"]
        for name, kernel_name in STRUCT_NAMES.items():
            kernel = "struct " + kernel_name
            assertions += [
                f'_Static_assert(sizeof({name}) == sizeof({kernel}), "{name} size");',
                f'_Static_assert(_Alignof({name}) == _Alignof({kernel}), "{name} alignment");',
            ]
            for field in cls.fields[name]:
                assertions += [
                    f'_Static_assert(offsetof({name}, {field}) == offsetof({kernel}, {field}), "{name}.{field} offset");',
                    f'_Static_assert(sizeof((({name} *)0)->{field}) == sizeof((({kernel} *)0)->{field}), "{name}.{field} size");',
                ]
        static_file = path / "layout-static.c"
        static_file.write_text("\n".join(assertions))
        run(compiler + ["-m32", "-ffreestanding", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-c", str(static_file), "-o", str(path / "layout32.o")])

        fill_source = path / "fill.c"
        fill_source.write_text(
            f"#include {json.dumps(str(KERNEL_HEADER))}\n"
            "void fill_conn_info(struct sle_conn_info *value) {\n"
            "    *value = (struct sle_conn_info) {\n"
            "        .tx_bytes = 0x1122334455667788ULL,\n"
            "        .rx_bytes = 0x8877665544332211ULL,\n"
            "        .handle = 0x1234, .peer_addr = {1, 2, 3, 4, 5, 6},\n"
            "        .ssap_mtu = 0x3141, .ssap_reliable_mode = 1,\n"
            "        .ssap_version_major = 2,\n"
            "        .smtc_tx_credits = 0x2345, .smtc_rx_credits = 0x3456,\n"
            "        .dudtc_tx_credits = 0x4567, .dudtc_rx_credits = 0x5678,\n"
            "    };\n"
            "}\n"
            "void fill_dli_info(struct sle_dli_info *value) {\n"
            "    *value = (struct sle_dli_info) {\n"
            "        .firmware_version = 0x12345678,\n"
            "        .security_cap = 0xbeef, .features_ext = 0xabcd,\n"
            '        .name = "abi-controller",\n'
            "    };\n"
            "}\n"
        )
        shared = path / "fill.so"
        run(compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared", str(fill_source), "-o", str(shared)])
        cls.library = ctypes.CDLL(str(shared))
        cls.library.fill_conn_info.argtypes = [ctypes.POINTER(structs.SleConnInfo)]
        cls.library.fill_conn_info.restype = None
        cls.library.fill_dli_info.argtypes = [ctypes.POINTER(structs.SleDliInfo)]
        cls.library.fill_dli_info.restype = None

    def test_every_python_struct_has_a_canonical_mapping(self):
        python_structs = {
            name for name, value in vars(structs).items()
            if isinstance(value, type) and issubclass(value, ctypes.Structure)
        }
        self.assertEqual(python_structs, set(STRUCT_NAMES))

    def test_all_fields_and_layouts_match_kernel(self):
        for name in STRUCT_NAMES:
            with self.subTest(struct=name):
                python_type = getattr(structs, name)
                canonical_fields = self.fields[name]
                self.assertEqual([field for field, _ in python_type._fields_], canonical_fields)
                self.assertEqual(c_fields(self.public_source, name), canonical_fields)
                self.assertEqual(rust_fields(self.rust_source, name), canonical_fields)
                canonical = self.layouts[("kernel", name)]
                python_layout = {
                    "size": ctypes.sizeof(python_type),
                    "alignment": ctypes.alignment(python_type),
                    "fields": {
                        field: (ctypes.sizeof(field_type), getattr(python_type, field).offset)
                        for field, field_type in python_type._fields_
                    },
                }
                self.assertEqual(python_layout, canonical, "Python vs kernel C UAPI")
                self.assertEqual(self.layouts[("public", name)], canonical, "public C vs kernel C UAPI")
                self.assertEqual(self.layouts[("rust", name)], canonical, "userspace Rust vs kernel C UAPI")

    def test_c_conn_info_write_preserves_bounds_and_credit_fields(self):
        class GuardedInfo(ctypes.Structure):
            _fields_ = [("before", ctypes.c_uint64), ("info", structs.SleConnInfo), ("after", ctypes.c_uint64)]

        buffer = GuardedInfo()
        sentinel = 0xCAFEBABE01234567
        buffer.before = buffer.after = sentinel
        self.library.fill_conn_info(ctypes.byref(buffer.info))
        self.assertEqual((buffer.before, buffer.after), (sentinel, sentinel))
        self.assertEqual(buffer.info.tx_bytes, 0x1122334455667788)
        self.assertEqual(buffer.info.rx_bytes, 0x8877665544332211)
        self.assertEqual(buffer.info.handle, 0x1234)
        self.assertEqual(list(buffer.info.peer_addr), [1, 2, 3, 4, 5, 6])
        self.assertEqual(buffer.info.ssap_mtu, 0x3141)
        self.assertEqual(buffer.info.ssap_reliable_mode, 1)
        self.assertEqual(buffer.info.ssap_version_major, 2)
        self.assertEqual(buffer.info.smtc_tx_credits, 0x2345)
        self.assertEqual(buffer.info.smtc_rx_credits, 0x3456)
        self.assertEqual(buffer.info.dudtc_tx_credits, 0x4567)
        self.assertEqual(buffer.info.dudtc_rx_credits, 0x5678)

    def test_c_dli_info_write_preserves_capability_widths_and_name(self):
        info = structs.SleDliInfo()
        self.library.fill_dli_info(ctypes.byref(info))
        self.assertEqual(info.firmware_version, 0x12345678)
        self.assertEqual(info.security_cap, 0xBEEF)
        self.assertEqual(info.features_ext, 0xABCD)
        self.assertEqual(bytes(info.name).split(b"\0", 1)[0], b"abi-controller")


if __name__ == "__main__":
    unittest.main()
