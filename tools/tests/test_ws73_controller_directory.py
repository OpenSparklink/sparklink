"""Actual parser/process recorder with explicit data fixtures, no WS73 proof."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import hashlib
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_controller_directory as gate
from ws73_daemon_hold import Invocation

class DirectoryObserver(unittest.TestCase):
    def fixture(self):
        a=dict(path='/org/sparklink/slk0_g1',index=0,generation=1)
        b=dict(path='/org/sparklink/slk1_g2',index=1,generation=2)
        n=dict(path='/org/sparklink/slk0_g3',index=0,generation=3)
        text=f"ControllerDirectorySnapshot: cursor=2 controllers={a['path']}|{b['path']}\nControllerDirectoryEvent: sequence=3 action=withdrawn path={a['path']}\nControllerDirectoryEvent: sequence=4 action=published path={n['path']}\n"
        daemon={'pid':10,'start':11}
        record=dict(status='COMPLETE_NOT_QUALIFIED',source={'sha256':'b'*64},program={'sha256':'a'*64},daemon_before=daemon,daemon_after=daemon,
            invocation={'pid':12,'exit':0,'stdout':text,'stderr':'','args':['/bin/slctl','controller-events','3','30000']},
            process={'pid':12,'uids':[1001]*4,'gids':[1001]*4,'groups':[],'caps':{'CapEff':0,'CapPrm':0,'CapAmb':0},'native_fds':[],'program_sha256':'a'*64})
        control=dict(initial=[a,b],replacement=n,daemon_before=daemon,daemon_after=daemon)
        return record,control

    def test_guest_absolute_alias_is_checked_inside_staged_root(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name);target='/usr/libexec/opensparklink/native-lab/'+'a'*12+'/slctl'
            actual=root/target.lstrip('/');actual.parent.mkdir(parents=True);actual.write_bytes(b'explicit ELF-identity fixture,not executable')
            (root/'bin').mkdir();(root/'bin/slctl').symlink_to(target)
            files=[{'path':str(actual),'sha256':hashlib.sha256(actual.read_bytes()).hexdigest()}]
            self.assertEqual(gate.staged_program(root,files)['sha256'],files[0]['sha256'])
            actual.write_bytes(b'changed')
            with self.assertRaises(ValueError):gate.staged_program(root,files)

    def test_actual_parser_and_scope_with_negative_mutations(self):
        r,c=self.fixture();proof=gate.corroborate(r,c,'a'*64,'b'*64);self.assertTrue(gate.valid_summary(proof))
        for name,mutate in [
            ('incomplete',lambda r:r['invocation'].__setitem__('stdout',r['invocation']['stdout'].rsplit('\n',2)[0]+'\n')),
            ('sequence',lambda r:r['invocation'].__setitem__('stdout',r['invocation']['stdout'].replace('sequence=4','sequence=5'))),
            ('stale',lambda r:r['invocation'].__setitem__('stdout',r['invocation']['stdout'].replace('published path=/org/sparklink/slk0_g3','published path=/org/sparklink/slk0_g1'))),
            ('wrong-image',lambda r:r['process'].__setitem__('program_sha256','c'*64)),
            ('wrong-verifier',lambda r:r['source'].__setitem__('sha256','c'*64)),
            ('uid',lambda r:r['process'].__setitem__('uids',[0]*4)),
            ('extra-group',lambda r:r['process'].__setitem__('groups',[1000])),
            ('caps',lambda r:r['process']['caps'].__setitem__('CapEff',1)),
            ('raw-fd',lambda r:r['process'].__setitem__('native_fds',['/dev/sparklink'])),
            ('false-exit',lambda r:r['invocation'].__setitem__('exit',False)),
            ('unreaped',lambda r:r.__setitem__('status','RUNNING_NOT_QUALIFIED')),
            ('restarted',lambda r:r['daemon_after'].__setitem__('pid',11))]:
            # Keep distinct daemon objects in fixture before testing mutation.
            bad=copy.deepcopy(r);bad['daemon_after']=dict(bad['daemon_after']);mutate(bad)
            with self.subTest(name=name),self.assertRaises((ValueError,KeyError)):gate.corroborate(bad,c,'a'*64,'b'*64)
        for change in [{},dict(proof,event_count=False),dict(proof,native_event_acceptance=True),dict(proof,verifier_sha256='bad')]:
            self.assertFalse(gate.valid_summary(change))

    def test_explicit_request_excludes_synthetic_or_other_scope(self):
        self.assertFalse(gate.requested(SimpleNamespace()))
        good=SimpleNamespace(controller_directory_events=True,qmp_hotplug=True,native_controller_return='initiator')
        self.assertTrue(gate.requested(good))
        for key,value in [('controller_directory_events',1),('qmp_hotplug',False),('native_controller_return',None)]:
            bad=copy.copy(good);setattr(bad,key,value)
            with self.assertRaises(ValueError):gate.requested(bad)

    def test_actual_shared_pipe_recorder_preserves_prefix_and_exit(self):
        r,_=self.fixture();text=r['invocation']['stdout']
        p=Invocation([sys.executable,'-c',f'import sys,time;print({text!r},end="",flush=True);time.sleep(.05)'],'directory-fixture')
        p.until(gate.SNAPSHOT,timeout=1,limit=16384,label='actual directory snapshot')
        row=p.finish();self.assertEqual(row['exit'],0);self.assertEqual(row['stdout'],text)
        self.assertEqual(gate.parse(row['stdout'])['before'],2)

    def languages(self):
        r,c=self.fixture()
        clients=dict(version=1,c=dict(path='/bin/controller-directory-client',sha256='c'*64),
            python=dict(path='/usr/bin/python3.14',sha256='d'*64),
            script=dict(path='/usr/share/sparklink/tools/ws73_controller_directory_client.py',sha256='e'*64),
            library=dict(path='/usr/lib/libsparklink.so.0',sha256='f'*64))
        children={}
        for language in ['c','python']:
            raw=copy.deepcopy(r);raw['program']=dict(clients[language]);raw['process']['program_sha256']=clients[language]['sha256']
            maps='00000000-00001000 r--p 00000000 00:01 1 /usr/lib/libsparklink.so.0\n'
            raw['process'].update(native_library_loaded=False,loaded_library=dict(clients['library']),maps=maps,maps_sha256=hashlib.sha256(maps.encode()).hexdigest())
            raw['invocation']['args']=gate.consumer_args(language,clients)
            raw['consumer_source']=clients['script']if language=='python'else None
            children[language]=raw
        r['languages']=children
        return r,c,clients

    def test_both_languages_mapped_library_source_and_original_rust_are_required(self):
        r,c,clients=self.languages();proof=gate.corroborate_all(r,c,'a'*64,'b'*64,clients);self.assertTrue(gate.valid_all_summary(proof))
        for language in ['c','python']:
            for mutate in [lambda x:x['languages'].pop(language),
                lambda x:x['languages'][language]['process']['loaded_library'].update(sha256='0'*64),
                lambda x:x['languages'][language]['process'].update(native_library_loaded=True),
                lambda x:x['languages'][language]['process'].update(program_sha256='0'*64),
                lambda x:x['languages'][language]['process'].update(uids=[0]*4),
                lambda x:x['languages'][language]['invocation'].update(exit=1),
                lambda x:x['languages'][language]['invocation'].update(stdout=x['invocation']['stdout'].replace('slk0_g3','slk0_g9'))]:
                bad=copy.deepcopy(r);mutate(bad)
                with self.assertRaises((ValueError,KeyError)):gate.corroborate_all(bad,c,'a'*64,'b'*64,clients)
            bad=copy.deepcopy(proof);bad['languages'].pop(language);self.assertFalse(gate.valid_all_summary(bad))
        bad=copy.deepcopy(r);bad['languages']['python']['consumer_source']=None
        with self.assertRaises(ValueError):gate.corroborate_all(bad,c,'a'*64,'b'*64,clients)
        for change in [dict(proof,program_sha256='0'*64),dict(proof,prepared_clients={}),dict(proof,rust={})]:self.assertFalse(gate.valid_all_summary(change))

    def test_sealed_staged_consumers_and_manifest_reject_missing_changed_or_escaped_inputs(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name)
            names=['/bin/controller-directory-client','/usr/bin/python3.14','/usr/share/sparklink/tools/ws73_controller_directory_client.py','/usr/lib/libsparklink.so.0']
            for path in names:
                p=root/path.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'explicit nonexecuted identity fixture:'+path.encode())
            script=root/names[2].lstrip('/');compilation=dict(script=dict(sha256=hashlib.sha256(script.read_bytes()).hexdigest()))
            value=gate.stage_clients(root,'python3.14',compilation)
            files=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())for p in root.rglob('*')if p.is_file()]
            self.assertEqual(gate.staged_clients(root,files,value),value)
            for bad in [None,{},dict(value,version=True),dict(value,library=dict(path='/tmp/elsewhere',sha256='f'*64))]:
                with self.assertRaises(ValueError):gate.staged_clients(root,files,bad)
            with self.assertRaises(ValueError):gate.staged_clients(root,files[:-1],value)
            library=root/names[-1].lstrip('/');library.write_bytes(b'changed')
            with self.assertRaises(ValueError):gate.staged_clients(root,files,value)
            library.unlink();library.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):gate.staged_clients(root,files,value)

    def test_actual_c_consumer_build_and_argument_failure_are_not_an_event_pass(self):
        import os
        source=Path(gate.__file__).parent/'testing/controller_events/client.c'
        header=Path(gate.__file__).parents[1]/'crates/libsparklink/include'
        with tempfile.TemporaryDirectory()as name:
            binary=Path(name)/'consumer'
            subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror','-I'+str(header),str(source),'-ldl','-o',str(binary)],check=True)
            for args in [[],['/explicitly-missing-app-library']]:
                result=subprocess.run([str(binary),*args],capture_output=True,text=True,timeout=3)
                self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,'');self.assertTrue(result.stderr)

    def test_host_without_explicit_native_vm_is_rejected_before_start(self):
        p=subprocess.run([sys.executable,gate.__file__,'--daemon-pid','1'],capture_output=True,text=True,timeout=5)
        self.assertNotEqual(p.returncode,0);self.assertIn('no process started',p.stderr)

if __name__=='__main__':unittest.main()
