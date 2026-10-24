# SPDX-License-Identifier: GPL-2.0-only
"""Finite copied metadata and actual parser/CLI tests; no Native syscall stubs.

These do not create a controller, run Root applications or prove real isolation.
The separate VM gate must obtain actual four-leaf/hold/USB/application evidence.
"""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[2]/'bindings/python')]
from test_ws73_channel_grant import fixture as grant_fixture
from ws73_channel_grant import Address, message, intent_receipt
from sparklink.structs import SleControllerSnapshot,SleManagementQuery,SleLinkSnapshot,SleSendConstraint,SleMessageSecurity
from ws73_capture import CaptureError
import ws73_channel_sibling as gate


def fixture(case='release',transition='withdrawal',primary=None):
    if primary is not None:
        outer=copy.deepcopy(primary);original=outer['channel_grant']
    elif transition=='down':
        from test_ws73_channel_link_down import fixture as primary_fixture
        outer,_=primary_fixture();original=outer['channel_grant']
    elif transition=='deadline':
        from test_ws73_channel_deadline import fixture as primary_fixture
        outer,*_=primary_fixture();original=outer['channel_grant']
    else:original,outer=grant_fixture(case)
    g={k:copy.deepcopy(original[k])for k in ['index','owners','workers','business']}
    row=dict(version=gate.CONTRACT_VERSION,case=case,transition=transition,status='SIBLING_NATIVE_BUSINESS_CONTINUITY_PASS',controller_ids=[2,3],index=0,initial_snapshots=[],usb=[],leases=[1,1],hcc_observations=[],management_before=[],management_after=[],links_before=[],links_after=[],cleanup=[],channel_grant=g)
    g.update(controller_ids=[2,3],tx_constraint_required=True,business=[])
    for n,index in enumerate((2,3)):
        snapshot=SleControllerSnapshot(version=1,flags=2,profile=1,valid_fields=1,dev_index=index,generation=7+n)
        snapshot.address[:]=bytes([1,2,3,4,5,index]);row['initial_snapshots'].append(bytes(snapshot).hex())
        usb=dict(bus=1,device=4+n);row['usb'].append(usb)
        row['hcc_observations'].append(dict(usb,index=index,generation=snapshot.generation,port=f'1-{index+1}',address=':'.join(f'{v:02X}'for v in snapshot.address)))
        owner=g['owners'][n];addr=Address.from_buffer_copy(bytes.fromhex(owner['address']));addr.controller=index;addr.generation=snapshot.generation;addr.lease=1;owner.update(index=index,generation=snapshot.generation,lease=1,address=bytes(addr).hex())
        held=SleManagementQuery(version=1,state=1,flags=1,mode=1,generation=snapshot.generation,lease=1)
        row['management_before'].append(bytes(held).hex());row['management_after'].append(bytes(held).hex())
        table=SleLinkSnapshot(version=1,generation=snapshot.generation,dev_index=index,profile=1,flags=1,count=1);table.links[0].lifetime=owner['lifetime'];table.links[0].handle=owner['handle']
        row['links_before'].append(bytes(table).hex());row['links_after'].append(bytes(table).hex())
        free=SleManagementQuery(version=1,generation=snapshot.generation,state=0)
        clean=6_750_000_000 if transition=='deadline'else 360 if transition=='down'else 120
        row['cleanup'].append(dict(controller=index,start_wall_ns=clean+10*n,end_wall_ns=clean+5+10*n,result=bytes(free).hex()))
    times=[(10,30),*([(64,67)]if case=='dup'else[]),(92,95),(111,114)]
    if transition=='down':times=[(10,30),(222,225),(262,265)]
    elif transition=='deadline':times=[(10,30),(1_350_000_000,1_400_000_000),(6_110_000_000,6_150_000_000),(6_510_000_000,6_550_000_000)]
    if case=='dup':
        outer.update(first_close_wall_ns=40,first_close_quiet_end_ns=60)
        for sample,when in zip(original['blocking_witness'],[80,90]):sample['wall_ns']=when
    for i,(label,start)in enumerate([(x,t)for x,ts in zip(gate.stage_labels(case,transition),times,strict=True)for t in ts]):
        initiator=i%2;payload=message();reply=bytearray(payload);reply[28]=1
        rowdata=dict(label=label,initiator=initiator,payload=payload.hex(),start_wall_ns=start,end_wall_ns=start+2,applications=[])
        for n,owner in enumerate(g['owners']):
            c=SleSendConstraint(version=1,size=48,controller=owner['index'],generation=owner['generation'],lifetime=owner['lifetime'],handle=owner['handle'],security_epoch=1,local_tcid=31,remote_tcid=31,pi=241,deadline_monotonic_ns=5_000_000_100)
            rx=SleMessageSecurity(version=1,size=40,controller=owner['index'],generation=owner['generation'],lifetime=owner['lifetime'],handle=owner['handle'],security_epoch=1,local_tcid=31,remote_tcid=31,pi=241,flags=3)
            rowdata['applications'].append(dict(sent=(payload if n==initiator else reply).hex(),received=(reply if n==initiator else payload).hex(),tx_intent=intent_receipt(c,100,101,102),rx_context=bytes(rx).hex()))
        g['business'].append(rowdata)
    outer.update(channel_grant=original,daemon_running=False,sibling_business=row)
    if transition!='deadline':outer['prefix_hold']={}
    return outer


