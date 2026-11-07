# SPDX-License-Identifier: GPL-2.0-only
"""Finite source/metadata/capture fixtures for the actual four-pair entry.

Reuses existing closed Root and codec fixtures. No live USB, kernel locking,
callback drain, hardware credit truth or physical qualification is simulated.
"""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError
import ws73_parallel_data as gate
import ws73_socket_benchmark as benchmark
from ws73_target import validate_business_mode,require_benchmark_preparation,valid_parallel_benchmark,run_exit_code
from test_ws73_parallel_benchmark import fixture
from test_ws73_benchmark_pair_namespace import paired


class FourDynamicClose(unittest.TestCase):
    def test_typed_case_boot_and_real_cli_reject_implicit_or_mixed_scope(self):
        args=SimpleNamespace(command='run',four_device_dynamic_benchmark=True,four_device_benchmark_case='close-short')
        validate_business_mode(args)
        for fields in [dict(four_device_dynamic_benchmark=False),dict(four_device_benchmark_case=True),dict(four_device_benchmark_case='unknown'),dict(four_device_burst=True)]:
            with self.subTest(fields=fields),self.assertRaises(ValueError):validate_business_mode(SimpleNamespace(**(vars(args)|fields)))
        words=['ws73.parallel_benchmark=1','ws73.parallel_benchmark_case=close-short']
        self.assertEqual(gate.benchmark_case_from_boot(words),'close-short')
        for tokens in [words+words,words+['ws73.parallel_benchmark_case=parallel'],words[1:],['ws73.parallel_benchmark_case'],['ws73.parallel_benchmark_case=unknown']]:
            with self.subTest(tokens=tokens),self.assertRaises(CaptureError):gate.benchmark_case_from_boot(tokens)
        for value in [True,1,None,'parallel','unknown']:
            with self.subTest(value=value),self.assertRaises(CaptureError):gate.benchmark_case(dict(dynamic_benchmark_mode=True,parallel_benchmark_contract_version=1,parallel_benchmark_case=value))
        with self.assertRaises(CaptureError):gate.benchmark_case(dict(parallel_benchmark_case='close-short'))
        here=Path(gate.__file__).parent
        for script,argv,expected in [('ws73_target.py',['run','--help'],'--four-device-benchmark-case'),('ws73_parallel_data.py',['--help'],'--dynamic-benchmark-case')]:
            result=subprocess.run([sys.executable,str(here/script),*argv],capture_output=True,text=True)
            self.assertEqual(result.returncode,0);self.assertIn(expected,result.stdout)

    def test_root_actual_request_uses_canonical_v3_and_matching_boot(self):
        words=[benchmark.ROLE_TOKEN,'ws73.parallel_benchmark=1']
        for pair in (0,1):
            row=paired(pair);benchmark.check_pair_channel_boot(row,words)
            row[benchmark.CHANNEL_FIELD]=benchmark.parallel_channel(close_short=True)
            benchmark.validate_role_request(row,0,live=True)
            with self.assertRaises(CaptureError):benchmark.check_pair_channel_boot(row,words)
            benchmark.check_pair_channel_boot(row,words+['ws73.parallel_benchmark_case=close-short'])
            row[benchmark.CHANNEL_FIELD]=benchmark.parallel_channel()
            with self.assertRaises(CaptureError):benchmark.check_pair_channel_boot(row,words+['ws73.parallel_benchmark_case=close-short'])
        for value in (None,True,0,2):
            package=dict(four_dynamic_benchmark_close_contract_version=value)
            with self.assertRaisesRegex(ValueError,'fresh four benchmark close'):require_benchmark_preparation(package,Path('/missing'),case='close-short')

    def test_full_existing_close_continuity_oracle_and_pair_summary(self):
        with tempfile.TemporaryDirectory()as temporary:record=fixture(Path(temporary),close_short=True)
        self.assertTrue(valid_parallel_benchmark(record));self.assertEqual(run_exit_code(record),0)
        proof=record['parallel_corroboration'];summary=proof['dynamic_benchmark']
        self.assertEqual((summary['round_trips'],summary['short_round_trips'],summary['long_round_trips']),(336,80,256))
        self.assertTrue(summary['channel_close_isolation_acceptance'])
        control=proof['parallel_benchmark_control'];gate.verify_records(control)
        for pair in proof['pairs']:
            for phase in pair['channel']['proofs']:
                self.assertEqual(phase['close_continuity'],benchmark.close_continuity(phase['channels'],phase['closed_short']))
                self.assertTrue(phase['close_continuity']['after_reply_sequences'])
        changes=['missing-case','missing-contract','false-contract','missing-boot','duplicate-boot','wrong-case','worker-case','worker-argv','row-v2','Root-v2','missing-wire-close','missing-short-exit','exit-after-long','missing-continuity','stale-continuity','halfcount','old144','missing-phase','false-acceptance','wrong-lifetime','crosspair','credit-truth','performance']
        for change in changes:
            bad=copy.deepcopy(record);p=bad['parallel_corroboration'];worker=p['parallel_benchmark_control']['workers'][1];pair=p['pairs'][1];phase=pair['channel']['proofs'][0]
            if change=='missing-case':bad.pop('four_benchmark_case')
            elif change=='missing-contract':bad.pop('four_dynamic_benchmark_close_contract_version')
            elif change=='false-contract':bad['four_dynamic_benchmark_close_contract_version']=True
            elif change=='missing-boot':bad['qemu_args'][-1]=bad['qemu_args'][-1].replace(' ws73.parallel_benchmark_case=close-short','')
            elif change=='duplicate-boot':bad['qemu_args'][-1]+=' ws73.parallel_benchmark_case=close-short'
            elif change=='wrong-case':bad['four_benchmark_case']='parallel'
            elif change=='worker-case':worker['run'].pop('parallel_benchmark_case')
            elif change=='worker-argv':worker['args'].remove('--dynamic-benchmark-case')
            elif change=='row-v2':worker['run']['socket_benchmark'][0][benchmark.CHANNEL_FIELD]=benchmark.parallel_channel()
            elif change=='Root-v2':pair['benchmark_supervision']['version']=2
            elif change=='missing-wire-close':phase['channels'][0]['close']=[]
            elif change=='missing-short-exit':phase['closed_short'].pop()
            elif change=='exit-after-long':phase['closed_short'][0]['reaped_wall_ns']=10**18
            elif change=='missing-continuity':phase.pop('close_continuity')
            elif change=='stale-continuity':phase['close_continuity']['after_reply_sequences']=[]
            elif change=='halfcount':p['round_trips']=168
            elif change=='old144':p['round_trips']=144
            elif change=='missing-phase':worker['run']['socket_benchmark'].pop()
            elif change=='false-acceptance':p['channel_close_isolation_acceptance']=False
            elif change=='wrong-lifetime':
                # The finite fixture shares dictionaries; persisted JSON does
                # not. Change only the decoded wire summary,not its request.
                phase['owners']=copy.deepcopy(phase['owners']);phase['owners'][0]['object']['lifetime']+=1
            elif change=='crosspair':pair['channel']['parallel_pair']=0
            elif change=='credit-truth':p['controller_credit_correctness_proof']=True
            elif change=='performance':p['performance_qualified']=True
            with self.subTest(change=change):self.assertFalse(valid_parallel_benchmark(bad));self.assertEqual(run_exit_code(bad),1)

    def test_default_v2_cannot_gain_close_acceptance_or_orphan_selector(self):
        with tempfile.TemporaryDirectory()as temporary:record=fixture(Path(temporary))
        self.assertTrue(valid_parallel_benchmark(record));self.assertEqual(run_exit_code(record),0)
        for values in [dict(four_benchmark_case='close-short'),dict(four_dynamic_benchmark_close_contract_version=1)]:
            bad=copy.deepcopy(record);bad.update(values);self.assertFalse(valid_parallel_benchmark(bad));self.assertEqual(run_exit_code(bad),1)
        bad=copy.deepcopy(record);bad['parallel_corroboration']['channel_close_isolation_acceptance']=True
        self.assertFalse(valid_parallel_benchmark(bad))
        self.assertEqual(run_exit_code(dict(status='PASS',qemu_exit=0,supervisor_exit=0,qemu_args=['ws73.parallel_benchmark_case=close-short'])),1)


if __name__=='__main__':unittest.main()
