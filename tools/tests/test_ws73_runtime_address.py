# SPDX-License-Identifier: GPL-2.0-only
"""Verifier fixtures; not controller, permission, RF or persistence tests."""
import copy
from contextlib import ExitStack
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_runtime_address import (parse_addresses, requested, boot_addresses, corroborate,
                                 check_originals, publish_originals, configure)

ADDRESSES=['A6:7B:73:10:E0:01','A6:7B:73:10:E0:02']


def fixture():
    owners=[dict(port=f'1-{n+1}',bus=1,device=n+2,index=n,generation=n+10,address='EE:EF:33:9B:8D:5C',hcc_chip=dict(model='E',bus='USB')) for n in range(2)]
    record=dict(version=1,status='REAL_READBACK_PENDING_CAPTURE_AUDIT',addresses=ADDRESSES,runtime_only=True,official_identity=False,uid=0,owners=owners,originals=[],setters=[],commands=[],
                sources=[dict(path='/fixture/helper',sha256='1'*64),dict(path='/fixture/slkconfig',sha256='2'*64)])
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


def stage_record(share, record):
    out=share/'runtime-address';out.mkdir()
    before=copy.deepcopy(record);before['commands']=before['commands'][:2];before['setters']=[]
    record['originals_record']=publish_originals(out,before)
    (out/'run.json').write_text(json.dumps(record))


class RuntimeAddressEvidence(unittest.TestCase):
    def test_controlled_grant_reuses_setup_without_awarding_a_verdict(self):
        args=dict(runtime_addresses=ADDRESSES,command='run',ports=['1-2.1.1','1-2.1.2'],
                  qmp_hotplug=False,connection_verify=False,channel_socket_verify=False,
                  managed_channel_grant=True,setup_release_verify=True)
        for case in ('release','close','dup'):
            for index in (0,1):
                selected=SimpleNamespace(**(args|dict(managed_connected_case=case,managed_connected_index=index)))
                before=copy.deepcopy(vars(selected))
                self.assertEqual(requested(selected),ADDRESSES)
                self.assertEqual(vars(selected),before)
        args['managed_connected_case']='release'
        for change in [dict(command='support'),dict(managed_connected_case=None),dict(managed_connected_case='echo'),
                       dict(managed_channel_grant=False),dict(setup_release_verify=False),dict(qmp_hotplug=True),
                       dict(connection_verify=True),dict(channel_socket_verify=True),dict(channel_benchmark='window'),
                       dict(ports=['1-2.1.1','1-2.1.3']),dict(ports=['1-1.1.1','1-1.1.2']),dict(ports=[args['ports'][0]]*2)]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                requested(SimpleNamespace(**(args|change)))

    def test_single_guest_setup_follows_untouched_setup_and_precedes_grant(self):
        text=(Path(__file__).parents[1]/'ws73_target_init.sh').read_text()
        untouched=text.index('/usr/share/sparklink/tools/ws73_management_setup.py')
        address=text.index('/usr/share/sparklink/tools/ws73_runtime_address.py')
        connected=text.index('/usr/share/sparklink/tools/ws73_connected_file_gate.py')
        finish=text.index("echo 'WS73_TARGET_CHANNEL_GRANT_FINISHED'")
        daemon=text.index('/bin/slkd ')
        self.assertEqual(text.count('/usr/share/sparklink/tools/ws73_runtime_address.py'),1)
        self.assertLess(untouched,address);self.assertLess(address,connected)
        self.assertLess(connected,finish);self.assertLess(finish,daemon)

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
            share=Path(tmp);stage_record(share,record)
            before=copy.deepcopy((record,capture))
            metadata=corroborate_runtime_addresses(share,capture,ADDRESSES,file_record(HERE/'ws73_runtime_address.py'))
            self.assertEqual(set(metadata),{'runtime_address_corroboration','runtime_address_record','runtime_address_originals_record'})
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
                share=Path(tmp);stage_record(share,record)
                with self.subTest(case=case),self.assertRaises(ValueError):corroborate_runtime_addresses(share,capture,ADDRESSES,pin)

    def test_host_evidence_binds_the_record_bytes_actually_verified(self):
        from ws73_target import corroborate_runtime_addresses,HERE
        from ws73_north_star import file_record
        from ws73_runtime_address import corroborate as actual_verifier
        record,capture=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            share=Path(tmp);stage_record(share,record);path=share/'runtime-address/run.json'
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

