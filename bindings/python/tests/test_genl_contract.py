"""Compile authoritative C/Rust enum declarations; no transport qualification."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
LINUX = Path(os.environ.get("SPARKLINK_KERNEL_SOURCE", ROOT.parent / "linux")).resolve()


def enum(source, name):
    return re.search(r"pub enum " + name + r" \{.*?\n\}", source, re.S).group()


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper().replace("TIMEOUT10MS", "TIMEOUT_10MS")


class GenericNetlinkContract(unittest.TestCase):
    def test_current_header_kernel_and_sdk_enum_values_match(self):
        kernel = (LINUX / "net/sparklink/sle_netlink.rs").read_text()
        sdk = (ROOT / "crates/slk-protocol/src/genl.rs").read_text()
        c_header = LINUX / "include/uapi/linux/sparklink.h"
        with tempfile.TemporaryDirectory(prefix="sparklink-genl-abi-") as directory:
            d = Path(directory)
            for family, kname, uname, prefix in (
                ("commands", "NlCmd", "GenlCmd", "SPARKLINK_CMD_"),
                ("attrs", "NlAttr", "GenlAttr", "SPARKLINK_ATTR_"),
            ):
                # Full actual enums, not a second set of numeric definitions.
                ke = enum(kernel, kname)
                ue = enum(sdk, uname)
                members = re.findall(r"    (\w+) = \d+,", ke)
                aliases = {"KeyFingerprint": "KeyFp"}
                macro_aliases = {"KeyFingerprint": "KEY_FP", "Timeout10ms": "TIMEOUT_10MS"}
                rust = ["#[derive(Clone,Copy)] #[repr(u16)] " + ke,
                        "#[derive(Clone,Copy)] #[repr(u16)] " + ue, "fn main() {"]
                c = [f"#include {json.dumps(str(c_header))}", "#include <stdio.h>", "int main(void) {"]
                for member in members:
                    other = aliases.get(member, member)
                    macro = prefix + macro_aliases.get(member, snake(member))
                    rust.append(f'assert_eq!({kname}::{member} as u16, {uname}::{other} as u16);')
                    rust.append(f'println!("{{}}", {kname}::{member} as u16);')
                    c.append(f'printf("%u\\n", (unsigned){macro});')
                rust.append("}")
                c.append("return 0; }")
                (d / "enum.rs").write_text("\n".join(rust))
                (d / "enum.c").write_text("\n".join(c))
                subprocess.run([os.environ.get("RUSTC", "rustc"), "--edition=2024", "-D", "warnings",
                                str(d / "enum.rs"), "-o", str(d / "rust")], check=True)
                subprocess.run([os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                                str(d / "enum.c"), "-o", str(d / "c")], check=True)
                self.assertEqual(subprocess.check_output([str(d / "rust")]),
                                 subprocess.check_output([str(d / "c")]), family)

