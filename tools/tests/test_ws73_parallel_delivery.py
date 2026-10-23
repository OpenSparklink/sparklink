# SPDX-License-Identifier: GPL-2.0-only
"""Report/coordination and real-file fixtures only,not Native security or RF.

Fragment shapes use the production codec;no successful controller/Agent/parser
is stubbed. The opaque security receipt below only exercises summary composition.
Actual relay/install/Grant,peer apps and USB are separate mandatory VM gates.
"""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ws73_parallel_data import fixture,burst_summary_fixture
from ws73_capture import CaptureError
from ws73_parallel_data import DELIVERY_SCOPE,verify_records,delivery_parallel_proof
from ws73_ssap_value import fragment_parts
from ws73_target import HERE,file_record,require_delivery_preparation,run_exit_code,validate_business_mode
from ws73_vm_native_root import retained_daemon,check_discovery_config_gate


def metadata_fixture():
    r=fixture();r.update(scope=DELIVERY_SCOPE,update_delivery_mode=True,parallel_delivery_contract_version=1)
    for w in r['workers']:
        d=w['run'];d.update(scope=DELIVERY_SCOPE,update_delivery_mode=True,parallel_delivery_contract_version=1,
            security_agent=[dict(mode='numeric-approve',ssap_security_requirement=2)for _ in range(2)])
        w['args'].insert(-2,'--update-delivery')
        for row in d['channel_socket']:row.update(ssap_update_delivery_required=True,ssap_update_delivery_version=2,security_requirement=2,ssap_security_requirement=2)
    return r


def pairs_fixture():
    pairs=[]
    for pair in range(2):
        phases=[];connections=[]
        for n in range(2):
            base=(n+1)*100000+pair*100;serial=0
            def packet(pdu):
                nonlocal serial
                serial+=1;frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
                return dict(data=frame.hex(),record=serial,wall_ns=base+serial)
            def leg(pdu):
                if len(pdu)>2042:
                    return dict(logical_pdu=pdu.hex(),tx=dict(ssap_fragments=[packet(v)for v in fragment_parts(pdu)]),rx=dict(ssap_fragments=[packet(v)for v in fragment_parts(pdu)]))
                return dict(tx=packet(pdu),rx=packet(pdu))
            directions=[]
            for sender in (0,1):
                # Literal bounded summary-shape corpus,not an emulated peer.
                wire=[leg(b'\x08\x03\x11\0\0')for _ in range(78)]
                for opcode,size,count in [(15,2043,1),(16,2043,1),(15,2048,1),(16,2048,1),(13,2047,2),(14,2047,2)]:
                    for _ in range(count):wire.append(leg(bytes([opcode,3])+b'\x11\0'+b'\0'*(size-4)))
                directions.append(dict(sender=sender,target=1-sender,publisher='c'if(n+sender)%2==0 else'python',peer='python'if(n+sender)%2==0 else'c',updates=8,application_replies=8,decisions=16,version=2,lengths=[32,2036,2037,2042],wire=wire))
            phases.append(dict(phase=n,legs=[{}for _ in range(40)],ssap_update_delivery=directions))
            connections.append(dict(steps=[dict(outcomes=[dict(wall_ns=base-1000)]),dict(outcomes=[dict(wall_ns=base+5000)])]))
        security=dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',business_round_trips=40,current_security_snapshots=8,
            phases=[dict(mode='numeric-approve',application_phase=n,application_security_requirement=2,ssap_security_requirement=2,current_security_snapshots=4,protected_grant_refusals=4,wire=dict(fixture='opaque metadata;not Native proof'))for n in range(2)])
        pairs.append(dict(connections=connections,security=security,channel=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=40,proofs=phases)))
    return pairs