class OriginalAddressJournal(unittest.TestCase):
    """Real files/fsync and production configure; CLI/HCC/sysfs are fixtures.

    These tests do not establish 9p crash durability, native ioctl, USB,
    firmware behavior or successful restoration.
    """
    def setUp(self):
        self.fresh_environment()

    def fresh_environment(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.out=self.root/'runtime-address'
        self.vendor=self.root/'vendor';self.vendor.write_text('QEMU\n')
        self.cmdline=self.root/'cmdline';self.cmdline.write_text('ws73.expected_models=E,E ws73.runtime_addresses='+','.join(ADDRESSES))
        self.cli=self.root/'slkconfig';self.cli.write_text('explicit subprocess fixture;never executed\n')
        self.owners=fixture()[0]['owners'];self.current=[o['address']for o in self.owners]
        self.calls=[];self.syncs=[];self.query_hook=None;self.setter_error=None;self.sync_error=None

    def path(self,value):
        return {'/evidence/runtime-address':self.out,'/sys/class/dmi/id/sys_vendor':self.vendor,
                '/proc/cmdline':self.cmdline,'/bin/slkconfig':self.cli}.get(str(value),Path(value))

    def registration(self,port):
        slot=int(port.split('-')[1])-1
        return dict(copy.deepcopy(self.owners[slot]),address=self.current[slot])

    def run_command(self,args,**kwargs):
        self.assertEqual(kwargs,dict(text=True,capture_output=True,timeout=12))
        self.calls.append(args);slot=int(args[2]);generation=int(args[4]);operation=args[5]
        if operation=='query':
            self.assertEqual(args[6],'mac')
            if self.query_hook:self.query_hook(len(self.calls))
            return subprocess.CompletedProcess(args,0,
                f'NativeDiagnosticQuery: index={slot} generation={generation} opcode=0x0406 admission_seq=1 status=0x00 data={self.current[slot].replace(":", "").lower()}\n','')
        self.assertEqual(operation,'runtime-address')
        # This assertion runs at the real production subprocess boundary.
        self.assertEqual(self.syncs[:2],['file','directory'])
        document=json.loads((self.out/'originals.json').read_text())
        self.assertEqual(document['status'],'ORIGINALS_SAVED_NOT_RESTORED')
        self.assertEqual([v['address']for v in document['originals']],['eeef339b8d5c']*2)
        self.assertEqual(stat.S_IMODE((self.out/'originals.json').stat().st_mode),0o400)
        if self.setter_error:raise self.setter_error
        self.current[slot]=args[6]
        return subprocess.CompletedProcess(args,0,'fixture setter result;raw verifier tested separately\n','')

    def invoke(self):
        from ws73_north_star import file_record
        real_fsync=os.fsync
        def sync(fd):
            kind='directory'if stat.S_ISDIR(os.fstat(fd).st_mode)else'file'
            self.syncs.append(kind)
            if kind==self.sync_error:raise OSError('fixture '+kind+' fsync failure')
            real_fsync(fd)
        with ExitStack()as stack:
            stack.enter_context(patch('ws73_runtime_address.Path',side_effect=self.path))
            stack.enter_context(patch('ws73_runtime_address.file_record',side_effect=lambda path:file_record(self.path(path))))
            stack.enter_context(patch('ws73_runtime_address.os.getuid',return_value=0))
            stack.enter_context(patch('ws73_runtime_address.registration',side_effect=self.registration))
            stack.enter_context(patch('ws73_runtime_address.observe_guest_hcc',side_effect=lambda owner,model:owner))
            stack.enter_context(patch('ws73_runtime_address.subprocess.run',side_effect=self.run_command))
            stack.enter_context(patch('ws73_runtime_address.os.fsync',side_effect=sync))
            configure()

    def test_original_queries_are_synced_before_first_setter_and_never_rewritten(self):
        self.invoke();record=json.loads((self.out/'run.json').read_text())
        self.assertEqual(record['status'],'REAL_READBACK_PENDING_CAPTURE_AUDIT')
        self.assertEqual(sum(args[5]=='runtime-address'for args in self.calls),2)
        saved=(self.out/'originals.json').read_bytes()
        self.assertEqual(check_originals(self.out,record)['sha256'],record['originals_record']['sha256'])
        self.assertEqual(len(json.loads(saved)['commands']),2)
        before=copy.deepcopy(record);before['commands']=before['commands'][:2];before['setters']=[]
        with self.assertRaises(FileExistsError):publish_originals(self.out,before)
        self.assertEqual((self.out/'originals.json').read_bytes(),saved)

    def test_missing_changed_or_unpinned_originals_prevent_the_first_setter(self):
        for kind in ['missing','changed','missing-pin','changed-query']:
            with self.subTest(kind=kind):
                self.fresh_environment()
                def corrupt(count):
                    if count!=3:return
                    path=self.out/'originals.json'
                    if kind=='missing':path.unlink()
                    elif kind=='changed':path.chmod(0o600);path.write_text('{}');path.chmod(0o400)
                    # The on-disk progress is not the in-memory authority. These
                    # separate readback checks exercise absent/tampered pins.
                if kind in ('missing','changed'):
                    self.query_hook=corrupt
                    with self.assertRaises((OSError,ValueError)):self.invoke()
                    self.assertFalse(any(args[5]=='runtime-address'for args in self.calls))
                    self.assertEqual(json.loads((self.out/'run.json').read_text())['status'],'FAIL')
                else:
                    record,_=fixture();stage_record(self.root,record)
                    if kind=='missing-pin':del record['originals_record']
                    else:record['commands'][0]['stdout']='cached address'
                    with self.assertRaises(ValueError):check_originals(self.out,record)

    def test_failed_sync_stops_before_mutation_and_preserves_partial_publication(self):
        for kind in ('file','directory'):
            with self.subTest(kind=kind):
                self.fresh_environment();self.sync_error=kind
                with self.assertRaises(OSError):self.invoke()
                record=json.loads((self.out/'run.json').read_text())
                self.assertEqual(record['status'],'FAIL')
                self.assertFalse(any(args[5]=='runtime-address'for args in self.calls))
                saved=(self.out/'originals.json').read_bytes()
                with self.assertRaises(FileExistsError):publish_originals(self.out,record)
                self.assertEqual((self.out/'originals.json').read_bytes(),saved)
                self.assertNotIn('originals_record',record)

    def test_lost_originals_after_first_setter_stops_second_without_claiming_restore(self):
        def remove_after_first(count):
            if count==6:(self.out/'originals.json').unlink()
        self.query_hook=remove_after_first
        with self.assertRaises(FileNotFoundError):self.invoke()
        record=json.loads((self.out/'run.json').read_text())
        self.assertEqual(record['status'],'FAIL')
        self.assertEqual(len(record['setters']),1)
        self.assertEqual(sum(args[5]=='runtime-address'for args in self.calls),1)
        self.assertEqual(self.current,[ADDRESSES[0],self.owners[1]['address']])
        self.assertEqual(len(record['originals']),2)
        self.assertNotIn('restored',record)

    def test_nonregular_or_symlink_originals_are_rejected_without_blocking(self):
        for kind in ('directory','symlink','fifo'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory()as tmp:
                share=Path(tmp);record,_=fixture();stage_record(share,record)
                path=share/'runtime-address/originals.json';saved=path.with_suffix('.saved');path.rename(saved)
                if kind=='directory':path.mkdir()
                elif kind=='symlink':path.symlink_to(saved)
                else:os.mkfifo(path)
                with self.assertRaises((OSError,ValueError)):check_originals(path.parent,record)

    def test_timeout_retains_partial_bytes_and_unknown_physical_outcome(self):
        partial=b'NativeRuntimeAddressOriginal: partial\n\xff'
        self.setter_error=subprocess.TimeoutExpired(['fixture'],12,output=partial,stderr=b'partial error\xfe')
        with self.assertRaises(subprocess.TimeoutExpired):self.invoke()
        record=json.loads((self.out/'run.json').read_text());row=record['commands'][-1]
        self.assertEqual(record['status'],'FAIL');self.assertIsNone(row['exit'])
        self.assertTrue(row['timed_out']);self.assertFalse(row['output_complete'])
        self.assertEqual(row['physical_outcome'],'unknown')
        self.assertEqual(bytes.fromhex(row['partial_stdout_hex']),partial)
        self.assertEqual(bytes.fromhex(row['partial_stderr_hex']),b'partial error\xfe')
        self.assertEqual(sum(args[5]=='runtime-address'for args in self.calls),1)
        self.assertEqual(record['setters'],[])
        check_originals(self.out,record)

    def test_host_requires_originals_and_checks_them_after_wire_verification(self):
        from ws73_target import corroborate_runtime_addresses,HERE
        from ws73_north_star import file_record
        for kind in ['missing','changed','missing-pin','changed-during-proof']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory()as tmp:
                record,capture=fixture();share=Path(tmp);stage_record(share,record)
                path=share/'runtime-address/originals.json'
                def change():path.chmod(0o600);path.write_text('{}');path.chmod(0o400)
                if kind=='missing':path.unlink()
                elif kind=='changed':change()
                elif kind=='missing-pin':
                    del record['originals_record'];(path.parent/'run.json').write_text(json.dumps(record))
                def verify_then_change(*args):
                    result=corroborate(*args);change();return result
                with ExitStack()as stack:
                    if kind=='changed-during-proof':stack.enter_context(patch('ws73_runtime_address.corroborate',side_effect=verify_then_change))
                    with self.assertRaises((OSError,ValueError)):
                        corroborate_runtime_addresses(share,capture,ADDRESSES,file_record(HERE/'ws73_runtime_address.py'))

    def test_prepared_old_or_changed_helper_is_rejected_before_vm(self):
        from ws73_target import validate_runtime_address_guest
        from ws73_north_star import file_record
        path=self.root/'usr/share/sparklink/tools/ws73_runtime_address.py';path.parent.mkdir(parents=True)
        path.write_text('fixture current helper')
        pin=file_record(path);package=dict(guest_files=[pin]);verifier=dict(path='/host/helper',sha256=pin['sha256'])
        validate_runtime_address_guest(self.root,package,verifier)
        for kind in ['missing-pin','duplicate-pin','old-pin','old-helper','symlink']:
            with self.subTest(kind=kind):
                bad=copy.deepcopy(package);selected=copy.deepcopy(verifier)
                if kind=='missing-pin':bad['guest_files']=[]
                elif kind=='duplicate-pin':bad['guest_files']*=2
                elif kind=='old-pin':bad['guest_files'][0]['sha256']='0'*64
                elif kind=='old-helper':selected['sha256']='0'*64
                else:
                    other=path.with_suffix('.saved');path.rename(other);path.symlink_to(other)
                with self.assertRaises(ValueError):validate_runtime_address_guest(self.root,bad,selected)

    def test_terminal_record_cannot_drop_or_weaken_the_originals_requirement(self):
        from ws73_target import run_exit_code
        # Actual finalizer, synthetic terminal shape; not raw-wire evidence.
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,
            runtime_addresses_requested=ADDRESSES,
            qemu_args=['ws73.runtime_addresses='+','.join(ADDRESSES)],
            runtime_address_corroboration=[dict(fixture=True)]*2,
            runtime_address_record=dict(fixture=True),runtime_address_verifier=dict(fixture=True),
            runtime_address_originals_record=dict(path='/fixture/originals.json',sha256='1'*64))
        self.assertEqual(run_exit_code(record),0)
        for value in [None,{},True,dict(path='/fixture/originals.json'),
                      dict(path='/fixture/other.json',sha256='1'*64),
                      dict(path='/fixture/originals.json',sha256='bad')]:
            with self.subTest(value=value):
                self.assertNotEqual(run_exit_code(record|dict(runtime_address_originals_record=value)),0)
        for fields in [('runtime_address_originals_record',),
                       ('runtime_address_originals_record','runtime_addresses_requested'),
                       ('runtime_address_originals_record','runtime_addresses_requested','runtime_address_corroboration')]:
            bad=copy.deepcopy(record)
            for field in fields:del bad[field]
            self.assertNotEqual(run_exit_code(bad),0)


if __name__=='__main__':unittest.main()
