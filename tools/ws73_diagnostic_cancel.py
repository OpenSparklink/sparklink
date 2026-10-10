# SPDX-License-Identifier: GPL-2.0-only
"""Strict syscall-record checks for real held-transfer cancellation gates.

Records alone do not qualify wire identity, QEMU timers or recovery. The
enclosing capture and host QMP checks must independently corroborate them.
"""
import ctypes
import errno
from sparklink.structs import SleDiagnosticResult, SleDiagnosticSubmit


COUNTERS = ('submitted', 'resolved', 'pending', 'timeouts')


def counts(row, suffix):
    values = [row[f'{key}_{suffix}'] for key in COUNTERS]
    if any(type(value) is not int or not 0 <= value < 1 << 32 for value in values):
        raise ValueError('actual typed cancellation counters required')
    return values


def result(generation, seq, opcode, state, error=0, data=b''):
    value = SleDiagnosticResult(version=1, generation=generation, seq=seq,
                                opcode=opcode, state=state, error=error, data_len=len(data))
    value.data[:len(data)] = data
    return bytes(value).hex()


def verify_cancellations(records):
    legacy = [r for r in records if 'legacy_poll' in r]
    metadata = next(r for r in records if r.get('case') == 'metadata')
    if len(legacy) != 3:
        raise ValueError('cancellation requires preceding real legacy seeds')
    at = records.index(legacy[-1])+1
    block = records[at:at+5]
    if [i for i,r in enumerate(records) if 'cancel' in r or 'hold_phase' in r] != list(range(at,at+5)):
        raise ValueError('no extra or out-of-order cancellation records allowed')
    if ([r.get('hold_phase') or r.get('cancel') for r in block] !=
            ['arm_ready', 'wait_held', 'held', 'release_ready', 'released']
            or records[at+5].get('case') != 'foreign_author_with_lease'):
        raise ValueError('exact contiguous pre-release cancellation coordination required')
    arm, waiting, held, release, final = block
    generation = metadata['generation']
    for row in (held, final):
        for key in ('generation', 'start_wall_ns', 'end_wall_ns'):
            if type(row[key]) is not int:
                raise ValueError('typed cancellation registration and clocks required')
        if row['generation'] != generation:
            raise ValueError('cancellation changed registration')
    for row in (arm, waiting, release):
        if type(row['wall_ns']) is not int:
            raise ValueError('typed hold coordination clock required')
    if (not legacy[-1]['end_wall_ns'] <= arm['wall_ns'] < held['start_wall_ns'] <
            waiting['wall_ns'] < held['end_wall_ns'] < release['wall_ns'] < final['end_wall_ns']
            or final['start_wall_ns'] != held['end_wall_ns']):
        raise ValueError('hold/cancel/release clocks are not ordered')
    if (type(held['quiet_elapsed_ns']) is not int or not 50_000_000 <= held['quiet_elapsed_ns'] < 2_000_000_000
            or type(held['observations']) is not int or not 1 <= held['observations'] <= 10000):
        raise ValueError('actual held quiet observation required')
    if not all(len(held[key]) == n for key, n in [('inputs',3),('outputs',3),('cancel_outputs',2),('results',3)]):
        raise ValueError('three admissions, two cancellations and three results required')
    seqs = []
    for i, opcode in enumerate([0x0406,0x0406,0x0403]):
        value = SleDiagnosticSubmit(version=1, generation=generation, request_id=8+i,
                                    timeout_ms=5000, opcode=opcode, action=1)
        if held['inputs'][i] != bytes(value).hex():
            raise ValueError('cancellation canonical admission input mismatch')
        raw = bytes.fromhex(held['outputs'][i])
        if len(raw) != ctypes.sizeof(SleDiagnosticSubmit):
            raise ValueError('canonical cancellation admission output size required')
        seq = SleDiagnosticSubmit.from_buffer_copy(raw).seq
        if seq != legacy[-1]['seq']+i+1:
            raise ValueError('held and queued admissions are not contiguous')
        seqs.append(seq); value.seq = seq
        if held['outputs'][i] != bytes(value).hex():
            raise ValueError('cancellation changed admission fields')
        if i != 1:
            value.action = 2
            if held['cancel_outputs'][int(i==2)] != bytes(value).hex():
                raise ValueError('cancellation must retain original admission sequence')
    expected = [result(generation,seqs[0],0x0406,3,-errno.ECANCELED),
                result(generation,seqs[1],0x0406,1),
                result(generation,seqs[2],0x0403,3,-errno.ECANCELED)]
    if held['results'] != expected:
        raise ValueError('active/queued canceled results or pending fresh result differ')
    expected[1] = result(generation,seqs[1],0x0406,2,data=bytes.fromhex(metadata['data']))
    if final['results'] != expected:
        raise ValueError('late reply revived canceled request or changed fresh result')
    before, pending = counts(held,'before'), counts(held,'after')
    after = counts(final,'after')
    if (before != counts(legacy[-1],'after') or before[2] or
            pending != [before[0]+3,before[1]+2,1,before[3]] or
            counts(final,'before') != pending or
            after != [pending[0],pending[1]+1,0,pending[3]]):
        raise ValueError('cancellation/replay/reply accounting mismatch')
    fill = next(r for r in records if r.get('eviction') == 'fill')
    if (counts(fill,'before') != after or fill['seq'] != seqs[-1]+1 or
            fill['start_wall_ns'] < final['end_wall_ns']):
        raise ValueError('cancellation/foreign eviction continuity mismatch')
