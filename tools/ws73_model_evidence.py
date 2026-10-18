#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only HCC firmware-reported identity evidence, never silicon attestation.

Reuse existing paired USB readers. No device I/O or protocol Engine. Allocation
padding is never exposed in the result, and is never interpreted as identity.
"""
import struct

from ws73_boot_code_evidence import successful_in
from ws73_capture import CaptureError, hcc_command, hcc_receive
from ws73_firmware_upload_evidence import successful_out


def corroborate_rows(outgoing, incoming):
    requests = []
    for row in outgoing:
        raw = row['raw']
        if len(raw) >= 72 and raw[64:66] == b'\x19\x09' and raw[68:70] == b'\x10\x00':
            if (len(raw) != 128 or struct.unpack_from('<II', raw) != (0, 128)
                    or raw[66:68] != b'\x20\x00' or raw[70:73] != b'\x01\x00\x00'
                    or any(raw[73:])):
                raise CaptureError('invalid GET_CHIP_TYPE request envelope')
            requests.append(row)
    if len(requests) != 1:
        raise CaptureError('one complete GET_CHIP_TYPE request required')
    request = requests[0]
    same = lambda row: (row['bus'], row['device']) == (request['bus'], request['device'])
    later = [row for row in outgoing if same(row) and row['record'] > request['completion_record']
             and hcc_command(row['raw']) is not None]
    if not later:
        raise CaptureError('identity must precede actual DLI bootstrap')
    end = min(row['record'] for row in later)
    candidates = []
    for row in incoming:
        if not same(row) or not request['completion_record'] < row['submit_record'] < row['record'] < end:
            continue
        if not row['successful']:
            raise CaptureError('failed/short IN during chip query')
        for service, queue, offset, payload in hcc_receive(row['raw']):
            if (service, queue) != (1, 9):
                continue
            if len(payload) < 4:
                raise CaptureError('short platform message')
            message, length = struct.unpack_from('<HH', payload)
            if message != 10:
                continue
            if length < 10 or length > len(payload) - 4 or len(payload) < 14:
                raise CaptureError('invalid platform allocation length')
            status, size = struct.unpack_from('<II', payload, 4)
            model, bus = payload[12:14]
            if status or size != 2 or model not in (0, 1, 2) or bus != 0:
                raise CaptureError('failed/unknown/nonUSB chip response')
            candidates.append(dict(model='WS73' + 'USE'[model], model_id=model, bus='USB', bus_id=bus,
                                   bus_number=row['bus'], device=row['device'], request_record=request['record'],
                                   request_completion=request['completion_record'], response_submit=row['submit_record'],
                                   response_record=row['record'], hcc_offset=offset, first_dli_record=end))
    if len(candidates) != 1:
        raise CaptureError('one unambiguous chip response before DLI required')
    return dict(status='ACTUAL_HCC_FIRMWARE_REPORTED_MODEL_MATCH', observation=candidates[0],
                scope='Paired physical USB request/reply before DLI; not silicon/board/firmware attestation, Ready, peer business or natural recovery')


def corroborate(path):
    return corroborate_rows(successful_out(path), successful_in(path))
