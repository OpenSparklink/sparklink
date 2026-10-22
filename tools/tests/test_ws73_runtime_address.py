# SPDX-License-Identifier: GPL-2.0-only
"""Verifier fixtures; not controller, permission, RF or persistence tests."""
import copy
from pathlib import Path
import sys
import unittest
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_runtime_address import parse_addresses, requested, boot_addresses, corroborate

ADDRESSES=['A6:7B:73:10:E0:01','A6:7B:73:10:E0:02']


def fixture():
    owners=[dict(port=f'1-{n+1}',bus=1,device=n+2,index=n,generation=n+10,address='EE:EF:33:9B:8D:5C',hcc_chip=dict(model='E',bus='USB')) for n in range(2)]
    record=dict(version=1,status='REAL_READBACK_PENDING_CAPTURE_AUDIT',addresses=ADDRESSES,runtime_only=True,official_identity=False,uid=0,owners=owners,originals=[],setters=[],commands=[])
    capture=dict(commands=[],complete=[])
    old='eeef339b8d5c'
    def wire(owner,opcode,value,clock,params=''):
        r=len(capture['commands'])*2+1
        base=dict(bus=owner['bus'],device=owner['device'],opcode=opcode)
        capture['commands'].append(dict(base,record=r,wall_ns=clock,params=params,completion=dict(wall_ns=clock+1)))
        capture['complete'].append(dict(base,record=r+1,wall_ns=clock+2,status=0,value=value))
    def row(owner,words,start,end,stdout):
        value=dict(args=['/bin/slkconfig','--adapter',str(owner['index']),'--generation',str(owner['generation']),*words],start_wall_ns=start,end_wall_ns=end,exit=0,stdout=stdout,stderr='')
        record['commands'].append(value);return len(record['commands'])-1
    def query(owner,value,clock):
        wire(owner,0x0406,value,clock+10)
        return row(owner,['query','mac'],clock,clock+50,f'NativeDiagnosticQuery: index={owner["index"]} generation={owner["generation"]} opcode=0x0406 admission_seq=1 status=0x00 data={value}\n')
    for slot,owner in enumerate(owners):
        record['originals'].append(dict(query=query(owner,old,slot*100+100),address=old))
    for slot,owner in enumerate(owners):
        clock=300+slot*400;peer=owners[1-slot];peer_value=ADDRESSES[0].replace(':','').lower() if slot else old
        pre=query(peer,peer_value,clock)
        target=ADDRESSES[slot].replace(':','').lower()
        wire(owner,0x0406,old,clock+110)
        wire(owner,0x0405,'',clock+120,target)
        wire(owner,0x0406,target,clock+130)
        prefix=f'index={owner["index"]} generation={owner["generation"]}'
        stdout=(f'NativeRuntimeAddressOriginal: {prefix} opcode=0x0406 admission_seq=1 data={old}\n'
                f'NativeRuntimeAddressSetComplete: {prefix} opcode=0x0405 admission_seq=2 status=0x00\n'
                f'NativeRuntimeAddressVerified: {prefix} setter_seq=2 readback_seq=3 original={old} readback={target} runtime_only=true official_identity=false\n')
        setter=row(owner,['runtime-address',ADDRESSES[slot]],clock+100,clock+150,stdout)
        post=query(peer,peer_value,clock+200)
        record['setters'].append(dict(slot=slot,command=setter,peer_before=pre,peer_after=post,configured=dict(owner,address=ADDRESSES[slot])))
    return record,capture


