"""Negative controls for the provenance checker, not protocol/hardware tests."""
import json
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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
        self.report = {'source': commit, 'scope': ['not locks, USB or RF'],
                       'status': 'SCOPED_PASS', 'bounds': 'fixture only'}
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
                                  bounds_pointer=['bounds'],
                                  source_pointers={'production': ['source']}, verdict_pointer=['status'],
                                  verdict_results={'SCOPED_PASS': 'PASS', 'UNSUPPORTED': 'UNPROVED'}),
                      artifact_materials=['artifact'], tool_materials=['artifact'], configuration_materials=[],
                      gates=[dict(id='gate', result='PASS', materials=['report.json', 'artifact'])],
                      required_gates=['gate'])
        # Publication and production compilation intentionally have distinct commits.
        subprocess.run(['git', '-C', str(self.repo), 'add', 'report.json', 'artifact'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
                        'commit', '-qm', 'publish report'], check=True)
        record['report_commit'] = q.git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        self.data = dict(schema_version=1, materials=materials, records=[record], overall_required_records=['one'])

    def run_check(self, **kwargs):
        return q.validate(self.data, self.repo, mode=kwargs.pop('mode', 'local'), **kwargs)

    def rejected(self):
        self.assertTrue(self.run_check()['errors'])

    def update_report(self):
        path = self.repo / 'report.json'
        path.write_text(json.dumps(self.report))
        self.data['materials']['report.json'].update(sha256=q.sha(path), bytes=path.stat().st_size)
        subprocess.run(['git', '-C', str(self.repo), 'add', 'report.json'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
                        'commit', '-qm', 'changed report'], check=True)
        self.data['records'][0]['report_commit'] = q.git(self.repo, 'rev-parse', 'HEAD').decode().strip()


    def test_positive_retained_bytes_is_not_replay(self):
        result = self.run_check(require_current=True)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['verification'], 'RETAINED_BYTES_VERIFIED_NOT_REPLAYED')

    def test_declared_evidence_level_cannot_be_reclassified_by_the_summary(self):
        self.report['qualification']=dict(level='offline');self.update_report()
        self.assertEqual(self.run_check()['errors'],[])
        record=self.data['records'][0];record['configuration_materials']=['artifact']
        for level in ('real_device','virtual_integration','formal_bounded','implemented'):
            record['level']=level
            with self.subTest(level=level):
                self.assertIn('one: evidence level/report mismatch',self.run_check()['errors'])

    def test_declared_report_level_is_typed_and_known(self):
        for level in (None,False,[],{},'hardware_assumed'):
            self.report['qualification']=dict(level=level);self.update_report()
            with self.subTest(level=level):
                self.assertIn('one: evidence level/report mismatch',self.run_check()['errors'])

    def typed_material_manifest(self, private=False):
        if private:
            self.data['materials']['artifact']['access'] = 'private'
        self.report.update(evidence_manifest_version=1,
                           materials={'artifact': copy.deepcopy(self.data['materials']['artifact'])})
        self.data['records'][0]['report'].update(material_binding_version=1,
                                                material_bindings={'artifact': 'artifact'})
        self.update_report()
        self.assertEqual(self.run_check()['errors'], [])

    def test_material_rehash_and_path_rebind_does_not_change_frozen_report_identity(self):
        self.typed_material_manifest()
        replacement = self.repo / 'replacement'
        replacement.write_bytes(b'a different freshly hashed artifact')
        self.data['materials']['artifact'].update(path='replacement', sha256=q.sha(replacement),
                                                  bytes=replacement.stat().st_size)
        self.assertIn('one: material/report binding mismatch artifact', self.run_check()['errors'])

    def test_material_binding_applies_to_private_metadata_without_claiming_bytes(self):
        self.typed_material_manifest(private=True)
        positive = self.run_check(mode='metadata')
        self.assertEqual(positive['errors'], [])
        self.assertEqual(positive['verification'], 'METADATA_ONLY_NOT_REVERIFIED')
        self.data['materials']['artifact']['sha256'] = 'f' * 64
        self.assertIn('one: material/report binding mismatch artifact', self.run_check(mode='metadata')['errors'])

    def test_declared_manifest_cannot_downgrade_to_legacy_or_omit_materials(self):
        self.typed_material_manifest()
        original = copy.deepcopy(self.data['records'][0]['report'])
        for change in [{'material_binding_version': 0}, {'material_binding_version': True},
                       {'material_binding_version': '1'}, {'material_bindings': {}},
                       {'material_bindings': {'another': 'artifact'}},
                       {'material_bindings': {'artifact': 'missing'}}]:
            self.data['records'][0]['report'] = dict(original, **change)
            with self.subTest(change=change):
                self.assertTrue(self.run_check()['errors'])
        self.data['records'][0]['report'] = {k:v for k,v in original.items()
                                           if k not in ['material_binding_version','material_bindings']}
        self.assertIn('one: invalid report material binding', self.run_check()['errors'])

    def typed_failed_matrix(self):
        record = self.data['records'][0]
        self.report.update(status='FAILED', runs=[
            dict(name='gate', status='PASS'), dict(name='failed', status='FAIL')])
        record.update(result='FAIL', required_gates=['gate', 'failed'])
        record['report']['verdict_results']['FAILED'] = 'FAIL'
        record['report']['gate_rows_pointer'] = ['runs']
        record['gates'] = [dict(id=name, result=status, materials=['report.json', 'artifact'],
                                report_pointer=['runs', i], reported_status=status,
                                result_binding_version=1)
                           for i, (name, status) in enumerate([('gate', 'PASS'), ('failed', 'FAIL')])]
        self.update_report()
        self.assertEqual(self.run_check()['errors'], [])
        self.assertNotEqual(self.run_check()['overall'], 'PASS')
        return record

    def test_failed_matrix_does_not_hide_individual_result_drift(self):
        record = self.typed_failed_matrix()
        for slot, status in [(0, 'UNPROVED'), (1, 'PASS')]:
            with self.subTest(slot=slot, status=status):
                gate = record['gates'][slot]
                original = gate['result']
                gate['result'] = status
                self.assertIn(f'one/{gate["id"]}: gate/report verdict mismatch',
                              self.run_check()['errors'])
                gate['result'] = original

    def test_typed_gate_rejects_unknown_status_even_when_identity_matches(self):
        record = self.typed_failed_matrix()
        self.report['runs'][0]['status'] = 'UNSUPPORTED_TOOL_EXIT_ZERO'
        record['gates'][0]['reported_status'] = 'UNSUPPORTED_TOOL_EXIT_ZERO'
        self.update_report()
        self.assertIn('one/gate: gate/report verdict mismatch', self.run_check()['errors'])

    def test_removing_optional_bindings_cannot_launder_a_failed_gate(self):
        record = self.typed_failed_matrix()
        for gate in record['gates']:
            for key in ['result_binding_version', 'report_pointer', 'reported_status']:
                del gate[key]
        record['gates'][1]['result'] = 'PASS'
        self.assertIn('one/failed: gate/report verdict mismatch', self.run_check()['errors'])

    def test_legacy_conservative_downgrade_is_retained(self):
        record = self.typed_failed_matrix()
        gate = record['gates'][0]
        for key in ['result_binding_version', 'report_pointer', 'reported_status']:
            del gate[key]
        gate['result'] = 'UNPROVED'
        self.assertEqual(self.run_check()['errors'], [])
        self.assertNotEqual(self.run_check()['overall'], 'PASS')

    def test_gate_result_binding_requires_known_version_and_report_pointer(self):
        record = self.typed_failed_matrix()
        gate = record['gates'][0]
        for version in [0, 2, True, False, None, '1']:
            with self.subTest(version=version):
                gate['result_binding_version'] = version
                self.assertIn('one/gate: invalid gate result binding', self.run_check()['errors'])
        gate['result_binding_version'] = 1
        del gate['report_pointer']
        self.assertIn('one/gate: invalid gate result binding', self.run_check()['errors'])

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

    def test_architecture_reference_cannot_maintain_independent_source_ids(self):
        self.data['baseline'] = {'kernel': 'a', 'compiled_userspace': 'b', 'executed_tools': 'c'}
        self.data['batch'] = {'id': 'fixture'}
        self.data['records'][0]['title'] = 'fixture'
        project = self.repo / 'project'
        project.mkdir()
        for name in ['current-capabilities.md', 'implementation-plan.md']:
            (project / name).write_text('<!-- qualification-summary:start -->old<!-- qualification-summary:end -->')
        path = project / 'goal-execution-state.json'
        path.write_text('{}')
        self.assertFalse(q.sync_views(self.data, self.repo, write=True))
        state = json.loads(path.read_text())
        state['architecture_retirement_current_batch'] = {
            'qualification_reference': {
                'source': 'qualification_view.selected_qualification',
                'scope': 'Selected retained artifact only;whole current tree not revalidated'}}
        path.write_text(json.dumps(state))
        self.assertFalse(q.sync_views(self.data, self.repo))
        for invalid in [None, {'record': 'older', 'compiled_kernel': 'old'},
                        dict(state['architecture_retirement_current_batch']['qualification_reference'], result='PASS')]:
            state['architecture_retirement_current_batch']['qualification_reference'] = invalid
            path.write_text(json.dumps(state))
            self.assertIn('goal: independent architecture qualification_reference', q.sync_views(self.data, self.repo))
            self.assertIn('goal: independent architecture qualification_reference', q.sync_views(self.data, self.repo, write=True))
            self.assertEqual(json.loads(path.read_text())['architecture_retirement_current_batch']['qualification_reference'], invalid)

    def test_allocated_lab_rejects_stale_operational_map_even_in_write_mode(self):
        import copy
        import ws73_lab_resources as resource
        self.data['baseline'] = {'kernel': 'a', 'compiled_userspace': 'b', 'executed_tools': 'c'}
        self.data['batch'] = {'id': 'fixture'}
        self.data['records'][0]['title'] = 'fixture'
        project = self.repo / 'project'
        project.mkdir()
        for name in ['current-capabilities.md', 'implementation-plan.md']:
            (project / name).write_text(q.render(self.data))
        policy = resource.policy()
        state = {'qualification_view': q.summary(self.data),
                 'hardware_resource_allocation': {
                     'policy': 'project/lab-resource-policy.json', 'owner': policy['owner'],
                     'allowed_U': ['1-1.1.1', '1-1.1.2'], 'allowed_E': ['1-2.1.1', '1-2.1.2'],
                     'forbidden': policy['forbidden_ports'], 'runtime_directory': policy['run_root'],
                     'source_worktree': policy['worktree']},
                 'hardware_constraint': {'operational_scope_ref': 'hardware_resource_allocation.policy'}}
        path = project / 'goal-execution-state.json'
        path.write_text(json.dumps(state))
        self.assertIn('goal: missing hardware allocation policy', q.sync_views(self.data, self.repo))
        (project / 'lab-resource-policy.json').write_text(json.dumps(policy))
        self.assertFalse(q.sync_views(self.data, self.repo))
        for key, value in [('current_operational_scope', 'old E1/U234 map'),
                           ('topology_revision', {'1-2.1.2': 'U'})]:
            bad = copy.deepcopy(state)
            bad['hardware_constraint'][key] = value
            path.write_text(json.dumps(bad))
            for write in [False, True]:
                self.assertIn('goal: stale independent hardware authority: ' + key,
                              q.sync_views(self.data, self.repo, write=write))
                self.assertEqual(json.loads(path.read_text()), bad)
        bad = copy.deepcopy(state)
        bad['hardware_resource_allocation']['allowed_U'] = ['1-1.1.3']
        path.write_text(json.dumps(bad))
        self.assertIn('goal: hardware allocation differs from policy: allowed_U',
                      q.sync_views(self.data, self.repo, write=True))
        self.assertEqual(json.loads(path.read_text()), bad)

    def test_selected_record_is_versioned_and_cannot_reference_retired_or_unknown(self):
        self.data['selected_qualification'] = {'version': 1, 'record': 'one'}
        self.assertFalse(self.run_check()['errors'])
        for value in [None, {}, 'one', {'version': 0, 'record': 'one'},
                      {'version': True, 'record': 'one'}, {'version': 1, 'record': []},
                      {'version': 1, 'record': 'unknown'},
                      {'version': 1, 'record': 'one', 'result': 'PASS'}]:
            with self.subTest(value=value):
                self.data['selected_qualification'] = value
                self.assertTrue(self.run_check()['errors'])

    def test_report_bound_counts_cannot_be_replaced_by_an_independent_summary(self):
        self.data['records'][0]['bounds'] = {'peer_roundtrips': 9999}
        self.assertIn('one: bounds mismatch', self.run_check()['errors'])

    def test_selected_pass_cannot_omit_bounds_mapping(self):
        self.data['selected_qualification'] = {'version': 1, 'record': 'one'}
        del self.data['records'][0]['report']['bounds_pointer']
        self.assertIn('selected PASS requires report-bound bounds', self.run_check()['errors'])

    def test_selection_renders_exact_sources_without_hiding_other_results(self):
        self.data['baseline'] = {'kernel': 'old-k', 'compiled_userspace': 'old-u', 'executed_tools': 'old-tools'}
        self.data['batch'] = {'id': 'fixture'}
        self.data['records'][0]['title'] = 'selected fixture'
        self.data['selected_qualification'] = {'version': 1, 'record': 'one'}
        other = dict(self.data['records'][0], id='unproved', title='required unproved', result='UNPROVED')
        self.data['records'].append(other)
        self.data['overall_required_records'].append('unproved')
        rendered = q.render(self.data)
        self.assertIn(self.data['records'][0]['sources']['production']['commit'], rendered)
        self.assertIn('required unproved', rendered)
        self.assertIn('UNPROVED', rendered)
        self.assertIn('NOT_REVALIDATED', rendered)
        self.assertIn('历史registry基线（非当前资格）', rendered)
        self.assertEqual(q.summary(self.data)['overall'], 'INCOMPLETE')
        self.assertEqual(q.summary(self.data)['selected_qualification'], self.data['selected_qualification'])

    def test_selected_bounds_follow_record_and_old_generated_counts_are_rejected(self):
        self.data['baseline'] = {'kernel': 'k', 'compiled_userspace': 'u', 'executed_tools': 't'}
        self.data['batch'] = {'id': 'fixture'}
        record = self.data['records'][0]
        record.update(title='source-bound fixture', bounds={'peer_roundtrips': 48, 'new_formal_proofs': 0})
        self.data['selected_qualification'] = {'version': 1, 'record': 'one'}
        project = self.repo / 'project'
        project.mkdir()
        for name in ['current-capabilities.md', 'implementation-plan.md']:
            (project / name).write_text(q.render(self.data))
        (project / 'goal-execution-state.json').write_text(json.dumps({'qualification_view': q.summary(self.data)}))
        self.assertFalse(q.sync_views(self.data, self.repo))
        old = (project / 'current-capabilities.md').read_text()
        self.assertIn('"peer_roundtrips": 48', old)
        self.assertIn('"new_formal_proofs": 0', old)
        record['bounds']['peer_roundtrips'] = 56
        self.assertIn('current-capabilities.md: stale qualification summary', q.sync_views(self.data, self.repo))
        self.assertFalse(q.sync_views(self.data, self.repo, write=True))
        self.assertIn('"peer_roundtrips": 56', (project / 'current-capabilities.md').read_text())
        self.assertNotIn('"peer_roundtrips": 48', (project / 'current-capabilities.md').read_text())

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

    def test_checker_crash_replaces_old_success_with_incomplete(self):
        output = self.repo / 'verdict.json'
        output.write_text(json.dumps({'verification': 'OLD_SUCCESS', 'completed': True}))
        # Crash in the actual CLI supervisor after its sentinel is published.
        with patch('sys.argv', ['check_qualifications', '--output', str(output)]):
            with patch.object(q, 'validate', side_effect=RuntimeError('injected supervisor crash')):
                with self.assertRaises(RuntimeError):
                    q.main()
        result = json.loads(output.read_text())
        self.assertEqual(result['verification'], 'RUNNING_NOT_QUALIFIED')
        self.assertFalse(result['completed'])
        self.assertTrue(result['errors'])

    def test_unknown_format_is_not_silently_opaque(self):
        self.data['materials']['report.json']['format'] = 'typo'
        self.rejected()

    def test_report_cannot_disable_binding_checks_as_bytes(self):
        self.data['materials']['report.json']['format'] = 'bytes'
        self.rejected()

    def test_retained_source_material_is_pinned_not_current_worktree(self):
        source = self.data['records'][0]['sources']['production']
        path = self.repo / 'production.rs'
        self.data['materials']['source'] = dict(base='repo', path='production.rs',
            source_commit=source['commit'], access='public', format='bytes',
            sha256=q.sha(path), bytes=path.stat().st_size)
        path.write_text('new development must not rewrite old retained qualification')
        self.assertFalse(self.run_check()['errors'])
        self.assertTrue(self.run_check(require_current=True)['errors'])

    def test_missing_source_material_object_is_not_a_worktree_fallback(self):
        self.data['materials']['artifact']['source_commit'] = 'f' * 40
        self.rejected()

    def test_report_revision_cannot_be_replaced_with_compiled_source(self):
        self.data['records'][0]['report_commit'] = self.report['source']
        self.rejected()

    def test_publication_identity_is_separate_and_checked(self):
        self.assertNotEqual(self.data['records'][0]['report_commit'], self.report['source'])
        self.assertFalse(self.run_check()['errors'])
        self.data['records'][0]['report_commit'] = None
        self.rejected()

    def test_unknown_schema(self):
        self.data['schema_version'] = 2
        self.rejected()

    def test_report_failure_not_rewriteable_as_pass(self):
        self.report['status'] = 'FAIL'
        self.update_report()
        self.rejected()


