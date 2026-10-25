# SPDX-License-Identifier: GPL-2.0-only
"""Bounded evidence-oracle fixtures, not device, concurrency or formal proof."""
import copy
import errno
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE/'tools'))
sys.path.insert(0, str(SOURCE/'tools/tests'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError
from test_ws73_ssap_provider_owner_exit import fixture as retained_fixture, summary as retained_summary
from test_ws73_ssap_command_deadline import ordinary_business
import ws73_ssap_provider_deadline as gate


def fixture(phase=0):
    """Reuse established identity/pipes/SDK fixture, alter only new literal scenario."""
    row, _, old_packets = retained_fixture(phase)
    item = copy.deepcopy(row['ssap_provider_owner_exit_cases'][0])
    old_base = 1_000_000_000_000+phase*1_000_000_000_000
    shift = 100_000_000
    def shift_observations(value):
        if type(value) is int and old_base <= value < old_base+10_000_000_000:return value+shift
        if isinstance(value,dict):return {k:shift_observations(v)for k,v in value.items()}
        if isinstance(value,list):return [shift_observations(v)for v in value]
        return value
    item = shift_observations(item)
    for key in ('guard','owner_exit','kill_before_wall_ns','kill_before_monotonic_ns',
                'kill_returned_wall_ns','kill_returned_monotonic_ns','owner_exit_monotonic_ns',
                'cleanup_completed_monotonic_ns','retired_read'):
        item.pop(key, None)
    base = old_base+shift
    stamp = lambda n: base+n*1_000_000
    source, target = row['owners']; app = item['read']
    app['args'][-1] = str(errno.ETIMEDOUT)
    app.update(ssap_expected_errno=errno.ETIMEDOUT, end_wall_ns=stamp(5011), end_monotonic_ns=stamp(5011))
    call, result = map(json.loads, app['stdout'].splitlines())
    call.update(deadline_ns=call['deadline_ns']+shift,call_ns=call['call_ns']+shift)
    result.update(errno=errno.ETIMEDOUT,deadline_ns=call['deadline_ns'],returned_ns=stamp(5010)+1000)
    app['stdout'] = json.dumps(call)+'\n'+json.dumps(result)+'\n'
    item['callback']['prompt']['deadline_ns'] = stamp(5011)
    item['callback'].pop('exit_deadline_ns')
    item.update(api=app['api'],late_value='e1'*32,status=gate.PENDING,exit=0,
        provider_deadline_observed_ns=stamp(5020)+1,terminal_observation_deadline_ns=stamp(7011),
        clock_before=dict(monotonic_before_ns=stamp(9),realtime_ns=stamp(9)+100,monotonic_after_ns=stamp(9)+200),
        clock_after=dict(monotonic_before_ns=stamp(5038),realtime_ns=stamp(5038)+100,monotonic_after_ns=stamp(5038)+200),
        owner_alive_after_business_ns=stamp(5033),quit_wall_ns=stamp(5034),owner_exit_wall_ns=stamp(5035),end_wall_ns=stamp(5040))
    item['terminal'] = 'original SSAP authorization deadline'
    def terminal(begin,end):
        return dict(args=['slctl','--adapter',target['owner']['path'],'ssap-info',target['object']['path']],exit=1,
            stdout=f'Selected {target["owner"]["path"]}\n',stderr='org.freedesktop.DBus.Error.Failed: '+item['terminal'],
            start_wall_ns=stamp(begin),end_wall_ns=stamp(end),start_monotonic_ns=stamp(begin),end_monotonic_ns=stamp(end))
    item['terminal_attempts'] = [terminal(5021,5022)]
    item['terminal_after_business'] = terminal(5031,5032)
    item['late_input'] = dict(text='provide p1 '+item['late_value'],wall_ns=stamp(5023),monotonic_ns=stamp(5023),
        completed_wall_ns=stamp(5024),completed_monotonic_ns=stamp(5024))
    item['business_window'] = dict(start_wall_ns=stamp(5025),start_monotonic_ns=stamp(5025),
        end_wall_ns=stamp(5030),end_monotonic_ns=stamp(5030))
    row['ssap_receipts'][0] = dict(args=['slctl','--adapter',source['owner']['path'],'ssap-info',source['object']['path']],
        exit=0,stderr='',stdout=f'Selected {source["owner"]["path"]}\nSsapExchangeInfo: original fixture identity\n')
    item['requester_observation'] = dict(row['ssap_receipts'][0],start_wall_ns=stamp(5030)+1000,
        end_wall_ns=stamp(5031)-1000,start_monotonic_ns=stamp(5030)+1000,end_monotonic_ns=stamp(5031)-1000)
    item['requester_outcome'] = dict(state='original-negotiated-observation',physical_drain_proven=False)
    item['cleanup'].update(start_wall_ns=stamp(5036),end_wall_ns=stamp(5037))
    data = item['callback']['prompt']; lines = item['stdout'].splitlines()
    lines[-1] = lines[-1].replace('deadline_ns='+str(old_base+4900_000_000), 'deadline_ns='+str(data['deadline_ns']))
    item['stdout'] = '\n'.join(lines+[gate.REJECTED])+'\n'
    item['captured_bytes']['stdout'] = len(item['stdout'].encode())
    row['ssap_provider_owner_exit_status'] = 'PROVIDER_OWNER_EXIT_PENDING_PAIRED_USB'
    row['ssap_language_clients'] = ([step['read']for owner in row['ssap_read_provider_cases']for step in owner['steps']]
        +[row['ssap_provider_owner_exit_cases'][0]['read'],row['ssap_provider_owner_exit_guards'][0]['read'],app])
    for number,call in enumerate(row['ssap_language_clients']):call['pid']=10000+number
    row.update(rounds=4,message_bytes=61,channel_info_required=True,tx_status_required=True,
        message_security_required=True,tx_constraint_required=True,security_requirement=0,
        dtap_limits_version=1,cmtc_local_capability=dict(mtu=2042,mps=2047),application_tool={},
        applications=[dict(exit=0,start_wall_ns=stamp(5026),end_wall_ns=stamp(5029)) for _ in range(2)],
        **{gate.PREFIX+'_required':True,gate.PREFIX+'_version':1,gate.COLLECTION:[item]})
    # These two placeholders only satisfy case chronology. They are not passed
    # to verify_business and cannot qualify peer delivery. Full parent integration
    # must run the existing slktest transcript/USB-leg business validators.
    packets = shift_observations(copy.deepcopy(old_packets[:2]))
    def matched(entry,direction,frame,window):
        key = (entry['owner']['bus'],entry['owner']['device'],entry['object']['handle'],direction,frame.hex())
        found = [p for p in packets if tuple(p[k] for k in ('bus','device','handle','direction','data')) == key
                 and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
        if len(found) != 1: raise CaptureError('one exact independent fixture leg required')
        packets.remove(found[0]); return found[0]
    return row,item,matched,packets


def combined_summary():
    """Original retained proofs plus existing complete CUTC transcript/USB fixtures.

    No verifier is mocked. The original ordinary_business helper authors its
    finite test vectors and calls the real ACB reassembler. All application,
    security/constraint, TX-budget, paired-packet and ordering checks run again
    through the production deadline summary validator. Synthetic artifact hashes
    and captures cannot qualify a real binary, kernel, scheduler or device.
    """
    summary = retained_summary()
    for phase, entry in enumerate(summary['proofs']):
        row, item, matched, packets = fixture(phase)
        # This existing fixture spans roughly 100 ms. Preserve its original
        # timestamps and put later observations after it; SDK/Provider deadlines
        # and the late-input rejection are unchanged.
        clock = item['business_window']['start_wall_ns']-5_006_000_000
        legs = ordinary_business(row, clock)
        end = clock+5_106_000_000
        item['business_window'].update(end_wall_ns=end,end_monotonic_ns=end)
        for key, before, after in [('requester_observation',1000,2000),
                                   ('terminal_after_business',1_000_000,2_000_000)]:
            item[key].update(start_wall_ns=end+before,end_wall_ns=end+after,
                             start_monotonic_ns=end+before,end_monotonic_ns=end+after)
        item.update(owner_alive_after_business_ns=end+3_000_000,quit_wall_ns=end+4_000_000,
                    owner_exit_wall_ns=end+5_000_000,end_wall_ns=end+10_000_000)
        item['cleanup'].update(start_wall_ns=end+6_000_000,end_wall_ns=end+7_000_000)
        item['clock_after'] = dict(monotonic_before_ns=end+8_000_000,
                                  realtime_ns=end+8_000_100,monotonic_after_ns=end+8_000_200)
        # Retain identical prior receipt inventories, including synthetic PIDs
        # assigned by fixture(), throughout the composite summary.
        for proof, original in zip(entry['ssap_read_providers'],row['ssap_read_provider_cases'],strict=True):
            proof['case'] = copy.deepcopy(original)
        entry['ssap_provider_owner_exit'][0]['case'] = copy.deepcopy(row['ssap_provider_owner_exit_cases'][0])
        evidence, credit = gate.corroborate(row,matched,packets)
        assert not packets and credit == {0:1,1:0}
        gate.verify_business_evidence(row,evidence,legs)
        entry[gate.PREFIX] = evidence
        entry['legs'] = legs
    # ordinary_business adds the exact DLI capacity used by its TX-status
    # receipts. Give every retained observation of those fixture controllers
    # the same metadata, preserving all original identities and wire bytes.
    def controller_metadata(value):
        if isinstance(value,dict):
            if {'index','generation','bus','device','path'} <= set(value):
                value['buffers'] = [254,5,0,0]
            for child in value.values():controller_metadata(child)
        elif isinstance(value,list):
            for child in value:controller_metadata(child)
    controller_metadata(summary)
    return summary


def combined_manifest(summary):
    """Literal manifest exercising the real inherited verdict chain, not a VM."""
    return dict(ssap_provider_deadline_requested=True,ssap_provider_deadline_version=1,
        ssap_provider_deadline_acceptance=True,
        ssap_provider_deadline_verifier=dict(path=str(Path(gate.__file__).resolve()),
            sha256=hashlib.sha256(Path(gate.__file__).read_bytes()).hexdigest()),
        ssap_provider_owner_exit_requested=True,ssap_provider_owner_exit_version=1,
        ssap_provider_owner_exit_acceptance=True,ssap_read_provider_requested=True,
        ssap_read_provider_version=2,ssap_read_provider_acceptance=True,
        ssap_owned_acceptance=True,ordinary_channel_socket_acceptance=True,
        status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,
        qemu_args=['ws73.ssap_owned=1 ws73.ssap_read_provider=1 '
                   'ws73.ssap_provider_owner_exit=1 '+gate.TOKEN],
        channel_socket_corroboration=summary)


class CombinedProviderDeadlineEvidence(unittest.TestCase):
    def test_full_retained_and_business_summary_and_manifest(self):
        from ws73_ssap_provider_owner_exit import valid_summary as retained_valid
        from ws73_ssap_read_provider import valid_summary as provider_valid
        summary = combined_summary()
        self.assertTrue(retained_valid(summary))
        self.assertTrue(provider_valid(summary,version=2))
        self.assertTrue(gate.valid_summary(summary))
        self.assertTrue(gate.valid_manifest(combined_manifest(summary)))
        for phase, row in enumerate(summary['proofs']):
            proof, = row[gate.PREFIX]
            self.assertEqual(len(proof['context']['ssap_language_clients']),9)
            self.assertEqual(proof['case']['api'],('c','python')[phase])
            self.assertEqual(len(row['legs']),8)
            self.assertEqual([app['role']for app in proof['context']['applications']],['initiator','peer'])
            self.assertFalse(proof['same_actor_recovery'])
            self.assertFalse(proof['case']['requester_outcome']['physical_drain_proven'])

    def test_business_requires_actual_peer_transcript_permissions_and_contracts(self):
        original = combined_summary()
        self.assertTrue(gate.valid_summary(original))
        for mutation in ('missing_peer','missing_reply','wrong_payload','failed_peer','root_peer',
                         'capability','wrong_argv','bad_artifact_hash','missing_channel_copy',
                         'wrong_tx_capacity','missing_security','changed_security_identity',
                         'missing_constraint','changed_constraint_epoch','before_business_window'):
            summary = copy.deepcopy(original); proof = summary['proofs'][0][gate.PREFIX][0]
            context,case = proof['context'],proof['case']; peer = context['applications'][1]
            if mutation=='missing_peer':context['applications'].pop()
            elif mutation=='missing_reply':peer['stdout']=peer['stdout'].replace('NativeChannelReply:','MissingReply:')
            elif mutation=='wrong_payload':peer['stdout']=peer['stdout'].replace('bytes=534c4b','bytes=004c4b',1)
            elif mutation=='failed_peer':peer['exit']=1
            elif mutation=='root_peer':peer['credentials']['uids']=[0]*4
            elif mutation=='capability':peer['credentials']['capabilities']['CapEff']='1'
            elif mutation=='wrong_argv':peer['args'][2]='/wrong-controller'
            elif mutation=='bad_artifact_hash':context['application_tool']['sha256']='not-a-sha256'
            elif mutation=='missing_channel_copy':peer['stdout']=peer['stdout'].replace('NativeChannelInfoCopy:','MissingCopy:')
            elif mutation=='wrong_tx_capacity':peer['stdout']=peer['stdout'].replace('capacity=5','capacity=6')
            elif mutation=='missing_security':peer['stdout']=peer['stdout'].replace('NativeMessageSecurity:','MissingSecurity:')
            elif mutation=='changed_security_identity':peer['stdout']=peer['stdout'].replace('epoch=42 flags=3','epoch=43 flags=3',1)
            elif mutation=='missing_constraint':peer['stdout']=peer['stdout'].replace('NativeConstrainedReply:','MissingConstraint:')
            elif mutation=='changed_constraint_epoch':peer['stdout']=peer['stdout'].replace('NativeConstrainedReply: sequence=0 epoch=42','NativeConstrainedReply: sequence=0 epoch=43')
            else:peer['start_wall_ns']=case['business_window']['start_wall_ns']-1
            with self.subTest(mutation=mutation):
                self.assertFalse(gate.valid_summary(summary))
                self.assertFalse(gate.valid_manifest(combined_manifest(summary)))

    def test_business_requires_complete_corresponding_usb_pairs_and_order(self):
        original = combined_summary()
        self.assertTrue(gate.valid_summary(original))
        for mutation in ('missing_leg','wrong_payload','wrong_handle','foreign_controller',
                         'wrong_direction','outside_window','rx_before_tx','out_of_order'):
            summary = copy.deepcopy(original); row = summary['proofs'][0]
            if mutation=='missing_leg':row['legs'].pop()
            elif mutation=='out_of_order':row['legs'][0],row['legs'][1]=row['legs'][1],row['legs'][0]
            else:
                packet=row['legs'][0]['rx']
                if mutation=='wrong_payload':
                    raw=bytearray.fromhex(packet['data']);raw[-1]^=1;packet['data']=raw.hex()
                    packet['fragments'][0]['data']=packet['data']
                elif mutation in ('wrong_handle','foreign_controller','wrong_direction'):
                    field,value={'wrong_handle':('handle',99),'foreign_controller':('device',99),
                                 'wrong_direction':('direction','out')}[mutation]
                    for fragment in [packet,*packet['fragments']]:fragment[field]=value
                else:
                    stamp=(row[gate.PREFIX][0]['case']['business_window']['end_wall_ns']+1
                           if mutation=='outside_window'else row['legs'][0]['tx']['wall_ns']-1)
                    packet['wall_ns']=stamp
                    for fragment in packet['fragments']:fragment['wall_ns']=stamp
            with self.subTest(mutation=mutation):
                self.assertFalse(gate.valid_summary(summary))
                self.assertFalse(gate.valid_manifest(combined_manifest(summary)))

    def test_summary_retains_original_gates_exact_context_and_limited_scope(self):
        original = combined_summary()
        self.assertTrue(gate.valid_summary(original))
        for mutation in ('missing_phase','missing_deadline','owner_exit_wire','provider_wire',
                         'wrong_version','wrong_api','wrong_generation','wrong_sdk_inventory',
                         'changed_sdk_receipt','unbounded_absence','same_actor_recovery','automatic_recovery'):
            summary=copy.deepcopy(original);row=summary['proofs'][0];proof=row[gate.PREFIX][0]
            if mutation=='missing_phase':summary['proofs'].pop()
            elif mutation=='missing_deadline':del row[gate.PREFIX]
            elif mutation=='owner_exit_wire':row['ssap_provider_owner_exit'][0]['wire'].pop()
            elif mutation=='provider_wire':row['ssap_read_providers'][0]['wire'].pop()
            elif mutation=='wrong_version':proof['version']=True
            elif mutation=='wrong_api':proof['case']['api']='python'
            elif mutation=='wrong_generation':proof['context']['owners'][0]['owner']['generation']+=1
            elif mutation=='wrong_sdk_inventory':proof['context']['ssap_language_clients'].pop()
            elif mutation=='changed_sdk_receipt':proof['sdk']['returned_ns']+=1
            elif mutation=='unbounded_absence':proof['bounded_absence_only']=False
            elif mutation=='same_actor_recovery':proof['same_actor_recovery']=True
            else:proof['automatic_recovery_qualification']=True
            with self.subTest(mutation=mutation):
                self.assertFalse(gate.valid_summary(summary))
                self.assertFalse(gate.valid_manifest(combined_manifest(summary)))

    def test_manifest_cannot_drop_gate_or_upgrade_failed_incomplete_execution(self):
        record=combined_manifest(combined_summary())
        self.assertTrue(gate.valid_manifest(record))
        for key,value in [('ssap_provider_deadline_requested',False),('ssap_provider_deadline_version',True),
                          ('ssap_provider_deadline_acceptance',False),('ssap_provider_owner_exit_requested',False),
                          ('ssap_provider_owner_exit_acceptance',False),('ssap_provider_owner_exit_version',2),
                          ('ssap_read_provider_acceptance',False),('ssap_read_provider_version',1),
                          ('ssap_owned_acceptance',False),('ordinary_channel_socket_acceptance',False),
                          ('qemu_exit',1),('qemu_exit',True),('status','FAIL')]:
            changed=copy.deepcopy(record);changed[key]=value
            with self.subTest(key=key,value=value):self.assertFalse(gate.valid_manifest(changed))
        for mutation in ('missing_verifier','wrong_verifier_name','invalid_hash','missing_boot',
                         'duplicate_boot','missing_owner_dependency','missing_summary'):
            changed=copy.deepcopy(record)
            if mutation=='missing_verifier':del changed[gate.PREFIX+'_verifier']
            elif mutation=='wrong_verifier_name':changed[gate.PREFIX+'_verifier']['path']='/fixture/old-verifier.py'
            elif mutation=='invalid_hash':changed[gate.PREFIX+'_verifier']['sha256']='invalid-sha256'
            elif mutation=='missing_boot':changed['qemu_args'][0]=changed['qemu_args'][0].replace(gate.TOKEN,'')
            elif mutation=='duplicate_boot':changed['qemu_args'][0]+=' '+gate.TOKEN
            elif mutation=='missing_owner_dependency':changed['qemu_args'][0]=changed['qemu_args'][0].replace('ws73.ssap_provider_owner_exit=1','')
            else:del changed['channel_socket_corroboration']
            with self.subTest(mutation=mutation):self.assertFalse(gate.valid_manifest(changed))

    def test_inventory_copies_bind_to_the_retained_original_proofs(self):
        original = combined_summary()
        self.assertTrue(gate.valid_summary(original))
        for mutation in ('provider','owner_exit','owner_exit_guard'):
            summary=copy.deepcopy(original);context=summary['proofs'][0][gate.PREFIX][0]['context']
            # Alter all matching copies inside the new deadline context. An
            # internal equality check alone must not substitute these records
            # for the separately validated original Provider/Owner-exit proof.
            if mutation=='provider':
                calls=[context['ssap_language_clients'][0],
                       context['ssap_read_provider_cases'][0]['steps'][0]['read']]
            elif mutation=='owner_exit':
                calls=[context['ssap_language_clients'][6],
                       context['ssap_provider_owner_exit_cases'][0]['read']]
            else:
                calls=[context['ssap_language_clients'][7],
                       context['ssap_provider_owner_exit_cases'][0]['guard']['read'],
                       context['ssap_provider_owner_exit_guards'][0]['read']]
            for call in calls:call['stdout']='not the original retained SDK receipt\n'
            with self.subTest(mutation=mutation):
                self.assertFalse(gate.valid_summary(summary))
                self.assertFalse(gate.valid_manifest(combined_manifest(summary)))

class ProviderDeadlineDraft(unittest.TestCase):
    def test_opt_in_and_destructive_exclusions(self):
        values=dict(ssap_provider_deadline_verify=True,ssap_provider_owner_exit_verify=True,ssap_read_provider_verify=True,ssap_owned_verify=True,
                    channel_socket_verify=True,channel_socket_rounds=4,channel_socket_bytes=61,passthrough=True)
        self.assertTrue(gate.requested(SimpleNamespace(**values)))
        self.assertFalse(gate.requested(SimpleNamespace()))
        for key,value in [('ssap_provider_deadline_verify',1),('ssap_read_provider_verify',False),
                          ('ssap_owned_verify',False),('ssap_provider_owner_exit_verify',False),('channel_socket_bytes',62),('passthrough',False),
                          *[(name,True)for name in gate.DESTRUCTIVE]]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                gate.requested(SimpleNamespace(**dict(values,**{key:value})))
        tokens=[gate.TOKEN,'ws73.ssap_provider_owner_exit=1','ws73.ssap_read_provider=1','ws73.ssap_owned=1']
        self.assertTrue(gate.boot_requested(tokens))
        for tokens in ([gate.TOKEN],tokens+[gate.TOKEN],['ws73.ssap_provider_deadline=0'],[1]):
            with self.subTest(tokens=tokens),self.assertRaises(ValueError):gate.boot_requested(tokens)

    def test_two_literal_roles_timeout_request_pair_only(self):
        physical=[]
        for phase in (0,1):
            row,item,matched,packets=fixture(phase)
            proof,credit=gate.corroborate(row,matched,packets)
            self.assertEqual(credit,{0:1,1:0});self.assertFalse(packets)
            self.assertEqual(item['api'],('c','python')[phase])
            self.assertEqual(proof[0]['sdk']['errno'],errno.ETIMEDOUT)
            self.assertFalse(proof[0]['same_actor_recovery'])
            physical.append(row['owners'][1]['owner']['index'])
        self.assertEqual(physical,[1,0])

    def test_sdk_early_return_is_not_original_deadline_reached(self):
        row,item,matched,packets=fixture()
        call,result=map(json.loads,item['read']['stdout'].splitlines())
        result['returned_ns']=call['deadline_ns']-1
        item['read']['stdout']=json.dumps(call)+'\n'+json.dumps(result)+'\n'
        with self.assertRaisesRegex(CaptureError,'original deadlines'):gate.corroborate(row,matched,packets)

    def test_provider_deadline_is_not_sdk_deadline(self):
        row,item,matched,packets=fixture()
        item['late_input']['monotonic_ns']=item['read']['ssap_error_deadline_ns']+1
        with self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)

    def test_late_answer_and_no_result_contract(self):
        for mutation in ('result','missing_rejection','duplicate_rejection','wrong_token','stored_value','wrong_prompt'):
            row,item,matched,packets=fixture()
            if mutation=='result':item['stdout']+='SsapReadProviderResult: request=9 property=17 status=0 bytes=32; application response only\n'
            elif mutation=='missing_rejection':item['stdout']=item['stdout'].replace(gate.REJECTED+'\n','')
            elif mutation=='duplicate_rejection':item['stdout']+=gate.REJECTED+'\n'
            elif mutation=='wrong_token':item['late_input']['text']=item['late_input']['text'].replace('p1 ','p2 ')
            elif mutation=='stored_value':item['late_value']=item['secret']
            else:item['callback']['prompt']['lifetime']+=1
            item['captured_bytes']['stdout']=len(item['stdout'].encode())
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)

    def test_exact_actor_terminal_not_arbitrary_error(self):
        for mutation in ('timeout','permission','success','revived','changed_target'):
            row,item,matched,packets=fixture();receipt=item['terminal_attempts'][-1]
            if mutation=='timeout':receipt['stderr']='RPC timed out'
            elif mutation=='permission':receipt['stderr']='org.freedesktop.DBus.Error.AccessDenied'
            elif mutation=='success':receipt.update(exit=0,stdout='SsapExchangeInfo: fabricated\n')
            elif mutation=='revived':item['terminal_after_business'].update(exit=0,stderr='')
            else:receipt['args'][2]='/wrong-controller'
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)

    def test_requester_can_be_original_snapshot_or_deadline_terminal(self):
        row,item,matched,packets=fixture()
        original=item['requester_observation']
        original.update(exit=1,stdout=f'Selected {row["owners"][0]["owner"]["path"]}\n',
            stderr='org.freedesktop.DBus.Error.Failed: original SSAP obligation deadline')
        item['requester_outcome']=dict(state='original-deadline-terminal',reason='original SSAP obligation deadline',physical_drain_proven=False)
        gate.corroborate(row,matched,packets)
        for mutation in ('wrong_identity','rpc_error','different_snapshot','drain_claim'):
            row,item,matched,packets=fixture();observation=item['requester_observation']
            if mutation=='wrong_identity':observation['args']=list(observation['args']);observation['args'][-1]='/other/lifetime'
            elif mutation=='rpc_error':observation.update(exit=1,stderr='RPC transport timeout')
            elif mutation=='different_snapshot':observation['stdout']+='changed\n'
            else:item['requester_outcome']['physical_drain_proven']=True
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)

    def test_original_bounded_observation_and_business(self):
        for mutation in ('renew','overrun','too_many','business_before_terminal','source_healthy_not_required'):
            row,item,matched,packets=fixture()
            if mutation=='renew':item['terminal_observation_deadline_ns']+=1
            elif mutation=='overrun':item['terminal_attempts'][-1]['end_monotonic_ns']=item['terminal_observation_deadline_ns']+1
            elif mutation=='too_many':item['terminal_attempts']*=17
            elif mutation=='business_before_terminal':item['business_window']['start_monotonic_ns']=item['read']['start_monotonic_ns']
            else:
                self.assertNotIn('source_info',item)
                gate.corroborate(row,matched,packets);continue
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)

    def test_actual_owner_cleanup_and_complete_output(self):
        for mutation in ('owner_killed','cleanup_failed','service_retained','output_incomplete','wrong_selected'):
            row,item,matched,packets=fixture()
            if mutation=='owner_killed':item['exit']=-9
            elif mutation=='cleanup_failed':item['cleanup']['exit']=1
            elif mutation=='service_retained':item['cleanup']['stdout']='SsapLocalServices: [[16]]\n'
            elif mutation=='output_incomplete':item['output_collection']['complete']=False
            else:
                item['stdout']=item['stdout'].replace('Selected /a1','Selected /wrong',1)
                item['captured_bytes']['stdout']=len(item['stdout'].encode())
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)

    def test_missing_conflicting_and_inverted_clock(self):
        for mutation in ('missing','conflict','inverted','wrong_scope'):
            row,item,matched,packets=fixture()
            if mutation=='missing':del item['clock_after']
            elif mutation=='conflict':item['clock_after']['realtime_ns']+=10000
            elif mutation=='inverted':item['clock_before']['monotonic_before_ns']=item['clock_before']['monotonic_after_ns']+1
            else:item['clock_contract']['domain']='host-guest-assumed'
            with self.subTest(mutation=mutation),self.assertRaises((CaptureError,KeyError)):
                gate.corroborate(row,matched,packets)

    def test_request_late_or_ambiguous_relative_to_provider_prompt(self):
        for delta in (-1000,1000):
            row,item,matched,packets=fixture()
            last=packets[1];last['wall_ns']=item['callback']['observed_wall_ns']+delta
            for fragment in last['fragments']:fragment['wall_ns']=last['wall_ns']
            with self.subTest(delta=delta),self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)

    def test_request_before_actual_sdk_call(self):
        row,item,matched,packets=fixture()
        original=json.loads(item['read']['stdout'].splitlines()[0])['call_ns']
        for packet in packets:
            packet['wall_ns']=original-1000
            for fragment in packet['fragments']:fragment['wall_ns']=packet['wall_ns']
        with self.assertRaisesRegex(CaptureError,'follow actual SDK call'):gate.corroborate(row,matched,packets)

    def test_exact_sdk_inventory_and_staging_order(self):
        for mutation in ('missing','duplicate_pid','unlisted_call','order','too_early'):
            row,item,matched,packets=fixture()
            if mutation=='missing':row['ssap_language_clients'].pop()
            elif mutation=='duplicate_pid':item['read']['pid']=row['ssap_language_clients'][0]['pid']
            elif mutation=='unlisted_call':row['ssap_language_clients'].append(copy.deepcopy(item['read']))
            elif mutation=='order':row['ssap_language_clients'][0],row['ssap_language_clients'][1]=row['ssap_language_clients'][1],row['ssap_language_clients'][0]
            else:row['ssap_read_provider_cases'][-1]['end_wall_ns']=item['start_wall_ns']+1
            with self.subTest(mutation=mutation),self.assertRaisesRegex(CaptureError,'inventory'):
                gate.corroborate(row,matched,packets)

    def test_extra_response_duplicate_or_missing_endpoint(self):
        for mutation in ('response','duplicate','missing_rx','late_response'):
            row,item,matched,packets=fixture()
            if mutation=='missing_rx':packets.pop()
            else:
                extra=copy.deepcopy(packets[1]);extra['record']=99
                if mutation!='duplicate':
                    extra.update(direction='out',data='0a000400090baf00')
                    extra['fragments']=[{k:v for k,v in extra.items()if k!='fragments'}]
                if mutation=='late_response':
                    extra['wall_ns']=item['late_input']['completed_wall_ns']+10000
                    for fragment in extra['fragments']:fragment['wall_ns']=extra['wall_ns']
                packets.append(extra)
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)


if __name__ == '__main__':
    unittest.main()
