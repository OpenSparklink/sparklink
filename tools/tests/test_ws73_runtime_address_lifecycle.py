# SPDX-License-Identifier: GPL-2.0-only
"""Syscall DTO and peer-wire fixtures,not a running kernel or hardware proof."""
import copy
import errno
import struct
import unittest
from test_ws73_management_ready_peer import ready_fixture
from ws73_management_ready_peer import corroborate_activity_rows
from ws73_runtime_address_lifecycle import verify_records
from ws73_diagnostic_cancel import result
from sparklink.structs import SleControllerSnapshot,SleManagementQuery,SleSnoopRecord


def fixture(kind='release'):
    previous,peer,wire=ready_fixture()
    target=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(previous['initial_snapshots'][0]));target.command_credits=1
    snapshots=[bytes(target).hex(),previous['initial_snapshots'][1]]
    rows=[]
    def observation(stage,t,fault=False,held=False):
        s=SleControllerSnapshot.from_buffer_copy(bytes(target))
        if held or fault:s.valid_fields=0;s.command_credits=0
        if fault:s.flags=4;s.error=-errno.EIO
        q=SleManagementQuery(version=1,generation=1,state=3 if fault else 1,mode=0 if fault else 2,error=-errno.EIO if fault else 0)
        rows.append(dict(stage=stage,wall_ns=t,snapshot=bytes(s).hex(),management=bytes(q).hex()))
    rows.append(dict(stage='owner',writer_fd=5,duplicate_fd=6 if kind=='dup'else-1,lease=struct.pack('<QQIIII',1,7,1,2,0,0).hex()))
    observation('initialized',110)
    raw=struct.pack('<IIQQIII6s6s',1,0,1,1,5000,0,1,bytes.fromhex('a67b7310e001'),bytes(6))
    out=struct.pack('<IIQQIII6s6s',1,0,1,1,5000,4,1,bytes.fromhex('a67b7310e001'),bytes(6))
    rows.append(dict(stage='admitted',start_wall_ns=150,end_wall_ns=160,input=raw.hex(),output=out.hex(),retry_output=out.hex()))
    pending=result(1,4,0x0405,1)
    rows.append(dict(stage='pending-result',wall_ns=201,result=pending));observation('held',202,held=True)
    if kind=='dup':
        rows.append(dict(stage='dup-first-close-result',wall_ns=301,result=pending));observation('dup-first-close',302,held=True)
    observation('withdrawn',310,fault=True)
    rows.insert(len(rows)-1,dict(stage='before-fault-assert',start_wall_ns=305,wall_ns=306,
        start_monotonic_ns=205,monotonic_ns=206,snapshot=rows[-1]['snapshot']))
    observation('after-late-reply',410,fault=True)
    activity=copy.deepcopy(previous['ready_peer']);activity['on_after_quarantine']=activity.pop('on_after_free')
    r=dict(version=1,status='RUNTIME_ADDRESS_FILE_PENDING_RAW_CORROBORATION',case=kind,runtime_only=True,
        official_identity=False,daemon_running=False,automatic_recovery_acceptance=False,
        whole_lifecycle_acceptance=False,peer_business_delivery_acceptance=False,uid=0,probe_exit=0,
        owners=[dict(index=i,generation=i+1)for i in range(2)],initial_snapshots=snapshots,
        timeout_ms=5000,probe_command=['/fixture/probe','0','1',kind,'a67b7310e001','5000'],events=rows,
        ready_peer=activity,peer_after=previous['peer_after'],peer_management_before=previous['peer_management_before'],
        peer_management_after=previous['peer_management_after'],markers=previous['markers'],withdraw_before_wall_ns=300,after_reply_wall_ns=412)
    ingress=SleSnoopRecord(seq=1,generation=1,dev_index=0,profile=1,direction=1,format=1,
        original_length=9,captured_length=9,timestamp_ns=403)
    ingress.payload[:9]=bytes.fromhex('a20200040005040100')
    r.update(snoop_base_seq=0,late_trace=[bytes(ingress).hex()],late_reply_trace=bytes(ingress).hex(),late_trace_observed_wall_ns=405)
    return r,peer,wire


