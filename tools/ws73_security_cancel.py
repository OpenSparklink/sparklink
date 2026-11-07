# SPDX-License-Identifier: GPL-2.0-only
"""Scratch-VM passive-author cancellation; no injected replies or wire Engine."""
import ctypes
import errno
import time

from sparklink.structs import SleSecurityNegotiationCancel as Cancel
from ws73_capture import CaptureError
from ws73_channel_grant import business_evidence

CANCEL = (1 << 30) | (ctypes.sizeof(Cancel) << 16) | (ord('S') << 8) | 0xd4
NEGATIVES = {'version': errno.EOPNOTSUPP, 'reserved': errno.EINVAL,
             'generation': errno.ENODEV, 'lifetime': errno.ESTALE,
             'handle': errno.ESTALE, 'request': errno.ENOENT,
             'nonowner': errno.EPERM}


def request(submit):
    return Cancel(version=1, generation=submit.generation, lifetime=submit.lifetime,
                  request_id=submit.request_id, handle=submit.handle)


def exercise(row, save, writers, observers, requests, links, passive, original_deadline=False):
    from ws73_security_capabilities import denied, RESULT, Result
    value = request(requests[passive])
    row['cancel'] = dict(input=bytes(value).hex(), negative=[], returns=[])
    evidence = row['cancel']
    for kind, expected in NEGATIVES.items():
        bad = Cancel.from_buffer_copy(bytes(value))
        if kind == 'version': bad.version = 0
        elif kind == 'reserved': bad.reserved = 1
        elif kind == 'generation': bad.generation += 1
        elif kind == 'lifetime': bad.lifetime += 1
        elif kind == 'handle': bad.handle ^= 1
        elif kind == 'request': bad.request_id += 1
        fd = (observers if kind == 'nonowner' else writers)[passive].fileno()
        actual = denied(fd, CANCEL, bad)
        observed = writers[passive].security_negotiation(links[passive].lifetime, links[passive].handle, 1)
        evidence['negative'].append(dict(kind=kind, input=bytes(bad).hex(), errno=actual, after=bytes(observed).hex()))
        save()
        if actual != expected or bytes(observed).hex() != row['t_armed']:
            raise ValueError('bad cancellation must not mutate the passive author: ' + kind)
    if original_deadline:
        remaining=(requests[passive].deadline_monotonic_ns-time.monotonic_ns())/1_000_000_000
        time.sleep(max(0,remaining)+0.02)
        expired=writers[passive].security_negotiation(value.lifetime,value.handle,1)
        evidence['expired_before_cancel']=bytes(expired).hex()
        save()
    evidence['before_wall_ns'] = time.time_ns()
    for _ in range(2):
        writers[passive].cancel_security_negotiation(value)
        evidence['returns'].append(0)
        observed = writers[passive].security_negotiation(value.lifetime, value.handle, 1)
        evidence.setdefault('observations', []).append(bytes(observed).hex())
        save()
    other = 1-passive
    req = requests[other]
    evidence['unapproved_errno'] = denied(writers[other].fileno(), RESULT,
        Result(version=1, generation=req.generation, lifetime=req.lifetime, handle=req.handle, request_id=1))
    row['results'] = [None, None]
    row['results'][passive] = bytes(observed).hex()


