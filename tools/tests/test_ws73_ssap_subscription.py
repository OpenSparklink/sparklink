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


def fixture(phase=0):
    row=old_fixture(phase)
    old=row.pop('ssap_update_delivery');row.pop('ssap_update_delivery_required');row.pop('ssap_update_delivery_status')
    observed=role_fixture()[0]['application_clients'][phase]
    row.update(ssap_subscription_required=True,ssap_subscription_contract_version=1,
               ssap_subscription_status=gate.STATUS,ssap_subscription=[],
               role_probe=copy.deepcopy(observed['role_probe']),channel_role='sparklink-apps-only',application_role_contract_version=2)
    row['role_probe']['args'][1]=row['owners'][0]['object']['path']
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
            app['stdout']='\n'.join(json.dumps(v)for v in raw)+'\n'
            lines.append('SdkOwnedConfiguration: '+json.dumps(lease['disabled'][0]['receipt']))
        lines.append(f'SdkOwnedRemoved: api={api} start=16');item['stdout']='\n'.join(lines)+'\n'
    return row


class SubscriptionGate(unittest.TestCase):
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
        for changes in [dict(status='PASSTHROUGH_SUPPORT_PASS'),dict(status='FAIL'),dict(qemu_exit=1),
                dict(supervisor_exit=1),dict(live_ssap_security_requirement=1),dict(live_security_agent_requested='approve'),
                dict(ssap_subscription_acceptance=False),dict(ssap_subscription_contract_version=True),
                dict(ordinary_channel_socket_acceptance=False),dict(qemu_args=[]),dict(security_agent_corroboration={}),
                dict(ssap_subscription_supervision={})]:
            with self.subTest(changes=changes):self.assertEqual(run_exit_code(record|changes),1)
        del record['supervisor_exit']
        self.assertEqual(run_exit_code(record),1)
        self.assertEqual(run_exit_code(record,supervisor_pending=True),0)

