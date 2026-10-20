# SPDX-License-Identifier: GPL-2.0-only
"""Explicit finite verifier/process fixtures;not Native/Engine/RF evidence."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from ws73_capture import CaptureError
import ws73_ssap_subscription as gate
from ws73_application_client import application_environment
from test_ws73_ssap_update_delivery import fixture as old_fixture,matched
from test_ws73_application_client import fixture as role_fixture


def credential(uid):
    return dict(uids=[uid]*4,gids=[uid]*4,groups=[],
                capabilities={k:'0'for k in ('CapEff','CapPrm','CapAmb','CapInh')})


def fixture(phase=0,*,renewal=False):
    row=old_fixture(phase)
    old=row.pop('ssap_update_delivery');row.pop('ssap_update_delivery_required');row.pop('ssap_update_delivery_status')
    observed=role_fixture()[0]['application_clients'][phase]
    row.update(ssap_subscription_required=True,ssap_subscription_contract_version=1,
               ssap_subscription_status=gate.STATUS,ssap_subscription=[],
               role_probe=copy.deepcopy(observed['role_probe']),channel_role='sparklink-apps-only',application_role_contract_version=2)
    row['role_probe']['args'][1]=row['owners'][0]['object']['path']
    if renewal:row.update(ssap_subscription_renewal_required=True,ssap_subscription_renewal_contract_version=1)
    def observation(api,wall,**data):
        return dict(start_wall_ns=wall,end_wall_ns=wall+1,start_monotonic_ns=1000,end_monotonic_ns=1010,
                    receipt=dict(api=api,handle=17,started_ns=1001,returned_ns=1002,deadline_ns=5000001001,**data))
    for s,base in enumerate(old):
        item=copy.deepcopy(base);item.pop('cases');item['end_wall_ns']=20000;item['credentials']=credential(1005);item['leases']=[]
        row['ssap_subscription'].append(item);api=item['publisher_api'];other='python'if api=='c'else'c';peer=row['owners'][s];server=row['owners'][1-s]
        lines=[f'SdkOwnedAPI: api={api} client_closed=true','SsapOwnedService: start=16 end=17 property=17; local registration only']
        for mode in (1,2):
            begin=1000*mode;lease=dict(mode=mode,start_wall_ns=begin,end_wall_ns=begin+900,messages=[])
            active=dict(stage='ssap_subscription_active',api=other,token=mode,epoch=41,started_ns=1000,
                        deadline_ns=5000001000,returned_ns=1001,expires_ns=30000001000,client_closed=True)
            prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
            app=dict(api=other,args=prefix+['subscription',str(peer['owner']['index']),'7',peer['object']['path'],'17',str(mode),'30000'],
                     environment=application_environment(),credentials=credential(1004),start_wall_ns=begin+1,end_wall_ns=begin+800,exit=0,stderr='')
            lease.update(active=active,application=app,enabled=[observation(api,begin+5,modes=mode)],disabled=[observation(api,begin+810,modes=0)])
            raw=[active];item['leases'].append(lease)
            for configured in (mode,0):
                decision=dict(api=api,index=server['owner']['index'],generation=7,token=mode*2+configured+1,request_id=mode*2+configured+1,
                              lifetime=server['object']['lifetime'],handle=server['object']['handle'],epoch=41,level=2,deadline_ns=5000000,
                              property=17,data_type=2,write=True,value=bytes([configured,0]).hex(),local_tcid=10,remote_tcid=10,pi=0,
                              allow=True,decision_ns=4000000,decision_wall_ns=begin+4)
                lines.append('SdkAuthorizationDecision: '+json.dumps(decision))
            lines.append('SdkOwnedConfiguration: '+json.dumps(lease['enabled'][0]['receipt']))
            for n in range(3):
                seq=(phase<<24)|(s<<20)|(mode<<16)|n;value=seq.to_bytes(4,'little')+bytes([s*60+mode*4+n+1])*28
                reply=(seq|0x80000000).to_bytes(4,'little')+bytes([s*60+mode*4+n+21])*28
                pdu=(bytes([16 if mode==2 else 15,3,17,0,32,0])+value).hex();start=begin+100+n*100
                checked=dict(stage='ssap_subscription_checked_reply',api=other,sequence=n+1,value=value.hex(),reply=reply.hex())
                batch=dict(stage='ssap_subscription_batch',api=other,last=n+1,dropped=0,refused=0,state=1,flags=0,reason=0,discarded=0,
                           packets=[dict(sequence=n+1,epoch=41,level=2,indication=mode==2,pdu=pdu)])
                case=dict(number=n,value=value.hex(),reply=reply.hex(),start_wall_ns=start,end_wall_ns=start+30,
                          replacement=observation(api,start,value=value.hex()),before=dict(value=value.hex()),after=dict(value=reply.hex()),
                          send=observation(api,start+10,stage=2 if mode==2 else 1,pdu=pdu,ack='110301'if mode==2 else''),checked=checked,batch=batch)
                lease['messages'].append(case);raw.extend((checked,batch))
                lines+=['SdkOwnedReplaced: '+json.dumps(case['replacement']['receipt']),f'SsapOwnedValue: handle=17 value={value.hex()}',
                        'SdkOwnedUpdate: '+json.dumps(case['send']['receipt']),f'SsapOwnedValue: handle=17 value={reply.hex()}']
            release=dict(stage='ssap_subscription_released',api=other,flags=1,discarded=0);lease['release']=release;raw.append(release)
            if renewal:
                active['expires_ns']=active['started_ns']+1_000_000_000;app['args'][-1]='1000'
                renewed=dict(stage='ssap_subscription_renewed',api=other,token=active['token'],epoch=active['epoch'],
                    expires_ns=30_000_002_000,started_ns=2000,deadline_ns=5_000_002_000,returned_ns=2001)
                lease['renewal']=renewed;raw.insert(3,renewed)
                upper=active['returned_ns']+1_000_000_000
                lease['old_expiry_barrier']=dict(original_expiry_upper_ns=upper,threshold_ns=upper+50_000_000,start_ns=2002,end_ns=upper+50_000_001)
                for n,message in enumerate(lease['messages']):
                    message['start_monotonic_ns']=1100 if n==0 else upper+50_000_010+n
                    message['end_monotonic_ns']=1500 if n==0 else upper+50_000_020+n
            app['stdout']='\n'.join(json.dumps(v)for v in raw)+'\n'
            lines.append('SdkOwnedConfiguration: '+json.dumps(lease['disabled'][0]['receipt']))
        lines.append(f'SdkOwnedRemoved: api={api} start=16');item['stdout']='\n'.join(lines)+'\n'
    return row


def pressure_fixture(phase=0):
    """Finite report-shape fixture only;not a successful Native/wire backend."""
    row=fixture(phase);row.update(ssap_subscription_pressure_required=True,ssap_subscription_pressure_contract_version=1)
    for s,item in enumerate(row['ssap_subscription']):
        api=item['publisher_api'];reader='python'if api=='c'else'c';old_lines=item['stdout'].splitlines()
        lines=old_lines[:2]
        decisions=[v for v in old_lines if v.startswith('SdkAuthorizationDecision: ')]
        item['end_wall_ns']=100000
        for mode,lease in zip((1,2),item['leases'],strict=True):
            template=copy.deepcopy(lease['messages'][0]);lease['messages']=[]
            begin=mode*20000;lease['start_wall_ns']=begin;lease['end_wall_ns']=begin+19000
            app=lease['application'];app.update(start_wall_ns=begin+1,end_wall_ns=begin+18000)
            for obs in lease['enabled']:obs.update(start_wall_ns=begin+5,end_wall_ns=begin+6)
            for obs in lease['disabled']:obs.update(start_wall_ns=begin+18010,end_wall_ns=begin+18011)
            for line in decisions[(mode-1)*2:mode*2]:
                v=json.loads(line.split(': ',1)[1]);v['decision_wall_ns']=begin+4;lines.append('SdkAuthorizationDecision: '+json.dumps(v))
            lines.append('SdkOwnedConfiguration: '+json.dumps(lease['enabled'][0]['receipt']))
            raw=[lease['active']]
            for n in range(18):
                c=copy.deepcopy(template);seq=(phase<<24)|(s<<20)|(mode<<16)|n
                c.update(number=n,value=(seq.to_bytes(4,'little')+bytes([n+1])*28).hex(),
                    reply=((seq|0x80000000).to_bytes(4,'little')+bytes([n+41])*28).hex(),start_wall_ns=begin+100+n*100,end_wall_ns=begin+10000+n*100)
                c['replacement']['receipt']['value']=c['value'];c['replacement'].update(start_wall_ns=c['start_wall_ns'],end_wall_ns=c['start_wall_ns']+1)
                c['before']['value']=c['value'];c['send'].update(start_wall_ns=c['start_wall_ns']+2,end_wall_ns=c['start_wall_ns']+3)
                pdu=bytes([16 if mode==2 else 15,3,17,0,32,0])+bytes.fromhex(c['value'])
                c['send']['receipt'].update(pdu=pdu.hex(),stage=2 if mode==2 else 1,ack='110301'if mode==2 else'')
                if n==16:
                    for k in ('after','batch','checked'):c.pop(k)
                    if mode==2:
                        for k in ('stage','pdu','ack'):c['send']['receipt'].pop(k)
                        c['send']['receipt']['result']=-5
                else:
                    c['after']['value']=c['reply'];c['checked'].update(sequence=n+1,value=c['value'],reply=c['reply'])
                    c.pop('batch')
                lease['messages'].append(c)
            lease['drained']=gate.pressure_batch(lease,reader,17)
            lease['messages'][-1]['batch']=gate.pressure_batch(lease,reader,17,resumed=True)
            raw += [lease['drained']]+[c['checked']for c in lease['messages']if c['number']!=16]+[lease['messages'][-1]['batch'],lease['release']]
            app['stdout']='\n'.join(json.dumps(v)for v in raw)+'\n'
            for c in lease['messages'][:17]:
                lines+=['SdkOwnedReplaced: '+json.dumps(c['replacement']['receipt']),f'SsapOwnedValue: handle=17 value={c["value"]}',
                    ('SdkOwnedUpdateObserved: 'if mode==2 and c['number']==16 else'SdkOwnedUpdate: ')+json.dumps(c['send']['receipt'])]
            lines += [f'SsapOwnedValue: handle=17 value={c["reply"]}'for c in lease['messages'][:16]]
            c=lease['messages'][-1];lines+=['SdkOwnedReplaced: '+json.dumps(c['replacement']['receipt']),f'SsapOwnedValue: handle=17 value={c["value"]}',
                'SdkOwnedUpdate: '+json.dumps(c['send']['receipt']),f'SsapOwnedValue: handle=17 value={c["reply"]}',
                'SdkOwnedConfiguration: '+json.dumps(lease['disabled'][0]['receipt'])]
        lines.append(f'SdkOwnedRemoved: api={api} start=16');item['stdout']='\n'.join(lines)+'\n'
    return row


class SubscriptionGate(unittest.TestCase):
    def test_pressure_shape_counts_and_distinct_old_qualifications(self):
        rows=[]
        for phase in (0,1):
            proof,credit=gate.corroborate(pressure_fixture(phase),matched)
            self.assertEqual(credit,{0:144,1:144})
            self.assertEqual([len(v['wire'])for v in proof],[144,144])
            rows.append(dict(phase=phase,ssap_subscription=proof))
        value=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows)
        self.assertTrue(gate.valid_summary(value));self.assertTrue(gate.valid_pressure_summary(value))
        self.assertFalse(gate.valid_pressure_summary(dict(status=value['status'],proofs=[dict(phase=p,ssap_subscription=gate.corroborate(fixture(p),matched)[0])for p in(0,1)])))
        for k,v in [('notification_drops',0),('indication_refusals',True),('resumed',1),('pressure_contract_version',True)]:
            bad=copy.deepcopy(value);bad['proofs'][0]['ssap_subscription'][0][k]=v;self.assertFalse(gate.valid_pressure_summary(bad),k)

    def test_pressure_original_batch_refusal_and_delivery_negatives(self):
        for kind in ('unrequested','version','count','eviction','reorder','epoch','missing-drop','missing-refusal','success','timeout','fake-ACK','overflow-app','resume','raw','store'):
            row=pressure_fixture();item=row['ssap_subscription'][0];lease=item['leases'][0];ind=item['leases'][1]
            if kind=='unrequested':row.pop('ssap_subscription_pressure_required')
            elif kind=='version':row['ssap_subscription_pressure_contract_version']=True
            elif kind=='count':lease['messages'].pop()
            elif kind=='eviction':lease['drained']['packets'][0]=copy.deepcopy(lease['drained']['packets'][1])
            elif kind=='reorder':lease['drained']['packets'].reverse()
            elif kind=='epoch':lease['drained']['packets'][0]['epoch']+=1
            elif kind=='missing-drop':lease['drained']['dropped']=0
            elif kind=='missing-refusal':ind['drained']['refused']=0
            elif kind=='success':ind['messages'][16]['send']['receipt']['result']=0
            elif kind=='timeout':ind['messages'][16]['send']['receipt']['result']=-110
            elif kind=='fake-ACK':ind['messages'][0]['send']['receipt']['ack']='110300'
            elif kind=='overflow-app':lease['messages'][16]['checked']={}
            elif kind=='resume':lease['messages'][-1]['batch']['packets'][0]['sequence']=17
            elif kind=='raw':lease['application']['stdout']=''
            else:lease['messages'][0]['after']['value']='00'
            with self.subTest(kind=kind),self.assertRaises((CaptureError,KeyError,ValueError)):
                gate.corroborate(row,matched)

    def test_buffered_indication_ack_uses_original_send_window(self):
        row=pressure_fixture();windows=[c['send']for item in row['ssap_subscription']for lease in item['leases']if lease['mode']==2 for c in lease['messages']]
        observed=[]
        def scoped(owner,direction,frame,window):
            if frame.endswith((b'\x11\x03\x01',b'\x11\x03\0')):
                self.assertIn(window,windows);observed.append(window)
            return matched(owner,direction,frame,window)
        gate.corroborate(row,scoped)
        self.assertEqual(len(observed),72)

    def test_real_renewal_verifier_fixture_is_distinct_from_continuous(self):
        rows=[]
        for phase in (0,1):
            proof,credit=gate.corroborate(fixture(phase,renewal=True),matched)
            self.assertEqual(credit,{0:43,1:43})
            self.assertEqual([v['renewals']for v in proof],[2,2])
            rows.append(dict(phase=phase,ssap_subscription=proof))
        value=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows)
        self.assertTrue(gate.valid_summary(value));self.assertTrue(gate.valid_renewal_summary(value))
        del rows[0]['ssap_subscription'][0]['renewal_contract_version']
        self.assertFalse(gate.valid_renewal_summary(value))

    def test_renewal_scope_original_expiry_and_transcript_negatives(self):
        for kind in ('unrequested','version','token','epoch','late','deadline','short-renewal','old-upper','early-barrier','early-update','first-update-order','raw','missing-renewal'):
            row=fixture(renewal=True);lease=row['ssap_subscription'][0]['leases'][0];r=lease['renewal'];b=lease['old_expiry_barrier']
            if kind=='unrequested':row.pop('ssap_subscription_renewal_required')
            elif kind=='version':row['ssap_subscription_renewal_contract_version']=True
            elif kind=='token':r['token']+=1
            elif kind=='epoch':r['epoch']+=1
            elif kind=='late':r['returned_ns']=lease['active']['expires_ns']
            elif kind=='deadline':r['deadline_ns']+=1
            elif kind=='short-renewal':r['expires_ns']=lease['active']['expires_ns']
            elif kind=='old-upper':b['original_expiry_upper_ns']-=1
            elif kind=='early-barrier':b['end_ns']=b['threshold_ns']-1
            elif kind=='early-update':lease['messages'][1]['start_monotonic_ns']=b['end_ns']-1
            elif kind=='first-update-order':lease['messages'][0]['end_monotonic_ns']=r['started_ns']+1
            elif kind=='raw':lease['application']['stdout']=''
            else:lease.pop('renewal')
            with self.subTest(kind=kind),self.assertRaises((CaptureError,KeyError,ValueError)):
                gate.corroborate(row,matched)

    def test_fixed_fixture_continuous_multiple_messages_and_both_roles(self):
        rows=[]
        for phase in (0,1):
            proof,credit=gate.corroborate(fixture(phase),matched)
            self.assertEqual(credit,{0:43,1:43})
            self.assertEqual([len(v['wire'])for v in proof],[43,43])
            rows.append(dict(phase=phase,ssap_subscription=proof))
        value=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows)
        self.assertTrue(gate.valid_summary(value))
        for kind in ('missing-lease','single-update','missing-wire','wrong-peer','false-count'):
            bad=copy.deepcopy(value);item=bad['proofs'][0]['ssap_subscription'][0]
            if kind=='missing-lease':item['leases']=1
            elif kind=='single-update':item['updates']=1
            elif kind=='missing-wire':item['wire'].pop()
            elif kind=='wrong-peer':item['peer']=item['publisher']
            else:item['updates']=True
            self.assertFalse(gate.valid_summary(bad),kind)

    def test_scope_payload_role_cleanup_and_raw_transcript_negatives(self):
        cases=('old-contract','missing-message','wrong-sequence','wrong-payload','wrong-epoch','wrong-level','drop',
               'fake-ACK','cleanup','owner-store','raw-application','raw-provider','management','extra-group','owner-role',
               'changed-expiry','late-acquisition','missing-preflight','wrong-approval')
        for kind in cases:
            row=fixture();item=row['ssap_subscription'][0];lease=item['leases'][0];message=lease['messages'][0]
            if kind=='old-contract':row.pop('ssap_subscription_contract_version')
            elif kind=='missing-message':lease['messages'].pop()
            elif kind=='wrong-sequence':message['checked']['sequence']=2
            elif kind=='wrong-payload':message['batch']['packets'][0]['pdu']='00'
            elif kind=='wrong-epoch':message['batch']['packets'][0]['epoch']+=1
            elif kind=='wrong-level':message['batch']['packets'][0]['level']=0
            elif kind=='drop':message['batch']['dropped']=1
            elif kind=='fake-ACK':message['send']['receipt']['ack']='110300'
            elif kind=='cleanup':lease['release']['flags']=0
            elif kind=='owner-store':message['after']['value']='00'
            elif kind=='raw-application':lease['application']['stdout']=lease['application']['stdout'].splitlines()[0]+'\n'
            elif kind=='raw-provider':item['stdout']=item['stdout'].replace('SsapOwnedValue','FakeValue')
            elif kind=='management':lease['application']['credentials']['uids']=[1000]*4
            elif kind=='extra-group':lease['application']['credentials']['groups']=[1000]
            elif kind=='owner-role':item['credentials']['uids']=[1000]*4
            elif kind=='changed-expiry':lease['active']['expires_ns']=1
            elif kind=='late-acquisition':lease['active']['returned_ns']=lease['active']['deadline_ns']
            elif kind=='missing-preflight':row['role_probe']['stdout']=row['role_probe']['stdout'].replace('AUTH_SSAP_PREFLIGHT: ReadSsapUpdates\n','')
            else:item['stdout']=item['stdout'].replace('"data_type": 2','"data_type": 0')
            with self.subTest(kind=kind),self.assertRaises((CaptureError,KeyError,ValueError)):
                gate.corroborate(row,matched)

    def test_lost_capture_is_not_application_success(self):
        def missing(*args):raise CaptureError('missing opposite RX fixture')
        with self.assertRaises(CaptureError):gate.corroborate(fixture(),missing)

    def test_requests_and_selector_cannot_be_arbitrary_root_work(self):
        row=fixture();request=dict(phase=0,owners=row['owners'],tools={},security_requirement=2,message_security_required=True,status='RUNNING',start_wall_ns=1)
        gate.validate_request(request,0)
        for k,v in [('phase',2),('status','PASS'),('security_requirement',0),('message_security_required',False),('program','/bin/sh')]:
            bad=request|{k:v}
            with self.subTest(k=k),self.assertRaises(CaptureError):gate.validate_request(bad,0)
        args=dict(ssap_subscription_verify=True,channel_socket_verify=True,security_agent='numeric-approve')
        self.assertTrue(gate.requested(SimpleNamespace(**args),passthrough=True))
        self.assertTrue(gate.requested(SimpleNamespace(**args,ssap_subscription_renewal_verify=True),passthrough=True))
        self.assertTrue(gate.requested(SimpleNamespace(**args,ssap_subscription_pressure_verify=True),passthrough=True))
        for invalid in (dict(ssap_subscription_pressure_verify=True),dict(**args,ssap_subscription_pressure_verify=True,ssap_subscription_renewal_verify=True)):
            with self.assertRaises(ValueError):gate.requested(SimpleNamespace(**invalid),passthrough=True)
        with self.assertRaises(ValueError):gate.requested(SimpleNamespace(ssap_subscription_renewal_verify=True),passthrough=True)
        for key in ('ssap_update_delivery_verify','application_client_verify','observer_policy','fault_recovery'):
            with self.subTest(key=key),self.assertRaises(ValueError):gate.requested(SimpleNamespace(**args,**{key:True}),passthrough=True)

    def test_live_incomplete_stdio_tail_is_pending_not_a_complete_receipt(self):
        with tempfile.TemporaryDirectory()as tmp:
            p=Path(tmp)/'output';p.write_text('{"stage":"ready"}\n{"sta')
            app=dict(output_files=[str(p)])
            self.assertEqual(gate.app_rows(None,app),[{'stage':'ready'}])

    def test_terminal_status_and_original_supervisor_receipt_fail_closed(self):
        # Report-shape fixtures only;no successful Native dependency or device.
        from ws73_target import run_exit_code
        rows=[]
        for phase in (0,1):
            rows.append(dict(phase=phase,ssap_subscription=gate.corroborate(fixture(phase),matched)[0],
                protected_ssap=dict(required=2,controllers=[{'fixture':0},{'fixture':1}]),
                ssap_values=[{'fixture':'checked-elsewhere'}],ssap_discovery=[{'fixture':'checked-elsewhere'}]))
        supervision=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,
            phases=2,reader_UID=1004,provider_UID=1005,readers=8,providers=4,updates=24,
            daemon=dict(pid=2,start_ticks=3),supervisor=dict(pid=4,start_ticks=5))
        record=dict(status='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS',qemu_exit=0,supervisor_exit=0,
            ssap_subscription_requested=True,ssap_subscription_contract_version=1,ssap_subscription_acceptance=True,
            ssap_subscription_supervision=supervision,ordinary_channel_socket_acceptance=True,
            live_ssap_security_requirement=2,live_security_agent_requested='numeric-approve',
            qemu_args=['ws73.ssap_subscription=1'],
            channel_socket_corroboration=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows,round_trips=8),
            security_agent_corroboration=dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',
                phases=[dict(mode='numeric-approve',ssap_security_requirement=2)for _ in (0,1)],business_round_trips=8))
        self.assertEqual(run_exit_code(record),0)
        pressure=copy.deepcopy(record)
        pressure.update(ssap_subscription_pressure_requested=True,ssap_subscription_pressure_contract_version=1,
            ssap_subscription_pressure_acceptance=True,qemu_args=['ws73.ssap_subscription=1 ws73.ssap_subscription_pressure=1'])
        for phase,row in enumerate(pressure['channel_socket_corroboration']['proofs']):
            row['ssap_subscription']=gate.corroborate(pressure_fixture(phase),matched)[0]
        pressure['ssap_subscription_supervision'].update(pressure_contract_version=1,updates=144,checked_replies=136,notification_drops=4,indication_refusals=4,resumed=8)
        self.assertEqual(run_exit_code(pressure),0)
        snapshot=copy.deepcopy(pressure)
        snapshot['ssap_subscription_snapshot_contract_version']=1
        snapshot['qemu_args'][0]+=' ws73.subscription_snapshot=1'
        snapshot['ssap_subscription_supervision'].update(snapshot_contract_version=1,snapshot_phases=2,snapshot_files=30,snapshot_bytes=2048)
        self.assertEqual(run_exit_code(snapshot),0)
        for kind in ('version','boot','missing-version','missing-proof','single-phase','truncated-files','excess-bytes','abnormal-exit'):
            bad=copy.deepcopy(snapshot)
            if kind=='version':bad['ssap_subscription_snapshot_contract_version']=True
            elif kind=='boot':bad['qemu_args']=pressure['qemu_args']
            elif kind=='missing-version':bad.pop('ssap_subscription_snapshot_contract_version')
            elif kind=='missing-proof':bad['ssap_subscription_supervision']=pressure['ssap_subscription_supervision']
            elif kind=='single-phase':bad['ssap_subscription_supervision']['snapshot_phases']=1
            elif kind=='truncated-files':bad['ssap_subscription_supervision']['snapshot_files']=0
            elif kind=='excess-bytes':bad['ssap_subscription_supervision']['snapshot_bytes']=2**63
            else:bad['supervisor_exit']=23
            with self.subTest(kind=kind):self.assertEqual(run_exit_code(bad),1)
        for change in [dict(ssap_subscription_pressure_requested=False),dict(ssap_subscription_pressure_contract_version=True),
                dict(ssap_subscription_pressure_acceptance=False),dict(qemu_args=['ws73.ssap_subscription=1']),
                dict(ssap_subscription_supervision=record['ssap_subscription_supervision']),
                dict(channel_socket_corroboration=record['channel_socket_corroboration']),dict(ssap_subscription_renewal_requested=True)]:
            with self.subTest(change=change):self.assertEqual(run_exit_code(pressure|change),1)
        renewed=copy.deepcopy(record)
        renewed.update(ssap_subscription_renewal_requested=True,ssap_subscription_renewal_contract_version=1,ssap_subscription_renewal_acceptance=True,
            qemu_args=['ws73.ssap_subscription=1 ws73.ssap_subscription_renewal=1'])
        for phase,row in enumerate(renewed['channel_socket_corroboration']['proofs']):
            row['ssap_subscription']=gate.corroborate(fixture(phase,renewal=True),matched)[0]
        renewed['ssap_subscription_supervision'].update(renewal_contract_version=1,renewals=8,post_original_expiry_updates=16)
        self.assertEqual(run_exit_code(renewed),0)
        for change in [dict(ssap_subscription_renewal_requested=False),dict(ssap_subscription_renewal_contract_version=True),
                dict(ssap_subscription_renewal_acceptance=False),dict(qemu_args=['ws73.ssap_subscription=1']),
                dict(ssap_subscription_supervision=record['ssap_subscription_supervision']),
                dict(channel_socket_corroboration=record['channel_socket_corroboration'])]:
            with self.subTest(change=change):self.assertEqual(run_exit_code(renewed|change),1)
        for changes in [dict(status='PASSTHROUGH_SUPPORT_PASS'),dict(status='FAIL'),dict(qemu_exit=1),
                dict(supervisor_exit=1),dict(live_ssap_security_requirement=1),dict(live_security_agent_requested='approve'),
                dict(ssap_subscription_acceptance=False),dict(ssap_subscription_contract_version=True),
                dict(ordinary_channel_socket_acceptance=False),dict(qemu_args=[]),dict(security_agent_corroboration={}),
                dict(ssap_subscription_supervision={})]:
            with self.subTest(changes=changes):self.assertEqual(run_exit_code(record|changes),1)
        del record['supervisor_exit']
        self.assertEqual(run_exit_code(record),1)
        self.assertEqual(run_exit_code(record,supervisor_pending=True),0)

