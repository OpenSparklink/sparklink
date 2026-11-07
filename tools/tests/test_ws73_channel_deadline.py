# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic failures for scoped evidence verifier; no hardware qualification."""
import copy
import errno
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ws73_channel_link_down import fixture as down_fixture
from ws73_channel_deadline import verify,corroborate
from ws73_diagnostic_hold import PROPERTIES
from sparklink.structs import SleChannelTxStatus


def fixture():
    r,c=down_fixture();d=r.pop('data_link_down');r['data_deadline']=d;r.update(status='DATA_DEADLINE_PASS',end_wall_ns=6_800_000_000)
    g=r['channel_grant'];a=g['armed'];owner=g['owners'][0]
    d.update(status='ACTUAL_ORIGINAL_DEADLINE_PASS',management_at_timeout=d['management_after'],links_at_timeout=copy.deepcopy(d['links_before']),ready_at_timeout=d['ready_before'],timeout_observed_wall_ns=6_100_000_000,post_release_checked_wall_ns=6_500_000_000,cleanup_before_wall_ns=6_600_000_000,cleanup_after_wall_ns=6_650_000_000,scan_checked_wall_ns=6_700_000_000,cleanup_disconnect_input=d['input'],cleanup_result=d['result'])
    a.update(admission_before_wall_ns=1_000_000_000,admission_after_wall_ns=1_001_000_000,admission_before_monotonic_ns=1_000_000_000,admission_after_monotonic_ns=1_001_000_000,pre_block_tx_status_wall_ns=1_250_000_000,wall_ns=1_260_000_000)
    tx=SleChannelTxStatus(version=1,size=64,controller=0,generation=owner['generation'],lifetime=owner['lifetime'],handle=owner['handle'],packet_maximum=254,capacity=5,outstanding=5,connection_debt=5,flags=3,active_pdu_bytes=2047,active_pdu_offset=1270,pool_exhaustions=10)
    a['pre_block_tx_status']=bytes(tx).hex();g['revoke_prefix']['admission_before_wall_ns']=a['admission_before_wall_ns']
    for n,sample in enumerate(g['blocking_witness']):sample['wall_ns']=1_270_000_000+n*30_000_000
    d['blocked_result']=dict(stage='blocked_denied',errno=errno.ETIMEDOUT,start_wall_ns=1_260_000_001,end_wall_ns=6_001_000_000,start_monotonic_ns=1_260_000_001,end_monotonic_ns=6_001_000_000)
    for key in ['old_fd_before_release','old_fd_after_release']:
        d[key]=copy.deepcopy(d['old_fd']);d[key]['errors']={'send':errno.ENOTCONN,'recv':errno.ENOTCONN}
    d['markers']=[dict(hold_phase=phase,wall_ns=when) for phase,when in [('arm_ready',500_000_000),('wait_held',1_320_000_000),('release_ready',6_200_000_000)]]
    d['acks']=[]
    for j,(phase,when) in enumerate([('armed',600_000_000),('held',1_330_000_000),('released',6_300_000_000)]):
        values=[[True,False,0,0,0,0,False,0],[False,True,1,0,0,0,False,0],[False,False,1,1,0,0,False,0]][j]
        d['acks'].append(dict(stage=phase,host_wall_ns=when,request=d['markers'][j],state=dict(zip(PROPERTIES,values))))
    d['ack_receipts']=[dict(stage=phase,wall_ns=when,monotonic_ns=when) for phase,when in [('armed',610_000_000),('held',1_340_000_000),('released',6_400_000_000)]]
    c['acb_packets'].pop();wire=b'\x1f\0\xfb\x07\xf1'+bytes.fromhex(g['revoke_prefix']['payload'])
    for n in range(5):c['acb_packets'].append(dict(**r['usb'][0],handle=0,direction='out',data=wire[n*254:(n+1)*254].hex(),boundary=1 if n==0 else 2,wall_ns=1_002_000_000+n*10_000_000,completion={'record':50+n*2},record=49+n*2))
    c['commands'][0]['wall_ns']=6_610_000_000;c['native_events'][0]['wall_ns']=6_620_000_000
    for n,e in enumerate(d['down']):
        e['wall_ns']=6_640_000_000+n;c['native_events'][n+1]['wall_ns']=6_630_000_000+n;c['native_events'][n+1]['record']=100+n
    for n in range(2):c['commands'][n+1]['wall_ns']=6_660_000_000+n*20_000_000;c['complete'][n]['wall_ns']=6_670_000_000+n*20_000_000
    for n in range(5):c['native_events'].append(dict(**r['usb'][0],event=9,params='000001',wall_ns=6_310_000_000+n,record=80+n,usb_sha256='a'*64,usb_length=96))
    hold=dict(method='BOUNDED8S_HOLD_REAL_IN81_FOR_ORIGINAL5S_PDU_DEADLINE',hold_budget_ms=8000,index=0,complete=True,physical_acceptance=False,automatic_fault_recovery_acceptance=False,observations=d['acks'])
    stderr='WS73_TEST_RUNTIME_HOLD: dev 1:2 bytes=96 host_status=0 holds=1 sha256='+'a'*64+'\nWS73_TEST_RUNTIME_HOLD_RELEASE: dev 1:2 bytes=96 bounded=0 releases=1\n'
    return r,c,hold,stderr,dict(bus=1,address=2)


