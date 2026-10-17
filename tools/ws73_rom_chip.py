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


def rom_observations(fd, record, save, expected):
    # Reuse the existing exact native usbfs ABI. A larger IN request detects a
    # long/ASCII reply instead of silently truncating it to four bytes.
    from ws73_vm_register_reset import Bulk
    rows=record.setdefault('rom_chip_reads',[])
    for _ in range(3):
        row=dict(command=COMMAND.hex(),command_ascii=COMMAND.decode(),endpoint_out=1,
                 endpoint_in=129,requested_in=512,before_wall_ns=time.time_ns())
        rows.append(row);save()
        out=ctypes.create_string_buffer(COMMAND)
        packet=Bulk(1,len(COMMAND),2000,ctypes.addressof(out))
        count=fcntl.ioctl(fd,0xc0185502,bytearray(bytes(packet)))
        row['out_actual']=count;save()
        if count != len(COMMAND):
            raise ValueError('short ROM READM command; no retry/fallback')
        incoming=ctypes.create_string_buffer(512)
        packet=Bulk(129,512,2000,ctypes.addressof(incoming))
        count=fcntl.ioctl(fd,0xc0185502,bytearray(bytes(packet)))
        row.update(in_actual=count,reply=incoming.raw[:max(0,min(count,512))].hex(),after_wall_ns=time.time_ns());save()
        if count != 4:
            raise ValueError('ROM chip read requires exact four-byte reply')
        result=observe_candidate(incoming.raw[:4]);row['candidate']=result;save()
        if result['model'] != expected or result['bus'] != 'USB':
            raise ValueError('ROM candidate differs from explicit board model/USB')
    if len({r['reply'] for r in rows}) != 1:
        raise ValueError('unstable ROM chip reply')
    return rows
