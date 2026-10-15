# SPDX-License-Identifier: GPL-2.0-only
"""Actual partial PDU withdrawal evidence, not a completed business exchange."""
from ws73_capture import CaptureError


def corroborate(row, outer, capture):
    prefix=row['revoke_prefix'];payload=bytes.fromhex(prefix['payload']);i=row['index']
    if len(payload)!=2042 or payload[:8]!=b'SLKREV01' or row['armed'].get('prefix')!=prefix['payload']:
        raise CaptureError('original random2042-byte admitted PDU required')
    expected=b'\x1f\0\xfb\x07\xf1'+payload
    owner=outer['usb'][i];handle=row['owners'][i]['handle']
    start=prefix['admission_before_wall_ns'];before=outer['release_before_wall_ns'];after=outer['release_after_wall_ns']
    packets=[p for p in capture['acb_packets'] if (p['bus'],p['device'])==(owner['bus'],owner['device'])
             and p['direction']=='out' and p['handle']==handle and start<=p['wall_ns']<=row['end_wall_ns']]
    if not packets or packets[0].get('boundary')!=1 or packets[0]['wall_ns']>=before:
        raise CaptureError('first actual USB prefix must precede authority withdrawal')
    data=b''
    for n,p in enumerate(packets):
        if p['wall_ns']>=after or p.get('boundary')!=(1 if n==0 else 2) or not p.get('completion'):
            raise CaptureError('new submit after withdrawal, interleaved PDU or completed prefix')
        data+=bytes.fromhex(p['data'])
    if not expected.startswith(data) or not 0<len(data)<len(expected) or not 1<=len(packets)<=8:
        raise CaptureError('exact incomplete original PDU prefix required')
    down=outer['down'][i]
    if not before<=down['wall_ns']<=row['end_wall_ns']:
        raise CaptureError('actual old physical connection down required')
    # NOCP may arrive after revocation; report it without inferring a reuse barrier.
    late=[e for e in capture['native_events'] if e['event']==9 and (e['bus'],e['device'])==(owner['bus'],owner['device']) and after<=e['wall_ns']<=row['end_wall_ns']]
    return dict(status='ACTUAL_BEGUN_PDU_WITHDRAWAL_PREFIX_PASS',submitted_fragments=len(packets),
                submitted_bytes=len(data),pdu_bytes=len(expected),first_submit_record=packets[0]['record'],
                last_submit_record=packets[-1]['record'],late_nocp_records=[e['record'] for e in late],
                no_new_submit_after_withdrawal=True,source_application_round_trips=0,
                scope='Per-controller Managed release/final File; actual disconnect and unchanged peer lease/readiness. Not peer business after disconnect, original-deadline or full late-NOCP/reuse safety.')
