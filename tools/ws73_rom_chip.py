#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only VM maintenance candidate, NOT an automatic firmware selector.

SDK110 e/us share the chip strap decoder at 0x40019000. Register decoding
does not establish ROM read validity, cold-power stability or authenticity.
No production firmware path is selected or changed by this module.
"""
import ctypes
import fcntl
import time
import hashlib
import json
from pathlib import Path
import subprocess

ADDRESS = 0x40019000
COMMAND = b'READM 0x40019000 4 '


def _decode_word(raw, allow_zero_observation):
    if not isinstance(raw, bytes) or len(raw) != 4:
        raise ValueError('exact four-byte chip observation required')
    value = int.from_bytes(raw, 'little')
    # Zero is mapped to U by the firmware, but is not evidence of a valid read.
    if value == 0xffffffff or value == 0 and not allow_zero_observation:
        raise ValueError('zero/all-one chip observation is not valid identification')
    strap = value & 0x0c
    model, bus = (0, 0) if strap in (0, 0x0c) else (1, 1) if strap == 4 else (2, 2 if value & 0x30 == 0x20 else 0)
    return dict(raw=raw.hex(),little_endian_u32=value,model_id=model,bus_id=bus,
                model=('U','S','E')[model],bus=('USB','SDIO','UART')[bus],
                zero_reply_ambiguous=value==0,
                access_validity='UNPROVED',automatic_selection_permitted=False)


def decode_candidate(raw):
    return _decode_word(raw,False)


def observe_candidate(raw):
    """Retain a known-board zero observation without accepting identification.

    A real U returned zero. Rejecting selection remains mandatory; discarding
    the observation would prevent testing its ROM/runtime/HCC consistency.
    """
    return _decode_word(raw,True)


def candidate_variant(raw):
    """Candidate directory only; callers MUST NOT treat this as authorization."""
    result = decode_candidate(raw)
    if result['bus_id'] != 0:
        raise ValueError('non-USB candidate is not supported by the USB driver')
    return 'e' if result['model_id'] == 2 else 'us'


def runtime_setup():
    # Fixed read only, same register-endpoint AHB mapping as the reference.
    return bytes(8)+b'\x00\x90\x00\x00'+((1 << 30) | 8).to_bytes(4,'little')


def runtime_observations(transfer, expected):
    rows=[]
    for _ in range(3):
        start=time.time_ns();transfer(2,runtime_setup());raw=transfer(130,4)
        result=observe_candidate(raw)
        if result['model'] != expected or result['bus'] != 'USB':
            raise ValueError('runtime strap differs from explicit board model/USB')
        rows.append(dict(before_wall_ns=start,after_wall_ns=time.time_ns(),**result))
    if len({r['raw'] for r in rows}) != 1:
        raise ValueError('unstable runtime chip observation')
    return rows


def rom_observations(fd, record, save, expected, *, directusb=None):
    # Reuse the existing exact native usbfs ABI. A larger IN request detects a
    # long/ASCII reply instead of silently truncating it to four bytes.
    from ws73_vm_register_reset import Bulk
    rows=record.setdefault('rom_chip_reads',[])
    for _ in range(3):
        row=dict(command=COMMAND.hex(),command_ascii=COMMAND.decode(),endpoint_out=1,
                 endpoint_in=129,requested_in=512,before_wall_ns=time.time_ns())
        rows.append(row);save()
        if directusb is not None:
            raw=directusb_exchange(directusb,row,save)
        else:
            out=ctypes.create_string_buffer(COMMAND)
            packet=Bulk(1,len(COMMAND),2000,ctypes.addressof(out))
            count=fcntl.ioctl(fd,0xc0185502,bytearray(bytes(packet)))
            row['out_actual']=count;save()
            if count != len(COMMAND):
                raise ValueError('short ROM READM command; no retry/fallback')
            incoming=ctypes.create_string_buffer(512)
            packet=Bulk(129,512,2000,ctypes.addressof(incoming))
            count=fcntl.ioctl(fd,0xc0185502,bytearray(bytes(packet)))
            raw=incoming.raw[:max(0,min(count,512))]
            row.update(in_actual=count,reply=raw.hex(),after_wall_ns=time.time_ns());save()
            if count != 4:
                raise ValueError('ROM chip read requires exact four-byte reply')
        result=observe_candidate(raw);row['candidate']=result;save()
        if result['model'] != expected or result['bus'] != 'USB':
            raise ValueError('ROM candidate differs from explicit board model/USB')
    if len({r['reply'] for r in rows}) != 1:
        raise ValueError('unstable ROM chip reply')
    return rows


DIRECTUSB_BINARY=Path('/bin/ws73-directusb-rom')


def validate_directusb_reply(value, guest):
    # Independent contract check, not a second chip decoder or transport.
    if (type(value)is not dict or type(value.get('schema'))is not int or value.get('schema')!=1 or
            value.get('status')!='ROM_BYTES_OBSERVED_NOT_MODEL_AUTHENTICATION' or
            value.get('scope')!='VM_ROM_READ_ONLY_NOT_HOST_OR_RECOVERY' or
            value.get('guest_port')!=guest or value.get('command')!=COMMAND.decode() or
            'error' in value):
        raise ValueError('incomplete/foreign DirectUSB ROM observation')
    for key,ep,requested,actual in [('out',1,len(COMMAND),len(COMMAND)),('in',129,512,4)]:
        v=value.get(key,{})
        if (type(v)is not dict or type(v.get('completion'))is not dict or
                any(type(v.get(k))is not int for k in ['endpoint','requested','pending_after']) or
                any(type(v['completion'].get(k))is not int for k in ['actual','buffer_length']) or v.get('endpoint')!=ep or v.get('requested')!=requested or
                v.get('stage')!='USB_COMPLETION_NOT_PROTOCOL_DELIVERY' or
                v.get('pending_after')!=0 or 'cancel_requested' in v or
                v.get('completion',{}).get('actual')!=actual or
                v['completion'].get('status')!='Ok(())' or
                v['completion'].get('buffer_length')!=actual):
            raise ValueError('DirectUSB short/failed/late/undrained operation')
    raw=value.get('reply')
    if type(raw)is not list or len(raw)!=4 or any(type(v)is not int or not 0<=v<=255 for v in raw):
        raise ValueError('exact DirectUSB four-byte receipt required')
    return bytes(raw)


def directusb_exchange(guest,row,save):
    binary=DIRECTUSB_BINARY
    expected=Path(str(binary)+'.sha256').read_text().strip()
    actual=hashlib.sha256(binary.read_bytes()).hexdigest()
    if expected!=actual:raise ValueError('frozen DirectUSB executor changed')
    row['directusb_executor']={'path':str(binary),'sha256':actual,'guest_port':guest};save()
    try:
        result=subprocess.run([str(binary),guest],capture_output=True,text=True,timeout=15)
    except subprocess.TimeoutExpired as error:
        row['directusb_failure']={'kind':'SUPERVISOR_TIMEOUT_NOT_DRAIN','stdout':str(error.stdout),'stderr':str(error.stderr)};save()
        raise
    row['directusb_result']={'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr};save()
    if result.returncode or result.stderr:raise ValueError('DirectUSB executor failed; no usbfs fallback')
    raw=validate_directusb_reply(json.loads(result.stdout),guest)
    row.update(out_actual=len(COMMAND),in_actual=len(raw),reply=raw.hex(),after_wall_ns=time.time_ns());save()
    return raw


def stage_directusb(source,root,manifest,copy_elf):
    from ws73_north_star import file_record
    source=source.resolve(strict=True);before=file_record(source)
    target=root/'bin/ws73-directusb-rom'
    copy_elf(source,target,root);target.chmod(0o755)
    if file_record(source)!=before or hashlib.sha256(target.read_bytes()).hexdigest()!=before['sha256']:
        raise ValueError('DirectUSB executor changed during staging')
    Path(str(target)+'.sha256').write_text(before['sha256']+'\n')
    manifest['directusb_rom_probe']={'source':before,'program':file_record(target),'scope':'EXPLICIT_VM_ROM_READ_ONLY_NOT_HOST_OR_MODEL_AUTHENTICATION'}
