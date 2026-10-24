# SPDX-License-Identifier: GPL-2.0-only
"""Actual coordinator/verdict and shell checks on finite synthetic files.

Uses the existing closed-report/wire fixtures; no successful Native operation,
kernel concurrency, physical credit, firmware or radio is simulated as proof.
"""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_ws73_parallel_benchmark import fixture
from test_ws73_parallel_benchmark_trace import paired_trace
from ws73_capture import CaptureError
from ws73_north_star import file_record
import ws73_parallel_data as parallel
import ws73_socket_benchmark as benchmark
from ws73_benchmark_timeline import check_xhci, valid_trace_summary
from ws73_target import require_benchmark_preparation, valid_parallel_benchmark, validate_business_mode, run_exit_code


class FourPressure(unittest.TestCase):
    def test_explicit_case_boot_cli_and_preparation_source_contract(self):
        control = dict(dynamic_benchmark_mode=True, parallel_benchmark_contract_version=1, parallel_benchmark_case='pressure')
        self.assertEqual(parallel.benchmark_channel(control), benchmark.parallel_channel(pressure=True))
        self.assertEqual(parallel.benchmark_case_from_boot(['ws73.parallel_benchmark=1', 'ws73.parallel_benchmark_case=pressure']), 'pressure')
        for words in [['ws73.parallel_benchmark_case=pressure'], ['ws73.parallel_benchmark=1', 'ws73.parallel_benchmark_case=pressure', 'ws73.parallel_benchmark_case=pressure'], ['ws73.parallel_benchmark=1', 'ws73.parallel_benchmark_case=pressure', 'ws73.parallel_benchmark_case=close-short']]:
            with self.assertRaises(CaptureError): parallel.benchmark_case_from_boot(words)
        validate_business_mode(SimpleNamespace(command='run', four_device_dynamic_benchmark=True, four_device_benchmark_case='pressure'))
        with self.assertRaises(ValueError): validate_business_mode(SimpleNamespace(command='run', four_device_business=True, four_device_benchmark_case='pressure'))
        here = Path(parallel.__file__).parent
        names = ['ws73_benchmark_resources.py', 'ws73_socket_benchmark.py', 'ws73_benchmark.py', 'ws73_benchmark_timeline.py', 'ws73_role_snapshot.py', 'ws73_application_role.py', 'ws73_target.py', 'ws73_target_control.py', 'ws73_target_guest.py', 'ws73_target_init.sh', 'ws73_dynamic_channels.py', 'ws73_channel_fairness.py', 'ws73_parallel_data.py', 'ws73_parallel.py', 'ws73_connection_control.py', 'ws73_trace_layout.py']
        package = dict(four_dynamic_benchmark_contract_version=1, socket_benchmark_role_contract_version=1, benchmark_trace_contract_version=1, benchmark_process_resource_contract_version=1, inputs=[file_record(here / n) for n in names])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dest = root / 'root/usr/share/sparklink/tools'; dest.mkdir(parents=True)
            for n in names: (dest / n).write_bytes((here / n).read_bytes())
            init = root / 'root/init'; init.write_bytes((here / 'ws73_target_init.sh').read_bytes()); init.chmod(0o755)
            for value in (None, True, 2):
                with self.assertRaisesRegex(ValueError, 'fresh four benchmark pressure'): require_benchmark_preparation(dict(package, four_dynamic_benchmark_pressure_contract_version=value), root, case='pressure')
            current = dict(package, four_dynamic_benchmark_pressure_contract_version=1)
            require_benchmark_preparation(current, root, case='pressure')
            (dest / 'ws73_parallel_data.py').write_text('# stale coordinator\n')
            with self.assertRaisesRegex(ValueError, 'source mismatch'): require_benchmark_preparation(current, root, case='pressure')
        for script, extra in [('ws73_target.py', ['run', '--help']), ('ws73_parallel_data.py', ['--help'])]:
            result = subprocess.run([sys.executable, str(here / script), *extra], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0); self.assertIn('parallel,close-short,pressure', result.stdout)

    def test_four_pair_role_witnesses_are_all_required_and_cannot_promote_credit_or_fairness(self):
        with tempfile.TemporaryDirectory() as tmp: record = fixture(Path(tmp), pressure=True)
        proof = record['parallel_corroboration']
        parallel.verify_records(proof['parallel_benchmark_control'])
        self.assertTrue(valid_parallel_benchmark(record)); self.assertEqual(run_exit_code(record), 0)
        self.assertEqual(proof['dynamic_benchmark']['round_trips'], 336)
        self.assertEqual(proof['dynamic_benchmark']['application_processes'], 16)
        for kind in ['missing-fresh', 'wrong-fresh', 'case', 'boot', 'worker', 'worker-argv', 'Root-route', 'missing-recovery', 'late', 'payload', 'identity', 'empty-count', 'missing-peer', 'trace-budget', 'promote-credit', 'promote-fairness', 'missing-acceptance', 'extra-close']:
            bad = copy.deepcopy(record); p = bad['parallel_corroboration']; child = p['parallel_benchmark_control']['workers'][1]['run']; pair = p['pairs'][1]; phase = pair['channel']['proofs'][1]; long = phase['channels'][1]; witness = long['application']['backpressure_recovery']
            if kind == 'missing-fresh': bad.pop('four_dynamic_benchmark_pressure_contract_version')
            elif kind == 'wrong-fresh': bad['four_dynamic_benchmark_pressure_contract_version'] = True
            elif kind == 'case': bad['four_benchmark_case'] = 'close-short'
            elif kind == 'boot': bad['qemu_args'][-1] += ' ws73.parallel_benchmark_case=close-short'
            elif kind == 'worker': child['parallel_benchmark_case'] = 'close-short'
            elif kind == 'worker-argv': p['parallel_benchmark_control']['workers'][1]['args'].remove('pressure')
            elif kind == 'Root-route': pair['benchmark_supervision'][benchmark.CHANNEL_FIELD] = benchmark.parallel_channel()
            elif kind == 'missing-recovery': long['application'].pop('backpressure_recovery')
            elif kind == 'late': witness['records'][0]['validated_ns'] = witness['records'][0]['deadline_ns']
            elif kind == 'payload': witness['records'][0]['frame_sha256'] = '0' * 64
            elif kind == 'identity': witness['source_identity']['lifetime'] += 1
            elif kind == 'empty-count': witness['records'] = []
            elif kind == 'missing-peer': long['legs'].pop()
            elif kind == 'trace-budget': p['paired_trace']['requested_buffer_kb'] = 8192
            elif kind == 'promote-credit': p['controller_credit_correctness_proof'] = True
            elif kind == 'promote-fairness': p['fairness_acceptance'] = True
            elif kind == 'missing-acceptance': p.pop('software_backpressure_acceptance')
            else: p['channel_close_isolation_acceptance'] = True
            with self.subTest(kind=kind): self.assertFalse(valid_parallel_benchmark(bad)); self.assertEqual(run_exit_code(bad), 1)
        for case in (None, 'close-short'):
            with tempfile.TemporaryDirectory() as tmp: normal = fixture(Path(tmp), close_short=case is not None)
            self.assertTrue(valid_parallel_benchmark(normal))
            normal['four_dynamic_benchmark_pressure_contract_version'] = 1
            self.assertFalse(valid_parallel_benchmark(normal))

    def test_same_trace_layout_bounded_paired_markers_and_actual_init_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); paired_trace(root, requested_kb=16384)
            proof = check_xhci(root, 'on', parallel=True, pressure=True)
            self.assertTrue(valid_trace_summary(proof, 'on', parallel=True, pressure=True))
            self.assertFalse(valid_trace_summary(proof, 'on', parallel=True))
            with self.assertRaises(CaptureError): check_xhci(root, 'on', parallel=True, pressure=True, close_short=True)
            with self.assertRaises(CaptureError): check_xhci(root, 'off', parallel=True, pressure=True)
            proof['trace']['bytes'] = 64 * 1024 * 1024 + 1
            self.assertFalse(valid_trace_summary(proof, 'on', parallel=True, pressure=True))
            (root / 'xhci-trace-stats.txt').write_text((root / 'xhci-trace-stats.txt').read_text().replace('overrun: 0', 'overrun: 1', 1))
            with self.assertRaises(CaptureError): check_xhci(root, 'on', parallel=True, pressure=True)
        text = Path(parallel.__file__).with_name('ws73_target_init.sh').read_text()
        function = re.search(r'^benchmark_trace_buffer_kb\(\) \{.*?^\}', text, re.M | re.S).group()
        for words, expected in [(['ws73.parallel_benchmark_case=pressure'], '1024'), (['ws73.parallel_benchmark=1', 'ws73.parallel_benchmark_case=pressure'], '16384'), (['ws73.parallel_benchmark=1'], '8192'), (['ws73.benchmark_pressure=1'], '16384')]:
            result = subprocess.run(['sh', '-c', function + '\nbenchmark_trace_buffer_kb "$@"', 'fixture', *words], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0); self.assertEqual(result.stdout, expected)


if __name__ == '__main__': unittest.main()