def summary_fixture():
    r=burst_summary_fixture();p=r['parallel_corroboration']
    for k in ['long_pdu_acceptance','software_backpressure_acceptance','observed_controller_pool_saturation_and_resumption','controller_credit_correctness_proof','fairness_acceptance']:p.pop(k)
    p.update(status='FOUR_REAL_PARALLEL_UPDATE_DELIVERY_CORROBORATED',round_trips=80,pairs=pairs_fixture(),parallel_delivery_contract_version=1,parallel_delivery_control=metadata_fixture(),update_delivery_acceptance=True,protected_ssap_acceptance=True)
    p['update_delivery']=delivery_parallel_proof(p['pairs'])
    r.update(status='FOUR_DEVICE_PARALLEL_UPDATE_DELIVERY_PASS',four_device_burst_requested=False,four_device_update_delivery_requested=True,four_delivery_contract_version=1,four_delivery_security_requirement=2,live_ssap_security_requirement=2,qemu_args=['ws73.parallel=1 ws73.parallel_business=1 ws73.parallel_delivery=1'])
    return r


class ParallelDelivery(unittest.TestCase):
    def test_preparation_binds_actual_files_init_config_and_witness(self):
        for case in ('valid','version','source','init','config','probe','identity','no-oracle','stale-oracle'):
            with self.subTest(case=case),tempfile.TemporaryDirectory()as tmp:
                path=Path(tmp);root=path/'root';share=root/'usr/share/sparklink/tools';share.mkdir(parents=True)
                for name in ['ws73_parallel_data.py','ws73_channel_socket.py','ws73_connection_control.py','ws73_security_agent.py','ws73_ssap_update_delivery.py','ws73_ssap_owned.py','ws73_dynamic_channels.py']:
                    (share/name).write_bytes((HERE/name).read_bytes())
                entry=root/'init';entry.write_bytes((HERE/'ws73_target_init.sh').read_bytes());entry.chmod(0o755)
                config=root/'etc/sparklink/main.conf';config.parent.mkdir(parents=True);config.write_text('[ssap]\nchannel_security = 2\n')
                witness=root/'bin/ws73-security-agent-probe';witness.parent.mkdir();witness.write_bytes(b'file identity fixture;never executed')
                record=file_record(witness)
                package=dict(four_delivery_contract_version=1,guest_files=[record],native_security_agent_probe=record)
                oracle=root/'usr/bin/openssl';oracle.parent.mkdir(parents=True);oracle.write_bytes(b'file identity fixture;never executed')
                oracle_record=file_record(oracle);package['guest_files'].append(oracle_record)
                package['native_verification_openssl']=dict(guest_path='/usr/bin/openssl',validation_exit=0,source=oracle_record,files=[dict(guest_path='/usr/bin/openssl',sha256=oracle_record['sha256'])])
                if case=='version':package['four_delivery_contract_version']=True
                elif case=='source':(share/'ws73_parallel_data.py').write_text('old source')
                elif case=='init':entry.chmod(0o644)
                elif case=='config':config.write_text('[ssap]\nchannel_security = 0\n')
                elif case=='probe':witness.write_bytes(b'changed')
                elif case=='identity':package['native_security_agent_probe']=dict(sha256='0'*64)
                elif case=='no-oracle':package.pop('native_verification_openssl')
                elif case=='stale-oracle':oracle.write_bytes(b'changed')
                if case=='valid':require_delivery_preparation(package,path)
                else:
                    with self.assertRaises(ValueError):require_delivery_preparation(package,path)

    def test_metadata_requires_explicit_full_protected2_request(self):
        self.assertEqual(len(verify_records(metadata_fixture())),4)
        for name in ('version','worker','plain','old-lengths','no-agent','local-approval','mixed','selector'):
            r=metadata_fixture();d=r['workers'][1]['run']
            if name=='version':r['parallel_delivery_contract_version']=True
            elif name=='worker':d['parallel_delivery_contract_version']=None
            elif name=='plain':d['channel_socket'][0]['security_requirement']=0
            elif name=='old-lengths':d['channel_socket'][0]['ssap_update_delivery_version']=1
            elif name=='no-agent':d['security_agent']=[]
            elif name=='local-approval':d['security_agent'][0]['mode']='approve'
            elif name=='mixed':r['owned_ssap_mode']=True
            else:r['workers'][1]['args'].remove('--update-delivery')
            with self.subTest(name=name),self.assertRaises(CaptureError):verify_records(r)

    def test_existing_codec_summary_and_numeric_contracts_are_composed_without_fallback(self):
        p=delivery_parallel_proof(pairs_fixture());self.assertEqual(p['updates'],64);self.assertEqual(p['application_replies'],64);self.assertFalse(p['rf_cipher_attested'])
        for name in ('no-security','plain-security','missing-refusal','wrong-mode','missing-length','missing-reply','bad-fragment','outside-link'):
            pairs=pairs_fixture();pair=pairs[1]
            if name=='no-security':pair.pop('security')
            elif name=='plain-security':pair['security']['phases'][0]['ssap_security_requirement']=0
            elif name=='missing-refusal':pair['security']['phases'][0]['protected_grant_refusals']=0
            elif name=='wrong-mode':pair['security']['phases'][0]['mode']='approve'
            elif name=='missing-length':pair['channel']['proofs'][0]['ssap_update_delivery'][0]['lengths']=[32]
            elif name=='missing-reply':pair['channel']['proofs'][0]['ssap_update_delivery'][0]['application_replies']=7
            elif name=='bad-fragment':pair['channel']['proofs'][0]['ssap_update_delivery'][0]['wire'][-1]['rx']['ssap_fragments'].pop()
            else:pair['connections'][0]['steps'][1]['outcomes'][0]['wall_ns']=1
            with self.subTest(name=name),self.assertRaises(CaptureError):delivery_parallel_proof(pairs)

    def test_verdict_requires_actual_scope_and_preserves_full_lengths_and_security(self):
        self.assertEqual(run_exit_code(summary_fixture()),0)
        for name in ('missing-control','bool-version','missing-boot','conflict','plain','summary','fault','status'):
            r=summary_fixture();p=r['parallel_corroboration']
            if name=='missing-control':p.pop('parallel_delivery_control')
            elif name=='bool-version':r['four_delivery_contract_version']=True
            elif name=='missing-boot':r['qemu_args']=[]
            elif name=='conflict':r['qemu_args'].append('ws73.parallel_owned=1')
            elif name=='plain':r['live_ssap_security_requirement']=0
            elif name=='summary':p['update_delivery']['updates']=1
            elif name=='fault':p['fault_isolation_acceptance']=True
            else:r['status']='FOUR_DEVICE_PARALLEL_OWNED_SSAP_PASS'
            with self.subTest(name=name):self.assertEqual(run_exit_code(r),1)

    def test_retained_daemon_alias_resolves_inside_root_and_refuses_arbitrary_programs(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);entry=root/'bin/slkd';entry.parent.mkdir();target='/usr/libexec/opensparklink/native-lab/000000000001/slkd';binary=root/target.lstrip('/');binary.parent.mkdir(parents=True);binary.write_bytes(b'file fixture never executed');binary.chmod(0o755);entry.symlink_to(target)
            self.assertEqual(retained_daemon(root),binary)
            entry.unlink();entry.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):retained_daemon(root)
            entry.unlink();entry.symlink_to(target);binary.chmod(0o644)
            with self.assertRaises(ValueError):retained_daemon(root)

    def test_custom_config_is_not_silently_enabled_for_old_modes(self):
        package=dict(discovery_config={},four_delivery_contract_version=1,policy_expectation=dict(data=dict(custom_configuration=True)))
        check_discovery_config_gate(package,SimpleNamespace(command='run',four_device_update_delivery=True))
        with self.assertRaises(ValueError):check_discovery_config_gate(package,SimpleNamespace(command='run',four_device_owned=True))
        package['four_delivery_contract_version']=True
        with self.assertRaises(ValueError):check_discovery_config_gate(package,SimpleNamespace(command='run',four_device_update_delivery=True))
        validate_business_mode(SimpleNamespace(command='run',four_device_update_delivery=True))
        with self.assertRaises(ValueError):validate_business_mode(SimpleNamespace(command='run',four_device_update_delivery=True,security_agent='numeric-approve'))
