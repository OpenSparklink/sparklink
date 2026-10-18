# SPDX-License-Identifier: GPL-2.0-only
"""Queued expiry counted by the worker before the first post-wait result call.

MGMT_STATS is observation-only. Wire/host corroboration and a frozen actual C
probe remain mandatory; this does not qualify active USB timeout or retirement.
"""
import errno
import struct
from sparklink.structs import SleDiagnosticSubmit
from ws73_diagnostic_cancel import counts,result


def stats_bytes(submitted,resolved,pending,timeouts):
    return struct.pack('<HHIII',pending,0,submitted,resolved,timeouts).hex()


def verify_autonomous(held,final,generation,last_seq):
    row=held.get('autonomous')
    clocks=('admit_before_monotonic_ns','admit_after_monotonic_ns',
            'quiet_before_monotonic_ns','quiet_after_monotonic_ns',
            'stats_before_monotonic_ns','stats_after_monotonic_ns',
            'result_before_monotonic_ns','result_after_monotonic_ns')
    if type(row) is not dict or set(row)!=set(clocks)|{'input','output','initial_result','stats_before','stats_after','result'}:
        raise ValueError('exact passive queued-expiry evidence required')
    request=SleDiagnosticSubmit(version=1,generation=generation,request_id=12,
                                timeout_ms=100,opcode=0x0403,action=1)
    if row['input']!=bytes(request).hex():
        raise ValueError('canonical autonomous original admission required')
    request.seq=last_seq+1
    expired=result(generation,request.seq,0x0403,3,-errno.ETIMEDOUT)
    if (row['output']!=bytes(request).hex() or row['initial_result']!=result(generation,request.seq,0x0403,1)
            or row['result']!=expired or final.get('autonomous')!={'result':expired}):
        raise ValueError('passive initial/expired/retained identity or result differs')
    times=[row[key] for key in clocks]
    if any(type(v) is not int or v<=0 for v in times) or times!=sorted(times):
        raise ValueError('typed ordered passive clocks required')
    a,b,c,d,e,f,g,h=times
    if (c-a>20_000_000 or not 700_000_000<=d-c<=1_000_000_000 or
            e-d>20_000_000 or f-e>20_000_000 or g-f>20_000_000 or h-g>20_000_000
            or h-a>held['quiet_elapsed_ns']):
        raise ValueError('bounded silent window and counters before result required')
    submitted,resolved,pending,timeouts=counts(held,'before')
    if (pending or row['stats_before']!=stats_bytes(submitted+5,resolved+3,2,timeouts+1)
            or row['stats_after']!=stats_bytes(submitted+5,resolved+4,1,timeouts+2)):
        raise ValueError('autonomous timeout must already be counted before result/retry')
    return request.seq
