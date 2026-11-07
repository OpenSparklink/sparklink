#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent fixed SLE eFuse read observation using existing USB readers.

No device I/O, address configuration, valid-address inference or Host Engine.
Firmware error output is deliberately withheld, even when present on USB.
"""
import struct

from ws73_boot_code_evidence import successful_in
from ws73_capture import CaptureError, hcc_command, hcc_receive
from ws73_firmware_upload_evidence import successful_out


def corroborate_rows(outgoing, incoming):
    requests = []
    for row in outgoing:
        raw = row['raw']
        if len(raw) >= 70 and raw[64:66] == b'\x19\x09' and raw[68:70] == b'\x0b\x00':
            if (len(raw) != 128 or struct.unpack_from('<II', raw) != (0, 128)
                    or raw[66:74] != b'\x20\x00\x0b\x00\x02\x00\x7d\x06'
                    or any(raw[74:])):
                raise CaptureError('invalid fixed read-only SLE eFuse request')
            requests.append(row)
    if len(requests) != 1:
        raise CaptureError('one complete fixed SLE eFuse request required')
    request = requests[0]
    same = lambda row: (row['bus'], row['device']) == (request['bus'], request['device'])
    later = [row for row in outgoing if same(row) and row['record'] > request['completion_record']
             and hcc_command(row['raw']) is not None]
    if not later:
        raise CaptureError('address-source observation must precede actual DLI bootstrap')
    end = min(row['record'] for row in later)
    for row in outgoing:
        raw = row['raw']
        if same(row) and row['record'] < end and len(raw) >= 70 and raw[64:66] == b'\x19\x09' and raw[68:70] == b'\x0a\x00':
            raise CaptureError('mutating platform request is not read-only evidence')
    observations = []
    for row in incoming:
        if not same(row) or not request['completion_record'] < row['submit_record'] < row['record'] < end:
            continue
        if not row['successful']:
            raise CaptureError('failed/short IN during address-source query')
        for service, queue, offset, payload in hcc_receive(row['raw']):
            if (service, queue) != (1, 9):
                continue
            if len(payload) < 4:
                raise CaptureError('short platform message')
            message, length = struct.unpack_from('<HH', payload)
            if message != 5:
                continue
            if len(payload) < 12 or not 8 <= length <= len(payload) - 4:
                raise CaptureError('invalid address-source allocation length')
            status, size = struct.unpack_from('<II', payload, 4)
            if size not in ([0, 6] if status else [6]) or size > length - 8 or size > len(payload) - 12:
                raise CaptureError('invalid address-source output length')
            observations.append(dict(field_id=125, status=status, length=size,
                                     bytes=payload[12:18].hex() if not status else None,
                                     bus_number=row['bus'], device=row['device'],
                                     request_record=request['record'], request_completion=request['completion_record'],
                                     response_submit=row['submit_record'], response_record=row['record'],
                                     hcc_offset=offset, first_dli_record=end))
    if len(observations) != 1:
        raise CaptureError('one unambiguous address-source response before DLI required')
    return dict(status='ACTUAL_HCC_READ_EFUSE_OBSERVATION', observation=observations[0],
                address_validated=False,
                scope='Paired USB observation only; not eFuse truth, uniqueness, initialization branch, silicon attestation, Ready or peer business')


def corroborate(path):
    return corroborate_rows(successful_out(path), successful_in(path))
