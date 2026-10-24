# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic receipt/USB rejection checks, never real device qualification."""
import copy
import errno
import json
from pathlib import Path
import select
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_channel_link_down import verify, corroborate
from ws73_channel_grant import Address
from ws73_connected_file_gate import bound_disconnect
from ws73_management_setup import setup, decode
from sparklink.structs import SleLinkSnapshot, SleManagementQuery, SleControllerSnapshot, SleConnectionResult
from test_ws73_channel_grant import fixture as grant_fixture


def fixture():
    r=json.loads((Path(__file__).parent/'data/connected_file_record.json').read_text())
    r.update(status='DATA_LINK_DOWN_PASS',case='release',index=0,end_wall_ns=400)
    g,_=grant_fixture();r['channel_grant']=g
    row=dict(status='ACTUAL_LINK_DOWN_PASS',management_before=[],management_after=[],management_cleaned=[],
             links_before=[],links_after=[],ready_before=[],ready_after=[],submit_before_wall_ns=230,
             submit_after_wall_ns=240,checks_after_wall_ns=260,scan_checked_wall_ns=300,end_wall_ns=400)
    r['data_link_down']=row;r['down']=[]
    for n,raw in enumerate(r['initial_snapshots']):
        s=setup(raw,n);owner=g['owners'][n];owner.update(generation=s.generation,lease=r['leases'][n])
        a=Address.from_buffer_copy(bytes.fromhex(owner['address']));a.generation=s.generation;a.lease=owner['lease'];owner['address']=bytes(a).hex()
        before=SleLinkSnapshot(version=1,flags=1,generation=s.generation,count=1)
        before.links[0].lifetime=owner['lifetime'];before.links[0].handle=owner['handle'];before.links[0].role=n
        row['links_before'].append(bytes(before).hex());row['links_after'].append(bytes(SleLinkSnapshot(version=1,flags=1,generation=s.generation)).hex())
        held=bytes(SleManagementQuery(version=1,generation=s.generation,state=1,mode=1)).hex()
        row['management_before'].append(held);row['management_after'].append(held)
        row['management_cleaned'].append(bytes(SleManagementQuery(version=1,generation=s.generation)).hex())
        ready=SleControllerSnapshot.from_buffer_copy(bytes(s));ready.flags=1
        row['ready_before'].append(bytes(ready).hex());row['ready_after'].append(bytes(ready).hex())
        r['down'].append(dict(event=5,params='00000013',generation=s.generation,lost=0,wall_ns=250+n))
    row['down']=copy.deepcopy(r['down'])
    row['input']=bytes(bound_disconnect(setup(r['initial_snapshots'][0],0),decode(SleLinkSnapshot,row['links_before'][0]).links[0],950)).hex()
    row['result']=bytes(SleConnectionResult(version=1,profile=1,operation=2,state=4,flags=7,generation=g['owners'][0]['generation'],request_id=950)).hex()
    g['armed'].update(wall_ns=200,prefix=(b'SLKREV01'+bytes(2034)).hex())
    g['blocking_witness'][0]['wall_ns']=210;g['blocking_witness'][1]['wall_ns']=220
    g['revoke_prefix']=dict(payload=g['armed']['prefix'],admission_before_wall_ns=190)
    row['blocked_result']=dict(stage='blocked_denied',errno=errno.ESTALE,start_wall_ns=205,end_wall_ns=255)
    row['old_fd']=dict(stage='denied',errors={'send':errno.ESTALE,'recv':errno.ESTALE},poll=select.POLLERR|select.POLLHUP,marker=(b'DOWNDENY'+bytes(32)).hex())
    capture=dict(acb_packets=[],native_events=[],commands=[],complete=[]);ordinal=1
    for b in g['business']:
        b.update(start_wall_ns=10,end_wall_ns=150)
        for n,app in enumerate(b['applications']):
            for key,direction in [('sent','out'),('received','in')]:
                payload=bytes.fromhex(app[key]);data=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                capture['acb_packets'].append(dict(**r['usb'][n],handle=0,direction=direction,data=data.hex(),boundary=0,wall_ns=100,record=ordinal));ordinal+=1
    data=b'\x1f\0\xfb\x07\xf1'+bytes.fromhex(g['armed']['prefix'])
    capture['acb_packets'].append(dict(**r['usb'][0],handle=0,direction='out',data=data[:254].hex(),boundary=1,completion={'record':20},record=19,wall_ns=225))
    capture['commands'].append(dict(**r['usb'][0],opcode=0x1403,params='000010',wall_ns=235,record=21,completion={'record':22}))
    capture['native_events'].append(dict(**r['usb'][0],event=1,params='03140100',wall_ns=245,record=23))
    for n,e in enumerate(row['down']):capture['native_events'].append(dict(**r['usb'][n],**e,record=24+n))
    for enabled,when in [(True,270),(False,290)]:
        capture['commands'].append(dict(**r['usb'][1],opcode=0x1002,params=bytes([enabled,0]).hex(),wall_ns=when,completion={'record':30}))
        capture['complete'].append(dict(**r['usb'][1],opcode=0x1002,status=0,wall_ns=when+1))
    return r,capture