class RuntimeAddressLifecycle(unittest.TestCase):
    def test_three_file_shapes_do_not_claim_full_lifecycle_or_peer_business(self):
        for kind in ['release','close','dup']:
            record,_,_=fixture(kind)
            self.assertEqual(len(verify_records(record)),2)
            self.assertFalse(record['peer_business_delivery_acceptance'])
            self.assertFalse(record['whole_lifecycle_acceptance'])

    def test_peer_wire_refactor_preserves_original_oracle_and_explicit_identity(self):
        record,peer,wire=fixture()
        self.assertEqual(len(corroborate_activity_rows(record['ready_peer'],peer,wire,dict(bus=1,device=3))),14)
        with self.assertRaises(ValueError):corroborate_activity_rows(record['ready_peer'],peer,wire,dict(bus=1,device=2))
        broken=copy.deepcopy(wire);broken['complete'].pop()
        with self.assertRaises(ValueError):corroborate_activity_rows(record['ready_peer'],peer,broken,dict(bus=1,device=3))

    def test_first_fault_operands_cannot_be_replaced_by_later_snapshot(self):
        for change in ['missing-first','missing-clock','bool-clock','backward-wall','backward-monotonic','before-previous','truncated','old-generation','different-error']:
            r,_,_=fixture();events={v['stage']:v for v in r['events']};first=events['before-fault-assert']
            if change=='missing-first':r['events'].remove(first)
            elif change=='missing-clock':del first['start_monotonic_ns']
            elif change=='bool-clock':first['wall_ns']=True
            elif change=='backward-wall':first['start_wall_ns']=first['wall_ns']+1
            elif change=='backward-monotonic':first['start_monotonic_ns']=first['monotonic_ns']+1
            elif change=='before-previous':first['start_wall_ns']=events['held']['wall_ns']-1
            elif change=='truncated':first['snapshot']=first['snapshot'][:-2]
            else:
                s=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(first['snapshot']))
                if change=='old-generation':s.generation+=1
                else:s.error=-errno.ETIMEDOUT
                first['snapshot']=bytes(s).hex()
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(r)

    def test_scope_exit_clock_retry_and_unverified_qualification_negatives(self):
        for change in ['scope','business','exit','uid-bool','version-bool','timeout','missing-stage','wrong-pending',
                       'retry','generation','same-dup','bad-clock','metadata-valid','fake-ready','free','address','peer-owner',
                       'missing-ingress','old-ingress','lost-ingress','ingress-after-snapshot','wrong-complete']:
            r,_,_=fixture('dup');events={v['stage']:v for v in r['events']}
            if change=='scope':r['whole_lifecycle_acceptance']=True
            elif change=='business':r['peer_business_delivery_acceptance']=True
            elif change=='exit':r['probe_exit']=True
            elif change=='uid-bool':r['uid']=False
            elif change=='version-bool':r['version']=True
            elif change=='timeout':r['timeout_ms']=4999
            elif change=='missing-stage':r['events'].pop(3)
            elif change=='wrong-pending':events['pending-result']['result']=result(1,4,0x0405,2)
            elif change=='retry':events['admitted']['retry_output']=events['admitted']['input']
            elif change=='generation':r['owners'][0]['generation']=3
            elif change=='same-dup':events['owner']['duplicate_fd']=5
            elif change=='bad-clock':events['held']['wall_ns']=True
            elif change in ['metadata-valid','fake-ready','address']:
                s=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(events['withdrawn']['snapshot']))
                if change=='metadata-valid':s.valid_fields=1
                elif change=='fake-ready':s.flags=1
                else:s.address[0]^=1
                events['withdrawn']['snapshot']=bytes(s).hex()
            elif change=='free':events['withdrawn']['management']=bytes(SleManagementQuery(version=1,generation=1)).hex()
            elif change=='peer-owner':r['peer_management_after']=bytes(SleManagementQuery(version=1,generation=2)).hex()
            elif change=='missing-ingress':r['late_trace']=[]
            elif change=='ingress-after-snapshot':r['late_trace_observed_wall_ns']=420
            else:
                ingress=SleSnoopRecord.from_buffer_copy(bytes.fromhex(r['late_trace'][0]))
                if change=='old-ingress':ingress.generation=2
                elif change=='lost-ingress':ingress.lost=1
                else:ingress.payload[5]=6
                r['late_trace']=[bytes(ingress).hex()];r['late_reply_trace']=r['late_trace'][0]
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(r)
