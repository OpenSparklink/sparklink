# SPDX-License-Identifier: GPL-2.0-only
"""Actual child/pipe orchestration that MUST fail, never a Native/peer fixture."""
import copy
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
            owners=[w['run']['initial']for w in fixture()['workers']]
            def start(argv,**kw):
                pair=int(argv[argv.index('--pair')+1])
                # First stage uses the real protocol. All subsequent input is
                # explicitly invalid coordination; no controller data exists.
                program=("import json,sys,time;owners=json.loads(sys.argv[1]);"+
                    f"print({PREFIX!r}+json.dumps(dict(pair={pair},phase='ready',round=0,wait_wall_ns=time.time_ns(),owners=owners)),flush=True);"+
                    "assert sys.stdin.readline()=='parallel-ready-0\\n';"+
                    f"print({PREFIX!r}+json.dumps(dict(pair={pair},phase='wrong',round=0,wait_wall_ns=time.time_ns())),flush=True);"+
                    "assert sys.stdin.readline()=='parallel-abort\\n';sys.exit(7)")
                child=original([sys.executable,'-c',program,json.dumps(owners[pair])],**kw);children.append(child);return child
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

    def test_invalid_ready_owners_abort_both_real_pipes_before_any_start_ack(self):
        for case in ('duplicate-E-address', 'cross-pair-address', 'wrong-slot', 'same-USB'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                base=Path(temporary);record_fixture=fixture()
                owners=[copy.deepcopy(w['run']['initial']) for w in record_fixture['workers']]
                if case=='duplicate-E-address':owners[1][1]['address']=owners[1][0]['address']
                elif case=='cross-pair-address':owners[1][0]['address']=owners[0][0]['address']
                elif case=='wrong-slot':owners[1].reverse()
                else:owners[1][0].update(bus=owners[0][0]['bus'],device=owners[0][0]['device'])
                policy=base/'policy.json';policy.write_text(json.dumps(record_fixture['policy_expectation']['data']))
                args=SimpleNamespace(ports=['1-1','1-2','1-3','1-4'],slctl=base/'never-executed-slctl',output=base/'out',slkd_pid=1,policy_expectation=policy)
                original=subprocess.Popen;children=[]
                def start(argv,**kw):
                    pair=int(argv[argv.index('--pair')+1])
                    program=("import json,sys,time;owners=json.loads(sys.argv[1]);"+
                        f"print({PREFIX!r}+json.dumps(dict(pair={pair},phase='ready',round=0,wait_wall_ns=time.time_ns(),owners=owners)),flush=True);"+
                        "token=sys.stdin.readline();"+
                        "print('UNEXPECTED_RF_START' if token=='parallel-ready-0\\n' else 'ABORTED_BEFORE_RF',flush=True);"+
                        "assert token=='parallel-abort\\n';sys.exit(7)")
                    child=original([sys.executable,'-c',program,json.dumps(owners[pair])],**kw);children.append(child);return child
                try:
                    with patch('ws73_parallel_data.subprocess.Popen',side_effect=start):self.assertEqual(run_parallel(args),1)
                    record=json.loads((args.output/'run.json').read_text())
                    self.assertEqual(record['status'],'FAIL');self.assertEqual(record['stages'],[])
                    self.assertIn(record['error'],['four distinct original owner identities required',
                        'four independent USB/controller registrations required',
                        'Ready observations must match the explicit pair and slots'])
                    self.assertEqual([p.returncode for p in children],[7,7])
                    self.assertTrue(all('ABORTED_BEFORE_RF' in w['stdout'] and 'UNEXPECTED_RF_START' not in w['stdout'] for w in record['workers']))
                    self.assertNotIn('parallel_corroboration',record)
                finally:
                    for child in children:
                        if child.poll() is None:child.kill();child.wait(timeout=2)
