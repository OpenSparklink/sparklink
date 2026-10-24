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


def fixture():
    original,outer=grant_fixture();g={k:copy.deepcopy(original[k])for k in ['index','owners','workers','business']}
    row=dict(version=1,status='SIBLING_NATIVE_BUSINESS_CONTINUITY_PASS',controller_ids=[2,3],index=0,initial_snapshots=[],usb=[],leases=[1,1],hcc_observations=[],management_before=[],management_after=[],links_before=[],links_after=[],cleanup=[],channel_grant=g)
    g.update(controller_ids=[2,3],tx_constraint_required=True,business=[])
    for n,index in enumerate((2,3)):
        snapshot=SleControllerSnapshot(version=1,flags=2,profile=1,valid_fields=1,dev_index=index,generation=7+n)
        snapshot.address[:]=bytes([1,2,3,4,5,index]);row['initial_snapshots'].append(bytes(snapshot).hex())
        usb=dict(bus=1,device=4+n);row['usb'].append(usb)
        row['hcc_observations'].append(dict(usb,index=index,generation=snapshot.generation,port=f'1-{index+1}',address=':'.join(f'{v:02X}'for v in snapshot.address)))
        owner=g['owners'][n];addr=Address.from_buffer_copy(bytes.fromhex(owner['address']));addr.controller=index;owner.update(index=index,address=bytes(addr).hex())
        held=SleManagementQuery(version=1,state=1,flags=1,mode=1,generation=snapshot.generation,lease=1)
        row['management_before'].append(bytes(held).hex());row['management_after'].append(bytes(held).hex())
        table=SleLinkSnapshot(version=1,generation=snapshot.generation,dev_index=index,profile=1,flags=1,count=1);table.links[0].lifetime=owner['lifetime'];table.links[0].handle=owner['handle']
        row['links_before'].append(bytes(table).hex());row['links_after'].append(bytes(table).hex())
        free=SleManagementQuery(version=1,generation=snapshot.generation,state=0)
        row['cleanup'].append(dict(controller=index,start_wall_ns=120+10*n,end_wall_ns=125+10*n,result=bytes(free).hex()))
    for i,(label,start)in enumerate([(x,t)for x,ts in zip(gate.LABELS,[(10,30),(92,95),(111,114)])for t in ts]):
        initiator=i%2;payload=message();reply=bytearray(payload);reply[28]=1
        rowdata=dict(label=label,initiator=initiator,payload=payload.hex(),start_wall_ns=start,end_wall_ns=start+2,applications=[])
        for n,owner in enumerate(g['owners']):
            c=SleSendConstraint(version=1,size=48,controller=owner['index'],generation=owner['generation'],lifetime=owner['lifetime'],handle=owner['handle'],security_epoch=1,local_tcid=31,remote_tcid=31,pi=241,deadline_monotonic_ns=5_000_000_100)
            rx=SleMessageSecurity(version=1,size=40,controller=owner['index'],generation=owner['generation'],lifetime=owner['lifetime'],handle=owner['handle'],security_epoch=1,local_tcid=31,remote_tcid=31,pi=241,flags=3)
            rowdata['applications'].append(dict(sent=(payload if n==initiator else reply).hex(),received=(reply if n==initiator else payload).hex(),tx_intent=intent_receipt(c,100,101,102),rx_context=bytes(rx).hex()))
        g['business'].append(rowdata)
    outer.update(channel_grant=original,daemon_running=False,prefix_hold={},sibling_business=row)
    return outer


class SiblingGate(unittest.TestCase):
    def test_closed_summary_requires_each_real_wire_leg_and_original_role(self):
        outer=fixture();r=outer['sibling_business'];g=r['channel_grant'];legs=[]
        owners=[dict(r['usb'][n],controller=o['index'],generation=o['generation'],lifetime=o['lifetime'],handle=o['handle'])for n,o in enumerate(g['owners'])]
        business=[{k:x[k]for k in ['label','initiator','payload','start_wall_ns','end_wall_ns']}for x in g['business']]
        for b in business:
            for n,owner in enumerate(owners):
                for out in(True,False):
                    reply=(n!=b['initiator'])if out else(n==b['initiator']);payload=bytearray.fromhex(b['payload']);payload[28]=int(reply)
                    legs.append(dict(bus=owner['bus'],device=owner['device'],handle=owner['handle'],direction='out'if out else'in',data=(b'\x1f\0\x3e\0\xf1'+payload).hex(),wall_ns=b['start_wall_ns']+1))
        proof=dict(status=gate.STATUS,controllers=[2,3],owners=owners,business=business,round_trips=6,while_held_round_trips=2,after_withdrawal_round_trips=2,application_UID=1000,daemon_policy_qualified=False,credit_truth=False,full_drain=False,natural_recovery=False,management_unchanged=True,links_unchanged=True,legs=legs,heard=[{}],links=[{},{}],discovery=[{}])
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
        self.assertTrue(gate.requested(args))
        for k,v in [('managed_connected_case','dup'),('managed_connected_index',True),('managed_channel_grant',False),('managed_channel_revoke_prefix',False),('setup_release_verify',False),('qmp_hotplug',True),('managed_channel_queued_discard',True),('session_service_observe',True),('managed_channel_security',1),('four_device_dynamic_benchmark',True)]:
            bad=copy.copy(args);setattr(bad,k,v)
            with self.subTest(k=k),self.assertRaises(ValueError):gate.requested(bad)
        words=[gate.TOKEN,'ws73.channel_grant=1','ws73.channel_revoke_prefix=1','ws73.connected_case=release','ws73.connected_index=0']
        self.assertTrue(gate.boot_enabled(words));self.assertFalse(gate.boot_enabled([]))
        for bad in [words+[gate.TOKEN],words+['ws73.connected_case=close'],words[1:]+['ws73.channel_sibling_business=0'],words[:-1]]:
            with self.assertRaises(ValueError):gate.boot_enabled(bad)
        here=Path(gate.__file__).parent
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);tools=root/'root/usr/share/sparklink/tools';tools.mkdir(parents=True)
            names=['ws73_channel_sibling.py','ws73_native_pair.py','ws73_channel_grant.py','ws73_connected_file_gate.py','ws73_channel_prefix_hold.py']
            for n in names:(tools/n).write_bytes((here/n).read_bytes())
            init=root/'root/init';init.write_bytes((here/'ws73_target_init.sh').read_bytes());init.chmod(0o755)
            package=dict(channel_sibling_business_contract_version=1,inputs=[gate.file_record(here/'ws73_target.py')])
            gate.require_preparation(package,root)
            with self.assertRaisesRegex(ValueError,'host runner'):
                gate.require_preparation(dict(package,inputs=[]),root)
            for value in(None,True,2):
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