class RetirementTests(unittest.TestCase):
    setUp = QualificationTests.setUp
    run_check = QualificationTests.run_check
    update_report = QualificationTests.update_report
    def retire(self):
        import copy
        directory=self.repo/'project';directory.mkdir()
        (directory/'qualification-records.json').write_text(json.dumps(self.data))
        subprocess.run(['git','-C',str(self.repo),'add','project/qualification-records.json'],check=True)
        subprocess.run(['git','-C',str(self.repo),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','commit','-qm','original registry'],check=True)
        revision=q.git(self.repo,'rev-parse','HEAD').decode().strip()
        old=copy.deepcopy(self.data['records'][0]);material=self.data['materials'].pop('artifact')
        record=self.data['records'][0];record.update(id='incident',result='UNPROVED',artifact_materials=['report.json'],tool_materials=['report.json'])
        record['gates'][0].update(result='UNPROVED',materials=['report.json'])
        self.report['status']='UNSUPPORTED';self.update_report()
        self.data['overall_required_records']=['incident']
        self.data['retirements']=[dict(original_registry_commit=revision,incident_record='incident',reason='original artifact lost; no replacement digest',records=[old],materials={'artifact':material})]
        (self.repo/'artifact').write_bytes(b'corrupted replacement is not the original')
    def test_retirement_preserves_originals_and_requires_unproved_incident(self):
        self.retire();result=self.run_check()
        self.assertEqual(result['errors'],[]);self.assertEqual(result['overall'],'INCOMPLETE')
        self.assertEqual(result['verification'],'ACTIVE_BYTES_VERIFIED_RETIRED_EVIDENCE_UNAVAILABLE_NOT_REPLAYED')
        self.assertEqual(result['retired_evidence_unavailable'],['incident'])
    def test_retirement_cannot_waive_requirement_or_rewrite_old_hash(self):
        import copy
        self.retire();original=copy.deepcopy(self.data)
        for mutation in ['unrequired','pass','old-hash','old-record','revision','active']:
            self.data=copy.deepcopy(original);retired=self.data['retirements'][0]
            if mutation=='unrequired':self.data['overall_required_records']=[]
            elif mutation=='pass':self.data['records'][0]['result']='PASS'
            elif mutation=='old-hash':retired['materials']['artifact']['sha256']='0'*64
            elif mutation=='old-record':retired['records'][0]['result']='UNPROVED'
            elif mutation=='revision':retired['original_registry_commit']='0'*40
            else:self.data['records'].append(copy.deepcopy(retired['records'][0]))
            with self.subTest(mutation=mutation):self.assertTrue(self.run_check()['errors'])


if __name__ == '__main__':
    unittest.main()
