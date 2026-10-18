#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify actual RAM firmware upload bytes in a sealed USB capture.

A staged file, warm Ready or matching version is not evidence that these bytes
were loaded. No device operations, firmware rewriting or recovery qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from ws73_capture import CaptureError

IMAGES = [(0x400000, 'ws73.bin'), (0x430000, 'wifi_cali.bin'), (0x440000, 'btc_cali.bin')]


def successful_out(path):
    pending = {}; result = []
    with Path(path).open('rb') as stream:
        h = stream.read(24)
        if len(h) != 24 or h[:4] != b'\xd4\xc3\xb2\xa1' or struct.unpack_from('<I', h, 20)[0] != 220 or struct.unpack_from('<HH',h,4)!=(2,4):
            raise CaptureError('classic little-endian USB mmapped pcap required')
        snaplen = struct.unpack_from('<I', h, 16)[0]
        ordinal = 0
        while header := stream.read(16):
            if len(header) != 16: raise CaptureError('truncated record')
            psec, fraction, size, original = struct.unpack('<IIII', header)
            if not 0<=fraction<1000000 or not 64 <= size <= original or size > snaplen: raise CaptureError('bad captured size')
            p = stream.read(size); ordinal += 1
            if len(p) != size: raise CaptureError('truncated USB data')
            urb, kind, transfer, ep, device, bus, _, flag, sec, usec, status, length, cap = struct.unpack_from('<QBBBBHBBqiiII', p)
            if transfer != 3 or ep != 1 or kind not in b'SCE': continue
            if sec<0 or not 0<=usec<1000000 or abs((sec*1000000000+usec*1000)-(psec*1000000000+fraction*1000))>1000000:
                raise CaptureError('USB/pcap timestamps disagree')
            key = bus, device, urb
            if kind == ord('S'):
                if key in pending or flag or cap != length or size != original or size != 64+cap:
                    raise CaptureError('missing/duplicate/truncated OUT submission')
                pending[key] = dict(bus=bus,device=device,record=ordinal,raw=p[64:],wall_ns=sec*1000000000+usec*1000)
            else:
                if key not in pending: raise CaptureError('completion without submit')
                row = pending.pop(key)
                if status or kind == ord('E') or length != len(row['raw']) or cap or size != 64:
                    raise CaptureError('failed/short OUT cannot prove firmware uploaded')
                row['completion_record'] = ordinal;result.append(row)
    if pending: raise CaptureError('unfinished OUT')
    return sorted(result,key=lambda row:row['record'])


def corroborate(rows, directory):
    chunks=[];command=None
    for row in rows:
        raw=row['raw']
        if raw.startswith(b'FILES '):
            if command is not None: raise CaptureError('missing prior firmware chunk')
            fields=re.fullmatch(rb'FILES 1 0x([0-9a-f]+) 0x([0-9a-f]+) 0x([0-9a-f]+)',raw.strip(b'\0 \r\n'))
            if not fields: raise CaptureError('malformed FILES')
            command=(row,*[int(v,16) for v in fields.groups()])
        elif command is not None:
            cmd,address,length,state=command;command=None
            if (row['bus'],row['device'])!=(cmd['bus'],cmd['device']) or len(raw)!=length:
                raise CaptureError('firmware body differs from command length or device')
            chunks.append(dict(address=address,state=state,raw=raw,command_record=cmd['record'],
                               data_record=row['record'],completion_record=row['completion_record'],bus=row['bus'],device=row['device']))
    if command is not None or not chunks: raise CaptureError('no complete actual upload; warm/staged is not loaded')
    if len({(c['bus'],c['device']) for c in chunks})!=1: raise CaptureError('one boot-device upload per report required')
    result=[];cursor=0
    for base,name in IMAGES:
        image=(Path(directory)/name).read_bytes();expected=image[64:]
        if len(image)<=64 or hashlib.sha256(expected).hexdigest().encode()!=image[:64]:
            raise CaptureError('invalid source image SHA header')
        offset=0;selected=[]
        while offset<len(expected):
            if cursor>=len(chunks): raise CaptureError('missing image chunks')
            c=chunks[cursor];cursor+=1;length=len(c['raw'])
            state=3 if len(expected)<=32768 else 0 if not offset else 2 if offset+length==len(expected) else 1
            if c['address']!=base+offset or not 0<length<=32768 or c['state']!=state:
                raise CaptureError('noncontiguous/oversize/out-of-order firmware chunk')
            if c['raw']!=expected[offset:offset+length]: raise CaptureError('actual USB bytes differ from staged image')
            selected.append({k:v for k,v in c.items() if k!='raw'});offset+=length
        result.append(dict(image=name,load_address=base,bytes=offset,image_sha256=hashlib.sha256(image).hexdigest(),
                           payload_sha256=hashlib.sha256(expected).hexdigest(),chunks=selected))
    if cursor!=len(chunks): raise CaptureError('extra/ambiguous upload')
    return dict(status='ACTUAL_RAM_UPLOAD_BYTES_MATCH',images=result,
                scope='Successful USB boot-mode OUT bytes match supplied images; not firmware execution/air delivery/secure attestation/natural recovery')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',type=Path,required=True)
    p.add_argument('--firmware-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('output exists; preserve sealed evidence')
    result=corroborate(successful_out(a.capture),a.firmware_dir)
    result['capture_sha256']=hashlib.sha256(a.capture.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])


if __name__=='__main__':main()
