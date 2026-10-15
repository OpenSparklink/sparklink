#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build an isolated SDK111 RAM table diagnostic, never a default firmware fix.

The original 44 packet and 60 dispatch entries are copied intact. Reserve the
last 4 KiB of the firmware's RAM pool for extended copies, instead of placing
them in BSS or sacrificing type146. Reduced pool capacity and all hardware
effects need independent qualification. No USB, flash, install or SDK mutation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

STOCK_SHA256 = 'ccba732d495c0c0d3b4e896c144f2d5ccd95896932879ca00d06ae52342f67e3'
BASE = 0x400000
PAYLOAD_SIZE = 0x2349c
POOL_START = 0x426c00
POOL_END = 0x430000
RESERVED = 0x42f000
PACKETS = (0x1c0d4, 44, 6)
DISPATCH = (0x1cdac, 60, 8)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _extend_payload(original):
    """Actual transformation, separately testable without redistributing SDK."""
    if len(original) != PAYLOAD_SIZE:
        raise ValueError('exact original111 payload size required')
    checks = [
        (0x1790a, bytes.fromhex('9307c0021ea11f05d4c041008280')),
        (0x1cfa4, bytes.fromhex('4a003c00accd4100')),
        (0x7168, bytes.fromhex('b7054300')),
        (0x1c1d6, bytes.fromhex('46010a1f0100')),
        (0x1cf2c, bytes.fromhex('46010600a4a64100')),
    ]
    if any(original[o:o+len(b)] != b for o,b in checks):
        raise ValueError('fixed getter/parent/pool/type146 preimages differ')
    packet_offset, packet_count, packet_stride = PACKETS
    dispatch_offset, dispatch_count, dispatch_stride = DISPATCH
    packet_rows = original[packet_offset:packet_offset+packet_count*packet_stride]
    dispatch_rows = original[dispatch_offset:dispatch_offset+dispatch_count*dispatch_stride]
    for rows, stride in [(packet_rows,packet_stride),(dispatch_rows,dispatch_stride)]:
        if any(struct.unpack_from('<H',rows,o)[0] == 0x1ff for o in range(0,len(rows),stride)):
            raise ValueError('source table already has diagnostic type')
    packet_table = packet_rows+bytes.fromhex('ff01041f0100')
    dispatch_table = dispatch_rows+bytes.fromhex('ff010600a4a64100')
    packet_address = RESERVED
    dispatch_address = (packet_address+len(packet_table)+3)&~3
    end = dispatch_address+len(dispatch_table)
    if not POOL_START < RESERVED < end <= POOL_END or end-BASE > 204736:
        raise ValueError('extension does not fit reserved RAM/load bound')
    result = bytearray(original)+bytearray(end-BASE-len(original))
    result[packet_address-BASE:packet_address-BASE+len(packet_table)] = packet_table
    result[dispatch_address-BASE:end-BASE] = dispatch_table
    patches = [
        (0x1790a,struct.pack('<I',0x02d00793),'packet getter count44->45'),
        (0x17912,struct.pack('<I',packet_address),'packet getter pointer'),
        (0x1cfa6,struct.pack('<H',61),'dispatch parent count60->61'),
        (0x1cfa8,struct.pack('<I',dispatch_address),'dispatch parent pointer'),
        (0x7168,struct.pack('<I',0x0042f5b7),'RAM pool upper bound430000->42f000'),
    ]
    changes = []
    for offset, data, reason in patches:
        changes.append(dict(address=BASE+offset, before=original[offset:offset+len(data)].hex(), after=data.hex(), reason=reason))
        result[offset:offset+len(data)] = data
    # Check both old locations and all rows in the new copies, including146.
    for offset,count,stride,address in [(*PACKETS,packet_address),(*DISPATCH,dispatch_address)]:
        size=count*stride
        if result[offset:offset+size] != original[offset:offset+size] or result[address-BASE:address-BASE+size] != original[offset:offset+size]:
            raise ValueError('existing protocol table changed')
    allowed={o+j for o,data,_ in patches for j in range(len(data))}
    if any(a != b and n not in allowed for n,(a,b) in enumerate(zip(original,result))):
        raise ValueError('unexpected original payload mutation')
    return bytes(result), dict(
        status='VM_DIAGNOSTIC_EXTENSION_NOT_RELEASED',
        packet_table=dict(address=packet_address, old_count=44, new_count=45, old_rows_sha256=digest(packet_rows)),
        dispatch_table=dict(address=dispatch_address, old_count=60, new_count=61, old_rows_sha256=digest(dispatch_rows)),
        original_entries_preserved=True, type146_preserved=True,
        reservation=dict(begin=RESERVED,end=POOL_END,bytes=POOL_END-RESERVED,
                         pool_start=POOL_START,original_pool_bytes=POOL_END-POOL_START,new_pool_bytes=RESERVED-POOL_START,
                         used_table_bytes=end-RESERVED),
        patches=changes,
        scope='Table byte preservation only; reduced RAM pool, placement and runtime behavior need VM hardware regression. Not stock111, approved security or natural recovery qualification.',
        production_default_changed=False, hardware_qualified=False,
    )


def extend(image):
    if digest(image) != STOCK_SHA256:
        raise ValueError('only pinned original ws73.bin accepted')
    if image[:64] != digest(image[64:]).encode():
        raise ValueError('invalid firmware payload digest header')
    payload, report = _extend_payload(image[64:])
    output = digest(payload).encode()+payload
    report.update(source_image_sha256=digest(image),source_payload_sha256=digest(image[64:]),
                  output_image_sha256=digest(output),output_payload_sha256=digest(payload),
                  output_payload_bytes=len(payload))
    return output, report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--vm-diagnostic',action='store_true',help='explicitly acknowledge unqualified RAM/pool diagnostic')
    a=p.parse_args()
    if not a.vm_diagnostic: p.error('--vm-diagnostic required; never auto-patch default firmware')
    if a.output.exists() or a.report.exists() or a.output.resolve() == a.report.resolve():
        p.error('fresh distinct output/report paths required')
    image,report=extend(a.source.read_bytes())
    with a.output.open('xb') as f: f.write(image)
    a.output.chmod(0o600)
    with a.report.open('x') as f: json.dump(report,f,indent=2);f.write('\n')
    print(report['status'])


if __name__ == '__main__': main()
