# SPDX-License-Identifier: GPL-2.0-only
"""Read-only actual 134..142 candidate agreement evidence; not an Engine.

The kernel alone produces public points/nonces/proofs. This checker sends no
raw PDU, supplies no keys and cannot replace crypto, Agent or install results.
"""
from ws73_security_capabilities import verify,OFFER
from ws73_channel_grant import business_evidence
from ws73_channel_deadline import control
from ws73_capture import CaptureError


def corroborate(r,capture):
    if r.get('key_agreement') is not True:raise CaptureError('explicit candidate agreement gate required')
    row=verify(r);g=r['channel_grant'];i=r['index'];commands={};received={};proof=[]
    for n in [0,1]:
        owner=g['owners'][n];usb=r['usb'][n];same=lambda v:(v['bus'],v['device'])==(usb['bus'],usb['device'])
        tx_indices=[0x134,0x136,0x139,0x141] if n==i else [0x135,0x137,0x138,0x13a,0x142]
        rx_indices=[0x135,0x137,0x138,0x13a,0x142] if n==i else [0x134,0x136,0x139,0x141]
        tx=[v for v in capture['commands'] if same(v) and v['opcode']==0x1812 and row['start_wall_ns']<=v['wall_ns']<=row['cleanup_before_wall_ns']]
        complete=[v for v in capture['complete'] if same(v) and v['opcode']==0x1812 and row['start_wall_ns']<=v['wall_ns']<=row['cleanup_before_wall_ns']]
        rx=[v for v in capture['native_events'] if same(v) and v['event']==0x14 and row['g_start_before_wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
        if len(tx)!=len(tx_indices) or len(complete)!=len(tx_indices) or len(rx)!=len(rx_indices):raise CaptureError('all9 real relay submits/Completes/opposite ingress required')
        local=[]
        for command,index in zip(tx,tx_indices):
            raw=bytes.fromhex(command['params']);length=10 if index in [0x134,0x135] else 70 if index==0x136 else 64 if index==0x137 else 16
            if raw[:2]!=owner['handle'].to_bytes(2,'little') or raw[2:4]!=index.to_bytes(2,'little') or len(raw)!=length+5 or raw[4]!=length or not command.get('completion') or not row['g_start_before_wall_ns']<=command['wall_ns']<=row['observed_wall_ns']:raise CaptureError('exact role/handle/index/length and real USB completion required')
            if index in [0x134,0x135] and raw[5:]!=OFFER or index==0x136 and raw[5:11]!=bytes([16,1,2,2,2,2]):raise CaptureError('only known no-entry/no-MITM/no-Bond offer accepted')
            replies=[v for v in complete if v['status']==0 and v['value']==raw[:4].hex() and command['wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
            if len(replies)!=1:raise CaptureError('real frozen handle/index terminal Complete required')
            commands[index]=(command,replies[0],raw[5:]);local.append(dict(command=command,complete=replies[0]))
        for event,index in zip(rx,rx_indices):
            raw=bytes.fromhex(event['params'])
            if raw[:2]!=owner['handle'].to_bytes(2,'little') or raw[2:4]!=index.to_bytes(2,'little'):raise CaptureError('opposite real ingress role/handle/index required')
            received[index]=event
        if any(same(v) and v['event'] in [0x11,0xe] and row['start_wall_ns']<=v['wall_ns']<=row['cleanup_before_wall_ns'] for v in capture['native_events']):raise CaptureError('candidate agreement cannot install/enable encryption')
        event=row['down'][n];raw=bytes.fromhex(event['params'])
        matches=[v for v in capture['native_events'] if same(v) and v['event']==event['event'] and v['params']==event['params'] and row['cleanup_before_wall_ns']<=v['wall_ns']<=row['cleanup_after_wall_ns']]
        if len(matches)!=1 or event['generation']!=owner['generation'] or event['lost'] or len(raw)!=4 or raw[0] or int.from_bytes(raw[1:3],'little')!=owner['handle']:raise CaptureError('actual same-lifetime cleanup Down required')
        proof.append(dict(controller=n,relays=local,peer_rx=rx))
    order=[0x134,0x135,0x136,0x137,0x138,0x139,0x13a,0x141,0x142]
    for index in order:
        command,complete,payload=commands[index];event=received[index];raw=bytes.fromhex(event['params'])
        if len(raw)!=len(payload)+5 or raw[4]!=len(payload) or raw[5:]!=payload or event['wall_ns']<command['wall_ns']:raise CaptureError('actual exact opposite receiver bytes required, Complete insufficient')
    for previous,index in zip(order,order[1:]):
        required=commands[previous][1] if index==0x138 else received[previous]
        if required['wall_ns']>commands[index][0]['wall_ns']:raise CaptureError('protocol dependency or T pub/confirm real Complete serialization missing')
    gp=commands[0x136][2][6:];tp=commands[0x137][2];gn=commands[0x139][2];tn=commands[0x13a][2]
    if gp==tp or not any(gp) or not any(tp) or gn==tn:raise CaptureError('distinct real public points and role nonces required')
    _,legs=business_evidence(g,r,capture)
    control(capture,r['usb'][i],0x1403,g['owners'][i]['handle'].to_bytes(2,'little')+b'\x13',row['cleanup_before_wall_ns'],row['cleanup_after_wall_ns'],status=True)
    for enabled in [True,False]:control(capture,r['usb'][1-i],0x1002,bytes([enabled,0]),row['cleanup_after_wall_ns'],row['scan_checked_wall_ns'])
    return dict(status='REAL_UNAUTHENTICATED_CANDIDATE_KEY_AGREEMENT_CORROBORATED',controllers=proof,business_legs=legs,business_round_trips=4,public_points=[gp.hex(),tp.hex()],public_nonces=[gn.hex(),tn.hex()],scope='Actual9 typed relay PDUs/realComplete/oppositeRX, kernel candidate proof state8, sameSession ordinary before/after replies. No independent standard/third-party interop, Agent, authenticated identity, install, encryption, Bond or natural recovery qualification.')
