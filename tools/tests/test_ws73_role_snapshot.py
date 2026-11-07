# SPDX-License-Identifier: GPL-2.0-only
"""Actual snapshot/remap functions on finite local FS fixtures,no mount/Native."""
from pathlib import Path
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
import ws73_role_snapshot as snapshot


class ClosedSnapshot(unittest.TestCase):
    def test_shared_child_record_is_remapped_once_without_destination_fallback(self):
        child=dict(output_files=['/run/root/child.stdout','/run/root/child.stderr'],stdout='/run/root/literal',stderr='')
        row=dict(index=[child],operation=dict(actual_child=child))
        snapshot.remap_outputs(row,Path('/run/root'),Path('/evidence/closed'))
        self.assertIs(row['index'][0],row['operation']['actual_child'])
        self.assertEqual(child['output_files'],['/evidence/closed/child.stdout','/evidence/closed/child.stderr'])
        self.assertEqual(child['stdout'],'/run/root/literal')
        # Independent pre-mapped data is still rejected,not called an alias.
        with self.assertRaises(ValueError):snapshot.remap_outputs(dict(output_files=child['output_files'].copy()),Path('/run/root'),Path('/evidence/closed'))

    def test_outside_explicit_vm_cannot_mount_or_create_scratch(self):
        # A rejecting boundary,not a successful VM or Native dependency stub.
        with patch('ws73_application_role.require_vm',side_effect=CaptureError('outside disposable VM')):
            with patch.object(snapshot.subprocess,'run',side_effect=AssertionError('must not mount')):
                with self.assertRaises(CaptureError):
                    with snapshot.local_root():self.fail('outside VM yielded local storage')

    def fixture(self,root):
        source=root/'source';source.mkdir();destination=root/'exported'
        raw=b'{"stage":"checked","value":"deadbeef"}\n'
        (source/'reader.stdout').write_bytes(raw);(source/'reader.stderr').write_bytes(b'')
        row=dict(output_files=[str(source/'reader.stdout'),str(source/'reader.stderr')],stdout=raw.decode(),stderr='',nested=[dict(stdout=str(source/'literal-not-a-path'))])
        snapshot.remap_outputs(row,source,Path('/evidence/subscription-role/phase-0'))
        (source/'run.json').write_text(json.dumps(row)+'\n')
        return source,destination,raw

    def test_closed_bytes_paths_and_hashes_without_mutating_raw(self):
        with tempfile.TemporaryDirectory()as tmp:
            source,target,raw=self.fixture(Path(tmp));before=(source/'run.json').read_bytes()
            proof=snapshot.publish(source,target,phase=0,success=True)
            self.assertEqual(proof,snapshot.verify(target,phase=0,runtime_root=source))
            self.assertEqual((target/'reader.stdout').read_bytes(),raw)
            self.assertEqual((target/'run.json').read_bytes(),before)
            row=json.loads(before);self.assertEqual(row['output_files'],['/evidence/subscription-role/phase-0/reader.stdout','/evidence/subscription-role/phase-0/reader.stderr'])
            self.assertEqual(row['nested'][0]['stdout'],str(source/'literal-not-a-path'))
            self.assertEqual(proof['bytes'],sum(x['bytes']for x in proof['files'].values()))
            with self.assertRaises(CaptureError):snapshot.publish(source,target,phase=0,success=True)

    def test_original_artifact_mutations_and_incomplete_export_rejected(self):
        for kind in ('missing','truncated','extra','hash','scope','helper','false-success','bool-version','bool-phase','wrong-total','missing-file-entry'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory()as tmp:
                source,target,raw=self.fixture(Path(tmp));snapshot.publish(source,target,phase=0,success=True)
                path=target/snapshot.NAME;proof=json.loads(path.read_text())
                if kind=='missing':(target/'reader.stdout').unlink()
                elif kind=='truncated':(target/'reader.stdout').write_bytes(raw[:-1])
                elif kind=='extra':(target/'extra').write_bytes(b'x')
                elif kind=='hash':proof['files']['reader.stdout']['sha256']='0'*64
                elif kind=='scope':proof['source_root']='/different/source'
                elif kind=='helper':proof['helper_sha256']='0'*64
                elif kind=='false-success':proof['success']=False
                elif kind=='bool-version':proof['version']=True
                elif kind=='bool-phase':proof['phase']=False
                elif kind=='wrong-total':proof['bytes']+=1
                else:proof['files'].pop('reader.stdout')
                path.write_text(json.dumps(proof)+'\n')
                with self.assertRaises((CaptureError,FileNotFoundError)):snapshot.verify(target,phase=0,runtime_root=source)

    def test_failed_phase_keeps_bytes_without_success(self):
        with tempfile.TemporaryDirectory()as tmp:
            source,target,_=self.fixture(Path(tmp));snapshot.publish(source,target,phase=0,success=False)
            self.assertTrue((target/'reader.stdout').exists())
            with self.assertRaises(CaptureError):snapshot.verify(target,phase=0,runtime_root=source)

    def test_interrupted_actual_process_cannot_commit_staging_as_success(self):
        with tempfile.TemporaryDirectory()as tmp:
            source,target,_=self.fixture(Path(tmp))
            code='''import os,sys
from pathlib import Path
import ws73_role_snapshot as s
original=Path.rename
def die(self,target):os._exit(23)
Path.rename=die
s.publish(Path(sys.argv[1]),Path(sys.argv[2]),phase=0,success=True)
'''
            result=subprocess.run([sys.executable,'-c',code,str(source),str(target)],env=dict(os.environ,PYTHONPATH=str(Path(snapshot.__file__).parent)),capture_output=True)
            self.assertEqual(result.returncode,23);self.assertEqual(result.stderr,b'')
            self.assertTrue(target.with_name('.'+target.name+'.staging').is_dir());self.assertFalse(target.exists())
            with self.assertRaises(CaptureError):snapshot.verify(target,phase=0,runtime_root=source)
            with self.assertRaises(FileExistsError):snapshot.publish(source,target,phase=0,success=True)

    def test_symlinks_hardlinks_and_bounded_inventory(self):
        for kind in ('symlink','hardlink','bytes','entries','predeclared'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory()as tmp:
                root=Path(tmp);source,target,_=self.fixture(root)
                if kind=='symlink':(source/'link').symlink_to(root/'outside')
                elif kind=='hardlink':os.link(source/'reader.stdout',source/'alias')
                elif kind=='bytes':
                    with(source/'huge').open('wb')as stream:stream.truncate(4*1024*1024+1)
                elif kind=='entries':
                    for n in range(snapshot.FILES+1):(source/str(n)).write_text('x')
                else:(source/snapshot.NAME).write_text('{}')
                with self.assertRaises(CaptureError):snapshot.publish(source,target,phase=0,success=True)
                self.assertFalse(target.exists())

    def test_output_reference_scope_and_contract_fail_closed(self):
        for fields in (dict(output_files=['/outside/a.stdout','/outside/a.stderr']),dict(output_files=['/run/root/a.stdout']),dict(output_files=['/run/root/../a.stdout','/run/root/a.stderr'])):
            with self.assertRaises((CaptureError,ValueError)):snapshot.remap_outputs(copy.deepcopy(fields),Path('/run/root'),Path('/evidence/destination'))
        self.assertFalse(snapshot.requested({}));self.assertTrue(snapshot.requested({'ssap_subscription_snapshot_contract_version':1}))
        for version in (False,True,0,2,'1'):
            with self.assertRaises(CaptureError):snapshot.requested({'ssap_subscription_snapshot_contract_version':version})
