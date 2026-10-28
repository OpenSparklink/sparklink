# SPDX-License-Identifier: GPL-2.0-only
"""Finite metadata/file/codec fixtures, not Native, Agent or RF qualification.

No successful production dependency is stubbed. Opaque security/supervisor
receipts below exercise summary composition only; actual raw root outputs,
credentials, snapshots, configuration writes and peer replies remain VM gates.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from test_ws73_parallel_delivery import metadata_fixture as delivery_metadata, pairs_fixture as delivery_pairs, summary_fixture as delivery_summary
from test_ws73_ssap_subscription import fixture as subscription_row
from ws73_capture import CaptureError
from ws73_parallel_data import SUBSCRIPTION_SCOPE,verify_records,subscription_parallel_proof
from ws73_role_snapshot import profile,publish,verify,local_root
from ws73_ssap_subscription import role_paths,validate_request,valid_shared_summary,verify_supervisor_artifacts
from ws73_target import run_exit_code,validate_business_mode
from ws73_vm_native_root import check_discovery_config_gate


def metadata_fixture():
    record=delivery_metadata();record.update(scope=SUBSCRIPTION_SCOPE,shared_subscription_mode=True,parallel_subscription_contract_version=1)
    record.pop('update_delivery_mode');record.pop('parallel_delivery_contract_version')
    for number,worker in enumerate(record['workers']):
        row=worker['run'];row.update(scope=SUBSCRIPTION_SCOPE,shared_subscription_mode=True,parallel_subscription_contract_version=1)
        row.pop('update_delivery_mode');row.pop('parallel_delivery_contract_version')
        worker['args'][worker['args'].index('--update-delivery')]='--shared-subscription'
        for phase in row['channel_socket']:
            phase.pop('ssap_update_delivery_required');phase.pop('ssap_update_delivery_version')
            phase.update(ssap_subscription_required=True,ssap_subscription_shared_required=True,parallel_pair=number)
    return record


def pairs_fixture():
    pairs=delivery_pairs()
    for number,pair in enumerate(pairs):
        for phase,row in enumerate(pair['channel']['proofs']):
            row.pop('ssap_update_delivery');row['ssap_subscription']=[]
            for sender in (0,1):
                base=(phase+1)*100000+number*100
                wire=[dict(tx=dict(data='0a00010001',wall_ns=base+2*n),rx=dict(data='0a00010001',wall_ns=base+2*n+1))for n in range(91)]
                row['ssap_subscription'].append(dict(sender=sender,target=1-sender,publisher='c'if(phase+sender)%2==0 else'python',peer='python'if(phase+sender)%2==0 else'c',leases=6,updates=14,application_replies=24,decisions=4,shared_contract_version=1,shared_groups=2,shared_joins=4,retained_releases=4,last_disables=2,wire=wire))
        pair['subscription_supervision']=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,phases=2,reader_UID=1004,provider_UID=1005,readers=24,providers=4,updates=56,daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2+number,start_ticks=2),shared_contract_version=1,shared_groups=8,shared_joins=16,checked_replies=96,retained_releases=16,last_disables=8,snapshot_contract_version=1,snapshot_phases=2,snapshot_files=30,snapshot_bytes=2048,parallel_pair=number)
        groups=[]
        for phase in (0,1):
            for sender in (0,1):
                for mode in (1,2):
                    raw=b'\x0a\0\x07\0\x0d\x23\x11\0'+bytes([2,mode,0])
                    writes=[dict(data=data.hex(),bus=1,device=10+sender,handle=12,direction='out',record=1+n,wall_ns=1+n)for n,data in enumerate((raw,raw[:9]+b'\0\0'))]
                    groups.append(dict(phase=phase,sender=sender,mode=mode,writes=writes))
        pair['subscription_configuration']=dict(status='EXACT_SHARED_REMOTE_CONFIGURATION_WRITES',enables=8,last_disables=8,groups=groups)
    return pairs


def summary_fixture():
    record=delivery_summary();proof=record['parallel_corroboration']
    for key in ('parallel_delivery_contract_version','parallel_delivery_control','update_delivery','update_delivery_acceptance'):proof.pop(key)
    for key in ('four_delivery_contract_version','four_delivery_security_requirement'):record.pop(key)
    record.update(status='FOUR_DEVICE_PARALLEL_SHARED_SUBSCRIPTION_PASS',four_device_update_delivery_requested=False,four_device_shared_subscription_requested=True,four_subscription_contract_version=1,four_subscription_security_requirement=2,qemu_args=['ws73.parallel=1 ws73.parallel_business=1 ws73.parallel_subscription=1 ws73.ssap_subscription=1 ws73.ssap_subscription_shared=1 ws73.subscription_snapshot=1'])
    pairs=pairs_fixture();control=metadata_fixture()
    for pair,worker in zip(pairs,control['workers'],strict=True):pair['subscription_supervision']['daemon']=copy.deepcopy(worker['run']['daemon_before'])
    proof.update(status='FOUR_REAL_PARALLEL_SHARED_SUBSCRIPTION_CORROBORATED',pairs=pairs,parallel_subscription_contract_version=1,parallel_subscription_control=control,shared_subscription_acceptance=True,shared_subscription=subscription_parallel_proof(pairs))
    return record


class ParallelSubscription(unittest.TestCase):
    def test_fixed_pair_namespaces_reject_arbitrary_inputs_and_other_profiles(self):
        self.assertEqual(role_paths()[0],Path('/evidence/subscription-role'))
        roots=[profile('subscription',p)for p in (None,0,1)]
        self.assertEqual(len({v['root']for v in roots}),3)
        self.assertEqual(len({v['artifact']for v in roots}),3)
        self.assertEqual({v['limit']for v in roots},{16*1024*1024})
        self.assertEqual(role_paths(1)[1],Path('/evidence/application/parallel-business/pair-1'))
        for pair in (True,False,-1,2,'0','../foreign'):
            with self.subTest(pair=pair),self.assertRaises(CaptureError):role_paths(pair)
        # Benchmark now has its own explicitly gated pair namespace;it cannot
        # alias subscription storage or admit any other role kind.
        self.assertNotEqual(profile('benchmark',0)['root'],profile('subscription',0)['root'])
        with self.assertRaises(CaptureError):profile('values',0)
        with patch('ws73_application_role.require_vm',side_effect=CaptureError('outside VM')):
            with self.assertRaises(CaptureError):
                with local_root(pair=0):self.fail('must not mount outside VM')

    def test_actual_closed_file_export_is_bound_to_pair_and_cannot_relabel_old(self):
        for pair in (None,0,1):
            with self.subTest(pair=pair),tempfile.TemporaryDirectory()as tmp:
                root=Path(tmp);source=root/'closed';source.mkdir();(source/'reader.stdout').write_text('actual local fixture bytes\n')
                target=root/'export';proof=publish(source,target,phase=0,success=True,pair=pair)
                self.assertEqual(verify(target,phase=0,runtime_root=source,pair=pair),proof)
                for wrong in {None,0,1}-{pair}:
                    with self.assertRaises(CaptureError):verify(target,phase=0,runtime_root=source,pair=wrong)
                (target/'reader.stdout').unlink()
                with self.assertRaises(CaptureError):verify(target,phase=0,runtime_root=source,pair=pair)

    def test_request_requires_selected_pair_ports_and_original_identity(self):
        row=subscription_row();request=dict(phase=0,owners=row['owners'],tools={},security_requirement=2,message_security_required=True,status='RUNNING',start_wall_ns=1,parallel_pair=0)
        for n,entry in enumerate(request['owners']):entry['owner']['port']='1-'+str(n+1)
        validate_request(request,0)
        for change in ('pair','bool','foreign','generation','arbitrary'):
            bad=copy.deepcopy(request)
            if change=='pair':bad['parallel_pair']=1
            elif change=='bool':bad['parallel_pair']=False
            elif change=='foreign':bad['owners'][0]['owner']['port']='1-9'
            elif change=='generation':bad['owners'][0]['owner']['generation']+=1
            else:bad['root']='/elsewhere'
            with self.subTest(change=change),self.assertRaises(CaptureError):validate_request(bad,0)
        with tempfile.TemporaryDirectory()as tmp:
            with self.assertRaises(FileNotFoundError):verify_supervisor_artifacts({},tmp,pair=0)

    def test_original_roles_and_workload_cannot_be_downgraded(self):
        self.assertEqual(len(verify_records(metadata_fixture())),4)
        for change in ('selector','mixed','no-agent','plain','wrong-pair','single-reader','other-case','bool-version'):
            record=metadata_fixture();worker=record['workers'][1];row=worker['run']['channel_socket'][0]
            if change=='selector':worker['args'].remove('--shared-subscription')
            elif change=='mixed':record['update_delivery_mode']=True
            elif change=='no-agent':worker['run']['security_agent']=[]
            elif change=='plain':row['security_requirement']=0
            elif change=='wrong-pair':row['parallel_pair']=0
            elif change=='single-reader':row['ssap_subscription_shared_required']=False
            elif change=='other-case':row['ssap_subscription_shared_case']='expiry'
            else:record['parallel_subscription_contract_version']=True
            with self.subTest(change=change),self.assertRaises(CaptureError):verify_records(record)

    def test_composes_full_existing_oracles_and_both_physical_lifetimes(self):
        pairs=pairs_fixture();proof=subscription_parallel_proof(pairs)
        self.assertEqual((proof['updates'],proof['application_replies'],proof['retained_releases']),(112,192,32))
        self.assertFalse(valid_shared_summary(pairs[0]['channel'])) # Old two-device gate still requires8.
        for change in ('missing-pair','shared','reply','socket','root','uid','snapshot','namespace','same-supervisor','other-daemon','configuration','security','outside-link','no-overlap'):
            pairs=pairs_fixture();pair=pairs[1]
            if change=='missing-pair':pairs.pop()
            elif change=='shared':pair['channel']['proofs'][0]['ssap_subscription'][0]['shared_joins']=0
            elif change=='reply':pair['channel']['proofs'][0]['ssap_subscription'][0]['application_replies']=1
            elif change=='socket':pair['channel']['round_trips']=8
            elif change=='root':pair.pop('subscription_supervision')
            elif change=='uid':pair['subscription_supervision']['reader_UID']=1000
            elif change=='snapshot':pair['subscription_supervision']['snapshot_files']=0
            elif change=='namespace':pair['subscription_supervision']['parallel_pair']=0
            elif change=='same-supervisor':pair['subscription_supervision']['supervisor']=pairs[0]['subscription_supervision']['supervisor']
            elif change=='other-daemon':pair['subscription_supervision']['daemon']['pid']=99
            elif change=='configuration':pair['subscription_configuration']['groups'][0]['writes'].pop()
            elif change=='security':pair['security']['phases'][0]['protected_grant_refusals']=0
            elif change=='outside-link':pair['connections'][0]['steps'][1]['outcomes'][0]['wall_ns']=1
            else:
                for phase in pair['channel']['proofs']:
                    for item in phase['ssap_subscription']:
                        for leg in item['wire']:
                            for end in ('tx','rx'):leg[end]['wall_ns']+=2000
            with self.subTest(change=change),self.assertRaises(CaptureError):subscription_parallel_proof(pairs)

    def test_verdict_requires_original_control_boot_and_exact_scoped_summary(self):
        self.assertEqual(run_exit_code(summary_fixture()),0)
        for change in ('control','version','boot','snapshot','conflict','count','uid','status','request','fault'):
            record=summary_fixture();proof=record['parallel_corroboration']
            if change=='control':proof.pop('parallel_subscription_control')
            elif change=='version':record['four_subscription_contract_version']=True
            elif change=='boot':record['qemu_args']=[]
            elif change=='snapshot':record['qemu_args'][0]=record['qemu_args'][0].replace('ws73.subscription_snapshot=1','')
            elif change=='conflict':record['qemu_args'].append('ws73.parallel_delivery=1')
            elif change=='count':proof['shared_subscription']['application_replies']=191
            elif change=='uid':proof['pairs'][0]['subscription_supervision']['reader_UID']=1000
            elif change=='status':record['status']='FOUR_DEVICE_PARALLEL_UPDATE_DELIVERY_PASS'
            elif change=='request':record['four_device_shared_subscription_requested']=False
            else:proof['fault_isolation_acceptance']=True
            with self.subTest(change=change):self.assertEqual(run_exit_code(record),1)

    def test_exclusive_front_door_and_custom_configuration(self):
        args=SimpleNamespace(command='run',four_device_shared_subscription=True)
        validate_business_mode(args)
        for mode in ('four_device_update_delivery','four_device_owned','ssap_subscription_shared_verify'):
            with self.assertRaises(ValueError):validate_business_mode(SimpleNamespace(**(vars(args)|{mode:True})))
        package=dict(discovery_config={},four_subscription_contract_version=1,policy_expectation=dict(data=dict(custom_configuration=True)))
        check_discovery_config_gate(package,args)
        package['four_subscription_contract_version']=True
        with self.assertRaises(ValueError):check_discovery_config_gate(package,args)
