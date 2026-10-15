"""Negative controls for the provenance checker, not protocol/hardware tests."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import check_qualifications as q


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'sparklink'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        (self.repo / 'production.rs').write_text('production v1\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
                        'commit', '-qm', 'fixture'], check=True)
        commit = q.git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        self.report = {'source': commit, 'scope': ['not locks, USB or RF'], 'status': 'SCOPED_PASS'}
        (self.repo / 'report.json').write_text(json.dumps(self.report))
        (self.repo / 'artifact').write_bytes(b'compiled fixture artifact')
        materials = {}
        for name in ['report.json', 'artifact']:
            path = self.repo / name
            materials[name] = dict(base='repo', path=name, access='public',
                                   format='json' if name.endswith('.json') else 'bytes',
                                   bytes=path.stat().st_size, sha256=q.sha(path))
        record = dict(id='one', level='offline', result='PASS', contracts=['contract'],
                      bounds='fixture only', remaining=['RF not covered'], excluded=self.report['scope'],
                      sources={'production': dict(repo='sparklink', commit=commit, scopes=['production.rs'],
                                                 files=q.scoped_files(self.repo, commit, ['production.rs']))},
                      report=dict(material='report.json', scope_pointer=['scope'],
                                  source_pointers={'production': ['source']}, verdict_pointer=['status'],
                                  verdict_results={'SCOPED_PASS': 'PASS', 'UNSUPPORTED': 'UNPROVED'}),
                      artifact_materials=['artifact'], tool_materials=['artifact'], configuration_materials=[],
                      gates=[dict(id='gate', result='PASS', materials=['report.json', 'artifact'])],
                      required_gates=['gate'])
        self.data = dict(schema_version=1, materials=materials, records=[record], overall_required_records=['one'])

    def run_check(self, **kwargs):
        return q.validate(self.data, self.repo, mode=kwargs.pop('mode', 'local'), **kwargs)

    def rejected(self):
        self.assertTrue(self.run_check()['errors'])

    def update_report(self):
        path = self.repo / 'report.json'
        path.write_text(json.dumps(self.report))
        self.data['materials']['report.json'].update(sha256=q.sha(path), bytes=path.stat().st_size)

    def test_positive_retained_bytes_is_not_replay(self):
        result = self.run_check(require_current=True)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['verification'], 'RETAINED_BYTES_VERIFIED_NOT_REPLAYED')

    def test_old_source_in_report(self):
        self.report['source'] = 'f' * 40
        self.update_report()
        self.rejected()

    def test_changed_source_map(self):
        self.data['records'][0]['sources']['production']['files']['production.rs'] = '0' * 64
        self.rejected()

    def test_dirty_source_not_current(self):
        (self.repo / 'production.rs').write_text('new unchecked runtime')
        self.assertFalse(self.run_check()['errors'])  # retained v1 stays v1
        self.assertTrue(self.run_check(require_current=True)['errors'])

    def test_untracked_production_file_not_current(self):
        self.data['records'][0]['sources']['production']['scopes'] = ['production*']
        self.data['records'][0]['sources']['production']['files'] = q.scoped_files(
            self.repo, self.report['source'], ['production*'])
        (self.repo / 'production-extra.rs').write_text('new production module')
        self.assertTrue(self.run_check(require_current=True)['errors'])

    def test_missing_artifact(self):
        (self.repo / 'artifact').unlink()
        self.rejected()

    def test_wrong_hash(self):
        (self.repo / 'artifact').write_bytes(b'altered')
        self.rejected()

    def test_scope_changed(self):
        self.data['records'][0]['excluded'] = []
        self.rejected()

    def test_report_truncated(self):
        (self.repo / 'report.json').write_text('{')
        self.rejected()

    def test_removing_gate_and_requirement_still_rejected(self):
        self.report['runs'] = [{'name': 'gate'}, {'name': 'must-not-delete'}]
        self.update_report()
        self.data['records'][0]['report']['gate_rows_pointer'] = ['runs']
        self.rejected()

    def test_stale_generated_views(self):
        self.data['baseline'] = {'kernel': 'a', 'compiled_userspace': 'b', 'executed_tools': 'c'}
        self.data['batch'] = {'id': 'fixture'}
        self.data['records'][0]['title'] = 'fixture'
        project = self.repo / 'project'
        project.mkdir()
        for name in ['current-capabilities.md', 'implementation-plan.md']:
            (project / name).write_text('<!-- qualification-summary:start -->old<!-- qualification-summary:end -->')
        (project / 'goal-execution-state.json').write_text('{}')
        self.assertEqual(len(q.sync_views(self.data, self.repo)), 3)
        self.assertFalse(q.sync_views(self.data, self.repo, write=True))
        self.assertFalse(q.sync_views(self.data, self.repo))
        state = json.loads((project / 'goal-execution-state.json').read_text())
        state['current_heads'] = {'stale': 'old'}
        (project / 'goal-execution-state.json').write_text(json.dumps(state))
        self.assertTrue(q.sync_views(self.data, self.repo))

    def test_missing_required_gate(self):
        self.data['records'][0]['gates'] = []
        self.rejected()

    def test_required_nonpass_not_hidden(self):
        for outcome in ['FAIL', 'UNPROVED', 'MISSING', 'SKIP', 'TIMEOUT', 'UNSUPPORTED']:
            with self.subTest(outcome=outcome):
                self.data['records'][0]['gates'][0]['result'] = outcome
                self.rejected()

    def test_unsupported_cannot_be_upgraded_by_exit_zero_or_count(self):
        self.report.update(status='UNSUPPORTED', exit=0, generated_checks=1766)
        self.update_report()
        self.rejected()
        self.data['records'][0]['result'] = 'UNPROVED'
        self.data['records'][0]['gates'][0]['result'] = 'UNPROVED'
        result = self.run_check()
        self.assertFalse(result['errors'])
        self.assertEqual(result['overall'], 'INCOMPLETE')

    def test_metadata_never_current_or_material_pass(self):
        self.data['materials']['artifact']['access'] = 'private'
        (self.repo / 'artifact').unlink()
        result = self.run_check(mode='metadata')
        self.assertFalse(result['errors'])
        self.assertEqual(result['verification'], 'METADATA_ONLY_NOT_REVERIFIED')
        self.assertTrue(self.run_check(mode='metadata', require_current=True)['errors'])
        self.rejected()

    def test_unknown_material(self):
        self.data['records'][0]['artifact_materials'] = ['absent']
        self.rejected()

    def test_duplicate_gate(self):
        self.data['records'][0]['gates'] *= 2
        self.rejected()

    def test_unsafe_path(self):
        for path in ['/etc/shadow', '../artifact']:
            self.data['materials']['artifact']['path'] = path
            self.rejected()

    def test_unknown_schema(self):
        self.data['schema_version'] = 2
        self.rejected()

    def test_report_failure_not_rewriteable_as_pass(self):
        self.report['status'] = 'FAIL'
        self.update_report()
        self.rejected()


if __name__ == '__main__':
    unittest.main()
