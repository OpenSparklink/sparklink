"""Real text-producing children,not an SDK/controller/peer implementation.

The ENODATA read is a visible injected filesystem dependency. Existing kernel
9p root cause is unproved;the actual old stack is retained separately. No
Native syscall,wire parser,security decision or application delivery is stubbed.
"""
import copy
import errno
import fcntl
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from ws73_capture import CaptureError
from ws73_ssap_owned import observed_process,output_text,wait_text,verify_output,OUTPUT_MAXIMUM,wait_output
from ws73_ssap_update_delivery import command_receipt
from ws73_ssap_subscription import app_rows,wait_stage,verify_outputs,require_current_output


class SsapOutput(unittest.TestCase):
    def test_reader_real_split_pipe_ignores_injected_live_file_read_failure(self):
        with tempfile.TemporaryDirectory()as tmp:
            out,err=[Path(tmp)/n for n in ('stdout','stderr')];app={}
            program="import os;os.write(1,b'{\"stage\":\"ready\"}\\n{\"sta');assert input()=='finish';os.write(1,b'ge\":\"done\"}\\n');assert input()=='quit'"
            with observed_process([sys.executable,'-c',program],app,out,err,stdin=subprocess.PIPE,text=True)as proc:
                actual=Path.read_text
                def fail_live_read(path,*a,**kw):
                    if path==out:raise OSError(errno.ENODATA,'explicit reader live-file dependency failure')
                    return actual(path,*a,**kw)
                with patch.object(Path,'read_text',fail_live_read):
                    with self.assertRaises(OSError):out.read_text()
                    self.assertEqual(wait_stage(proc,app,'ready',1,time.monotonic()+2),dict(stage='ready'))
                    self.assertEqual(app_rows(proc,app),[dict(stage='ready')])
                    proc.stdin.write('finish\n');proc.stdin.flush()
                    self.assertEqual(wait_stage(proc,app,'done',1,time.monotonic()+2),dict(stage='done'))
                proc.stdin.write('quit\n');proc.stdin.flush();self.assertEqual(wait_output(proc,2),0)
            verify_output(app);self.assertEqual(app['stdout'],out.read_text())
            self.assertEqual(app['stdout'],'{"stage":"ready"}\n{"stage":"done"}\n')

    def test_reader_never_falls_back_to_unobserved_or_wrong_path_file(self):
        with tempfile.TemporaryDirectory()as tmp:
            out,err=[Path(tmp)/n for n in ('stdout','stderr')];out.write_text('{"stage":"fake"}\n')
            with self.assertRaises(CaptureError):app_rows(SimpleNamespace(),dict(output_files=[str(out)]))
            out.unlink();app={}
            with observed_process([sys.executable,'-c',"print('{}',flush=True);input()"],app,out,err,stdin=subprocess.PIPE,text=True)as proc:
                foreign=dict(app,output_files=[str(Path(tmp)/'foreign')])
                with self.assertRaises(CaptureError):app_rows(proc,foreign)

    def test_reader_original_row_budget_duplicate_malformed_and_deadline_reject(self):
        fixtures=[('budget',"import os;os.write(1,b'{}\\n'*25);input()"),
                  ('duplicate',"print('{\"stage\":\"ready\"}\\n{\"stage\":\"ready\"}',flush=True);input()"),
                  ('malformed',"print('{bad}',flush=True);input()"),
                  ('deadline',"input()"),('EOF',"print('{}',flush=True)")]
        for case,program in fixtures:
            with self.subTest(case=case),tempfile.TemporaryDirectory()as tmp:
                out,err=[Path(tmp)/n for n in ('stdout','stderr')];app={}
                with self.assertRaises(CaptureError):
                    with observed_process([sys.executable,'-c',program],app,out,err,stdin=subprocess.PIPE,text=True)as proc:
                        wait_stage(proc,app,'ready',1,time.monotonic()+.15)

    def test_reader_complete_pipe_contract_does_not_replace_raw_or_current_identity(self):
        # Real child stream and report-only composition,not a provider/SDK stub.
        for newline in (True,False):
            with self.subTest(newline=newline),tempfile.TemporaryDirectory()as tmp:
                out,err=[Path(tmp)/n for n in ('stdout','stderr')];app={}
                raw='{}\n'if newline else'{}'
                with observed_process([sys.executable,'-c','import os;os.write(1,'+repr(raw.encode())+')'],app,out,err,text=True)as proc:
                    wait_output(proc,2)
                row=dict(ssap_subscription_output_contract_version=1,
                         ssap_subscription=[dict(app,leases=[dict(application=copy.deepcopy(app))])])
                if not newline:
                    with self.assertRaises(CaptureError):verify_outputs(row)
                    continue
                require_current_output(row);verify_outputs(row)
                for change in ('incomplete','bytes','budget','cleanup','version'):
                    bad=copy.deepcopy(row);reader=bad['ssap_subscription'][0]['leases'][0]['application']
                    if change=='incomplete':reader['output_collection']['complete']=False
                    elif change=='bytes':reader['captured_bytes']['stdout']+=1
                    elif change=='budget':reader['output_collection']['maximum_bytes_per_stream']+=1
                    elif change=='cleanup':reader['output_cleanup_errors']=[dict(error='retained original failure')]
                    else:bad['ssap_subscription_output_contract_version']=True
                    with self.subTest(change=change),self.assertRaises(CaptureError):verify_outputs(bad)
                for value in (None,True,0,2,'1'):
                    with self.subTest(value=value),self.assertRaises(CaptureError):
                        require_current_output(dict(ssap_subscription_output_contract_version=value))

    def test_exit_wait_drains_real_small_pipe_without_extending_deadline(self):
        with tempfile.TemporaryDirectory()as tmp:
            out,err=[Path(tmp)/n for n in ('stdout','stderr')];item={}
            program="import sys,os;print('ready',flush=True);assert input()=='write';os.write(1,b'x'*50000)"
            with observed_process([sys.executable,'-c',program],item,out,err,stdin=subprocess.PIPE,text=True)as proc:
                wait_text(proc,out,'^ready$',time.monotonic()+2)
                fcntl.fcntl(proc.stdout.fileno(),fcntl.F_SETPIPE_SZ,4096)
                proc.stdin.write('write\n');proc.stdin.flush()
                with self.assertRaises(subprocess.TimeoutExpired):proc.wait(timeout=.05)
                self.assertEqual(wait_output(proc,2),0)
            verify_output(item);self.assertEqual(item['captured_bytes']['stdout'],50006)

    def test_exit_wait_has_finite_original_budget(self):
        with tempfile.TemporaryDirectory()as tmp:
            out,err=[Path(tmp)/n for n in ('stdout','stderr')];item={}
            with self.assertRaises(subprocess.TimeoutExpired):
                with observed_process([sys.executable,'-c',"input()"],item,out,err,stdin=subprocess.PIPE,text=True)as proc:
                    wait_output(proc,.05)

    def test_real_pipe_receipt_does_not_reopen_live_evidence_file(self):
        with tempfile.TemporaryDirectory()as tmp:
            out,err=[Path(tmp)/n for n in ('stdout','stderr')];item={}
            program="import json,sys;print('ready',flush=True);assert sys.stdin.readline()=='configuration\\n';print('Receipt: '+json.dumps(dict(value=7)),flush=True);assert sys.stdin.readline()=='quit\\n'"
            with observed_process([sys.executable,'-c',program],item,out,err,stdin=subprocess.PIPE,text=True)as proc:
                actual=Path.read_text
                def failing_read(path,*args,**kw):
                    if path==out:raise OSError(errno.ENODATA,'explicit live artifact read failure')
                    return actual(path,*args,**kw)
                with patch.object(Path,'read_text',failing_read):
                    with self.assertRaises(OSError):out.read_text()
                    self.assertEqual(wait_text(proc,out,'^ready$',time.monotonic()+2)[0],['ready'])
                    receipt=command_receipt(proc,item,'configuration','Receipt')
                    self.assertEqual(receipt['receipt'],dict(value=7))
                    self.assertEqual(output_text(proc,err),'')
                proc.stdin.write('quit\n');proc.stdin.flush();proc.wait(timeout=2)
            verify_output(item)
            self.assertEqual(item['exit'],0)
            self.assertEqual(out.read_text(),item['stdout'])
            for case in ('incomplete','bytes','budget','cleanup'):
                bad=copy.deepcopy(item)
                if case=='incomplete':bad['output_collection']['complete']=False
                elif case=='bytes':bad['captured_bytes']['stdout']+=1
                elif case=='budget':bad['output_collection']['maximum_bytes_per_stream']+=1
                else:bad['output_cleanup_errors']=[dict(error='original sink failure')]
                with self.subTest(case=case),self.assertRaises(CaptureError):verify_output(bad)

    def test_unobserved_or_wrong_child_path_never_falls_back_to_file(self):
        with tempfile.TemporaryDirectory()as tmp:
            out,err=[Path(tmp)/n for n in ('stdout','stderr')];out.write_text('fake ready')
            with self.assertRaises(CaptureError):wait_text(SimpleNamespace(),out,'.',time.monotonic()+1)
            out.unlink();item={}
            with observed_process([sys.executable,'-c',"print('real')"],item,out,err,text=True)as proc:
                with self.assertRaises(CaptureError):output_text(proc,Path(tmp)/'foreign')
                proc.wait(timeout=2)
            verify_output(item)

    def test_original_deadline_and_missing_receipt_still_fail(self):
        with tempfile.TemporaryDirectory()as tmp:
            out,err=[Path(tmp)/n for n in ('stdout','stderr')];item={}
            with self.assertRaises(CaptureError):
                with observed_process([sys.executable,'-c',"print('wrong',flush=True);input()"],item,out,err,stdin=subprocess.PIPE,text=True)as proc:
                    wait_text(proc,out,'^missing$',time.monotonic()+.05)
            self.assertEqual(item['exit'],-9)

    def test_final_decode_failure_is_not_pass_or_a_replacement_for_author_failure(self):
        for primary in (False,True):
            with self.subTest(primary=primary),tempfile.TemporaryDirectory()as tmp:
                out,err=[Path(tmp)/n for n in ('stdout','stderr')];item={}
                with self.assertRaises(RuntimeError if primary else UnicodeDecodeError):
                    with observed_process([sys.executable,'-c',"import os;os.write(1,b'\\xe6')"],item,out,err,text=True)as proc:
                        proc.wait(timeout=2)
                        if primary:raise RuntimeError('original author failure')
                self.assertFalse(item['output_collection']['complete'])
                self.assertEqual(item['output_cleanup_errors'][0]['error_type'],'UnicodeDecodeError')
                with self.assertRaises(CaptureError):verify_output(item)

    def test_actual_pipe_byte_budget_is_finite(self):
        with tempfile.TemporaryDirectory()as tmp:
            out,err=[Path(tmp)/n for n in ('stdout','stderr')];item={}
            with self.assertRaises(CaptureError):
                with observed_process([sys.executable,'-c',f"import os;os.write(1,b'x'*{OUTPUT_MAXIMUM+1})"],item,out,err,text=True)as proc:
                    wait_text(proc,out,'^impossible$',time.monotonic()+3)
            self.assertEqual(item['output_collection_error']['operation'],'byte-budget')

