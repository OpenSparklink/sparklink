"""Real child pipe collector tests; no controller/kernel/firmware qualification."""
import errno
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from ws73_capture import CaptureError
from ws73_dynamic_channels import ApplicationOutput,await_marker


class OutputCollector(unittest.TestCase):
    def spawn(self,program,maximum=128*1024,sink_mode=None):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        paths=[Path(directory.name)/n for n in ['stdout','stderr']]
        sinks=[p.open('xb') for p in paths]
        for f in sinks:self.addCleanup(f.close)
        if sink_mode:
            real=sinks[0]
            class Sink:
                name=real.name
                def write(self,data):
                    if sink_mode=='short':return 0
                    raise OSError(errno.ENODATA,'injected artifact write failure')
                def flush(self):real.flush()
                def fileno(self):return real.fileno()
            sinks[0]=Sink()
        reader=ApplicationOutput(maximum);self.addCleanup(reader.close)
        proc=subprocess.Popen([sys.executable,'-c',program],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        def stop():
            if proc.poll() is None:proc.kill()
            proc.wait(timeout=2)
        self.addCleanup(stop)
        app=dict(output_files=list(map(str,paths)));reader.add(proc,app,sinks)
        return proc,app,reader,paths
    def finish(self,proc,app,reader):
        deadline=time.monotonic()+2
        while proc.poll() is None:
            reader.drain()
            if time.monotonic()>=deadline:self.fail('real child deadline')
            time.sleep(.002)
        reader.final(app)
    def test_partial_utf8_both_streams_and_original_bytes(self):
        proc,app,reader,paths=self.spawn("import os,time;os.write(1,b'\\xe6');time.sleep(.02);os.write(1,b'\\x98\\x9f\\n');os.write(2,b'error\\n')")
        self.finish(proc,app,reader)
        self.assertEqual(app['stdout'],'星\n');self.assertEqual(app['stderr'],'error\n')
        self.assertEqual(paths[0].read_bytes(),'星\n'.encode());self.assertEqual(app['captured_bytes']['stdout'],4)
    def test_budget_overflow_is_not_truncation_or_pass(self):
        proc,app,reader,_=self.spawn("import os;os.write(1,b'x'*128)",maximum=64)
        with self.assertRaises(CaptureError):self.finish(proc,app,reader)
        self.assertEqual(app['output_collection_error']['operation'],'byte-budget')
    def test_sink_errors_and_short_write_fail_closed(self):
        for mode in ['error','short']:
            proc,app,reader,_=self.spawn("print('output')",sink_mode=mode)
            with self.subTest(mode=mode),self.assertRaises((OSError,CaptureError)):self.finish(proc,app,reader)
            self.assertEqual(app['output_collection_error']['operation'],'persist-artifact')
            self.assertIn('traceback',app['output_collection_error'])
    def test_missing_marker_or_process_exit_is_not_success(self):
        proc,app,reader,_=self.spawn("print('incomplete')")
        class Run:
            def save(self):pass
        with self.assertRaises(CaptureError):await_marker(Run(),[(proc,app)],'MISSING',time.monotonic()+1,reader)
    def test_partial_utf8_at_eof_fails(self):
        proc,app,reader,_=self.spawn("import os;os.write(1,b'\\xe6')")
        with self.assertRaises(UnicodeDecodeError):self.finish(proc,app,reader)
        self.assertEqual(app['output_collection_error']['operation'],'finalize-utf8')
    def test_deleted_or_truncated_artifact_fails_final_check(self):
        for deleted in [True,False]:
            proc,app,reader,paths=self.spawn("print('captured')");self.finish(proc,app,reader)
            if deleted:paths[0].unlink()
            else:paths[0].write_bytes(b'')
            with self.subTest(deleted=deleted),self.assertRaises((OSError,CaptureError)):reader.final(app)
    def test_incomplete_eof_cannot_be_final(self):
        proc,app,reader,_=self.spawn("import time;print('held',flush=True);time.sleep(.5)")
        with self.assertRaises(CaptureError):reader.final(app)


if __name__=='__main__':unittest.main()
