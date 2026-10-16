# SPDX-License-Identifier: GPL-2.0-only
"""Evidence and counted QMP negatives only; no hardware qualification."""
import copy
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from test_ws73_channel_deadline import fixture as deadline_fixture
import test_ws73_diagnostic_hold as diagnostic_tests
from ws73_channel_prefix_hold import PrefixCoordinator, METHOD, QEMU_SHA256, verify, corroborate


def fixture():
    r,c,h,s,e=deadline_fixture();d=r.pop('data_deadline');r['prefix_hold']=d
    r.update(release_before_wall_ns=1_500_000_000,release_after_wall_ns=1_510_000_000)
    d['markers'][2]['wall_ns']=1_520_000_000
    d['acks'][2]['host_wall_ns']=1_530_000_000;d['ack_receipts'][2]['wall_ns']=1_540_000_000
    for n,event in enumerate(c['native_events'][3:]):event['wall_ns']=1_531_000_000+n
    h.update(method=METHOD,hold_budget_ms=2000,qemu_sha256=QEMU_SHA256)
    return r,c,h,s,e


class PrefixHold(unittest.TestCase):
    def test_exhausted_real_pool_and_explicit_after_withdrawal_release(self):
        r,c,h,s,e=fixture();verify(r);p=corroborate(r,c,h,s,e)
        self.assertEqual(p['submitted_before_snapshot'],5)
        self.assertFalse(p['host_hold']['automatic_fault_recovery_acceptance'])

    def test_wrong_pool_identity_causal_receipts_or_expiry_rejected(self):
        for kind in ['no_pool','late_arm','early_release','missing_ack','auto_release','wrong_target','wrong_fixture','early_nocp','corrupt_prefix','missing_fragment','wrong_real_reply']:
            r,c,h,s,e=fixture();d=r['prefix_hold']
            if kind=='no_pool':r['channel_grant']['armed']['pre_block_tx_status']='00'*64
            elif kind=='late_arm':d['ack_receipts'][0]['wall_ns']=1_010_000_000
            elif kind=='early_release':d['markers'][2]['wall_ns']=1_400_000_000
            elif kind=='missing_ack':d['acks'].pop()
            elif kind=='auto_release':d['acks'][2]['state']['test-runtime-in-bounded-releases']=1
            elif kind=='wrong_target':h['index']=1
            elif kind=='wrong_fixture':h['qemu_sha256']='0'*64
            elif kind=='early_nocp':c['native_events'][3]['wall_ns']=1_001_000_001
            elif kind=='corrupt_prefix':c['acb_packets'][-1]['data']='ff'*254
            elif kind=='missing_fragment':c['acb_packets'].pop()
            else:c['native_events'][3]['usb_sha256']='b'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c,h,s,e)

    def test_host_guest_offsets_do_not_replace_causal_receipts(self):
        for offset in [-500_000_000,10_000_000_000]:
            r,c,h,s,e=fixture()
            for ack in h['observations']:ack['host_wall_ns']+=offset
            corroborate(r,c,h,s,e)

    def test_only_pinned_two_second_fixture_can_arm_target_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            qemu=Path(tmp)/'qemu';qemu.write_bytes(b'counted fixture')
            with self.assertRaises(ValueError):PrefixCoordinator(tmp,{},0,qemu)
            with patch('ws73_channel_prefix_hold.QEMU_SHA256',hashlib.sha256(qemu.read_bytes()).hexdigest()):
                h=PrefixCoordinator(tmp,{},1,qemu)
                self.assertEqual(h.path,'/machine/peripheral/ws73_1')
                self.assertEqual(h.record['hold_budget_ms'],2000)
                m=diagnostic_tests.Monitor();execute=m.execute
                def call(command,args):
                    self.assertEqual(args['path'],'/machine/peripheral/ws73_1')
                    return execute(command,dict(args,path='/machine/peripheral/ws73_0'))
                m.execute=call
                helper=diagnostic_tests.HoldCoordinatorTests();helper.marker(h,'arm_ready');h.poll(m)
                helper.marker(h,'wait_held');h.poll(m);self.assertEqual(h.phase,'wait_held')
                helper.held(m);h.poll(m);helper.marker(h,'release_ready');h.poll(m)
                self.assertTrue(h.record['complete'])
                self.assertEqual(len(m.sets),2)


