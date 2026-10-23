# SPDX-License-Identifier: GPL-2.0-only
"""Finite report/parser fixtures only;not a kernel,Host or RF qualification."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock

from ws73_capture import CaptureError
from ws73_diagnostic_hold import PROPERTIES
import ws73_ssap_subscription as gate
import ws73_ssap_sender_deadline as hold_gate
from test_ws73_ssap_subscription import fixture as subscription_fixture
from test_ws73_ssap_update_delivery import matched
from test_ws73_north_star import aggregate,command_payload,pcap


def fixture(phase=0):
    row=subscription_fixture(phase);row.update(ssap_subscription_inflight_release_required=True,
        ssap_subscription_inflight_release_contract_version=1)
    for i,owner in enumerate(row['owners']):owner['owner'].update(port=f'1-{(i^phase)+1}',bus=1,device=10+(i^phase))
    for sender,item in enumerate(row['ssap_subscription']):
        api=item['publisher_api'];lines=item['stdout'].splitlines()[:2]
        decisions=[json.loads(v.split(': ',1)[1])for v in item['stdout'].splitlines()if v.startswith('SdkAuthorizationDecision: ')]
        if sender==0:item['leases'].append(copy.deepcopy(item['leases'][1]))
        for position,lease in enumerate(item['leases']):
            attempt=int(position==2);lease['attempt']=attempt;app=lease['application'];app['pid']=100+position
            if attempt:
                delta=1000;lease['start_wall_ns']+=delta;lease['end_wall_ns']+=delta
                app['start_wall_ns']+=delta;app['end_wall_ns']+=delta;lease['active']['token']=3
                for k in ('enabled','disabled'):
                    for o in lease[k]:o['start_wall_ns']+=delta;o['end_wall_ns']+=delta
                for c in lease['messages']:
                    seq=(phase<<24)|(sender<<20)|(lease['mode']<<16)|(1<<12)|c['number']
                    for k,head in [('value',seq),('reply',seq|0x80000000)]:c[k]=(head.to_bytes(4,'little')+bytes.fromhex(c[k])[4:]).hex()
                    c['start_wall_ns']+=delta;c['end_wall_ns']+=delta
                    for k in ('replacement','send'):c[k]['start_wall_ns']+=delta;c[k]['end_wall_ns']+=delta
                    c['replacement']['receipt']['value']=c['value'];c['before']['value']=c['value'];c['after']['value']=c['reply']
                    pdu=(bytes([16,3,17,0,32,0])+bytes.fromhex(c['value'])).hex()
                    c['send']['receipt']['pdu']=pdu;c['batch']['packets'][0]['pdu']=pdu;c['checked'].update(value=c['value'],reply=c['reply'])
            for d in decisions[2*(lease['mode']-1):2*lease['mode']]:
                d=copy.deepcopy(d);d['decision_wall_ns']=lease['start_wall_ns']+4
                lines.append('SdkAuthorizationDecision: '+json.dumps(d))
            lines.append('SdkOwnedConfiguration: '+json.dumps(lease['enabled'][0]['receipt']))
            raw=[lease['active']]
            for c in lease['messages']:
                raw.extend((c['checked'],c['batch']))
                lines+=['SdkOwnedReplaced: '+json.dumps(c['replacement']['receipt']),f'SsapOwnedValue: handle=17 value={c["value"]}',
                    'SdkOwnedUpdate: '+json.dumps(c['send']['receipt']),f'SsapOwnedValue: handle=17 value={c["reply"]}']
            if sender==0 and position==1:
                value=(((phase<<24)|(2<<16)|3).to_bytes(4,'little')+b'z'*28).hex()
                selection=dict(version=1,phase=phase,property=17,value=value,start_wall_ns=2405,
                    clock=dict(before_ns=1000,wall_ns=2405,after_ns=1001),controllers=[dict(bus=v['owner']['bus'],device=v['owner']['device'],index=v['owner']['index'],generation=v['owner']['generation'],lifetime=v['object']['lifetime'],handle=v['object']['handle'],port=v['owner']['port'])for v in row['owners']])
                case=dict(mode=2,value=value,start_wall_ns=2400,end_wall_ns=2480,start_monotonic_ns=1000,end_monotonic_ns=1_000_000_010,
                    selection=selection,release_request_wall_ns=2440,release_request_monotonic_ns=999_999_999,
                    release_started=dict(stage='ssap_subscription_release_started',api=app['api'],started_ns=1_000_000_000,deadline_ns=6_000_000_000),
                    replacement=copy.deepcopy(lease['messages'][0]['replacement']),before=dict(value=value),send=copy.deepcopy(lease['messages'][0]['send']),
                    hold=dict(markers=[],acks=[],ack_receipts=[]))
                case['replacement']['receipt']['value']=value;case['replacement'].update(start_wall_ns=2400,end_wall_ns=2401)
                case['send'].update(start_wall_ns=2420,end_wall_ns=2470);case['send']['receipt']['pdu']=(b'\x10\x03\x11\0\x20\0'+bytes.fromhex(value)).hex()
                for phase_name,ack_name,start,end,state in [('arm_ready','armed',2410,2411,[True,False,0,0,0,0,False,0]),
                        ('wait_held','held',2430,2431,[False,True,1,0,0,0,False,0]),('release_ready','released',2449,2450,[False,False,1,1,0,0,False,0])]:
                    marker=dict(hold_phase=phase_name,wall_ns=start);case['hold']['markers'].append(marker)
                    case['hold']['acks'].append(dict(stage=ack_name,request=marker,state=dict(zip(PROPERTIES,state))))
                    case['hold']['ack_receipts'].append(dict(stage=ack_name,wall_ns=end))
                lease['inflight_release']=case;lease['release']['discarded']=1;raw.append(case['release_started'])
                lines+=['SdkOwnedReplaced: '+json.dumps(case['replacement']['receipt']),f'SsapOwnedValue: handle=17 value={value}','SdkOwnedUpdate: '+json.dumps(case['send']['receipt'])]
            raw.append(lease['release']);app['stdout']='\n'.join(json.dumps(v)for v in raw)+'\n'
            lines.append('SdkOwnedConfiguration: '+json.dumps(lease['disabled'][0]['receipt']))
        lines.append(f'SdkOwnedRemoved: api={api} start=16');item['stdout']='\n'.join(lines)+'\n'
    pending=row['ssap_subscription'][0]['leases'][1]['inflight_release']
    def match(owner,direction,frame,window):
        packet=matched(owner,direction,frame,window);at=window['start_wall_ns']
        if window is pending:
            if frame[4]==16:at=2421 if direction=='out'else 2422
            else:at=2423 if direction=='out'else 2460
        elif window is row['ssap_subscription'][0]['leases'][1]and frame[4:]==b'\x0d\x23\x11\0\x02\0\0':at=2445
        elif window is row['ssap_subscription'][0]['leases'][1]and frame[4:]==b'\x0e\x03\x11\0\x02\0\0':at=2461 if direction=='out'else 2462
        return packet|{'wall_ns':at}
    return row,match


def terminal_hold(rows):
    phases=[];proofs=[]
    for phase,row in enumerate(rows):
        case=row['ssap_subscription'][0]['leases'][1]['inflight_release'];s=case['selection'];slot=hold_gate.check_selection(s,phase);obs=[dict(bytes=24,sha256='a'*64)]
        phases.append(dict(method=hold_gate.RELEASE_METHOD,slot=slot,selection=s,selection_sha256=hashlib.sha256((json.dumps(s)+'\n').encode()).hexdigest(),complete=True,
            physical_acceptance=False,automatic_fault_recovery_acceptance=False,observations=case['hold']['acks'],live_observations=obs,
            live_witness=dict(observations=obs,indication_tx={'fixture':1},indication_rx={'fixture':2},ack_tx={'fixture':3}),
            release_observations=obs,release_witness=dict(observations=obs,disable_tx={'fixture':4})))
        proofs.append(dict(phase=phase,slot=slot,held_kind='NOCP',host_hold=dict(status='ACTUAL_HOST_HOLD_CORROBORATED',host_transfer_sha256='b'*64,
            host_transfer_bytes=128,delivered_usb_record=20,physical_acceptance=False,automatic_fault_recovery_acceptance=False)))
    return dict(method=hold_gate.RELEASE_METHOD,qemu_sha256=hold_gate.SEQUENCE_QEMU_SHA256,complete=True,physical_acceptance=False,automatic_fault_recovery_acceptance=False,phases=phases),dict(status='TWO_ORIGINAL_SUBSCRIPTION_RELEASE_HOLDS_CORROBORATED',phases=proofs)


class InflightRelease(unittest.TestCase):
    def test_receipt_callback_cannot_restart_original_observation_deadline(self):
        import ws73_ssap_update_delivery as delivery
        from ws73_ssap_owned import observed_process,wait_text
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/'owner.stdout';err=path.with_suffix('.stderr');clock=[0.0];events=[];item={}
            # Real child text producer,not an SDK/Native/peer success stub.
            program="import sys;print('ready',flush=True);assert input()=='indicate';print('Command: indicate',flush=True);print('SdkOwnedUpdate: {\"fixture\":1}',flush=True);assert input()=='quit'"
            with observed_process([sys.executable,'-c',program],item,path,err,stdin=subprocess.PIPE,text=True)as process:
                wait_text(process,path,'^ready$',time.monotonic()+2)
                def before():
                    wait_text(process,path,r'^SdkOwnedUpdate: (.+)$',4)
                    events.append('barrier');clock[0]=6.0
                with patch.object(delivery.time,'monotonic',side_effect=lambda:clock[0]):
                    with self.assertRaises(CaptureError):delivery.command_receipt(process,item,'indicate','SdkOwnedUpdate',before_receipt=before)
                process.stdin.write('quit\n');process.stdin.flush();process.wait(timeout=2)
            self.assertEqual(events,['barrier']);self.assertEqual(item['stdout'].count('SdkOwnedUpdate:'),1)
            self.assertEqual(item['stdout'].count('Command: indicate'),1)

    def test_same_coordinator_waits_for_actual_disable_capture_before_unhold(self):
        row,_=fixture();case=row['ssap_subscription'][0]['leases'][1]['inflight_release'];s=case['selection']
        with tempfile.TemporaryDirectory()as tmp,patch.object(hold_gate,'validate_qemu',return_value=hold_gate.CURRENT_QEMU_SHA256):
            root=Path(tmp);coordinator=hold_gate.Coordinator(root,root,{},root/'qemu',purpose='subscription-release')
            folder=coordinator.root/'phase-0';folder.mkdir(parents=True);raw=(json.dumps(s)+'\n').encode();(folder/'selection.json').write_bytes(raw);(folder/'hold-release_ready.json').write_text('{}')
            child=Mock();child.phase='release_ready';child.record=dict(selection=s,selection_sha256=hashlib.sha256(raw).hexdigest());coordinator.child=child
            with patch.object(hold_gate,'release_witness',return_value=None):coordinator.poll(Mock(),Mock())
            child.poll.assert_not_called()
            with patch.object(hold_gate,'release_witness',return_value={'fixture':'actualdecodercheckedseparately'}):coordinator.poll(Mock(),Mock())
            child.poll.assert_called_once()

    def test_terminal_run_requires_new_snapshot_both_scoped_proofs_and_hold(self):
        from ws73_target import run_exit_code
        pairs=[fixture(p)for p in(0,1)];originals=[p[0]for p in pairs];hold,held_proof=terminal_hold(originals)
        proof=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8,proofs=[])
        for phase,row in enumerate(originals):
            parts=gate.corroborate(row,pairs[phase][1])[0]
            proof['proofs'].append(dict(phase=phase,ssap_subscription=parts,protected_ssap=dict(required=2,controllers=[{'fixture':0},{'fixture':1}]),ssap_values=[{'fixture':'outside this shape'}],ssap_discovery=[{'fixture':'outside this shape'}]))
        record=dict(status='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS',qemu_exit=0,supervisor_exit=0,
            ssap_subscription_requested=True,ssap_subscription_contract_version=1,ssap_subscription_acceptance=True,
            ssap_subscription_inflight_release_requested=True,ssap_subscription_inflight_release_contract_version=1,ssap_subscription_inflight_release_acceptance=True,
            ssap_subscription_inflight_hold=hold,ssap_subscription_inflight_corroboration=held_proof,
            ssap_subscription_snapshot_contract_version=1,
            ssap_subscription_supervision=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,phases=2,reader_UID=1004,provider_UID=1005,readers=10,providers=4,updates=32,
                inflight_release_contract_version=1,inflight_releases=2,replacement_leases=2,checked_replies=30,discarded_pending=2,snapshot_contract_version=1,snapshot_phases=2,snapshot_files=34,snapshot_bytes=2048,
                daemon=dict(pid=2,start_ticks=3),supervisor=dict(pid=4,start_ticks=5)),
            ordinary_channel_socket_acceptance=True,live_ssap_security_requirement=2,live_security_agent_requested='numeric-approve',
            qemu_args=['ws73.ssap_subscription=1 ws73.subscription_snapshot=1 ws73.ssap_subscription_inflight_release=1'],channel_socket_corroboration=proof,
            security_agent_corroboration=dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',phases=[dict(mode='numeric-approve',ssap_security_requirement=2)for _ in(0,1)],business_round_trips=8))
        self.assertEqual(run_exit_code(record),0)
        for change in [dict(ssap_subscription_inflight_release_requested=1),dict(ssap_subscription_inflight_release_requested=False),dict(ssap_subscription_inflight_release_contract_version=True),
                dict(ssap_subscription_inflight_release_acceptance=False),dict(ssap_subscription_inflight_hold={}),dict(ssap_subscription_inflight_corroboration={}),dict(ssap_subscription_supervision={}),dict(channel_socket_corroboration={}),
                dict(ssap_subscription_snapshot_contract_version=None),dict(qemu_args=['ws73.ssap_subscription=1 ws73.subscription_snapshot=1']),dict(ssap_subscription_owner_loss_requested=True)]:
            with self.subTest(change=change):self.assertEqual(run_exit_code(record|change),1)

    def test_finite_shape_credits_and_no_false_delivery_for_discarded_packet(self):
        rows=[]
        for phase in (0,1):
            row,match=fixture(phase);proof,credit=gate.corroborate(row,match)
            self.assertEqual(credit,{0:53,1:53});self.assertEqual([len(v['wire'])for v in proof],[63,43]);rows.append(dict(phase=phase,ssap_subscription=proof))
        summary=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows)
        self.assertTrue(gate.valid_inflight_summary(summary));self.assertFalse(gate.valid_owner_loss_summary(summary))
        for k in ('updates','application_replies','inflight_releases','discarded_pending','replacement_leases'):
            bad=copy.deepcopy(summary);bad['proofs'][0]['ssap_subscription'][0][k]+=1;self.assertFalse(gate.valid_inflight_summary(bad),k)

    def test_actual_pending_release_scope_identity_deadline_cleanup_and_transcript(self):
        for kind in ('unrequested','version','mode','pending-value','endpoint','old-token','epoch','deadline','late','early-request',
                'early-send','automatic-release','hold-error','missing-ack','discard','fake-delivery','raw','owner-store'):
            row,match=fixture();item=row['ssap_subscription'][0];lease=item['leases'][1];case=lease['inflight_release'];new=item['leases'][2]
            if kind=='unrequested':row.pop('ssap_subscription_inflight_release_required')
            elif kind=='version':row['ssap_subscription_inflight_release_contract_version']=True
            elif kind=='mode':case['mode']=1
            elif kind=='pending-value':case['value']='00'*32
            elif kind=='endpoint':case['selection']['controllers'][0]['generation']+=1
            elif kind=='old-token':new['active']['token']=lease['active']['token']
            elif kind=='epoch':new['active']['epoch']+=1
            elif kind=='deadline':case['release_started']['deadline_ns']+=1
            elif kind=='late':case['end_monotonic_ns']=case['release_started']['deadline_ns']
            elif kind=='early-request':case['release_request_wall_ns']=2422
            elif kind=='early-send':case['send']['end_wall_ns']=2440
            elif kind=='automatic-release':case['hold']['acks'][2]['state']['test-runtime-in-bounded-releases']=1
            elif kind=='hold-error':case['hold']['acks'][1]['state']['test-runtime-in-errors']=1
            elif kind=='missing-ack':case['send']['receipt']['ack']=''
            elif kind=='discard':lease['release']['discarded']=0
            elif kind=='fake-delivery':lease['messages'].append(copy.deepcopy(lease['messages'][0]))
            elif kind=='raw':lease['application']['stdout']=''
            else:case['before']['value']='00'
            with self.subTest(kind=kind),self.assertRaises((CaptureError,KeyError,ValueError)):gate.corroborate(row,match)

    def test_disable_must_be_transmitted_before_ack_returns(self):
        row,match=fixture()
        def late(owner,direction,frame,window):
            p=match(owner,direction,frame,window)
            if frame[4:]==b'\x0d\x23\x11\0\x02\0\0'and window is row['ssap_subscription'][0]['leases'][1]:p['wall_ns']=2460
            return p
        with self.assertRaises(CaptureError):gate.corroborate(row,late)

    def test_real_parser_release_witness_rejects_early_ack_wrong_handle_or_missing_tx(self):
        row,_=fixture();case=row['ssap_subscription'][0]['leases'][1]['inflight_release'];s=case['selection'];s['start_wall_ns']=10**15
        peer,server=s['controllers'];frame=b'\x0a\0\x07\0\x0d\x23\x11\0\x02\0\0'
        raw=bytearray(command_payload(peer['handle'],frame));raw[68]=0xa3
        records=[(peer['bus'],peer['device'],10**15+1000,raw,'S',1,-115),(peer['bus'],peer['device'],10**15+2000,raw,'C',1,0)]
        with tempfile.TemporaryDirectory()as tmp:
            p=Path(tmp)/'capture.pcap';p.write_bytes(pcap([]));self.assertIsNone(hold_gate.release_witness(tmp,p,s,[]))
            p.write_bytes(pcap(records));self.assertEqual(hold_gate.release_witness(tmp,p,s,[])['disable_tx']['direction'],'out')
            wrong=copy.deepcopy(s);wrong['controllers'][0]['handle']+=1;self.assertIsNone(hold_gate.release_witness(tmp,p,wrong,[]))
            ack=b'\x0a\0\x03\0\x11\x03\x01';incoming=aggregate(b'\xa3'+struct.pack('<HH',server['handle'],len(ack))+ack)
            p.write_bytes(pcap(records+[(server['bus'],server['device'],10**15+3000,incoming,'C',0x81,0)]))
            with self.assertRaises(CaptureError):hold_gate.release_witness(tmp,p,s,[])

    def test_terminal_hold_purpose_cannot_relabel_author_deadline(self):
        rows=[fixture(p)[0]for p in(0,1)];record,proof=terminal_hold(rows)
        self.assertTrue(hold_gate.valid_hold_summary(record,proof,purpose='subscription-release'))
        self.assertFalse(hold_gate.valid_hold_summary(record,proof))
        for mutate in [lambda r:r.update(method=hold_gate.METHOD),lambda r:r['phases'][0].pop('release_witness'),
                lambda r:r['phases'][0].update(release_observations=[]),lambda r:r['phases'][0]['observations'][2]['state'].update({'test-runtime-in-bounded-releases':1})]:
            bad=copy.deepcopy(record);mutate(bad);self.assertFalse(hold_gate.valid_hold_summary(bad,proof,purpose='subscription-release'))

    def test_selector_excludes_other_scenarios_and_uses_fixed_matrix(self):
        args=dict(ssap_subscription_verify=True,channel_socket_verify=True,security_agent='numeric-approve',ssap_subscription_inflight_release_verify=True)
        self.assertTrue(gate.requested(SimpleNamespace(**args),passthrough=True))
        for k in ('ssap_subscription_renewal_verify','ssap_subscription_pressure_verify','ssap_subscription_owner_loss_verify'):
            with self.assertRaises(ValueError):gate.requested(SimpleNamespace(**args,**{k:True}),passthrough=True)
        with self.assertRaises(ValueError):gate.requested(SimpleNamespace(ssap_subscription_inflight_release_verify=True),passthrough=True)
        for v in (1,None,'true'):
            with self.assertRaises(ValueError):gate.requested(SimpleNamespace(**(args|{'ssap_subscription_inflight_release_verify':v})),passthrough=True)