class DirectLinkDown(unittest.TestCase):
    def test_missing_or_extra_application_receipt_cannot_qualify_down_business(self):
        for count in [0,1,3]:
            r,c=fixture();apps=r['channel_grant']['business'][0]['applications']
            r['channel_grant']['business'][0]['applications']=(apps*2)[:count]
            # Extra entries may fail earlier in the existing payload oracle;
            # missing entries must reach the new shared completeness check.
            pattern='two actual business application receipts' if count<2 else '.+'
            with self.subTest(count=count),self.assertRaisesRegex(ValueError,pattern):
                corroborate(r,c)

    def test_scoped_receipts_and_actual_packet_paths(self):
        r,c=fixture();verify(r);p=corroborate(r,c)
        self.assertEqual(p['submitted_bytes'],254)
        self.assertEqual(p['business_round_trips_before_down'],2)
        self.assertFalse(p['original_deadline_qualified'])
        self.assertFalse(p['handle_reuse_qualified'])

    def test_revoke_is_not_physical_down_and_old_epoch_cannot_change(self):
        for kind in ['lease','generation','lifetime','privileged','success','direction','witness','blocked_error','event_kind','event_count','result_operation']:
            r,_=fixture();d=r['data_link_down']
            if kind=='lease':d['management_after'][0]=d['management_cleaned'][0]
            elif kind=='generation':d['ready_after'][0]=d['ready_after'][1]
            elif kind=='lifetime':r['channel_grant']['owners'][0]['lifetime']+=1
            elif kind=='privileged':r['channel_grant']['workers'][0]['credentials']['uids']=[0]*4
            elif kind=='success':d['old_fd']['errors']['send']=0
            elif kind=='direction':
                a=Address.from_buffer_copy(bytes.fromhex(r['channel_grant']['owners'][0]['address']));a.directions=1;r['channel_grant']['owners'][0]['address']=bytes(a).hex()
            elif kind=='witness':r['channel_grant']['blocking_witness'][0]['syscall']=0
            elif kind=='blocked_error':d['blocked_result']['errno']=errno.EACCES
            elif kind=='event_kind':d['down'][0]['event']=0x14
            elif kind=='event_count':d['down'].pop()
            else:
                result=decode(SleConnectionResult,d['result']);result.operation=1;d['result']=bytes(result).hex()
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify(r)

    def test_usb_and_peer_evidence_cannot_be_replaced_by_local_success(self):
        for kind in ['disconnect','status','down','scan','prefix_last','late_submit','prefix_data','business']:
            r,c=fixture()
            if kind=='disconnect':c['commands'][0]['params']='010013'
            elif kind=='status':c['native_events'][0]['params']='03140101'
            elif kind=='down':c['native_events'].pop(1)
            elif kind=='scan':c['complete'][0]['status']=1
            elif kind=='prefix_last':c['acb_packets'][-1]['boundary']=0
            elif kind=='late_submit':c['acb_packets'][-1]['wall_ns']=260
            elif kind=='prefix_data':c['acb_packets'][-1]['data']='aa'*254
            else:c['acb_packets'].pop(0)
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c)
