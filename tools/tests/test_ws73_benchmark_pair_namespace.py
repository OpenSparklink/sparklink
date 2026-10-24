# SPDX-License-Identifier: GPL-2.0-only
"""Production request/path/snapshot functions on finite metadata and FS fixtures.

No Native/kernel/controller success stub;this is not four-device qualification.
"""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_ws73_benchmark_role import request
from ws73_capture import CaptureError
import ws73_socket_benchmark as gate
import ws73_role_snapshot as snapshot
import ws73_application_role as role


def paired(pair=0):
    r=request();r.update(parallel_pair=pair,**{gate.PAIR_FIELD:1,gate.CHANNEL_FIELD:gate.parallel_channel(),gate.RESOURCE_FIELD:1});return r


class PairedBenchmarkNamespace(unittest.TestCase):
    def test_exact_two_pair_roots_inputs_and_unchanged_legacy_budgets(self):
        self.assertEqual(gate.role_paths(),(gate.ROLE_ROOT,gate.ROLE_RUNTIME,gate.ROLE_INPUT))
        roots=[]
        for pair in (0,1):
            artifact,runtime,inputs=gate.role_paths(pair);roots.extend([artifact,runtime,inputs])
            self.assertEqual(artifact,Path('/evidence/benchmark-role-pair-'+str(pair)))
            self.assertEqual(runtime,Path('/run/ws73-benchmark-role-pair-'+str(pair)))
            self.assertEqual(inputs,Path('/evidence/application/parallel-business/pair-'+str(pair)))
            self.assertEqual(snapshot.profile('benchmark',pair)['limit'],snapshot.profile('benchmark')['limit'])
        self.assertEqual(len(set(roots)),6)
        with tempfile.TemporaryDirectory()as temporary:
            control=SimpleNamespace(args=SimpleNamespace(benchmark_parallel_pair=0),output=Path(temporary))
            with self.assertRaisesRegex(CaptureError,'fixed input directory'):gate.execute(control,{})
        for pair in (-1,2,True,'0','../pair-0'):
            with self.subTest(pair=pair),self.assertRaises(CaptureError):gate.role_paths(pair)

    def test_pair_request_is_versioned_and_only_canonical_parallel_profile(self):
        for pair in (0,1):
            r=paired(pair);gate.validate_role_request(r,0,live=True)
            self.assertEqual(gate.parallel_pair(r),pair)
            self.assertTrue({gate.PAIR_FIELD,'parallel_pair'}<=gate.request_fields(r))
        for case in ('version-missing','pair-missing','boolean-version','boolean-pair','outside-pair','close-profile','single-profile'):
            r=paired()
            if case=='version-missing':r.pop(gate.PAIR_FIELD)
            elif case=='pair-missing':r.pop('parallel_pair')
            elif case=='boolean-version':r[gate.PAIR_FIELD]=True
            elif case=='boolean-pair':r['parallel_pair']=True
            elif case=='outside-pair':r['parallel_pair']=2
            elif case=='close-profile':r[gate.CHANNEL_FIELD]=gate.parallel_channel(close_short=True)
            else:r[gate.CHANNEL_FIELD]=r[gate.CHANNEL_FIELD]['channels'][0]['route']
            with self.subTest(case=case),self.assertRaises(CaptureError):gate.validate_role_request(r,0,live=True)

    def test_matching_boot_and_pair_required_before_allocation(self):
        words=[gate.ROLE_TOKEN,'ws73.parallel_benchmark=1']
        for pair in (0,1):gate.check_pair_boot(pair,words)
        gate.check_pair_boot(None,[gate.ROLE_TOKEN])
        for pair,tokens in [(0,[]),(None,words),(0,words+words),(0,[gate.ROLE_TOKEN,'ws73.parallel_benchmark=0']),
                (0,['ws73.parallel_benchmark=1']),(0,[gate.ROLE_TOKEN,'ws73.parallel_benchmark']),(None,['ws73.parallel_benchmark']),(True,words),(0,words+['ws73.parallel_benchmark=0'])]:
            with self.subTest(pair=pair,tokens=tokens),self.assertRaises(CaptureError):gate.check_pair_boot(pair,tokens)
        with patch('ws73_role_snapshot.local_root',side_effect=AssertionError('must not create or mount')):
            # Real host has no explicit disposable-VM pair token. It must reject
            # before the storage dependency;no successful VM guard is mocked.
            with self.assertRaises(CaptureError):role.supervise(1,mode='benchmark',pair=0)

    def test_actual_closed_snapshots_cannot_cross_pairs_or_legacy_namespace(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary)
            for pair in (0,1):
                source=root/('source'+str(pair));source.mkdir();(source/'run.json').write_text(json.dumps(dict(parallel_pair=pair)))
                dest=root/('export'+str(pair));snapshot.publish(source,dest,phase=0,success=True,kind='benchmark',pair=pair)
                snapshot.verify(dest,phase=0,runtime_root=source,kind='benchmark',pair=pair)
                with self.assertRaises(CaptureError):snapshot.verify(dest,phase=0,kind='subscription',pair=pair)
                for wrong in (None,1-pair):
                    with self.subTest(pair=pair,wrong=wrong),self.assertRaises(CaptureError):snapshot.verify(dest,phase=0,kind='benchmark',pair=wrong)

    def test_report_location_and_summary_need_explicit_expected_pair(self):
        r=paired(0);wrong='/run/ws73-benchmark-role-pair-1/phase-0/reports/benchmark-0-0.json'
        r['applications']=[dict(report_path=wrong,report_file=dict(path=wrong))]
        with tempfile.TemporaryDirectory()as temporary:
            with self.assertRaisesRegex(CaptureError,'report location'):gate.check_report_files(r,temporary)
        proof=dict(status='ACTUAL_ROOT_BENCHMARK_APPS_ONLY_PHASES_CHECKED',version=2,uid=1004,gid=1004,extra_groups=[],
            role_probes=2,application_processes=8,report_files=8,phases=2,performance_qualified=False,
            daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2,start_ticks=2),snapshot_files=30,snapshot_bytes=1,
            parallel_pair=0,**{gate.PAIR_FIELD:1,gate.CHANNEL_FIELD:gate.parallel_channel()})
        self.assertFalse(gate.valid_role_supervision(proof))
        self.assertTrue(gate.valid_role_supervision(proof,pair=0))
        self.assertFalse(gate.valid_role_supervision(proof,pair=1))
        self.assertFalse(gate.valid_role_supervision(proof,pair=True))
        with patch.object(gate,'_match_payloads',side_effect=AssertionError('must not match another pair')):
            with self.assertRaises(CaptureError):gate.corroborate(dict(socket_benchmark=[paired(0),paired(0)]),{},'.',pair=1)
            with self.assertRaises(CaptureError):gate.corroborate(dict(socket_benchmark=[paired(0),paired(1)]),{},'.',pair=0)
        bad=copy.deepcopy(proof);bad[gate.PAIR_FIELD]=True
        self.assertFalse(gate.valid_role_supervision(bad,pair=0))


if __name__=='__main__':unittest.main()
