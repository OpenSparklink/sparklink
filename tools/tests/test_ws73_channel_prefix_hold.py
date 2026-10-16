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
