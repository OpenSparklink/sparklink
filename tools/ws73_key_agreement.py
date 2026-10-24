# SPDX-License-Identifier: GPL-2.0-only
"""Read-only actual 134..142 candidate agreement evidence; not an Engine.

The kernel alone produces public points/nonces/proofs. This checker sends no
raw PDU, supplies no keys and cannot replace crypto, Agent or install results.
"""
from ws73_security_capabilities import verify,OFFER
from ws73_channel_grant import business_evidence
from ws73_channel_deadline import control
from ws73_capture import CaptureError


def corroborate(r,capture,*,prefix_only=False):
    numeric=r.get('numeric_comparison')
    if not numeric and r.get('key_agreement') is not True:raise CaptureError('explicit candidate agreement gate required')
    installation=r.get('unauthenticated_encryption',False) or numeric=='numeric-approve'
    offer=bytes([1,0,4,16,0,2,2,2,2,0]) if numeric else OFFER
    order=([0x134,0x135,0x136,0x137,0x13c,0x139]+([0x141,0x142] if installation else [])) if numeric else [0x134,0x135,0x136,0x137,0x138,0x139,0x13a,0x141,0x142]
    if prefix_only and (r.get('protected_requirement') not in (1,2) or not installation or numeric and numeric!='numeric-approve'):
        raise CaptureError('explicit positive protected-fd prelude required')
    row=r['security_capabilities'] if prefix_only else verify(r)
    high=row['observed_wall_ns'] if prefix_only else row['cleanup_before_wall_ns']
    g=r['channel_grant'];i=r['index'];commands={};received={};proof=[]
    for n in [0,1]:
        owner=g['owners'][n];usb=r['usb'][n];same=lambda v:(v['bus'],v['device'])==(usb['bus'],usb['device'])
        tx_indices=[index for index in order if (index in [0x134,0x136,0x139,0x141])==(n==i)]
        rx_indices=[index for index in order if index not in tx_indices]
        tx=[v for v in capture['commands'] if same(v) and v['opcode']==0x1812 and row['start_wall_ns']<=v['wall_ns']<=high]
        complete=[v for v in capture['complete'] if same(v) and v['opcode']==0x1812 and row['start_wall_ns']<=v['wall_ns']<=high]
        rx=[v for v in capture['native_events'] if same(v) and v['event']==0x14 and row['g_start_before_wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
        if len(tx)!=len(tx_indices) or len(complete)!=len(tx_indices) or len(rx)!=len(rx_indices):raise CaptureError('all9 real relay submits/Completes/opposite ingress required')
        local=[]
        for command,index in zip(tx,tx_indices):
            raw=bytes.fromhex(command['params']);length=10 if index in [0x134,0x135] else 70 if index==0x136 else 64 if index==0x137 else 32 if index==0x13c else 16
            if raw[:2]!=owner['handle'].to_bytes(2,'little') or raw[2:4]!=index.to_bytes(2,'little') or len(raw)!=length+5 or raw[4]!=length or not command.get('completion') or not row['g_start_before_wall_ns']<=command['wall_ns']<=row['observed_wall_ns']:raise CaptureError('exact role/handle/index/length and real USB completion required')
            if index in [0x134,0x135] and raw[5:]!=offer or index==0x136 and raw[5:11]!=bytes([16,0 if numeric else 1,2,2,2,2]):raise CaptureError('only known no-entry/no-MITM/no-Bond offer accepted')
            replies=[v for v in complete if v['status']==0 and v['value']==raw[:4].hex() and command['wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
            if len(replies)!=1:raise CaptureError('real frozen handle/index terminal Complete required')
            commands[index]=(command,replies[0],raw[5:]);local.append(dict(command=command,complete=replies[0]))
        for event,index in zip(rx,rx_indices):
            raw=bytes.fromhex(event['params'])
            if raw[:2]!=owner['handle'].to_bytes(2,'little') or raw[2:4]!=index.to_bytes(2,'little'):raise CaptureError('opposite real ingress role/handle/index required')
            received[index]=event
        if not installation and any(same(v) and v['event'] in [0x11,0xe] and row['start_wall_ns']<=v['wall_ns']<=high for v in capture['native_events']):raise CaptureError('candidate agreement cannot install/enable encryption')
        if not installation and any(same(v) and v['opcode'] in [0x1c03,0x1c05] and row['start_wall_ns']<=v['wall_ns']<=high for v in capture['commands']):raise CaptureError('candidate-only evidence must contain no key install command')
        if not prefix_only:
            event=row['down'][n];raw=bytes.fromhex(event['params'])
            matches=[v for v in capture['native_events'] if same(v) and v['event']==event['event'] and v['params']==event['params'] and row['cleanup_before_wall_ns']<=v['wall_ns']<=row['cleanup_after_wall_ns']]
            if len(matches)!=1 or event['generation']!=owner['generation'] or event['lost'] or len(raw)!=4 or raw[0] or int.from_bytes(raw[1:3],'little')!=owner['handle']:raise CaptureError('actual same-lifetime cleanup Down required')
        proof.append(dict(controller=n,relays=local,peer_rx=rx))
    for index in order:
        command,complete,payload=commands[index];event=received[index];raw=bytes.fromhex(event['params'])
        if len(raw)!=len(payload)+5 or raw[4]!=len(payload) or raw[5:]!=payload or event['wall_ns']<command['wall_ns']:raise CaptureError('actual exact opposite receiver bytes required, Complete insufficient')
    for previous,index in zip(order,order[1:]):
        required=commands[previous][1] if index in [0x138,0x13c] else received[previous]
        if required['wall_ns']>commands[index][0]['wall_ns']:raise CaptureError('protocol dependency or T pub/confirm real Complete serialization missing')
    gp=commands[0x136][2][6:];tp=commands[0x137][2];gn=commands[0x139][2];tn=commands[0x13c][2][16:] if numeric else commands[0x13a][2]
    if gp==tp or not any(gp) or not any(tp) or gn==tn:raise CaptureError('distinct real public points and role nonces required')
    numeric_proof=None
    if numeric:
        from ws73_security_numeric import corroborate_numeric_decisions
        numeric_proof=corroborate_numeric_decisions(r,commands,gp,tp,gn,tn)
    legs=[]
    if not prefix_only:
        _,legs=business_evidence(g,r,capture)
        control(capture,r['usb'][i],0x1403,g['owners'][i]['handle'].to_bytes(2,'little')+b'\x10',row['cleanup_before_wall_ns'],row['cleanup_after_wall_ns'],status=True)
        for enabled in [True,False]:control(capture,r['usb'][1-i],0x1002,bytes([enabled,0]),row['cleanup_after_wall_ns'],row['scan_checked_wall_ns'])
    installs=[]
    if installation:
        keys=[];on=[]
        for n in [0,1]:
            same=lambda v:(v['bus'],v['device'])==(r['usb'][n]['bus'],r['usb'][n]['device'])
            expected=0x1c03 if n==i else 0x1c05
            tx=[v for v in capture['commands'] if same(v) and v['opcode'] in [0x1c03,0x1c05] and row['start_wall_ns']<=v['wall_ns']<=high]
            if len(tx)!=1 or tx[0]['opcode']!=expected:raise CaptureError('one role-exact real key install command required')
            cmd=tx[0];raw=bytes.fromhex(cmd['params']);length=21 if n==i else 20
            if len(raw)!=length or raw[:2]!=g['owners'][n]['handle'].to_bytes(2,'little') or raw[18:]!=(b'\x01\x01\0' if n==i else b'\x01\x01') or not any(raw[2:18]) or not cmd.get('completion'):raise CaptureError('exact role-specific install schema and real USB completion required')
            # These actual USB captures contain secrets and remain private. No
            # key, install params or key-bearing raw event enters public proof.
            keys.append(raw[2:18])
            accepted=[v for v in capture['native_events'] if same(v) and v['event']==1 and v['params']==(expected.to_bytes(2,'little')+b'\x01\0').hex() and cmd['wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
            accepted += [v for v in capture['complete'] if same(v) and v['opcode']==expected and v['status']==0 and cmd['wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
            events=[v for v in capture['native_events'] if same(v) and v['event']==0x11 and cmd['wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
            enabled=[v for v in events if v['params']==(b'\0'+raw[:2]+b'\x01').hex()]
            if not accepted or len(events)!=1 or len(enabled)!=1:raise CaptureError('real command acceptance AND exact initial0011 required')
            on.append(enabled[0]['wall_ns'])
            installs.append(dict(controller=n,opcode=expected,handle=g['owners'][n]['handle'],parameter_length=length,key_redacted=True,command_record=cmd['record'],accept_records=[v['record'] for v in accepted],encryption_event=enabled[0]))
        if keys[0]!=keys[1]:raise CaptureError('both actual controllers must receive the same newly derived candidate')
        request_events=[v for v in capture['native_events'] if (v['bus'],v['device'])==(r['usb'][1-i]['bus'],r['usb'][1-i]['device']) and v['event']==0xe and row['g_start_before_wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
        gcmd=next(v for v in capture['commands'] if v['opcode']==0x1c03 and (v['bus'],v['device'])==(r['usb'][i]['bus'],r['usb'][i]['device']) and row['g_start_before_wall_ns']<=v['wall_ns']<=row['observed_wall_ns'])
        tcmd=next(v for v in capture['commands'] if v['opcode']==0x1c05 and (v['bus'],v['device'])==(r['usb'][1-i]['bus'],r['usb'][1-i]['device']) and row['g_start_before_wall_ns']<=v['wall_ns']<=row['observed_wall_ns'])
        if len(request_events)!=1 or request_events[0]['params']!=g['owners'][1-i]['handle'].to_bytes(2,'little').hex() or not received[0x142]['wall_ns']<=gcmd['wall_ns']<=request_events[0]['wall_ns']<=tcmd['wall_ns'] or commands[0x142][1]['wall_ns']>tcmd['wall_ns']:raise CaptureError('proof and real T-key request must precede role installation')
        if any(b['start_wall_ns']<max(on) for b in g['business'] if b['label']=='after_capabilities'):raise CaptureError('after-encryption business must start after both real encryption events')
        if prefix_only:
            return dict(status='REAL_POSITIVE_EXCHANGE_ONLY_CORROBORATED',controllers=proof,installations=installs,numeric=numeric_proof,scope='Existing typed mechanism,actual relay/peer RX/acceptance/0011 only;business and lifecycle corroborated separately;not identity/Bond/RFattestation/recovery')
        if numeric:
            return dict(status='REAL_NUMERIC_COMPARISON_MECHANISM_CORROBORATED',numeric_mode=numeric,numeric=numeric_proof,controllers=proof,installations=installs,business_legs=legs,business_round_trips=4,scope='Explicit privileged automated two-code comparison, actual8 relay PDUs, own acceptance/0011 and ordinary before/after replies; not human/Agent identity, trustedGrant, Bond, third-party interop, independent RF cipher attestation or natural recovery. Raw USB keys remain private.')
        return dict(status='REAL_UNAUTHENTICATED_LINK_ENCRYPTION_CORROBORATED',controllers=proof,installations=installs,business_legs=legs,business_round_trips=4,scope='Actual9 relay PDUs, role-specific key installation/acceptance, both lifetime-bound controller0011 and actual ordinary opposite application checks/replies. Not Agent consent, authenticated identity, Bond, independent radio cipher attestation, third-party interop or natural recovery. USB captures contain private key material and must remain private.')
    if numeric:
        return dict(status='REAL_NUMERIC_COMPARISON_MECHANISM_CORROBORATED',numeric_mode=numeric,numeric=numeric_proof,controllers=proof,installations=[],business_legs=legs,business_round_trips=4,scope='Actual6 relay prefix, independent two-code comparison, original rejection/expiry, no DHproof/install/encryption and ordinary before/after replies. Not authenticated identity, Agent, trustedGrant, Bond or natural recovery.')
    return dict(status='REAL_UNAUTHENTICATED_CANDIDATE_KEY_AGREEMENT_CORROBORATED',controllers=proof,business_legs=legs,business_round_trips=4,public_points=[gp.hex(),tp.hex()],public_nonces=[gn.hex(),tn.hex()],scope='Actual9 typed relay PDUs/realComplete/oppositeRX, kernel candidate proof state8, sameSession ordinary before/after replies. No independent standard/third-party interop, Agent, authenticated identity, install, encryption, Bond or natural recovery qualification.')
