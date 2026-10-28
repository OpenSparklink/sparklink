# SPDX-License-Identifier: GPL-2.0-only
"""Actual fixture functions with synthetic ABI/USB rows, not kernel/RF proof."""
import copy
import struct
import time
import unittest
from unittest.mock import patch

from test_ws73_channel_prefix_hold import primed_fixture
from test_ws73_channel_deadline import fixture as deadline_fixture
from ws73_channel_grant import Gate,message
from ws73_channel_prefix_hold import geometry_plan,geometry,full_pool,corroborate,corroborate_geometry,valid_geometry_summary
from ws73_channel_deadline import corroborate as deadline_corroborate
from sparklink.structs import SleChannelTxStatus


def reported_fixture(*,deadline=False,packet_maximum=1024,capacity=8):
    """Reuse old fixtures; all controller/IPC/USB dependencies remain synthetic."""
    if deadline:
        r,c,h,s,e=deadline_fixture();d=r['data_deadline']
        d['markers'][1]['wall_ns']=850_000_000;d['acks'][1]['host_wall_ns']=900_000_000
        d['ack_receipts'][1].update(wall_ns=950_000_000,monotonic_ns=950_000_000)
        # Retain only original baseline application legs, not the old prefix.
        keep=[p for p in c['acb_packets']if len(bytes.fromhex(p['data']))==66]
    else:
        r,c,h,s,e=primed_fixture();r.pop('data_link_down');d=r['prefix_hold'];keep=[]
        r.update(release_before_wall_ns=1_900_000_000,release_after_wall_ns=1_910_000_000)
    g=r['channel_grant'];i=r['index'];o=g['owners'][i];w=g['workers'][i]
    plan=geometry_plan(packet_maximum,capacity);assert plan['prime_count']
    empty=SleChannelTxStatus(version=1,size=64,controller=i,generation=o['generation'],lifetime=o['lifetime'],handle=o['handle'],packet_maximum=packet_maximum,capacity=capacity)
    end=d['markers'][0]['wall_ns']-100_000_000
    d['geometry']=dict(version=1,force_prime=False,plan=plan,start_wall_ns=end-10_000_000,end_wall_ns=end,
        start_monotonic_ns=1_000_000,end_monotonic_ns=2_000_000,
        samples=[dict(stage='tx_status',pid=w['pid'],fd=w['fd'],value=bytes(empty).hex(),wall_ns=end-1)])
    d['primed']=True
    payloads=[message().hex()for _ in range(plan['prime_count'])]
    unpaid=SleChannelTxStatus.from_buffer_copy(bytes(empty));unpaid.outstanding=unpaid.connection_debt=plan['prime_count']
    p=dict(status='PRIMING_RECEIPTS_RECORDED',payloads=payloads,start_wall_ns=700_000_000,end_wall_ns=800_000_000,
        source_pool_samples=[dict(stage='tx_status',pid=w['pid'],fd=w['fd'],value=bytes(unpaid).hex(),wall_ns=790_000_000)],
        applications=[dict(stage='primed',sender=n==i,pid=v['pid'],fd=v['fd'],values=payloads.copy(),start_wall_ns=710_000_000,end_wall_ns=780_000_000)for n,v in enumerate(g['workers'])])
    g['priming']=p
    active=SleChannelTxStatus.from_buffer_copy(bytes(empty));active.outstanding=active.connection_debt=capacity;active.flags=3
    active.active_pdu_bytes=2047;active.active_pdu_offset=plan['offset'];active.pool_exhaustions=1
    g['armed']['pre_block_tx_status']=bytes(active).hex()
    c['acb_packets']=keep
    for j,payload in enumerate(payloads):
        wire=b'\x1f\0\x3e\0\xf1'+bytes.fromhex(payload)
        for n,direction in[(i,'out'),(1-i,'in')]:
            c['acb_packets'].append(dict(**r['usb'][n],handle=o['handle'],direction=direction,boundary=0,data=wire.hex(),wall_ns=720_000_000+j*1_000_000+n,record=1000+j*2+n,completion=dict(record=1100+j*2+n)))
    wire=b'\x1f\0\xfb\x07\xf1'+bytes.fromhex(g['revoke_prefix']['payload'])
    c['acb_packets'].append(dict(**r['usb'][i],handle=o['handle'],direction='out',boundary=1,data=wire[:plan['offset']].hex(),wall_ns=g['revoke_prefix']['admission_before_wall_ns']+2_000_000,record=1300,completion=dict(record=1301)))
    event=copy.deepcopy(c['native_events'][3]);c['native_events']=c['native_events'][:3]
    for j in range(capacity):c['native_events'].append(dict(event,record=2000+j,wall_ns=d['acks'][2]['host_wall_ns']+1_000_000+j))
    c['commands'].append(dict(**r['usb'][i],opcode=0x0402,params='',wall_ns=100_000_000,record=40,completion=dict(record=41,wall_ns=100_000_001)))
    c['complete'].append(dict(**r['usb'][i],opcode=0x0402,status=0,value=struct.pack('<HBHB',packet_maximum,capacity,0,0).hex(),wall_ns=110_000_000,record=42))
    # The real decoder emits file order. Keep synthetic packet/Down records
    # in the same chronological order so an unfinished PDU is retired by its
    # later real-event-shaped Down, not silently discarded at capture end.
    for j,item in enumerate(sorted(c['acb_packets']+c['native_events'],key=lambda v:v['wall_ns'])):
        item['record']=100+j*2
        if item.get('completion'):item['completion']['record']=item['record']+1
    return r,c,h,s,e


