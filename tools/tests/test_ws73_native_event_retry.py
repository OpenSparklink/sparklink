"""Actual parser/selector/verdict with transcript fixtures; no kernel/VM claim."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_native_event_retry as gate


def fixture():
    owners=[dict(index=0,generation=9),dict(index=1,generation=13)]
    rows=[];receipts=[]
    for a,b in (owners,owners[::-1]):
        value=dict(index=a['index'],generation=a['generation'],sibling_index=b['index'],sibling_generation=b['generation'],
            initial_kernel_snapshot=True,retry_pending_with_lock_held=True,joined_with_lock_held=True,subscription_fd_closed=True,both_still_ready=True)
        receipts.append(value)
        rows.append(dict(exit=0,stderr='',args=[gate.BINARY,'--quiet','--ignored','--exact',gate.TEST,'--nocapture','--test-threads=1'],
            environment=dict(SPARKLINK_NATIVE_EVENT_VM='1',SPARKLINK_TEST_DBUS_DAEMON='/bin/dbus-daemon',SPARKLINK_NATIVE_EVENT_TARGET=f"{a['index']}:{a['generation']}",SPARKLINK_NATIVE_EVENT_SIBLING=f"{b['index']}:{b['generation']}"),
            stdout='running 1 test\nNativeRetryVm: '+json.dumps(value)+'\n.\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 214 filtered out; finished in 0.1s\n',
            start_monotonic_ns=100,end_monotonic_ns=200))
    binary=dict(path=gate.BINARY,sha256='1'*64)
    control=dict(connection_control=dict(owners=owners),native_event_retry_commands=rows,
        native_event_retry=dict(version=1,owners=owners,receipts=receipts,binary=binary))
    package=dict(native_vm={},native_event_retry_test=dict(version=1,program=dict(path='/staged'+gate.BINARY,sha256='1'*64)))
    return control,package


class NativeRetry(unittest.TestCase):
    def test_explicit_selectors(self):
        self.assertFalse(gate.boot_requested([]));self.assertTrue(gate.boot_requested([gate.TOKEN+'=1']))
        for value in [gate.TOKEN,gate.TOKEN+'=0',gate.TOKEN+'=true']:
            with self.subTest(value=value),self.assertRaises(ValueError):gate.boot_requested([value])
        with self.assertRaises(ValueError):gate.boot_requested([gate.TOKEN+'=1']*2)
        a=SimpleNamespace(native_event_retry_verify=True,qmp_hotplug=True,connection_verify=True,channel_socket_verify=True)
        c,p=fixture();self.assertTrue(gate.requested(a,p))
        for key in ['qmp_hotplug','connection_verify','channel_socket_verify']:
            b=copy.copy(a);setattr(b,key,False)
            with self.subTest(key=key),self.assertRaises(ValueError):gate.requested(b,p)
        with self.assertRaises(ValueError):gate.requested(a,{})
        a.native_event_retry_verify=1
        with self.assertRaises(ValueError):gate.requested(a,p)

    def test_staging_identity_and_private_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';(root/'bin').mkdir(parents=True)
            binary=Path(tmp)/'compiled';binary.write_bytes(b'explicit ELF-copy fixture, not executable')
            spec=Path(tmp)/'input.json';data=dict(version=1,source_head='1'*40,binary=gate.pin(binary));spec.write_text(json.dumps(data))
            manifest=dict(userspace_head='1'*40,inputs=[],unstripped_programs=[])
            # ELF/dependency copying is an explicit fixture; actual prepare uses copy_elf.
            gate.stage(spec,root,manifest,lambda source,target,root:shutil.copyfile(source,target))
            self.assertEqual(manifest['native_event_retry_test']['input'],data['binary'])
            self.assertTrue((root/gate.CONFIG.lstrip('/')).is_file())
            for mode in ['source','version','binary']:
                changed=copy.deepcopy(data)
                if mode=='source':changed['source_head']='2'*40
                elif mode=='version':changed['version']=True
                else:changed['binary']['sha256']='3'*64
                spec.write_text(json.dumps(changed))
                with self.subTest(mode=mode),self.assertRaises(ValueError):gate.stage(spec,root,manifest,lambda *args:None)

    def test_actual_cli(self):
        import ws73_target
        with patch.object(sys,'argv',['ws73_target.py','run','--prepared','/tmp/prepared','--output','/tmp/output','--ports','1-1.1.1','1-1.1.2','--qmp-hotplug','--connection-verify','--channel-socket-verify','--native-event-retry-verify']),patch.object(ws73_target,'run',return_value=0)as run:
            self.assertEqual(ws73_target.main(),0);self.assertTrue(run.call_args.args[0].native_event_retry_verify)

    def test_transcript_and_terminal_negative_controls(self):
        c,p=fixture();proof=gate.corroborate(c,p)
        m=dict(native_event_retry_requested=True,native_event_retry_acceptance=True,native_event_retry_test=p['native_event_retry_test'],native_event_retry_corroboration=proof)
        self.assertTrue(gate.accepted(m));self.assertTrue(gate.accepted({}))
        for mode in ['missing','zero-tests','timeout','wrong-id','boolean-id','no-fd-close','bad-binary','negative-time','late','wrong-command','false-exit']:
            bad=copy.deepcopy(c);row=bad['native_event_retry_commands'][0]
            if mode=='missing':bad['native_event_retry_commands'].pop()
            elif mode=='zero-tests':row['stdout']=row['stdout'].replace('1 passed','0 passed')
            elif mode=='timeout':row['exit']='timeout'
            elif mode in ['wrong-id','boolean-id','no-fd-close']:
                value=copy.deepcopy(bad['native_event_retry']['receipts'][0]);value[{'wrong-id':'generation','boolean-id':'index','no-fd-close':'subscription_fd_closed'}[mode]]={'wrong-id':12,'boolean-id':False,'no-fd-close':False}[mode]
                lines=row['stdout'].splitlines();lines[1]='NativeRetryVm: '+json.dumps(value);row['stdout']='\n'.join(lines)+'\n'
            elif mode=='bad-binary':bad['native_event_retry']['binary']['sha256']='2'*64
            elif mode=='negative-time':row['end_monotonic_ns']=0
            elif mode=='late':row['end_monotonic_ns']=10_000_000_101
            elif mode=='wrong-command':row['args'][4]='different_test'
            else:row['exit']=False
            with self.subTest(mode=mode),self.assertRaises(ValueError):gate.corroborate(bad,p)
        for mode in ['requested','acceptance','version','receipt','binary','identity','count']:
            bad=copy.deepcopy(m)
            if mode=='requested':bad['native_event_retry_requested']=False
            elif mode=='acceptance':bad['native_event_retry_acceptance']=False
            elif mode=='version':bad['native_event_retry_corroboration']['version']=True
            elif mode=='receipt':bad['native_event_retry_corroboration']['receipts'].pop()
            elif mode=='binary':bad['native_event_retry_corroboration']['binary']['sha256']='2'*64
            elif mode=='identity':bad['native_event_retry_corroboration']['receipts'][0]['generation']+=1
            else:bad['native_event_retry_corroboration']['actual_subscriptions']=True
            with self.subTest(mode=mode):self.assertFalse(gate.accepted(bad))


if __name__=='__main__':unittest.main()