def summary(case='release',transition='withdrawal'):
    outer=fixture(case,transition);r=outer['sibling_business'];g=r['channel_grant'];legs=[]
    owners=[dict(r['usb'][n],controller=o['index'],generation=o['generation'],lifetime=o['lifetime'],handle=o['handle'])for n,o in enumerate(g['owners'])]
    business=[{k:x[k]for k in ['label','initiator','payload','start_wall_ns','end_wall_ns']}for x in g['business']]
    for b in business:
        for n,owner in enumerate(owners):
            for out in(True,False):
                reply=(n!=b['initiator'])if out else(n==b['initiator']);payload=bytearray.fromhex(b['payload']);payload[28]=int(reply)
                legs.append(dict(bus=owner['bus'],device=owner['device'],handle=owner['handle'],direction='out'if out else'in',data=(b'\x1f\0\x3e\0\xf1'+payload).hex(),wall_ns=b['start_wall_ns']+1))
    proof=dict(version=gate.CONTRACT_VERSION,case=case,transition=transition,phase_bounds=gate.phase_bounds(outer),after_first_close_round_trips=2 if case=='dup'else 0,status=gate.STATUS,controllers=[2,3],owners=owners,business=business,round_trips=len(business),while_held_round_trips=2,after_withdrawal_round_trips=2 if transition=='withdrawal'else 0,after_transition_round_trips=2,after_late_reply_round_trips=2 if transition=='deadline'else 0,application_UID=1000,daemon_policy_qualified=False,credit_truth=False,full_drain=False,natural_recovery=False,management_unchanged=True,links_unchanged=True,legs=legs,heard=[{}],links=[{},{}],discovery=[{}])
    return proof


