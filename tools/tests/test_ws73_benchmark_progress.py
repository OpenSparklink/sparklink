# SPDX-License-Identifier: GPL-2.0-only
"""Original report/ACB metadata fixtures, not real kernel/USB/RF execution."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ws73_benchmark import fixture as complete_fixture
import ws73_benchmark as gate
from ws73_benchmark_progress import application_prefixes,read_failed_reports,transport_prefixes,business_legs,observed_link_window
from ws73_capture import CaptureError,reassemble_acb,reassemble_acb_retired


def fixture():
    reports=complete_fixture('window')
    for i,r in enumerate(reports):
        r.update(status='INCOMPLETE',correctness=False)
        r['observation']['error']='original socket fault'
        r['finalization'].update(completed=False,error='finish barrier EOF is author withdrawal')
        r['channel_identity'].update(local_tcid=128,remote_tcid=128,mtu=249,mps=254)
        r['channel_request']=dict(version=1,kind='dynamic_basic',source_port=24576+i,
            destination_port=24577-i,aid=29441,mtu=249,mps=254,slqi=1,passive=bool(i))
    source,peer=reports
    source['outgoing'][1].update(read_ns=None,validated_ns=None,reply_count=0)
    row=source['outgoing'][2]
    for k in ('planned_ns','dispatch_ns','first_syscall_ns','admitted_ns','syscall_ns','deadline_ns','read_ns','validated_ns'):row[k]=None
    row.update(frame_hex='',send_attempts=0,would_block=0,reply_count=0)
    source['summary'].update(dispatched=2,unattempted=1,admitted=2,validated_replies=1,successful_timely_replies=1,missing_admitted_replies=1)
    source['counters']['rx_packets']=1
    peer['incoming'].pop();peer['summary'].update(peer_validated_requests=2,peer_reply_admissions=2,peer_validated_application_bytes=122)
    peer['counters']['rx_packets']=2
    return reports,dict(source['config'])


def packet(handle,boundary,record,data,*,device=2,direction='in'):
    return dict(bus=1,device=device,handle=handle,boundary=boundary,record=record,
                wall_ns=record*1000,direction=direction,data=data.hex())


class FailedProgress(unittest.TestCase):
    def test_physical_windows_keep_whole_current_lifetime_not_old_role_data(self):
        owners=[];events=[];packets=[]
        for i in range(2):
            owner=dict(index=i,generation=7+i,bus=1,device=2+i)
            identity=dict(generation=7+i,lifetime=3,handle=0,role=i,address_type=0,address='00:01:09:32:54:CD')
            owners.append(dict(owner=owner,object=identity))
            for record,up in [(1,True),(4,False),(6,True),(12,False)]:
                body=b'\0\0\0'+bytes([i,0])+bytes.fromhex('0001093254cd') if up else bytes.fromhex('00000007')
                events.append(dict(bus=1,device=2+i,record=record,wall_ns=record*1000,
                                   event=0x1401 if up else 5,params=body.hex()))
            for record in (2,7,10,13):
                packets.append(packet(0,0,record,b'unknown-current-data',device=2+i))
        capture=dict(native_events=events,acb_packets=packets)
        scoped,windows=observed_link_window(capture,owners,9000)
        self.assertEqual([p['record']for p in scoped['acb_packets']],[7,10,7,10])
        self.assertEqual([(w['up']['record'],w['down']['record'])for w in windows],[(6,12),(6,12)])
        self.assertEqual([p['record']for p in capture['acb_packets']],[2,7,10,13,2,7,10,13])
        # The full interval, including unknown payloads on either side of the
        # original app start, survives. No payload-based selection is allowed.
        for case in ('role','address-type','address','generation','lifetime','missing-up','missing-down',
                     'down-before-start','replacement-up','duplicate-owner','invalid-anchor'):
            old=copy.deepcopy(capture);entries=copy.deepcopy(owners);anchor=9000
            if case=='role':entries[0]['object']['role']=1
            elif case=='address-type':entries[0]['object']['address_type']=1
            elif case=='address':entries[0]['object']['address']='00:01:09:32:54:F9'
            elif case=='generation':entries[0]['object']['generation']+=1
            elif case=='lifetime':entries[0]['object']['lifetime']=0
            elif case=='missing-up':old['native_events']=[e for e in old['native_events']if not(e['device']==2 and e['record']==6)]
            elif case=='missing-down':old['native_events']=[e for e in old['native_events']if not(e['device']==2 and e['record']==12)]
            elif case=='down-before-start':anchor=13000
            elif case=='replacement-up':old['native_events'][3]['event']=0x1401
            elif case=='duplicate-owner':entries[1]=copy.deepcopy(entries[0])
            else:anchor=True
            with self.subTest(case=case),self.assertRaises(CaptureError):observed_link_window(old,entries,anchor)

    def test_business_legs_use_payload_and_trace_fragments_not_admission_id(self):
        reports, config = fixture();app = application_prefixes(reports, config)
        owners = [dict(owner=dict(index=r['channel_identity']['controller'],
            generation=r['channel_identity']['generation'],bus=1,device=2+i),
            object=dict(lifetime=r['channel_identity']['lifetime'],handle=0)) for i,r in enumerate(reports)]
        packets=[]
        for i in range(2):
            for endpoint,direction,reply in [(0,'out',False),(1,'in',False),(1,'out',True),(0,'in',True)]:
                payload = bytes.fromhex(reports[1]['incoming'][i]['frame_hex'] if reply else reports[0]['outgoing'][i]['frame_hex'])
                raw=b'\x80\x00'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                partial = i==1 and endpoint==0 and direction=='in'
                packets.append(packet(0,1 if partial else 0,len(packets)+1,raw[:40] if partial else raw,
                                      device=2+endpoint,direction=direction))
        capture=dict(acb_packets=packets,native_events=[dict(bus=1,device=2,event=5,params='00000007',record=9,wall_ns=9000)])
        operations=[]
        for p in packets:
            if p['direction']!='out':continue
            identity=reports[p['device']-2]['channel_identity']
            operations.append(dict(controller=identity['controller'],generation=identity['generation'],
                lifetime=identity['lifetime'],epoch=1,slot=2,admission_sequence=1234+p['record'],
                admission_ns=100,retirement_ns=1000,deadline_jiffies=5000,dtap_bytes=66,
                accepted_fragments=1,reported_credit_waits=0,accepted_usb_records=[p['record']]))
        timings=dict(operations=operations)
        rows=business_legs(capture,reports,app,owners,timings)
        self.assertEqual(len(rows),8)
        incomplete=[r for r in rows if not r['complete_sdu']]
        self.assertEqual([(r['application_index'],r['reply'],r['bytes'])for r in incomplete],[(1,True,40)])
        self.assertEqual(rows[0]['application_index'],0)
        self.assertNotEqual(rows[0]['operation']['admission_sequence'],0)
        for case in ['missing-validated-reply','missing-peer-request','wrong-accepted-record','wrong-generation','payload','duplicate-leg']:
            c,ts=copy.deepcopy(capture),copy.deepcopy(timings)
            if case=='missing-validated-reply':c['acb_packets'].pop(3)
            elif case=='missing-peer-request':c['acb_packets'].pop(1)
            elif case=='wrong-accepted-record':ts['operations'][0]['accepted_usb_records']=[999]
            elif case=='wrong-generation':ts['operations'][0]['generation']+=1
            elif case=='payload':c['acb_packets'][0]['data']=c['acb_packets'][0]['data'][:-2]+'ff'
            else:c['acb_packets'].append(copy.deepcopy(c['acb_packets'][0])|dict(record=10))
            with self.subTest(case=case),self.assertRaises(CaptureError):business_legs(c,reports,app,owners,ts)

    def test_actual_files_must_match_closed_snapshot_not_just_parse(self):
        reports,_=fixture()
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);(root/'reports').mkdir();snapshot=dict(files={})
            for i,report in enumerate(reports):
                name=f'reports/benchmark-0-{i}.json';raw=json.dumps(report).encode()
                (root/name).write_bytes(raw);snapshot['files'][name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            actual,_=read_failed_reports(root,0,snapshot);self.assertEqual(actual,reports)
            for kind in ('hash','missing-binding','changed-bytes','missing-file'):
                copied=copy.deepcopy(snapshot)
                name='reports/benchmark-0-0.json'
                if kind=='hash':copied['files'][name]['sha256']='0'*64
                elif kind=='missing-binding':copied['files'].pop(name)
                elif kind=='changed-bytes':(root/name).write_text(json.dumps(reports[0])+' ')
                else:(root/name).unlink()
                with self.subTest(kind=kind),self.assertRaises((CaptureError,OSError)):
                    read_failed_reports(root,0,copied)
                (root/name).write_text(json.dumps(reports[0]))

    def test_failed_reports_account_for_unanswered_and_unattempted_separately(self):
        reports,config=fixture();out=application_prefixes(reports,config)
        self.assertEqual(out['validated_indices'],[0]);self.assertEqual(out['unanswered_indices'],[1])
        self.assertEqual(out['unattempted_indices'],[2]);self.assertEqual(len(out['catalog']),2)
        self.assertFalse(out['original_gate_qualified']);self.assertFalse(out['performance_qualified'])
        with self.assertRaises(CaptureError):gate.load_application_reports(*reports)

    def test_failed_report_negatives_keep_original_payload_scope_and_budgets(self):
        for name in ('status','correctness','performance','budget','finalization','missing-row','hidden-admission',
                     'invented-unsent-payload','wrong-typed-summary','peer-changed-payload','duplicate-peer',
                     'false-reply','late','wrong-channel','bad-counter','missing-counter','missing-resource','whole-claim'):
            reports,config=fixture();left,right=reports
            if name=='status':left['status']='LOAD_OBSERVED_NOT_QUALIFIED'
            elif name=='correctness':left['correctness']=True
            elif name=='performance':left['performance_qualified']=True
            elif name=='budget':left['request_deadline_ns']+=1
            elif name=='finalization':left['finalization']['completed']=True
            elif name=='missing-row':left['outgoing'].pop()
            elif name=='hidden-admission':left['outgoing'][2]['admitted_ns']=1
            elif name=='invented-unsent-payload':left['outgoing'][2]['frame_hex']=left['outgoing'][0]['frame_hex']
            elif name=='wrong-typed-summary':left['summary']['validated_replies']=True
            elif name=='peer-changed-payload':right['incoming'][0]['frame_hex']=right['incoming'][1]['frame_hex']
            elif name=='duplicate-peer':right['incoming'][1]=copy.deepcopy(right['incoming'][0])
            elif name=='false-reply':left['outgoing'][1]['reply_count']=1
            elif name=='late':left['outgoing'][0]['late']=True
            elif name=='wrong-channel':right['channel_identity']['remote_tcid']=129
            elif name=='bad-counter':left['counters']['corrupt_packets']=1
            elif name=='missing-counter':left['counters'].pop('receiver_record_overflow')
            elif name=='missing-resource':left['process_resources']['incomplete']=True
            else:left['summary']['validated_replies']=3
            with self.subTest(name=name),self.assertRaises((CaptureError,KeyError,TypeError)):
                application_prefixes(reports,config)

    def test_retired_prefix_has_actual_opposite_pdu_but_no_application_delivery(self):
        reports,config=fixture();app=application_prefixes(reports,config)
        owners=[dict(owner=dict(index=i,generation=7+i,bus=1,device=2+i),object=dict(lifetime=11+i,handle=0))for i in(0,1)]
        payload=bytes.fromhex(reports[1]['incoming'][1]['frame_hex'])
        full=b'\x80\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
        capture=dict(acb_packets=[packet(0,0,1,full,device=3,direction='out'),packet(0,1,2,full[:40])],
                     native_events=[dict(bus=1,device=2,event=5,params='00000007',record=3,wall_ns=3000)])
        out=transport_prefixes(capture,reports,app,owners);part=out['matched_application_prefixes'][0]
        self.assertEqual(part['application_index'],1);self.assertTrue(part['reply'])
        self.assertEqual(part['prefix_bytes'],40);self.assertEqual(part['opposite_complete_records'],[1])
        self.assertFalse(part['hardware_cause_proved']);self.assertFalse(part['application_delivery_qualified'])
        for name in ('owner','handle','channel','payload','duplicate-opposite','missing-retirement'):
            bad=copy.deepcopy(capture);old=copy.deepcopy(owners)
            if name=='owner':old[0]['owner']['generation']+=1
            elif name=='handle':bad['acb_packets'][1]['handle']=1
            elif name=='channel':bad['acb_packets'][1]['data']='8100'+bad['acb_packets'][1]['data'][4:]
            elif name=='payload':bad['acb_packets'][1]['data']=bad['acb_packets'][1]['data'][:-2]+'aa'
            elif name=='duplicate-opposite':bad['acb_packets'].insert(1,bad['acb_packets'][0]|dict(record=2))
            else:bad['native_events']=[]
            with self.subTest(name=name):
                if name=='channel':
                    # An unclassified stream stays explicit, not attributed.
                    self.assertEqual(transport_prefixes(bad,reports,app,old)['unclassified_retirements'],1)
                else:
                    with self.assertRaises(CaptureError):transport_prefixes(bad,reports,app,old)

    def test_other_handle_link_event_cannot_erase_unfinished_stream(self):
        body=b'\x80\0\x05\0\xf1abcde'
        capture=dict(acb_packets=[packet(1,1,1,body[:7])],native_events=[dict(bus=1,device=2,event=5,params='00020007',record=2,wall_ns=2000)])
        with self.assertRaisesRegex(CaptureError,'incomplete A3'):reassemble_acb(capture)
        capture['native_events'].append(dict(bus=1,device=2,event=5,params='00010007',record=3,wall_ns=3000))
        sdus,retired=reassemble_acb_retired(capture)
        self.assertEqual(sdus,[]);self.assertEqual(retired[0]['handle'],1)
        self.assertEqual(retired[0]['retired_by']['record'],3);self.assertFalse(retired[0]['complete_sdu'])
        for params in ('00','0000','00ffff07'):
            bad=copy.deepcopy(capture);bad['native_events'][0]['params']=params
            with self.subTest(params=params),self.assertRaises(CaptureError):reassemble_acb(bad)


if __name__=='__main__':unittest.main()
