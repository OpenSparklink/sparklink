#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CBMC directly includes the optional production Virtual codec; no Core proof."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from run_standard_usb_writer_proof import verdict


HARNESS = r'''
#include <errno.h>
#include <assert.h>
#include <stdint.h>
#include "virtual_codec.h"
extern unsigned short nondet_u16(void);
extern size_t nondet_size(void);
extern unsigned char nondet_u8(void);
int main(void) {
 struct sparklink_native_info info;
 unsigned char *bytes=(unsigned char*)&info;
 for(size_t i=0;i<sizeof(info);i++) bytes[i]=nondet_u8();
 u16 opcode=nondet_u16(); size_t length=nondet_size(); u8 param=nondet_u8(),out[18],old[18];
 for(size_t i=0;i<18;i++) out[i]=old[i]=nondet_u8();
 int ret=sparklink_virtual_reply(&info,opcode,&param,length,out);
 if(ret<0) { for(size_t i=0;i<18;i++) assert(out[i]==old[i]); }
 else {
  assert(ret>=8 && ret<=18);assert(out[0]==2 && out[1]==0);
  assert(out[2]==ret-4 && out[3]==0 && out[4]==(u8)opcode && out[5]==(u8)(opcode>>8));
  assert(out[6]==1 && out[7]==0);
  if(opcode==0x0401) {assert(ret==10);assert(out[8]==255 && out[9]==0);}
  else if(opcode==0x0402) {assert(ret==14);for(size_t i=8;i<14;i++) assert(out[i]==0);}
  else if(opcode==0x0403) {assert(ret==18);for(size_t i=0;i<10;i++) assert(out[8+i]==info.features[i]);}
  else if(opcode==0x0404) {assert(ret==13);for(size_t i=0;i<5;i++) assert(out[8+i]==info.version[i]);}
  else {assert(opcode==0x0406 && length==1);assert(ret==14);for(size_t i=0;i<6;i++) assert(out[8+i]==info.address[i]);}
 }
}
'''


def run(args):
    kernel = args.kernel_tree.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(mode=0o700)
    source = kernel / 'drivers/sparklink/virtual_codec.h'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    harness = output / 'actual.c'
    harness.write_text(HARNESS)
    cmd = ['cbmc', str(harness), '-I', str(kernel / 'include'), '-I', str(source.parent),
           '--bounds-check', '--pointer-check', '--signed-overflow-check',
           '--unsigned-overflow-check', '--unwind', '34', '--unwinding-assertions', '--json-ui']
    result = {'status': 'NOT_PROVEN', 'source_sha256': digest,
              'native_header_sha256': hashlib.sha256((kernel / 'include/linux/sparklink_native.h').read_bytes()).hexdigest(),
              'source_head': subprocess.check_output(['git', '-C', str(kernel), 'rev-parse', 'HEAD'], text=True).strip(),
              'source_clean': not bool(subprocess.check_output(['git', '-C', str(kernel), 'status', '--porcelain'])),
              'tool': subprocess.check_output(['cbmc', '--version'], text=True).strip(),
              'command': cmd, 'harness_sha256': hashlib.sha256(harness.read_bytes()).hexdigest(),
              'assumptions': ['Live initialized NativeInfo, valid one-byte parameter object and 18-byte output; no aliasing.',
                              'Pure test codec only; no Core/Host credit/Runtime/worker/IRQ/refcount/lifetime/hardware proof.'],
              'bounds': 'All u16 opcodes, size_t lengths, u8 parameter and metadata bytes; unwind34 with unwinding assertions.',
              'source_mapping': ['sparklink_virtual_validate', 'sparklink_virtual_reply'],
              'physical_acceptance': False}
    try:
        with (output / 'solver.json').open('w') as stdout, (output / 'stderr.log').open('w') as stderr:
            process = subprocess.run(cmd, stdout=stdout, stderr=stderr, timeout=args.timeout)
        data = json.loads((output / 'solver.json').read_text())
        checks = [item for row in data for item in row.get('result', [])]
        warnings = [row.get('messageText') for row in data if row.get('messageType') == 'WARNING']
        result.update(exit=process.returncode, properties=len(checks), warnings=warnings,
                      failures=[v['property'] for v in checks if v.get('status') != 'SUCCESS'])
        final_head = subprocess.check_output(['git', '-C', str(kernel), 'rev-parse', 'HEAD'], text=True).strip()
        still_clean = not subprocess.check_output(['git', '-C', str(kernel), 'status', '--porcelain'])
        if (result['source_clean'] and still_clean and final_head == result['source_head']
                and hashlib.sha256(source.read_bytes()).hexdigest() == digest):
            result['status'] = verdict(process.returncode, False, data,
                                       (output / 'stderr.log').read_text(), False)
    except subprocess.TimeoutExpired:
        result.update(timed_out=True, status='NOT_PROVEN_TIMEOUT')
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'source_head', 'source_sha256')}))
    return 0 if result['status'] == 'MODEL_CHECKED_SCOPED' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-tree', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=120)
    raise SystemExit(run(parser.parse_args()))