class SiblingGate(unittest.TestCase):
    def test_closed_summary_requires_each_real_wire_leg_and_original_role(self):
        proof=summary()
        self.assertTrue(gate.valid_summary(proof))
        for kind in ['missing-leg','payload','device','direction','window','role','phase','credit','daemon','count','missing-radio']:
            bad=copy.deepcopy(proof)
            if kind=='missing-leg':bad['legs'].pop()
            elif kind=='payload':bad['legs'][0]['data']='00'*66
            elif kind=='device':bad['legs'][0]['device']=99
            elif kind=='direction':bad['legs'][0]['direction']='in'
            elif kind=='window':bad['legs'][0]['wall_ns']=999
            elif kind=='role':bad['business'][0]['initiator']=True
            elif kind=='phase':bad['business'][2]['label']='after_withdrawal'
            elif kind=='credit':bad['credit_truth']=True
            elif kind=='daemon':bad['daemon_policy_qualified']=True
            elif kind=='count':bad['round_trips']=True
            else:bad['heard']=[]
            with self.subTest(kind=kind):self.assertFalse(gate.valid_summary(bad))

    def test_explicit_host_guest_and_fresh_preparation_contract(self):
        args=SimpleNamespace(command='run',managed_channel_sibling_business=True,managed_connected_case='release',managed_connected_index=0,managed_channel_grant=True,managed_channel_revoke_prefix=True,setup_release_verify=True)
        for case in ('release','close','dup'):
            selected=copy.copy(args);selected.managed_connected_case=case
            self.assertTrue(gate.requested(selected))
            self.assertTrue(gate.boot_enabled([gate.TOKEN,'ws73.channel_grant=1','ws73.channel_revoke_prefix=1','ws73.connected_case='+case,'ws73.connected_index=0']))
        for k,v in [('managed_connected_case','down'),('managed_connected_index',True),('managed_channel_grant',False),('managed_channel_revoke_prefix',False),('setup_release_verify',False),('qmp_hotplug',True),('managed_channel_queued_discard',True),('session_service_observe',True),('managed_channel_security',1),('four_device_dynamic_benchmark',True)]:
            bad=copy.copy(args);setattr(bad,k,v)
            with self.subTest(k=k),self.assertRaises(ValueError):gate.requested(bad)
        words=[gate.TOKEN,'ws73.channel_grant=1','ws73.channel_revoke_prefix=1','ws73.connected_case=release','ws73.connected_index=0']
        self.assertTrue(gate.boot_enabled(words));self.assertFalse(gate.boot_enabled([]))
        for bad in [words+[gate.TOKEN],words+['ws73.connected_case=close'],words[1:]+['ws73.channel_sibling_business=0'],words[:-1]]:
            with self.assertRaises(ValueError):gate.boot_enabled(bad)
        here=Path(gate.__file__).parent
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);tools=root/'root/usr/share/sparklink/tools';tools.mkdir(parents=True)
            names=['ws73_channel_sibling.py','ws73_native_pair.py','ws73_channel_grant.py','ws73_connected_file_gate.py','ws73_channel_prefix_hold.py','ws73_channel_link_down.py','ws73_channel_deadline.py']
            for n in names:(tools/n).write_bytes((here/n).read_bytes())
            init=root/'root/init';init.write_bytes((here/'ws73_target_init.sh').read_bytes());init.chmod(0o755)
            package=dict(channel_sibling_business_contract_version=gate.CONTRACT_VERSION,inputs=[gate.file_record(here/'ws73_target.py')])
            gate.require_preparation(package,root)
            for name in ('ws73_channel_link_down.py','ws73_channel_deadline.py'):
                staged=tools/name;original=staged.read_bytes();staged.write_bytes(original+b'\n# mismatched staged helper\n')
                with self.subTest(name=name),self.assertRaisesRegex(ValueError,'source mismatch'):
                    gate.require_preparation(package,root)
                staged.write_bytes(original)
            with self.assertRaisesRegex(ValueError,'host runner'):
                gate.require_preparation(dict(package,inputs=[]),root)
            for value in(None,True,1,2,4):
                with self.assertRaises(ValueError):gate.require_preparation(dict(channel_sibling_business_contract_version=value),root)
            init.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'executable'):gate.require_preparation(package,root)
        p=subprocess.run([sys.executable,str(here/'ws73_target.py'),'run','--help'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0);self.assertIn('--managed-channel-sibling-business',p.stdout)

    def test_actual_receipt_validator_requires_other_pair_held_and_postwithdrawal_business(self):
        outer=fixture();self.assertIs(gate.verify(outer),outer['sibling_business'])
        for kind in ['ids','epoch','link','credentials','held-order','after-order','payload','RX-context','cleanup','missing-HCC','version','constraints','nonce','missing-worker']:
            bad=copy.deepcopy(outer);r=bad['sibling_business'];g=r['channel_grant']
            if kind=='ids':g['owners'][0]['index']=0
            elif kind=='epoch':r['management_after'][0]='00'*len(bytes.fromhex(r['management_after'][0]))
            elif kind=='link':r['links_after'][0]='00'*len(bytes.fromhex(r['links_after'][0]))
            elif kind=='credentials':g['workers'][0]['credentials']['uids']=[0]*4
            elif kind=='held-order':g['business'][2]['start_wall_ns']=80
            elif kind=='after-order':g['business'][4]['start_wall_ns']=105
            elif kind=='payload':g['business'][0]['applications'][0]['sent']='00'*61
            elif kind=='RX-context':g['business'][0]['applications'][0]['rx_context']='00'*40
            elif kind=='cleanup':r['cleanup'][0]['result']=r['management_before'][0]
            elif kind=='missing-HCC':r['hcc_observations'].pop()
            elif kind=='version':r['version']=True
            elif kind=='constraints':g['tx_constraint_required']=False
            elif kind=='nonce':g['business'][2]=copy.deepcopy(g['business'][0]);g['business'][2].update(label='while_held',start_wall_ns=92,end_wall_ns=94)
            else:g['workers'].pop()
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError,KeyError,IndexError)):gate.verify(bad)

    def test_File_cases_require_exact_stages_and_dup_first_close_business(self):
        for case in ('release','close','dup'):
            outer=fixture(case)
            self.assertIs(gate.verify(outer),outer['sibling_business'])
            proof=summary(case);self.assertTrue(gate.valid_summary(proof))
            self.assertEqual(proof['round_trips'],8 if case=='dup'else 6)
            self.assertEqual(len(proof['legs']),32 if case=='dup'else 24)
            for kind in ('case','legacy-version','missing-phase','missing-leg'):
                bad=copy.deepcopy(outer);changed=copy.deepcopy(proof)
                if kind=='case':
                    bad['sibling_business']['case']='other';changed['case']='other'
                elif kind=='legacy-version':
                    bad['sibling_business']['version']=1;changed['version']=1
                elif kind=='missing-phase':
                    del bad['sibling_business']['channel_grant']['business'][2:4];del changed['business'][2:4]
                else:
                    bad['sibling_business']['channel_grant']['workers'].pop();changed['legs'].pop()
                with self.subTest(case=case,kind=kind),self.assertRaises((ValueError,KeyError)):gate.verify(bad)
                self.assertFalse(gate.valid_summary(changed))
        for field,value in [('first_close_wall_ns',31),('first_close_quiet_end_ns',65)]:
            bad=fixture('dup');bad[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(CaptureError,'first dup close'):gate.verify(bad)
        bad=fixture('dup');bad['sibling_business']['channel_grant']['business'][2]['end_wall_ns']=81
        with self.assertRaisesRegex(CaptureError,'ordered finite'):gate.verify(bad)

    def test_supervisor_binds_case_version_and_complete_dup_summary(self):
        from ws73_target import run_exit_code
        from test_ws73_prefix_geometry import reported_fixture
        from ws73_channel_prefix_hold import corroborate_geometry
        raw,capture,_,_,_=reported_fixture();geometry=corroborate_geometry(raw,capture)
        for case in ('release','close','dup'):
            proof=summary(case)
            base=dict(supervisor_exit=0,qemu_exit=0,status='REAL_CHANNEL_GRANT_PASS',
                qemu_args=[gate.TOKEN+' ws73.prefix_geometry=1'],
                channel_sibling_business_requested=True,channel_sibling_business_contract_version=gate.CONTRACT_VERSION,
                live_connected_file_case=case,live_connected_file_index=0,live_channel_grant_gate=True,
                live_channel_revoke_prefix_gate=True,managed_prefix_geometry_contract_version=1,
                channel_sibling_business_acceptance=True,
                connected_file_corroboration=dict(sibling_business=proof,prefix_geometry=geometry,
                    channel_grant=dict(status='REAL_BLOCKED_RX_GRANT_USB_CORROBORATED',
                        begun_revoke=dict(status='ACTUAL_BEGUN_PDU_WITHDRAWAL_PREFIX_PASS',no_new_submit_after_withdrawal=True,submitted_bytes=1024)),
                    held_reply=dict(status='REAL_INCOMPLETE_PDU_BARRIER_CORROBORATED')))
            self.assertEqual(run_exit_code(base),0)
            for kind in ('case','version','phase','acceptance'):
                bad=copy.deepcopy(base)
                if kind=='case':bad['live_connected_file_case']='close'if case!='close'else'release'
                elif kind=='version':bad['channel_sibling_business_contract_version']=1
                elif kind=='phase':bad['connected_file_corroboration']['sibling_business']['business'].pop()
                else:bad['channel_sibling_business_acceptance']=False
                with self.subTest(case=case,kind=kind):self.assertNotEqual(run_exit_code(bad),0)

    def test_transition_selectors_are_explicit_mutually_exclusive_and_typed(self):
        args=SimpleNamespace(command='run',managed_channel_sibling_business=True,managed_connected_case='release',managed_connected_index=0,managed_channel_grant=True,managed_channel_revoke_prefix=True,setup_release_verify=True)
        words=[gate.TOKEN,'ws73.channel_grant=1','ws73.channel_revoke_prefix=1','ws73.connected_case=release','ws73.connected_index=0']
        for transition,flag in [('down','managed_channel_link_down'),('deadline','managed_channel_deadline')]:
            selected=copy.copy(args);setattr(selected,flag,True)
            token='ws73.channel_'+('link_down'if transition=='down'else'deadline')
            self.assertTrue(gate.requested(selected));self.assertTrue(gate.boot_enabled(words+[token+'=1']))
            self.assertEqual(gate.transition_flags('release',transition=='down',transition=='deadline'),transition)
            for value in (1,None,'true'):
                bad=copy.copy(selected);setattr(bad,flag,value)
                with self.subTest(transition=transition,value=value),self.assertRaises(ValueError):gate.requested(bad)
            for case in ('close','dup'):
                bad=copy.copy(selected);bad.managed_connected_case=case
                with self.subTest(transition=transition,case=case),self.assertRaises(ValueError):gate.requested(bad)
                with self.assertRaises(ValueError):gate.boot_enabled([x.replace('case=release','case='+case)for x in words]+[token+'=1'])
            for tokens in ([token],[token+'=0'],[token+'=1',token+'=1'],['ws73.channel_link_down=1','ws73.channel_deadline=1']):
                with self.subTest(tokens=tokens),self.assertRaises(ValueError):gate.boot_enabled(words+tokens)
        args.managed_channel_link_down=args.managed_channel_deadline=True
        with self.assertRaises(ValueError):gate.requested(args)

    def test_transition_stages_compose_with_unchanged_primary_receipt_and_wire_oracles(self):
        # Both primary inputs and USB packets below are synthetic metadata.
        # Calling the real validators checks composition, not native concurrency.
        from ws73_channel_link_down import verify as down_verify,corroborate as down_wire
        from ws73_channel_deadline import verify as deadline_verify,corroborate as deadline_wire
        from test_ws73_channel_link_down import fixture as down_fixture
        from test_ws73_channel_deadline import fixture as deadline_fixture
        for transition in ('down','deadline'):
            source,*materials=down_fixture()if transition=='down'else deadline_fixture()
            outer=fixture(transition=transition,primary=source)
            primary=down_verify if transition=='down'else deadline_verify
            primary(outer);self.assertIs(gate.verify(outer),outer['sibling_business'])
            if transition=='down':down_wire(outer,*materials)
            else:deadline_wire(outer,*materials)
            proof=summary(transition=transition);self.assertTrue(gate.valid_summary(proof))
            self.assertEqual(proof['round_trips'],6 if transition=='down'else 8)
            self.assertEqual(len(proof['legs']),24 if transition=='down'else 32)
            for kind in ('missing-phase','missing-application','payload','RX-context','wrong-transition','missing-cleanup','late-held','early-after','lost-leg','duplicate-phase'):
                bad=copy.deepcopy(outer);row=bad['sibling_business'];g=row['channel_grant'];changed=copy.deepcopy(proof)
                if kind=='missing-phase':del g['business'][2:4];del changed['business'][2:4]
                elif kind=='missing-application':g['business'][2]['applications'].pop();changed['legs'].pop(8)
                elif kind=='payload':g['business'][2]['applications'][0]['sent']='00'*61;changed['legs'][8]['data']='00'*66
                elif kind=='RX-context':g['business'][2]['applications'][0]['rx_context']='00'*40;changed['owners'][0]['controller']=0
                elif kind=='wrong-transition':row['transition']='withdrawal';changed['transition']='withdrawal'
                elif kind=='missing-cleanup':row['cleanup'].pop();changed['management_unchanged']=False
                elif kind=='late-held':
                    end=gate.phase_bounds(bad)['held_end'];g['business'][3]['end_wall_ns']=end;changed['business'][3]['end_wall_ns']=end
                elif kind=='early-after':
                    start=gate.phase_bounds(bad)['after_start'];g['business'][4]['start_wall_ns']=start;changed['business'][4]['start_wall_ns']=start
                elif kind=='lost-leg':g['workers'].pop();changed['legs'].pop()
                else:g['business'][2]['label']='before_hold';changed['business'][2]['label']='before_hold'
                with self.subTest(transition=transition,kind=kind),self.assertRaises((ValueError,KeyError,IndexError)):gate.verify(bad)
                self.assertFalse(gate.valid_summary(changed),(transition,kind))
            bad=copy.deepcopy(outer)
            if transition=='down':bad['data_link_down']['old_fd']['errors']['send']=0
            else:bad['data_deadline']['blocked_result']['end_monotonic_ns']+=1_000_000_000
            with self.subTest(transition=transition),self.assertRaises(ValueError):primary(bad)

    def test_deadline_stages_remain_inside_original_timeout_and_late_reply_windows(self):
        outer=fixture(transition='deadline');proof=summary(transition='deadline')
        for kind in ('before-held-receipt','after-release','before-late-reply','after-cleanup','missing-late-stage','late-count','mixed-primary','missing-bounds'):
            bad=copy.deepcopy(outer);changed=copy.deepcopy(proof);d=bad['data_deadline'];business=bad['sibling_business']['channel_grant']['business']
            if kind=='before-held-receipt':
                when=d['ack_receipts'][1]['wall_ns'];business[2]['start_wall_ns']=when;changed['business'][2]['start_wall_ns']=when
            elif kind=='after-release':
                when=d['markers'][2]['wall_ns'];business[5]['end_wall_ns']=when;changed['business'][5]['end_wall_ns']=when
            elif kind=='before-late-reply':
                when=d['post_release_checked_wall_ns'];business[6]['start_wall_ns']=when;changed['business'][6]['start_wall_ns']=when
            elif kind=='after-cleanup':
                when=d['cleanup_before_wall_ns'];business[7]['end_wall_ns']=when;changed['business'][7]['end_wall_ns']=when
            elif kind=='missing-late-stage':del business[6:];del changed['business'][6:]
            elif kind=='late-count':
                del business[6:];changed['after_late_reply_round_trips']=0
            elif kind=='mixed-primary':bad['data_link_down']={};changed['transition']='down'
            else:del d['ack_receipts'][1]['wall_ns'];changed.pop('phase_bounds')
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError,IndexError)):gate.verify(bad)
            self.assertFalse(gate.valid_summary(changed),kind)

    def test_supervisor_requires_corresponding_primary_transition_not_file_withdrawal(self):
        from ws73_target import run_exit_code
        from test_ws73_prefix_geometry import reported_fixture
        from ws73_channel_prefix_hold import corroborate_geometry
        for transition in ('down','deadline'):
            raw,capture,_,_,_=reported_fixture(deadline=transition=='deadline')
            if transition=='down':
                raw['data_link_down']={};raw['prefix_hold']['geometry']['force_prime']=True
            geometry=corroborate_geometry(raw,capture,'data_deadline'if transition=='deadline'else'prefix_hold')
            connected=dict(sibling_business=summary(transition=transition),prefix_geometry=geometry,
                status='REAL_BEGUN_LINK_DOWN_CORROBORATED'if transition=='down'else'REAL_ORIGINAL5S_BEGUN_DEADLINE_CORROBORATED',
                submitted_bytes=1024,partial_pdu_application_round_trips=0)
            if transition=='down':connected.update(both_leases_preserved=True,prefix_hold=dict(status='REAL_INCOMPLETE_PDU_BARRIER_CORROBORATED'))
            else:connected.update(delayed_nocp_records=[42],host_hold=dict(status='ACTUAL_HOST_HOLD_CORROBORATED'))
            token='ws73.channel_link_down=1'if transition=='down'else'ws73.channel_deadline=1'
            base=dict(supervisor_exit=0,qemu_exit=0,status='REAL_CHANNEL_LINK_DOWN_PREFIX_PASS'if transition=='down'else'REAL_CHANNEL_ORIGINAL_DEADLINE_PREFIX_PASS',
                qemu_args=[gate.TOKEN+' ws73.prefix_geometry=1 '+token],channel_sibling_business_requested=True,
                channel_sibling_business_contract_version=gate.CONTRACT_VERSION,live_connected_file_case='release',live_connected_file_index=0,
                live_channel_link_down_requested=transition=='down',live_channel_deadline_requested=transition=='deadline',
                live_channel_grant_gate=True,live_channel_revoke_prefix_gate=True,managed_prefix_geometry_contract_version=1,
                channel_sibling_business_acceptance=True,connected_file_corroboration=connected)
            self.assertEqual(run_exit_code(base),0,transition)
            for kind in ('wrong-result','missing-token','wrong-request','wrong-proof','missing-original-hold','full-pdu','fake-app-reply','missing-after-stage','old-version'):
                bad=copy.deepcopy(base);p=bad['connected_file_corroboration']
                if kind=='wrong-result':bad['status']='REAL_CHANNEL_GRANT_PASS'
                elif kind=='missing-token':bad['qemu_args']=[gate.TOKEN+' ws73.prefix_geometry=1']
                elif kind=='wrong-request':bad['live_channel_link_down_requested']=bad['live_channel_deadline_requested']=True
                elif kind=='wrong-proof':p['status']='REAL_BLOCKED_RX_GRANT_USB_CORROBORATED'
                elif kind=='missing-original-hold':p.pop('prefix_hold'if transition=='down'else'host_hold')
                elif kind=='full-pdu':p['submitted_bytes']=2047
                elif kind=='fake-app-reply':p['partial_pdu_application_round_trips']=1
                elif kind=='missing-after-stage':p['sibling_business']['business'].pop()
                else:bad['channel_sibling_business_contract_version']=2
                with self.subTest(transition=transition,kind=kind):self.assertNotEqual(run_exit_code(bad),0)

    def test_dependencies_reuse_one_pair_oracle_without_circular_fixture_import(self):
        import ws73_connected_file_gate as primary
        import ws73_native_pair as common
        self.assertIs(primary.discovery_operation,common.discovery_operation)
        self.assertIs(gate.discovery_operation,common.discovery_operation)
        self.assertIs(primary.corroborate_discovery,gate.corroborate_discovery)
        self.assertIs(primary.corroborate_transition,gate.corroborate_transition)
        self.assertNotIn('from ws73_connected_file_gate import',Path(gate.__file__).read_text())

    def test_transport_failures_are_bound_to_selected_pair_and_original_window(self):
        import ws73_native_pair as common
        row=dict(usb=[dict(bus=1,device=4),dict(bus=1,device=5)])
        capture=dict(failures=[dict(bus=1,device=2,wall_ns=110,status=-2),
                              dict(bus=1,device=4,wall_ns=99,status=-2)])
        original=copy.deepcopy(capture)
        common.check_transport(row,capture,100,200)
        self.assertEqual(capture,original) # retain out-of-scope failures
        for device in (4,5):
            for when in (100,150,200):
                bad=copy.deepcopy(capture);bad['failures'].append(dict(bus=1,device=device,wall_ns=when,status=-2))
                with self.subTest(device=device,when=when),self.assertRaises(CaptureError):
                    common.check_transport(row,bad,100,200)


if __name__=='__main__':unittest.main()