def verify(row, requests, passive, original_deadline=False):
    from ws73_management_setup import decode
    from ws73_security_capabilities import Result, OFFER
    evidence = row['cancel']
    if bytes(decode(Cancel, evidence['input'])) != bytes(request(requests[passive])):
        raise ValueError('cancel must bind the original author request')
    if evidence['returns'] != [0, 0] or evidence['unapproved_errno'] != errno.ENOENT:
        raise ValueError('idempotent local withdrawal cannot approve the peer')
    rows = evidence['negative']
    if len(rows) != len(NEGATIVES) or {v['kind']: v['errno'] for v in rows} != NEGATIVES:
        raise ValueError('all exact cancel authority/reference denials required')
    good = request(requests[passive])
    for item in rows:
        bad = Cancel.from_buffer_copy(bytes(good));kind = item['kind']
        if kind == 'version': bad.version = 0
        elif kind == 'reserved': bad.reserved = 1
        elif kind == 'generation': bad.generation += 1
        elif kind == 'lifetime': bad.lifetime += 1
        elif kind == 'handle': bad.handle ^= 1
        elif kind == 'request': bad.request_id += 1
        if item['input'] != bytes(bad).hex() or item['after'] != row['t_armed']:
            raise ValueError('invalid cancellation must preserve exact armed state')
    if evidence['observations'] != [row['results'][passive]] * 2:
        raise ValueError('one terminal observation retained across repeated cancellation')
    out = decode(Result, row['results'][passive]);req = requests[passive]
    if original_deadline and evidence.get('expired_before_cancel')!=row['results'][passive]:raise ValueError('deadline terminal must exist before cancelling it')
    if (out.version,out.profile,out.generation,out.lifetime,out.request_id,out.handle,out.role,out.state,out.flags,out.status,out.error) != (1,1,req.generation,req.lifetime,1,req.handle,1,7 if original_deadline else 6,0,0,-errno.ETIMEDOUT if original_deadline else -errno.ECANCELED) or bytes(out.local_caps) != OFFER or any(out.peer_caps) or out.comparison_code != 0:
        raise ValueError('exact cancelled original passive request required')
    if row['results'][1-passive] is not None or not row['t_arm_before_wall_ns'] <= evidence['before_wall_ns'] <= row['observed_wall_ns']:
        raise ValueError('no peer approval or time reversal')
    if row['ordinary_denial'].get('cancel_errno') != errno.EPERM:
        raise ValueError('ordinary inherited Managed fd must not cancel')


def corroborate(r, capture):
    from ws73_security_capabilities import verify as verify_all
    from ws73_channel_deadline import control
    row = verify_all(r);g = r['channel_grant'];i = r['index']
    _, legs = business_evidence(g, r, capture)
    for n in [0, 1]:
        same = lambda v: (v['bus'], v['device']) == (r['usb'][n]['bus'], r['usb'][n]['device'])
        window = lambda v: same(v) and row['start_wall_ns'] <= v['wall_ns'] <= row['cleanup_before_wall_ns']
        if any(window(v) and v['opcode'] in [0x1812, 0x1c03, 0x1c05] for v in capture['commands']) or any(window(v) and v['event'] in [0x14, 0x11, 0xe] for v in capture['native_events']):
            raise CaptureError('passive local cancellation must not send or receive security protocol')
        event = row['down'][n];raw = bytes.fromhex(event['params']);owner = g['owners'][n]
        matches = [v for v in capture['native_events'] if same(v) and v['event'] == event['event'] and v['params'] == event['params'] and row['cleanup_before_wall_ns'] <= v['wall_ns'] <= row['cleanup_after_wall_ns']]
        if len(matches) != 1 or event['generation'] != owner['generation'] or event['lost'] or len(raw) != 4 or raw[0] or int.from_bytes(raw[1:3], 'little') != owner['handle']:
            raise CaptureError('actual later cleanup Down required on both sides')
    control(capture,r['usb'][i],0x1403,g['owners'][i]['handle'].to_bytes(2,'little')+b'\x10',row['cleanup_before_wall_ns'],row['cleanup_after_wall_ns'],status=True)
    for enabled in [True,False]: control(capture,r['usb'][1-i],0x1002,bytes([enabled,0]),row['cleanup_after_wall_ns'],row['scan_checked_wall_ns'])
    return dict(status='REAL_SECURITY_ORIGINAL_DEADLINE_CORROBORATED' if r.get('security_original_deadline',False) else 'REAL_PASSIVE_AUTHOR_CANCEL_CORROBORATED', business_legs=legs,
        business_round_trips=4, in_flight_installation_qualified=False,
        scope='Same physical Session/lease retained; ordinary random peer-checked business before/after one passive request cancellation. No Agent, wire cancellation, post-submit race, authentication, Bond or automatic recovery qualification.')
