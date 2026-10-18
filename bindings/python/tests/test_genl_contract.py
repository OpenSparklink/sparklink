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
    def test_canonical_c_header_and_sdk_enum_values_match(self):
        sdk = (ROOT / "crates/slk-protocol/src/genl.rs").read_text()
        c_header = LINUX / "include/uapi/linux/sparklink.h"
        with tempfile.TemporaryDirectory(prefix="sparklink-genl-abi-") as directory:
            d = Path(directory)
            for family, uname, prefix in (
                ("commands", "GenlCmd", "SPARKLINK_CMD_"),
                ("attrs", "GenlAttr", "SPARKLINK_ATTR_"),
            ):
                # Full actual enums, not a second set of numeric definitions.
                ue = enum(sdk, uname)
                members = re.findall(r"    (\w+) = \d+,", ue)
                macro_aliases = {"Timeout10ms": "TIMEOUT_10MS"}
                rust = ["#[derive(Clone,Copy)] #[repr(u16)] " + ue, "fn main() {"]
                c = [f"#include {json.dumps(str(c_header))}", "#include <stdio.h>", "int main(void) {"]
                for member in members:
                    macro = prefix + macro_aliases.get(member, snake(member))
                    rust.append(f'println!("{{}}", {uname}::{member} as u16);')
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

