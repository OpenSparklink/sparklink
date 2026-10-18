#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only corroboration of fixed boot READM code windows, not execution proof.

No device access or memory-read command is performed here. Raw bytes remain in
the private capture/dump; the report contains hashes and record provenance only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from ws73_capture import CaptureError
from ws73_firmware_upload_evidence import successful_out


def successful_in(path):
    pending = {}; rows = []
    with Path(path).open('rb') as stream:
        h = stream.read(24)
        if len(h) != 24 or h[:4] != b'\xd4\xc3\xb2\xa1' or struct.unpack_from('<HH', h, 4) != (2, 4) or struct.unpack_from('<I', h, 20)[0] != 220:
            raise CaptureError('classic little-endian USB mmapped pcap required')
        snaplen = struct.unpack_from('<I', h, 16)[0]; ordinal = 0
        while header := stream.read(16):
            if len(header) != 16: raise CaptureError('truncated record')
            psec, fraction, size, original = struct.unpack('<IIII', header)
            if not 0 <= fraction < 1000000 or not 64 <= size <= original or size > snaplen:
                raise CaptureError('bad captured size')
            p = stream.read(size); ordinal += 1
            if len(p) != size: raise CaptureError('truncated USB record')
            urb, kind, transfer, ep, device, bus, _, flag, sec, usec, status, length, cap = struct.unpack_from('<QBBBBHBBqiiII', p)
            if transfer != 3 or ep != 0x81 or kind not in b'SCE': continue
            if sec < 0 or not 0 <= usec < 1000000 or abs(sec*1000000000+usec*1000-psec*1000000000-fraction*1000) > 1000000:
                raise CaptureError('USB/pcap timestamps disagree')
            key = bus, device, urb
            if kind == ord('S'):
                if key in pending or cap or size != 64 or size != original:
                    raise CaptureError('duplicate/truncated IN submission')
                pending[key] = dict(bus=bus, device=device, submit_record=ordinal, requested=length)
            else:
                if key not in pending: raise CaptureError('IN completion without submit')
                row = pending.pop(key)
                if size != original or size != 64+cap or cap > length or (cap and flag):
                    raise CaptureError('truncated IN completion')
                row.update(record=ordinal, raw=p[64:], length=length,
                           successful=kind == ord('C') and status == 0 and cap == length)
                rows.append(row)
    # Unrelated runtime URBs can be pending when capture is sealed. Selected
    # READM operations must independently have a complete exact response below.
    return rows


def corroborate(capture, dump, windows):
    if not windows or len(windows) > 4: raise CaptureError('one to four bounded code windows required')
    addresses = []
    for address, size in windows:
        if address % 4 or size % 4 or not 0 < size <= 4096 or not 0x100000 <= address < address+size <= 0x200000:
            raise CaptureError('aligned fixed ROM code window required')
        addresses.extend(range(address, address+size, 4))
    if len(set(addresses)) != len(addresses): raise CaptureError('overlapping windows')
    expected = Path(dump).read_bytes()
    if len(expected) != len(addresses)*4: raise CaptureError('complete bounded dump required')
    outgoing = successful_out(capture); incoming = successful_in(capture); selected = []
    wanted = set(addresses)
    for i, row in enumerate(outgoing):
        fields = re.fullmatch(rb'READM 0x([0-9a-f]{8}) 4 ', row['raw'])
        if not fields or int(fields[1], 16) not in wanted: continue
        end = outgoing[i+1]['record'] if i+1 < len(outgoing) else float('inf')
        responses = [v for v in incoming if row['completion_record'] < v['submit_record'] < v['record'] < end]
        if len(responses) != 1: raise CaptureError('one complete response before next command required')
        response = responses[0]
        if ((response['bus'], response['device']) != (row['bus'], row['device']) or
                not response['successful'] or response['requested'] != 4 or response['length'] != 4):
            raise CaptureError('successful same-device four-byte READM required')
        selected.append((int(fields[1], 16), row, response))
    if [v[0] for v in selected] != addresses or len({(v[1]['bus'], v[1]['device']) for v in selected}) != 1:
        raise CaptureError('exact ordered single-device code words required')
    actual = b''.join(v[2]['raw'] for v in selected)
    if actual != expected: raise CaptureError('dump differs from actual received USB bytes')
    return dict(status='ACTUAL_BOOT_READM_CODE_BYTES_MATCH', bytes=len(actual),
                dump_sha256=hashlib.sha256(actual).hexdigest(),
                capture_sha256=hashlib.sha256(Path(capture).read_bytes()).hexdigest(),
                windows=[dict(address=a, bytes=n) for a,n in windows],
                words=[dict(address=a, command_record=o['record'], command_completion=o['completion_record'],
                            receive_submit=i['submit_record'], receive_completion=i['record'], bus=o['bus'], device=o['device'])
                       for a,o,i in selected],
                scope='Captured fixed code bytes only; not authenticated firmware identity, valid disassembly, control-flow proof, peer delivery or natural recovery')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--dump', type=Path, required=True)
    p.add_argument('--window', action='append', required=True, help='base:size; integer literals, fixed code only')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists(): p.error('output exists; preserve sealed evidence')
    windows = [tuple(int(v, 0) for v in x.split(':')) for x in a.window]
    if any(len(v) != 2 for v in windows): p.error('base:size required')
    report = corroborate(a.capture, a.dump, windows)
    with a.output.open('x') as out: json.dump(report, out, indent=2); out.write('\n')
    print(report['status'])


if __name__ == '__main__': main()