def primed_fixture():
    from ws73_channel_grant import message
    from sparklink.structs import SleChannelTxStatus
    r,c,h,s,e=fixture();g=r['channel_grant'];d=r['prefix_hold'];d['primed']=True
    payloads=[message().hex() for _ in range(4)];o=g['owners'][0]
    v=SleChannelTxStatus(version=1,size=64,controller=0,generation=o['generation'],lifetime=o['lifetime'],handle=o['handle'],packet_maximum=254,capacity=5,outstanding=4,connection_debt=4,flags=0)
    p=dict(status='PRIMING_RECEIPTS_RECORDED',payloads=payloads,start_wall_ns=700_000_000,end_wall_ns=900_000_000,source_pool_samples=[dict(stage='tx_status',pid=g['workers'][0]['pid'],fd=g['workers'][0]['fd'],value=bytes(v).hex())],applications=[])
    for n,w in enumerate(g['workers']):p['applications'].append(dict(stage='primed',sender=n==0,pid=w['pid'],fd=w['fd'],values=payloads.copy(),start_wall_ns=710_000_000,end_wall_ns=800_000_000))
    g['priming']=p;g['revoke_prefix']['admission_before_wall_ns']=1_400_000_000
    g['armed'].update(pre_block_tx_status_wall_ns=1_650_000_000,wall_ns=1_660_000_000)
    v=SleChannelTxStatus.from_buffer_copy(bytes.fromhex(g['armed']['pre_block_tx_status']));v.active_pdu_offset=254;g['armed']['pre_block_tx_status']=bytes(v).hex()
    peer=dict(wall_ns=2_100_000_000);r['data_link_down']=dict(submit_before_wall_ns=1_900_000_000,submit_after_wall_ns=1_910_000_000,peer_down_while_held=peer.copy(),peer_down_receipt_wall_ns=2_110_000_000,down=[dict(wall_ns=2_300_000_000),peer])
    d['markers'][2]['wall_ns']=2_200_000_000;d['acks'][2]['host_wall_ns']=2_210_000_000;d['ack_receipts'][2]['wall_ns']=2_220_000_000
    c['acb_packets']=[]
    for j,payload in enumerate(payloads):
        wire=b'\x1f\0\x3e\0\xf1'+bytes.fromhex(payload)
        for n,direction in [(0,'out'),(1,'in')]:c['acb_packets'].append(dict(**r['usb'][n],handle=0,direction=direction,boundary=0,data=wire.hex(),wall_ns=720_000_000+j*1_000_000+n,record=100+j*2+n,completion={'record':200+j*2+n}))
    wire=b'\x1f\0\xfb\x07\xf1'+bytes.fromhex(g['revoke_prefix']['payload'])
    c['acb_packets'].append(dict(**r['usb'][0],handle=0,direction='out',boundary=1,data=wire[:254].hex(),wall_ns=1_410_000_000,record=300,completion={'record':301}))
    c['native_events'][1].update(record=500,wall_ns=2_300_000_000)
    c['native_events'][2].update(record=400,wall_ns=2_100_000_000)
    for j,event in enumerate(c['native_events'][3:]):event['wall_ns']=2_211_000_000+j
    return r,c,h,s,e


class PrimedDownHold(unittest.TestCase):
    def test_four_real_peer_primers_leave_one_credit_for_begun_pdu(self):
        r,c,h,s,e=primed_fixture();p=corroborate(r,c,h,s,e)
        self.assertEqual(p['submitted_before_snapshot'],1);self.assertEqual(p['priming_one_way_deliveries'],4)

    def test_priming_does_not_replace_peer_receipt_credit_or_wire_evidence(self):
        for kind in ['count','app','fd','debt','late-prime','peer-down','early-release','missing-wire','corrupt-wire']:
            r,c,h,s,e=primed_fixture();p=r['channel_grant']['priming']
            if kind=='count':p['payloads'].pop()
            elif kind=='app':p['applications'][1]['values'][0]=p['applications'][1]['values'][1]
            elif kind=='fd':p['source_pool_samples'][0]['fd']+=1
            elif kind=='debt':p['source_pool_samples'][0]['value']='00'*64
            elif kind=='late-prime':p['end_wall_ns']=1_500_000_000
            elif kind=='peer-down':r['data_link_down']['peer_down_while_held']['wall_ns']=1
            elif kind=='early-release':r['prefix_hold']['markers'][2]['wall_ns']=2_105_000_000
            elif kind=='missing-wire':c['acb_packets'].pop(1)
            else:c['acb_packets'][1]['data']='00'*66
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c,h,s,e)

    def test_actual_captured_four_debt_snapshot_has_no_active_or_begun_flags(self):
        from ws73_channel_prefix_hold import verify_priming
        from sparklink.structs import SleChannelTxStatus
        r,_,_,_,_=primed_fixture();g=r['channel_grant'];p=g['priming']
        # Exact64byte producer receipt from failed2451 VM;not a READY bit.
        raw='010040000000000001000000000000000100000000000000fe000500040004000400000008000000000000000000000000000000000000000000000000000000'
        g['owners'][0]['generation']=1;p['source_pool_samples'][0]['value']=raw
        self.assertEqual(SleChannelTxStatus.from_buffer_copy(bytes.fromhex(raw)).flags,0)
        verify_priming(r)
        v=SleChannelTxStatus.from_buffer_copy(bytes.fromhex(raw));v.flags=1;p['source_pool_samples'][0]['value']=bytes(v).hex()
        with self.assertRaises(ValueError):verify_priming(r)
