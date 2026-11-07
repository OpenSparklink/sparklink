# SPDX-License-Identifier: GPL-2.0-only
"""Explicit synthetic receipts/trace association, not running-kernel or RF proof."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ws73_session_service import fixture, BASE, WALL
from ws73_session_service import parse, queued_lifecycle, valid_queued_summary, join
from ws73_channel_grant import queued_admissions, verify_intents
from sparklink.structs import SleChannelTxStatus, SleSendConstraint


def intent(before):
    c=SleSendConstraint(version=1,size=48,controller=0,generation=1,lifetime=1,
        handle=0,local_tcid=31,remote_tcid=31,pi=241,security_epoch=1,
        deadline_monotonic_ns=before+5_000_000_000)
    return dict(constraint=bytes(c).hex(),before_monotonic_ns=before,
                prepared_monotonic_ns=before+100,after_monotonic_ns=before+500)


def queued_fixture():
    text,row,owners,cap=fixture();parsed=parse(text,row)
    for v in parsed['rows']:
        if v['ctl']!=0:continue
        if v['event']=='queue':v['bytes']=2047
        elif v['event']=='tx':v.update(pb=1,len=254)
        elif v['event']=='work'and v['stage']==1:v['bytes']=254
    cap['acb_packets'][0].update(boundary=1,data='00'*254)
    for seq,delta in [(2,60_000),(3,70_000)]:
        for stage,time in [(0,delta),(3,180_000+seq*10_000)]:
            parsed['rows'].append(dict(event='queue',ctl=0,gen=1,life=1,epoch=4,
                sequence=seq,slot=0,bytes=2047,deadline=5042,stage=stage,mono_ns=BASE+time))
    tx=SleChannelTxStatus(version=1,size=64,controller=0,generation=1,lifetime=1,
        handle=0,packet_maximum=254,capacity=5,outstanding=5,connection_debt=5,
        queued=2,queue_limit=8,busy=1,active_pdu_bytes=2047,active_pdu_offset=1270,flags=3)
    armed=dict(admission_before_monotonic_ns=BASE+49_000,admission_after_monotonic_ns=BASE+51_000,
        admission_before_wall_ns=WALL+BASE+49_000,admission_after_wall_ns=WALL+BASE+51_000,
        monotonic_ns=BASE+300_000,wall_ns=WALL+BASE+300_000,
        pre_block_tx_status=bytes(tx).hex(),tx_intent=intent(BASE+49_500),queued=[])
    for n,delta in enumerate([60_000,70_000]):
        armed['queued'].append(dict(payload=(b'SLKQUE01'+bytes([n])*2034).hex(),
            before_monotonic_ns=BASE+delta-1_000,after_monotonic_ns=BASE+delta+1_000,
            before_wall_ns=WALL+BASE+delta-1_000,after_wall_ns=WALL+BASE+delta+1_000,
            tx_intent=intent(BASE+delta-500)))
    g=dict(queued_discard_contract_version=1,queue_boot_id='11111111-2222-3333-4444-555555555555',armed=armed,revoke_prefix={},business=[],
        owners=[dict(index=i,generation=i+1,lifetime=1,handle=0,lease=4)for i in range(2)])
    record=dict(index=0,case='release',usb=[dict(bus=1,device=n+2)for n in range(2)],channel_grant=g)
    return record,parsed,cap


class QueuedLifecycle(unittest.TestCase):
    def test_actual_join_keeps_begun_operation_and_two_unsubmitted_terminals_separate(self):
        record,p,cap=queued_fixture();proof=queued_lifecycle(record,p,cap)
        self.assertTrue(valid_queued_summary(proof));self.assertEqual(proof['queued_discarded_operations'],2)
        self.assertEqual(proof['queued_accepted_usb_packets'],0);self.assertEqual(proof['begun_sequence'],1)
        self.assertEqual([v['sequence']for v in proof['admissions']],[2,3])
        joined=join(p,{(0,1,1):dict(bus=1,device=2,handle=0,epoch=4),(1,2,1):dict(bus=1,device=3,handle=0,epoch=4)},cap)
        # The legacy counter includes every not-fully-submitted operation:
        # one begun prefix and two explicitly unsubmitted queued discards.
        self.assertEqual(joined['partial_retired_operations'],3)
        self.assertEqual(joined['queued_discarded_operations'],2)

    def test_receipt_profile_requires_queue_snapshot_and_original_order(self):
        record,p,cap=queued_fixture();original=record['channel_grant'];self.assertEqual(len(queued_admissions(original)),2)
        self.assertEqual(queued_admissions({}),[])
        for kind in ['version','boot','count','duplicate-payload','length','marker','time','float-time','queued-count','limit','not-busy']:
            g=copy.deepcopy(original);a=g['armed'];tx=SleChannelTxStatus.from_buffer_copy(bytes.fromhex(a['pre_block_tx_status']))
            if kind=='version':g['queued_discard_contract_version']=True
            elif kind=='boot':g['queue_boot_id']='invalid'
            elif kind=='count':a['queued'].pop()
            elif kind=='duplicate-payload':a['queued'][1]['payload']=a['queued'][0]['payload']
            elif kind=='length':a['queued'][0]['payload']='00'
            elif kind=='marker':a['queued'][0]['payload']='00'*2042
            elif kind=='time':a['queued'][0]['before_monotonic_ns']=a['admission_before_monotonic_ns']
            elif kind=='float-time':a['queued'][0]['before_monotonic_ns']=float(a['queued'][0]['before_monotonic_ns'])
            elif kind=='queued-count':tx.queued=1
            elif kind=='limit':tx.queue_limit=16
            else:tx.busy=0
            a['pre_block_tx_status']=bytes(tx).hex()
            with self.subTest(kind=kind),self.assertRaises(ValueError):queued_admissions(g)

    def test_actual_association_rejects_wrong_identity_window_terminal_or_physical_prefix(self):
        record,p,cap=queued_fixture()
        for kind in ['wrong-generation','wrong-epoch','missing-admission','missing-terminal','duplicate-terminal','sent-prefix','ambiguous-window','wrong-bytes','wrong-intent']:
            r,a,b=copy.deepcopy((record,p,cap));target=next(v for v in a['rows']if v['event']=='queue'and v['sequence']==2 and v['stage']==3)
            if kind=='wrong-generation':target['gen']=2
            elif kind=='wrong-epoch':target['epoch']=5
            elif kind=='missing-admission':a['rows'].remove(next(v for v in a['rows']if v['event']=='queue'and v['sequence']==2 and v['stage']==0))
            elif kind=='missing-terminal':a['rows'].remove(target)
            elif kind=='duplicate-terminal':a['rows'].append(copy.deepcopy(target))
            elif kind=='sent-prefix':
                # Move the accepted physical attempt from the begun PDU onto
                # queued ID2; the common production-trace association rejects it.
                for v in a['rows']:
                    if v['ctl']==0 and v['event']=='tx':v['sequence']=2
            elif kind=='ambiguous-window':r['channel_grant']['armed']['queued'][1]['before_monotonic_ns']=BASE+59_000
            elif kind=='wrong-bytes':target['bytes']=2046
            else:
                entry=r['channel_grant']['armed']['queued'][0];c=SleSendConstraint.from_buffer_copy(bytes.fromhex(entry['tx_intent']['constraint']));c.lifetime=2;entry['tx_intent']['constraint']=bytes(c).hex()
            with self.subTest(kind=kind),self.assertRaises(ValueError):queued_lifecycle(r,a,b)

    def test_queued_admissions_do_not_replace_cached_begun_retry(self):
        record,p,cap=queued_fixture();g=record['channel_grant'];original=g['armed']['tx_intent']['constraint']
        denied=dict(errors=dict(send=13,recv=13),tx_intent_denial=dict(constraint=original,errors=dict(prepare=13,submit=13),calls={k+'_monotonic_ns':BASE+500_000+n for n,k in enumerate(['prepare_before','prepare_after','submit_before','submit_after'])}))
        g['after_withdrawal']=denied;verify_intents(g,record)
        denied['tx_intent_denial']['constraint']=g['armed']['queued'][1]['tx_intent']['constraint']
        with self.assertRaisesRegex(ValueError,'original admitted intent unchanged'):verify_intents(g,record)

    def test_finalizer_requires_explicit_matching_profile_and_does_not_replace_original_gate(self):
        from ws73_target import run_exit_code
        record,p,cap=queued_fixture();queued=queued_lifecycle(record,p,cap)
        good=dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,
            session_service_observation_requested=True,session_service_acceptance=True,
            session_service_observation=dict(status='REAL_SESSION_SERVICE_AND_USB_SUBMITS_CORROBORATED',services=2,attempts=2,accepted_usb_packets=2,operations=4,queued_discarded_operations=2,queued_discard_lifecycle=queued),
            queued_discard_contract_version=1,qemu_args=['ws73.channel_queued_discard=1'],
            live_channel_grant_gate=True,live_channel_revoke_prefix_gate=True,live_connected_file_case='release',live_connected_file_index=0)
        self.assertEqual(run_exit_code(good),0)
        for kind in ['old-boot','missing-profile','bool-version','missing-proof','wrong-mode','wrong-controller','overstated-USB','sibling-discard','zero-identity','wrong-hash-type','same-ID','original-FAIL']:
            bad=copy.deepcopy(good);v=bad['session_service_observation']['queued_discard_lifecycle']
            if kind=='old-boot':bad['qemu_args']=[]
            elif kind=='missing-profile':bad.pop('queued_discard_contract_version')
            elif kind=='bool-version':bad['queued_discard_contract_version']=True
            elif kind=='missing-proof':bad['session_service_observation'].pop('queued_discard_lifecycle')
            elif kind=='wrong-mode':v['mode']='close'
            elif kind=='wrong-controller':v['controller']=1
            elif kind=='overstated-USB':v['queued_accepted_usb_packets']=1
            elif kind=='sibling-discard':v['sibling_discarded_operations']=1
            elif kind=='zero-identity':v['lifetime']=0
            elif kind=='wrong-hash-type':v['admissions'][0]['payload_sha256']=False
            elif kind=='same-ID':v['admissions'][1]['sequence']=v['admissions'][0]['sequence']
            else:bad['status']='FAIL'
            with self.subTest(kind=kind):self.assertEqual(run_exit_code(bad),1)

    def test_invalid_profile_rejected_before_preparation_or_device_access(self):
        import tempfile
        import ws73_target
        for fields in [dict(),dict(managed_channel_grant=True,managed_channel_revoke_prefix=True,managed_connected_case='release'),dict(session_service_observe=True)]:
            with tempfile.TemporaryDirectory()as folder:
                args=SimpleNamespace(command='run',output=Path(folder)/'absent',managed_channel_queued_discard=True,**fields)
                with patch.object(ws73_target,'ordinary_identity'),patch.object(ws73_target,'prepared')as prepare,self.assertRaisesRegex(ValueError,'queued discard'):
                    ws73_target._run(args)
                prepare.assert_not_called();self.assertFalse(args.output.exists())
