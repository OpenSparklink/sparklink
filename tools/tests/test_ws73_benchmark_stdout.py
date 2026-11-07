# SPDX-License-Identifier: GPL-2.0-only
"""Actual local child/pipe capture;no VM,Native,USB or protocol-success fixture."""
import ast
import copy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_socket_benchmark as gate
from ws73_capture import CaptureError


class BenchmarkStdout(unittest.TestCase):
    def child(self, tail, exit_code=0, *, retained_writer=False):
        code='import os,sys;os.write(1,bytes.fromhex(sys.argv[1]));sys.exit(int(sys.argv[2]))'
        args=[sys.executable,'-c',code,tail.hex(),str(exit_code)]
        if retained_writer:
            read,write=os.pipe()
            self.addCleanup(os.close,write)
            proc=subprocess.Popen(args,stdout=write,stdin=subprocess.PIPE)
            proc.stdout=os.fdopen(read,'rb',buffering=0)
        else:proc=subprocess.Popen(args,stdout=subprocess.PIPE,stdin=subprocess.PIPE,bufsize=0)
        self.addCleanup(proc.stdout.close);self.addCleanup(proc.stdin.close)
        proc.wait(timeout=5)
        return proc

    def test_tail_after_reap_is_not_lost_and_prefix_is_not_duplicated(self):
        proc=self.child(b'first\nlast\n');prefix=os.read(proc.stdout.fileno(),6)
        raw,receipt=gate.capture_stdout(proc,prefix,time.monotonic()+1)
        self.assertEqual(raw,b'first\nlast\n');self.assertTrue(receipt['complete']);self.assertTrue(proc.stdout.closed)
        app=dict(stdout=raw.decode(),stdout_capture=receipt);gate.check_stdout_capture(app)
        self.assertEqual(receipt['observed_bytes_at_least'],len(raw))
        self.assertEqual(receipt['sha256'],hashlib.sha256(raw).hexdigest())

    def test_nonzero_exit_and_failure_are_separate_from_complete_capture(self):
        proc=self.child(b'SocketBenchmarkQuiescent: mode=Window correctness=true\n',23)
        raw,receipt=gate.capture_stdout(proc,b'',time.monotonic()+1)
        self.assertTrue(receipt['complete']);self.assertEqual(proc.returncode,23)
        self.assertIn(b'Quiescent',raw) # Raw text is not an observed live barrier.

    def test_exact_limit_passes_but_extra_bytes_are_bounded_and_refused(self):
        for tail,valid in [(b'abcdef',True),(b'abcdefg',False)]:
            with self.subTest(tail=tail):
                proc=self.child(tail);raw,receipt=gate.capture_stdout(proc,b'x'*(gate.STDOUT_LIMIT-6),time.monotonic()+1)
                self.assertEqual(len(raw),gate.STDOUT_LIMIT);self.assertEqual(receipt['complete'],valid)
                self.assertEqual(receipt['limit_exceeded'],not valid)
                self.assertEqual(receipt['observed_bytes_at_least'],gate.STDOUT_LIMIT+(not valid))
                self.assertTrue(proc.stdout.closed)
                if valid:gate.check_stdout_capture(dict(stdout=raw.decode(),stdout_capture=receipt))
                else:
                    with self.assertRaises(CaptureError):gate.check_stdout_capture(dict(stdout=raw.decode(),stdout_capture=receipt))
        proc=self.child(b'');raw,receipt=gate.capture_stdout(proc,b'x'*(gate.STDOUT_LIMIT+1),time.monotonic()+1)
        self.assertEqual(len(raw),gate.STDOUT_LIMIT);self.assertFalse(receipt['complete']);self.assertTrue(receipt['limit_exceeded'])

    def test_writer_retained_after_exit_cannot_block_or_synthesize_eof(self):
        # An extra real write-fd has the same pipe EOF condition as a descendant
        # holding stdout;not a claim to exercise fork/SCM_RIGHTS lifecycle.
        proc=self.child(b'actual tail\n',retained_writer=True);begin=time.monotonic()
        raw,receipt=gate.capture_stdout(proc,b'',begin+.05)
        self.assertEqual(raw,b'actual tail\n');self.assertFalse(receipt['eof']);self.assertFalse(receipt['complete'])
        self.assertIn('deadline',receipt['error']);self.assertTrue(proc.stdout.closed)
        self.assertLess(time.monotonic()-begin,2) # Hang guard,not real-time latency qualification.
        with self.assertRaises(CaptureError):gate.check_stdout_capture(dict(stdout=raw.decode(),stdout_capture=receipt))

    def test_invalid_utf8_and_closed_pipe_preserve_raw_or_explicit_error(self):
        proc=self.child(b'\xff');raw,receipt=gate.capture_stdout(proc,b'',time.monotonic()+1)
        self.assertEqual(raw,b'\xff');self.assertTrue(receipt['eof']);self.assertFalse(receipt['utf8_valid']);self.assertFalse(receipt['complete'])
        self.assertEqual(receipt['sha256'],hashlib.sha256(b'\xff').hexdigest())
        proc=self.child(b'');proc.stdout.close();raw,receipt=gate.capture_stdout(proc,b'known',time.monotonic()+1)
        self.assertEqual(raw,b'known');self.assertFalse(receipt['complete']);self.assertFalse(receipt['eof']);self.assertIn('ValueError',receipt['error'])

    def test_selected_capture_metadata_and_bytes_fail_closed(self):
        proc=self.child(b'actual\n');raw,receipt=gate.capture_stdout(proc,b'',time.monotonic()+1)
        app=dict(stdout=raw.decode(),stdout_capture=receipt);gate.check_stdout_capture(app)
        for field,value in [('version',True),('eof',False),('complete',False),('utf8_valid',False),('limit_exceeded',True),('error','missing'),('bytes',True),('observed_bytes_at_least',8),('sha256','0'*64),('deadline_monotonic_ns',receipt['end_monotonic_ns']-1),('end_monotonic_ns',0)]:
            bad=copy.deepcopy(app);bad['stdout_capture'][field]=value
            with self.subTest(field=field),self.assertRaises(CaptureError):gate.check_stdout_capture(bad)
        for bad in [dict(stdout=app['stdout']),dict(stdout=app['stdout']+' ',stdout_capture=receipt)]:
            with self.assertRaises(CaptureError):gate.check_stdout_capture(bad)

    def test_actual_storage_keeps_invalid_bytes_and_original_exception_on_io_error(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);proc=self.child(b'raw\xff\n');app={};target=root/'raw.stdout'
            gate.store_stdout_capture(proc,app,b'',target,time.monotonic()+1)
            self.assertEqual(target.read_bytes(),b'raw\xff\n');self.assertFalse(app['stdout_capture']['complete'])
            # Actual IsADirectoryError in the production storage helper must
            # not mask the original supervision exception during finally.
            proc=self.child(b'late tail\n',23);app={};original=CaptureError('original SSAP exception')
            try:
                try:raise original
                finally:gate.store_stdout_capture(proc,app,b'',root,time.monotonic()+1)
            except CaptureError as caught:self.assertIs(caught,original)
            else:self.fail('original exception lost')
            self.assertEqual(app['stdout'],'late tail\n');self.assertTrue(app['stdout_capture']['eof'])
            self.assertFalse(app['stdout_capture']['complete']);self.assertIn('stdout storage',app['stdout_capture']['error'])

    def test_expired_deadline_keeps_known_prefix_without_new_read(self):
        proc=self.child(b'unread');raw,receipt=gate.capture_stdout(proc,b'known',time.monotonic()-1)
        self.assertEqual(raw,b'known');self.assertFalse(receipt['eof']);self.assertFalse(receipt['complete'])
        self.assertIn('deadline',receipt['error']);self.assertTrue(proc.stdout.closed)

    def test_actual_supervision_validator_requires_every_selected_capture(self):
        # Existing synthetic report/credential metadata fixture only;this is
        # not a claim that a Native application or real device was run.
        from test_ws73_socket_benchmark import fixture
        with tempfile.TemporaryDirectory()as directory:
            run,_=fixture(Path(directory));row=run['socket_benchmark'][0]
            gate.check_supervision(row);row[gate.STDOUT_FIELD]=1
            for app in row['applications']:
                proc=self.child(app['stdout'].encode());raw,proof=gate.capture_stdout(proc,b'',time.monotonic()+1)
                self.assertEqual(raw.decode(),app['stdout']);app['stdout_capture']=proof
            gate.check_supervision(row)
            for case in ('missing','no-eof','bad-hash','bool-version','absent-selector'):
                bad=copy.deepcopy(row)
                if case=='missing':bad['applications'][0].pop('stdout_capture')
                elif case=='no-eof':bad['applications'][0]['stdout_capture']['eof']=False
                elif case=='bad-hash':bad['applications'][0]['stdout_capture']['sha256']='0'*64
                elif case=='bool-version':bad[gate.STDOUT_FIELD]=True
                else:bad.pop(gate.STDOUT_FIELD)
                with self.subTest(case=case),self.assertRaises(CaptureError):gate.check_supervision(bad)

    def test_actual_supervisor_normal_and_failure_paths_share_capture_without_markers(self):
        # Source wiring only;the OS tests above exercise the actual reader.
        # This does not fake a successful VM or Native syscall dependency.
        tree=ast.parse(Path(gate.__file__).read_text())
        live=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='execute_supervised')
        nested={n.name:n for n in live.body if isinstance(n,ast.FunctionDef)}
        calls=lambda node,name:[n for n in ast.walk(node)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id==name]
        self.assertEqual(len(calls(nested['collect_stdout'],'store_stdout_capture')),1)
        self.assertEqual(len(calls(nested['collect_ends'],'collect_stdout')),1)
        attempt=next(n for n in live.body if isinstance(n,ast.Try))
        self.assertEqual(sum(len(calls(n,'collect_stdout'))for n in attempt.finalbody),1)
        self.assertFalse(calls(nested['collect_stdout'],'event'));self.assertFalse(calls(nested['collect_stdout'],'release'))
        self.assertFalse(any(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr=='read'for n in ast.walk(nested['collect_ends'])))


if __name__=='__main__':unittest.main()
