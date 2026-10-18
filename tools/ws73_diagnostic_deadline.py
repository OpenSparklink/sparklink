# SPDX-License-Identifier: GPL-2.0-only
"""Strict original-deadline records; wire/host checks remain mandatory.

This is queued expiry observed through real submit/result syscalls, not proof
of autonomous heartbeat expiry, active USB timeout or fault recovery.
"""
import errno
from sparklink.structs import SleDiagnosticSubmit
from ws73_diagnostic_cancel import result


def verify_deadline(held, final, generation, last_seq):
    row = held.get('deadline')
    if type(row) is not dict or set(row) != {'input','output','initial_result',
            'admit_before_monotonic_ns','admit_after_monotonic_ns','samples'}:
        raise ValueError('exact queued original-deadline evidence required')
    request = SleDiagnosticSubmit(version=1,generation=generation,request_id=11,
                                  timeout_ms=100,opcode=0x0403,action=1)
    if row['input'] != bytes(request).hex():
        raise ValueError('original 100ms admission fields changed')
    request.seq = last_seq+1
    output = bytes(request).hex()
    pending = result(generation,request.seq,0x0403,1)
    expired = result(generation,request.seq,0x0403,3,-errno.ETIMEDOUT)
    if row['output'] != output or row['initial_result'] != pending:
        raise ValueError('queued initial identity/state differs')
    before, after = row['admit_before_monotonic_ns'], row['admit_after_monotonic_ns']
    if (type(before) is not int or type(after) is not int or
            not 0 < before <= after <= before+20_000_000):
        raise ValueError('bounded actual monotonic admission interval required')
    samples=row['samples']
    if type(samples) is not list or not 10 <= len(samples) <= 512:
        raise ValueError('bounded repeated-ID observations required')
    previous=after; first_timeout=None; pending_count=0
    for sample in samples:
        if type(sample) is not dict or set(sample) != {'before_monotonic_ns','after_monotonic_ns','retry','result'}:
            raise ValueError('canonical deadline sample required')
        start,end=sample['before_monotonic_ns'],sample['after_monotonic_ns']
        if (type(start) is not int or type(end) is not int or
                not previous <= start <= end <= start+20_000_000 or start-previous > 20_000_000):
            raise ValueError('monotonic continuous repeated-ID sampling required')
        if sample['retry'] != output:
            raise ValueError('deadline retry changed admission or sequence')
        if sample['result']==pending and first_timeout is None:
            pending_count+=1
        elif sample['result']==expired:
            if first_timeout is None:first_timeout=end
        else:
            raise ValueError('expired result revived, wrong errno or payload')
        previous=end
    if (pending_count < 5 or first_timeout is None or
            not before+75_000_000 <= first_timeout <= after+180_000_000 or
            samples[-1]['before_monotonic_ns'] < after+125_000_000 or
            previous-before > held['quiet_elapsed_ns']):
        raise ValueError('original deadline was renewed, early, unobserved or not retained')
    if final.get('deadline') != {'result':expired}:
        raise ValueError('release changed or revived expired queued result')
    return request.seq