class ReportedGeometry(unittest.TestCase):
    def test_live_planner_full_finite_input_domain(self):
        for packet in range(66,2047):
            for capacity in range(2,33):
                for force in(False,True):
                    p=geometry_plan(packet,capacity,force)
                    self.assertTrue(0<p['offset']<2047)
                    self.assertEqual(p['offset'],packet*p['fragments'])
                    self.assertEqual(p['prime_count']+p['fragments'],capacity)
                    self.assertEqual(bool(p['prime_count']),force or packet*capacity>=2047)
        self.assertEqual(geometry_plan(254,5)['offset'],1270)
        for packet,capacity,force in[(65,5,False),(2047,5,False),(254,1,False),(254,33,False),(True,5,False),(254,True,False),(254,5,1)]:
            with self.subTest(packet=packet,capacity=capacity,force=force),self.assertRaises(ValueError):geometry_plan(packet,capacity,force)

    def test_reported_buffers_real_priming_shape_and_full_pool(self):
        r,c,h,s,e=reported_fixture();p=corroborate(r,c,h,s,e)
        self.assertEqual((p['submitted_before_snapshot'],p['priming_one_way_deliveries']),(1,7))
        self.assertTrue(valid_geometry_summary(p['prefix_geometry']))

    def test_deadline_keeps_original_five_seconds_with_primed_geometry(self):
        r,c,h,s,e=reported_fixture(deadline=True);p=deadline_corroborate(r,c,h,s,e)
        self.assertEqual((p['submitted_fragments'],p['submitted_bytes'],p['elapsed_monotonic_ns']),(1,1024,5_000_000_000))
        self.assertTrue(valid_geometry_summary(p['prefix_geometry']))

    def test_geometry_does_not_accept_completed_pdu_or_loose_bounds(self):
        for case in['missing-prime','old-generation','nonempty','long-observation','late-observation','changed-plan','completed','not-full','missing-peer','extra-source','wrong-buffers','missing-buffers','missing-NOCP']:
            r,c,h,s,e=reported_fixture();d=r['prefix_hold'];g=r['channel_grant']
            if case=='missing-prime':d['primed']=False
            elif case in['old-generation','nonempty']:
                v=SleChannelTxStatus.from_buffer_copy(bytes.fromhex(d['geometry']['samples'][0]['value']));setattr(v,'generation'if case=='old-generation'else'outstanding',1 if case=='nonempty'else v.generation+1);d['geometry']['samples'][0]['value']=bytes(v).hex()
            elif case=='long-observation':d['geometry']['end_monotonic_ns']+=500_000_000
            elif case=='late-observation':d['geometry']['end_wall_ns']=d['markers'][0]['wall_ns']+1
            elif case=='changed-plan':d['geometry']['plan']['prime_count']=0
            elif case in['completed','not-full']:
                v=SleChannelTxStatus.from_buffer_copy(bytes.fromhex(g['armed']['pre_block_tx_status']))
                if case=='completed':v.active_pdu_bytes=v.active_pdu_offset=v.flags=0
                else:v.outstanding-=1
                g['armed']['pre_block_tx_status']=bytes(v).hex()
            elif case=='missing-peer':c['acb_packets'].pop(1)
            elif case=='extra-source':c['acb_packets'].append(copy.deepcopy(c['acb_packets'][0]))
            elif case=='wrong-buffers':c['complete'][-1]['value']=struct.pack('<HBHB',254,5,0,0).hex()
            elif case=='missing-buffers':c['complete'].pop()
            else:c['native_events'].pop()
            with self.subTest(case=case),self.assertRaises(ValueError):corroborate(r,c,h,s,e)

    def test_saved_geometry_summary_requires_original_reply_and_scope(self):
        r,c,_,_,_=reported_fixture();p=corroborate_geometry(r,c)
        for case in['missing','wrong-raw','unknown-version','wrong-plan','bool-status']:
            bad=copy.deepcopy(p)
            if case=='missing':bad.pop('buffers')
            elif case=='wrong-raw':bad['buffers']['reply']['value']='00'*6
            elif case=='unknown-version':bad['version']=True
            elif case=='wrong-plan':bad['plan']['offset']=2047
            else:bad['buffers']['reply']['status']=False
            with self.subTest(case=case):self.assertFalse(valid_geometry_summary(bad))

    def test_actual_sampler_uses_typed_source_receipts_and_rejects_bad_identity(self):
        r,_,_,_,_=reported_fixture();g=r['channel_grant'];w=g['workers'][0];o=g['owners'][0]
        gate=object.__new__(Gate);gate.index=0;gate.controllers=[0,1];gate.parents=[object(),object()];gate.row=g;gate.save=lambda:None
        value=SleChannelTxStatus(version=1,size=64,controller=0,generation=o['generation'],lifetime=o['lifetime'],handle=o['handle'],packet_maximum=1024,capacity=8)
        def receipt():return dict(stage='tx_status',pid=w['pid'],fd=w['fd'],value=bytes(value).hex(),wall_ns=time.time_ns())
        # IPC is a visible fixture; this executes the live sampler, not a
        # Native ioctl, real concurrent ledger or successful physical peer.
        with patch('ws73_channel_grant.send')as send,patch('ws73_channel_grant.receive',side_effect=lambda _:receipt()):
            result=gate.prefix_geometry();self.assertEqual(result['plan']['prime_count'],7)
            send.assert_called_once_with(gate.parents[0],dict(kind='tx_status'))
        value.generation+=1
        with patch('ws73_channel_grant.send'),patch('ws73_channel_grant.receive',side_effect=lambda _:receipt()),self.assertRaises(ValueError):gate.prefix_geometry()
