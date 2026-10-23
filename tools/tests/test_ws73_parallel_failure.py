# SPDX-License-Identifier: GPL-2.0-only
"""Actual child/pipe orchestration that MUST fail, never a Native/peer fixture."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ws73_parallel_data import fixture
from ws73_parallel_data import run_parallel
from ws73_parallel import PREFIX


class PreserveFirstFailure(unittest.TestCase):
    def test_real_children_extra_events_do_not_replace_the_original_failure(self):
        with tempfile.TemporaryDirectory()as temporary:
            base=Path(temporary);policy=base/'policy.json';policy.write_text(json.dumps(fixture()['policy_expectation']['data']))
            args=SimpleNamespace(ports=['1-1','1-2','1-3','1-4'],slctl=base/'never-executed-slctl',output=base/'out',slkd_pid=1,policy_expectation=policy)
            original=subprocess.Popen;children=[]
            def start(argv,**kw):
                pair=int(argv[argv.index('--pair')+1])
                # First stage uses the real protocol. All subsequent input is
                # explicitly invalid coordination; no controller data exists.
                program=("import json,sys,time;"+
                    f"print({PREFIX!r}+json.dumps(dict(pair={pair},phase='ready',round=0,wait_wall_ns=time.time_ns())),flush=True);"+
                    "assert sys.stdin.readline()=='parallel-ready-0\\n';"+
                    f"print({PREFIX!r}+json.dumps(dict(pair={pair},phase='wrong',round=0,wait_wall_ns=time.time_ns())),flush=True);"+
                    "assert sys.stdin.readline()=='parallel-abort\\n';sys.exit(7)")
                child=original([sys.executable,'-c',program],**kw);children.append(child);return child
            try:
                with patch('ws73_parallel_data.subprocess.Popen',side_effect=start):self.assertEqual(run_parallel(args),1)
                record=json.loads((args.output/'run.json').read_text())
                self.assertEqual(record['status'],'FAIL')
                self.assertEqual(record['error'],'wrong/duplicate/out-of-order parallel event')
                self.assertEqual(record['cleanup_errors'],['extra barrier events'])
                self.assertEqual([p.returncode for p in children],[7,7])
                self.assertNotIn('parallel_corroboration',record)
            finally:
                for child in children:
                    if child.poll()is None:child.kill();child.wait(timeout=2)