class RuntimeAddressEvidence(unittest.TestCase):
    def test_shared_setup_accepts_canonical_benchmark_without_baseline_flag(self):
        # This is the actual host selector,not a VM or a successful peer.
        args=dict(runtime_addresses=ADDRESSES,command='run',ports=['1-2.1.1','1-2.1.2'],
                  qmp_hotplug=True,channel_socket_verify=False,connection_verify=True)
        for mode in ('rate','window','duplex'):
            with self.subTest(mode=mode):
                self.assertEqual(requested(SimpleNamespace(**(args|dict(channel_benchmark=mode)))),ADDRESSES)
        for mode in (None,'','unknown',True):
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                requested(SimpleNamespace(**(args|dict(channel_benchmark=mode))))

    def test_benchmark_setup_preserves_leaf_connection_and_vm_boundaries(self):
        args=dict(runtime_addresses=ADDRESSES,command='run',ports=['1-2.1.1','1-2.1.2'],
                  qmp_hotplug=True,channel_socket_verify=False,connection_verify=True,channel_benchmark='window')
        for change in [dict(command='support'),dict(connection_verify=False),dict(qmp_hotplug=False),
                       dict(ports=['1-2.1.1','1-2.1.3']),dict(ports=['1-1.1.1','1-1.1.2']),
                       dict(ports=['1-2.1.1']*2),dict(ports=[]),dict(runtime_addresses=[ADDRESSES[0]]*2)]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                requested(SimpleNamespace(**(args|change)))

    def test_host_evidence_addition_never_awards_run_or_business_success(self):
        from ws73_target import corroborate_runtime_addresses, HERE
        from ws73_north_star import file_record
        record,capture=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            share=Path(tmp);(share/'runtime-address').mkdir()
            (share/'runtime-address/run.json').write_text(json.dumps(record))
            before=copy.deepcopy((record,capture))
            metadata=corroborate_runtime_addresses(share,capture,ADDRESSES,file_record(HERE/'ws73_runtime_address.py'))
            self.assertEqual(set(metadata),{'runtime_address_corroboration','runtime_address_record'})
            self.assertEqual(len(metadata['runtime_address_corroboration']),2)
            self.assertEqual((record,capture),before)
            # Add to an in-progress manifest exactly as the actual caller does.
            manifest=dict(status='RUNNING',connection_verify_requested=True,channel_socket_verification_requested=True)
            manifest.update(metadata)
            self.assertEqual(manifest['status'],'RUNNING')
            self.assertNotIn('ordinary_channel_socket_acceptance',manifest)
            self.assertNotIn('supervisor_exit',manifest)
            benchmark=dict(status='FAIL',socket_benchmark_requested='window',socket_benchmark_acceptance=False)
            benchmark.update(metadata)
            self.assertEqual(benchmark['status'],'FAIL')
            self.assertFalse(benchmark['socket_benchmark_acceptance'])
            self.assertNotIn('socket_benchmark_corroboration',benchmark)

    def test_host_evidence_addition_rejects_raw_loss_pin_and_bad_original(self):
        from ws73_target import corroborate_runtime_addresses,HERE
        from ws73_north_star import file_record
        for case in ['missing-set-complete','bad-record','changed-verifier']:
            record,capture=fixture();pin=file_record(HERE/'ws73_runtime_address.py')
            if case=='missing-set-complete':capture['complete'].pop(4)
            elif case=='bad-record':record['status']='FAIL'
            else:pin['sha256']='0'*64
            with tempfile.TemporaryDirectory() as tmp:
                share=Path(tmp);(share/'runtime-address').mkdir();(share/'runtime-address/run.json').write_text(json.dumps(record))
                with self.subTest(case=case),self.assertRaises(ValueError):corroborate_runtime_addresses(share,capture,ADDRESSES,pin)

    def test_host_evidence_binds_the_record_bytes_actually_verified(self):
        from ws73_target import corroborate_runtime_addresses,HERE
        from ws73_north_star import file_record
        from ws73_runtime_address import corroborate as actual_verifier
        record,capture=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            share=Path(tmp);(share/'runtime-address').mkdir();path=share/'runtime-address/run.json'
            path.write_text(json.dumps(record))
            def verify_then_change(*args):
                proof=actual_verifier(*args)  # Real verifier,not an always-success stub.
                path.write_text('{}')
                return proof
            with patch('ws73_runtime_address.corroborate',side_effect=verify_then_change):
                with self.assertRaisesRegex(ValueError,'record changed'):
                    corroborate_runtime_addresses(share,capture,ADDRESSES,file_record(HERE/'ws73_runtime_address.py'))

    def test_explicit_parse_and_scope(self):
        self.assertEqual(parse_addresses([x.lower() for x in ADDRESSES]),ADDRESSES)
        for bad in [[],[ADDRESSES[0]]*2,['0:7B:73:10:E0:01',ADDRESSES[1]],['00:00:00:00:00:00',ADDRESSES[1]],['FF:FF:FF:FF:FF:FF',ADDRESSES[1]]]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):parse_addresses(bad)
        args=dict(runtime_addresses=ADDRESSES,command='run',ports=['1-2.1.1','1-2.1.2'],qmp_hotplug=True,channel_socket_verify=True,connection_verify=True)
        self.assertEqual(requested(SimpleNamespace(**args)),ADDRESSES)
        # An explicit permutation preserves caller address order. It grants no
        # permission to select another leaf or infer a model from enumeration.
        reverse=args|dict(ports=list(reversed(args['ports'])),runtime_addresses=list(reversed(ADDRESSES)))
        self.assertEqual(requested(SimpleNamespace(**reverse)),list(reversed(ADDRESSES)))
        self.assertEqual(reverse['ports'],['1-2.1.2','1-2.1.1'])
        for changes in [dict(ports=[]),dict(ports=['1-2.1.1']),dict(ports=['1-2.1.1']*2),dict(ports=['1-2.1.1','1-2.1.2','1-2.1.1']),dict(ports=['1-2.1.3','1-2.1.4']),dict(ports=['1-2.1.1','1-2.1.3']),dict(ports=['1-1.1.1','1-2.1.2']),dict(ports=['1-1.1.1','1-1.1.2']),dict(qmp_hotplug=False),dict(channel_socket_verify=False),dict(connection_verify=False),dict(command='support')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):requested(SimpleNamespace(**(args|changes)))
        self.assertIsNone(requested(SimpleNamespace()))
        words=['ws73.expected_models=E,E','ws73.runtime_addresses='+','.join(ADDRESSES)]
        self.assertEqual(boot_addresses(words),ADDRESSES)
        for bad in [words+words,words[1:],['ws73.expected_models=U,U',words[1]]]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):boot_addresses(bad)

    def test_complete_fixture_checks_actual_capture_verifier(self):
        record,capture=fixture();proof=corroborate(record,capture,ADDRESSES)
        self.assertEqual(len(proof),2)
        self.assertTrue(all(p['setter']['command']['opcode']==0x0405 for p in proof.values()))

    def test_negative_controls_preserve_required_evidence(self):
        record,capture=fixture()
        mutations=[lambda r,c:c['commands'].pop(4),lambda r,c:c['complete'].pop(4),
                   lambda r,c:c['commands'][4].update(params='00'*6),
                   lambda r,c:c['complete'][5].update(value='00'*6),
                   lambda r,c:r.update(status='FAIL'),lambda r,c:r.update(official_identity=True),
                   lambda r,c:r['owners'][0]['hcc_chip'].update(model='U'),
                   lambda r,c:r['setters'][0]['configured'].update(generation=999),
                   lambda r,c:r['commands'][3].update(exit=1),lambda r,c:r['commands'][3].update(stderr='rejected'),
                   lambda r,c:r['commands'][3]['args'].__setitem__(-1,ADDRESSES[1]),
                   lambda r,c:r['commands'][0].update(stdout='cached address'),
                   lambda r,c:c['complete'][6].update(value='12'*6),
                   lambda r,c:r['commands'][3].update(stdout=r['commands'][3]['stdout'].replace('readback_seq=3','readback_seq=2'))]
        for n,change in enumerate(mutations):
            r,c=copy.deepcopy((record,capture));change(r,c)
            with self.subTest(n=n),self.assertRaises((ValueError,KeyError,IndexError)):corroborate(r,c,ADDRESSES)

if __name__=='__main__':unittest.main()