class OriginalDeadline(unittest.TestCase):
    def test_missing_or_extra_application_receipt_cannot_qualify_deadline_business(self):
        for count in [0,1,3]:
            r,c,h,s,e=fixture();apps=r['channel_grant']['business'][0]['applications']
            r['channel_grant']['business'][0]['applications']=(apps*2)[:count]
            # Extra entries may fail earlier in the existing payload oracle;
            # missing entries must reach the new shared completeness check.
            pattern='two actual business application receipts' if count<2 else '.+'
            with self.subTest(count=count),self.assertRaisesRegex(ValueError,pattern):
                corroborate(r,c,h,s,e)

    def test_exact_original_five_seconds_and_actual_wire_requirements(self):
        r,c,h,s,e=fixture();verify(r);v=corroborate(r,c,h,s,e)
        self.assertEqual(v['elapsed_monotonic_ns'],5_000_000_000)
        self.assertEqual(v['submitted_bytes'],1270)
        self.assertEqual(v['partial_pdu_application_round_trips'],0)

    def test_host_and_guest_wall_offsets_do_not_change_causality(self):
        for offset in [-500_000_000,10_000_000_000]:
            r,c,h,s,e=fixture()
            for ack in r['data_deadline']['acks']:ack['host_wall_ns']+=offset
            # Handshakes and same-clock ordering still required.
            verify(r);corroborate(r,c,h,s,e)

    def test_wrong_clock_credit_lifetime_or_revoke_is_not_timeout(self):
        for kind in ['early','refreshed','recv_timeout','revoke','debt','prefix','lifetime','lease','revived','guest_receipt','autobound']:
            r,c,h,s,e=fixture();d=r['data_deadline'];a=r['channel_grant']['armed']
            if kind in ['early','refreshed']:d['blocked_result']['end_monotonic_ns']=4_000_000_000 if kind=='early' else 7_000_000_000
            elif kind in ['recv_timeout','revoke']:d['blocked_result']['errno']=errno.EAGAIN if kind=='recv_timeout' else errno.EACCES
            elif kind in ['debt','prefix','lifetime']:
                tx=SleChannelTxStatus.from_buffer_copy(bytes.fromhex(a['pre_block_tx_status']));setattr(tx,{'debt':'connection_debt','prefix':'active_pdu_offset','lifetime':'lifetime'}[kind],0);a['pre_block_tx_status']=bytes(tx).hex()
            elif kind=='lease':d['management_at_timeout'][0]=d['management_cleaned'][0]
            elif kind=='revived':d['old_fd_after_release']['errors']['send']=0
            elif kind=='guest_receipt':d['ack_receipts'][2]['wall_ns']=6_900_000_000
            else:d['acks'][2]['state']['test-runtime-in-bounded-releases']=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify(r)

    def test_usb_success_or_log_cannot_replace_original_held_reply(self):
        for kind in ['early_nocp','nocp_count','foreign_nocp','late_submit','end_pdu','changed_real_reply','wrong_budget','scan_failed','down_missing']:
            r,c,h,s,e=fixture()
            if kind=='early_nocp':c['native_events'][3]['wall_ns']=2_000_000_000
            elif kind=='nocp_count':c['native_events'].pop()
            elif kind=='foreign_nocp':c['native_events'][3]['params']='010001'
            elif kind=='late_submit':c['acb_packets'][-1]['wall_ns']=6_400_000_000
            elif kind=='end_pdu':c['acb_packets'][-1]['boundary']=3
            elif kind=='changed_real_reply':c['native_events'][3]['usb_sha256']='b'*64
            elif kind=='wrong_budget':h['hold_budget_ms']=2000
            elif kind=='scan_failed':c['complete'][0]['status']=1
            else:c['native_events'].pop(1)
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c,h,s,e)
