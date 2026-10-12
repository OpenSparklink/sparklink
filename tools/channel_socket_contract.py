#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the actual Rust broker address and compare with the actual C UAPI.
Only encoding/layout; never socket, authorization or physical qualification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def run(kernel, output=None):
    repo = Path(__file__).resolve().parents[1]
    rust_path = repo / 'crates/slkd/src/channel.rs'
    header = kernel / 'include/uapi/linux/sparklink_socket.h'
    source = rust_path.read_text()
    structure = re.search(r'#\[repr\(C\)\]\nstruct Address \{[^}]+\}', source)[0]
    initializer = re.search(r'let address = Address \{[^}]+\};', source)[0]
    c = r'''#include <stdio.h>
#include <stddef.h>
#include <linux/sparklink_socket.h>
int main(void) {
 struct sockaddr_sparklink address = {
  .family=46,.controller=19,.version=SPARKLINK_SOCKET_VERSION,
  .generation=0x123456789abcdef0ULL,.lifetime=0xfedcba9876543210ULL,
  .lease=0x456789abcdef0123ULL,.handle=123,
  .local_tcid=31,.remote_tcid=31,.pi=SPARKLINK_SOCKET_USER_PI,
  .directions=SPARKLINK_SOCKET_TX|SPARKLINK_SOCKET_RX,.security=0,
 };
 _Static_assert(sizeof(address)==48,"socket ABI size");
 _Static_assert(offsetof(struct sockaddr_sparklink,lease)==24,"lease offset");
 _Static_assert(offsetof(struct sockaddr_sparklink,directions)==40,"direction offset");
 const unsigned char *p=(void *)&address;
 for(size_t i=0;i<sizeof(address);i++)printf("%02x",p[i]);
 return 0;
}'''
    rust = structure + '''
fn main() {
 let controller=19;let generation=0x123456789abcdef0;let lifetime=0xfedcba9876543210;
 let lease=0x456789abcdef0123;let handle=123;let directions=3;let security=0;
''' + initializer + '''
 assert_eq!(core::mem::size_of_val(&address),48);
 // All layout bytes are explicit fields; C/Rust compare includes reserved zeros.
 let bytes=unsafe{core::slice::from_raw_parts((&address as *const Address).cast::<u8>(),48)};
 for byte in bytes {print!("{byte:02x}");}
}'''
    with tempfile.TemporaryDirectory(prefix='sparklink-channel-contract-') as directory:
        tmp = Path(directory)
        (tmp/'contract.c').write_text(c)
        (tmp/'contract.rs').write_text(rust)
        subprocess.run([os.environ.get('CC','clang'), '-std=c11', '-D__EXPORTED_HEADERS__', '-Wall', '-Wextra', '-Werror',
                        '-I'+str(kernel/'include/uapi'), str(tmp/'contract.c'), '-o', str(tmp/'c')], check=True)
        subprocess.run([os.environ.get('RUSTC','rustc'), '--edition=2021', '-D','warnings',
                        str(tmp/'contract.rs'), '-o', str(tmp/'rust')], check=True)
        c_bytes = subprocess.check_output([str(tmp/'c')], text=True)
        rust_bytes = subprocess.check_output([str(tmp/'rust')], text=True)
        assert c_bytes == rust_bytes, (c_bytes,rust_bytes)
    result={'status':'ACTUAL_C_RUST_SOCKET_V2_LAYOUT_PASS', 'size':48,
            'scope':'actual broker struct/initializer and C UAPI; no kernel admission/VFS/RF proof',
            'sources':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (rust_path,header)}}
    if output:output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel',type=Path,default=Path(__file__).resolve().parents[2]/'linux')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    run(args.kernel.resolve(),args.output)
