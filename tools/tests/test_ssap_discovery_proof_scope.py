# SPDX-License-Identifier: GPL-2.0-only
"""Proof-result admission controls,not discovery implementation proof."""
import copy
import importlib.util
from pathlib import Path
import unittest

from run_formal import kani_export_verdict

SPEC = importlib.util.spec_from_file_location(
    'discovery_proof_runner',
    Path(__file__).resolve().parents[2] / 'formal/ssap_value/check.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class DiscoveryProofVerdict(unittest.TestCase):
    def fixture(self, harness, properties):
        return {
            'metadata': {'version': '1.0', 'kani_version': '0.68.0'},
            'error_details': [{'harness_id': harness, 'has_errors': False}],
            'verification_results': {
                'summary': {'total_harnesses': 1, 'executed': 1,
                            'status': 'completed', 'successful': 1, 'failed': 0},
                'results': [{'harness_id': harness, 'status': 'Success',
                             'checks': [dict(status='Success', category='assertion',
                                             description=p) for p in properties]}]}}

    def test_each_required_discovery_property_must_exist_and_succeed(self):
        for harness, properties in RUNNER.DISCOVERY.items():
            good = self.fixture(harness, properties)
            self.assertEqual(kani_export_verdict(good, harness, properties), 'PROVED_SCOPED')
            for index in range(len(properties)):
                for status in [None, 'Unreachable', 'Failure', 'Unknown']:
                    bad = copy.deepcopy(good)
                    checks = bad['verification_results']['results'][0]['checks']
                    if status is None:
                        checks.pop(index)
                    else:
                        checks[index]['status'] = status
                    self.assertNotEqual(kani_export_verdict(bad, harness, properties,
                        allowed_unreachable=RUNNER.discovery_unreachable(harness)), 'PROVED_SCOPED')

    def test_std_library_opt_in_is_explicit_and_never_admits_unsupported(self):
        for harness, properties in RUNNER.DISCOVERY.items():
            good = self.fixture(harness, properties)
            function, category, description = RUNNER.DISCOVERY_REQUEST_UNREACHABLE[0]
            good['verification_results']['results'][0]['checks'].append(dict(
                status='Unreachable', function=function, category=category, description=description))
            result = kani_export_verdict(good, harness, properties,
                                         allowed_unreachable=RUNNER.discovery_unreachable(harness))
            self.assertEqual(result == 'PROVED_SCOPED', bool(RUNNER.discovery_unreachable(harness)))
            good['verification_results']['results'][0]['checks'][-1]['category'] = 'unsupported_construct'
            self.assertNotEqual(kani_export_verdict(good, harness, properties,
                allowed_unreachable=RUNNER.discovery_unreachable(harness)), 'PROVED_SCOPED')

    def test_loop_contract_binds_sources_and_rejects_flag_overrides(self):
        import json
        import tempfile
        real = Path(__file__).resolve().parents[2]
        config = real / 'formal/ssap_value/discovery-unwindset-0.68.json'
        _, value = RUNNER.discovery_unwindset(config)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for file in value['sources']:
                path = root / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((real / file).read_bytes())
            path = root / 'bounds.json'
            for mutation in ['valid', 'source', 'tool', 'missing', 'flag', 'zero', 'bool', 'unknown', 'bound']:
                bad = copy.deepcopy(value)
                harness = next(k for k, v in bad['harnesses'].items() if v)
                loop = next(iter(bad['harnesses'][harness]))
                if mutation == 'source': bad['sources'][next(iter(bad['sources']))] = '0' * 64
                if mutation == 'tool': bad['kani_version'] = 'unknown'
                if mutation == 'missing': bad['harnesses'].pop(harness)
                if mutation == 'flag': bad['harnesses'][harness]['--no-unwinding-checks'] = 1
                if mutation == 'zero': bad['harnesses'][harness][loop] = 0
                if mutation == 'bool': bad['harnesses'][harness][loop] = True
                if mutation == 'unknown': bad['harnesses'][harness]['_Unknown.0'] = 4
                if mutation == 'bound': bad['harnesses'][harness][loop] = 1
                path.write_text(json.dumps(bad))
                if mutation == 'valid': self.assertEqual(RUNNER.discovery_unwindset(path, root)[1], value)
                else:
                    with self.assertRaises(ValueError): RUNNER.discovery_unwindset(path, root)

    def test_scope_does_not_claim_full_pages_or_peer_semantics(self):
        self.assertIn('arbitrary0..32 bytes', RUNNER.DISCOVERY_SCOPE)
        self.assertIn('Not full MTU/page80 exploration', RUNNER.DISCOVERY_SCOPE)
        self.assertIn('not proof of peer intent', RUNNER.DISCOVERY_SCOPE)
