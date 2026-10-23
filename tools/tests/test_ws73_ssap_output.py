"""Real text-producing children,not an SDK/controller/peer implementation.

The ENODATA read is a visible injected filesystem dependency. Existing kernel
9p root cause is unproved;the actual old stack is retained separately. No
Native syscall,wire parser,security decision or application delivery is stubbed.
"""
import copy
import errno
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from ws73_capture import CaptureError
from ws73_ssap_owned import observed_process,output_text,wait_text,verify_output,OUTPUT_MAXIMUM
from ws73_ssap_update_delivery import command_receipt


class SsapOutput(unittest.TestCase):
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

