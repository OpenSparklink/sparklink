#!/usr/bin/env python3
"""Fail-closed qualification provenance checks; never executes a device test.

Metadata mode cannot verify private materials or certify current code. Local mode
checks retained bytes; --require-current additionally checks scoped source bytes.
Neither mode independently re-decodes RF captures or proves build reproducibility.
"""
import argparse
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RESULTS = {'PASS', 'FAIL', 'UNPROVED', 'MISSING', 'SKIP'}
LEVELS = {'implemented', 'offline', 'formal_bounded', 'virtual_integration', 'real_device'}


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def select(value, pointer):
    for key in pointer:
        value = value[key]
    return value


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def scoped_files(repo, commit, paths):
    return dict(_scoped_files(repo, commit, tuple(paths)))


@lru_cache(maxsize=32)
def _scoped_files(repo, commit, paths):
    """Hash ALL committed files in declared scopes, not a selected positive subset."""
    names = git(repo, 'ls-tree', '-r', '--name-only', commit, '--', *paths).decode().splitlines()
    return {name: hashlib.sha256(git(repo, 'show', f'{commit}:{name}')).hexdigest()
            for name in names}


def validate(data, repo=ROOT, workspace=None, mode='metadata', require_current=False):
    workspace = workspace or repo.parent
    errors, unavailable, changed, unavailable_sources = [], [], [], []
    documents = {}
    if data.get('schema_version') != 1:
        return {'errors': ['unsupported schema'], 'verification': 'INVALID'}
    materials = data['materials']
    for ident, item in materials.items():
        path = Path(item['path'])
        if path.is_absolute() or '..' in path.parts or not re.fullmatch(r'[a-f0-9]{64}', item['sha256']):
            errors.append(f'{ident}: unsafe path or invalid hash')
            continue
        if item['base'] not in ('repo', 'workspace') or item['access'] not in ('public', 'private') or item['format'] not in ('json', 'bytes'):
            errors.append(f'{ident}: invalid location/access')
            continue
        if item['access'] == 'private' and mode == 'metadata':
            unavailable.append(ident)
            continue
        revision = item.get('source_commit')
        if revision is not None:
            if item['base'] != 'repo' or not re.fullmatch(r'[a-f0-9]{40}', revision):
                errors.append(f'{ident}: invalid source material revision')
                continue
            try:
                blob = git(repo, 'show', f'{revision}:{path.as_posix()}')
            except subprocess.CalledProcessError:
                errors.append(f'{ident}: missing retained source object')
                continue
            if hashlib.sha256(blob).hexdigest() != item['sha256'] or len(blob) != item['bytes']:
                errors.append(f'{ident}: retained source hash/size mismatch')
                continue
            content = blob if item['format'] == 'json' else None
        else:
            location = (repo if item['base'] == 'repo' else workspace) / path
            if not location.is_file():
                errors.append(f'{ident}: missing material')
                continue
            if sha(location) != item['sha256'] or location.stat().st_size != item['bytes']:
                errors.append(f'{ident}: hash/size mismatch')
                continue
            content = location.read_bytes() if item['format'] == 'json' else None
        if item['format'] == 'json':
            documents[ident] = json.loads(content)
            for assertion in item.get('assertions', []):
                if select(documents[ident], assertion['pointer']) != assertion['equals']:
                    errors.append(f'{ident}: assertion mismatch {assertion["pointer"]}')

    record_ids = set()
    for record in data['records']:
        ident = record['id']
        if ident in record_ids or record['level'] not in LEVELS or record['result'] not in RESULTS:
            errors.append(f'{ident}: duplicate/invalid record')
        record_ids.add(ident)
        if not record['contracts'] or not record['remaining'] or not record['bounds']:
            errors.append(f'{ident}: missing contract/bounds/remaining scope')
        # A scope copied into a summary may never silently diverge from its report.
        binding = record.get('report')
        if binding and binding['material'] not in materials:
            errors.append(f'{ident}: missing report material')
        if binding and binding['material'] in materials and materials[binding['material']]['format'] != 'json':
            errors.append(f'{ident}: report must be parsed JSON')
        if binding and record['result'] in ('PASS', 'UNPROVED'):
            revision = record.get('report_commit')
            material = materials.get(binding['material'], {})
            if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision) or material.get('base') != 'repo':
                errors.append(f'{ident}: missing exact public report revision')
            else:
                try:
                    published = git(repo, 'show', f'{revision}:{material["path"]}')
                    if hashlib.sha256(published).hexdigest() != material['sha256'] or len(published) != material['bytes']:
                        errors.append(f'{ident}: report publication hash/size mismatch')
                except subprocess.CalledProcessError:
                    errors.append(f'{ident}: report absent at publication revision')
        if binding:
            report = documents.get(binding['material'])
            if report is not None:
                if binding['verdict_results'].get(select(report, binding['verdict_pointer'])) != record['result']:
                    errors.append(f'{ident}: report/result mismatch')
                if select(report, binding['scope_pointer']) != record['excluded']:
                    errors.append(f'{ident}: scope mismatch')
                if 'bounds_pointer' in binding and select(report, binding['bounds_pointer']) != record['bounds']:
                    errors.append(f'{ident}: bounds mismatch')
                if 'gate_rows_pointer' in binding and [row['name'] for row in select(report, binding['gate_rows_pointer'])] != record['required_gates']:
                    errors.append(f'{ident}: required gates differ from complete report matrix')
                for role, pointer in binding['source_pointers'].items():
                    if select(report, pointer) != record['sources'][role]['commit']:
                        errors.append(f'{ident}: report/source mismatch {role}')
        gates = {gate['id']: gate for gate in record['gates']}
        if len(gates) != len(record['gates']) or not record['required_gates'] or set(gates) != set(record['required_gates']):
            errors.append(f'{ident}: missing/extra/duplicate gate')
        if any(gate['result'] not in RESULTS for gate in gates.values()):
            errors.append(f'{ident}: invalid gate result')
        if record['result'] == 'PASS':
            if any(gate['result'] != 'PASS' for gate in gates.values()):
                errors.append(f'{ident}: PASS hides a required non-PASS gate')
            if not record['sources'] or not binding or not record['artifact_materials'] or not record['tool_materials']:
                errors.append(f'{ident}: PASS lacks source/artifact/tools/report')
            if record['level'] == 'real_device' and not record['configuration_materials']:
                errors.append(f'{ident}: real qualification lacks config/firmware')
        for material in (record['artifact_materials'] + record['tool_materials'] + record['configuration_materials']):
            if material not in materials:
                errors.append(f'{ident}: unknown required material {material}')
        for gate in gates.values():
            if gate['result'] == 'PASS' and not gate['materials']:
                errors.append(f'{ident}/{gate["id"]}: PASS lacks evidence')
            for material in gate['materials']:
                if material not in materials:
                    errors.append(f'{ident}: unknown gate material {material}')
            # Independent gate identity/status pinned in the published matrix.
            if binding and (report := documents.get(binding['material'])) is not None and 'report_pointer' in gate:
                row = select(report, gate['report_pointer'])
                if row['name'] != gate['id'] or row['status'] != gate['reported_status']:
                    errors.append(f'{ident}/{gate["id"]}: gate/report identity mismatch')
        for role, source in record['sources'].items():
            if source['repo'] not in ('sparklink', 'linux') or any(Path(p).is_absolute() or '..' in Path(p).parts for p in source['scopes']):
                errors.append(f'{ident}/{role}: unsafe source scope')
                continue
            if not re.fullmatch(r'[a-f0-9]{40}', source['commit']) or not source['files']:
                errors.append(f'{ident}/{role}: missing exact source')
                continue
            mapping = source.get('manifest_mapping')
            if mapping and (mapping['material'] not in materials or materials[mapping['material']]['format'] != 'json'):
                errors.append(f'{ident}/{role}: source mapping requires JSON manifest')
            if mapping and (manifest := documents.get(mapping['material'])) is not None:
                if select(manifest, mapping['pointer']) != source['files']:
                    errors.append(f'{ident}/{role}: build manifest/source mapping mismatch')
            location = repo if source['repo'] == 'sparklink' else workspace / source['repo']
            if not (location / '.git').exists():
                unavailable_sources.append(f'{ident}/{role}')
                if require_current:
                    errors.append(f'{ident}/{role}: source checkout unavailable')
                continue
            try:
                if scoped_files(location, source['commit'], source['scopes']) != source['files']:
                    errors.append(f'{ident}/{role}: stale/incomplete source mapping')
                if require_current:
                    names = git(location, 'ls-files', '--cached', '--others', '--exclude-standard', '--', *source['scopes']).decode().splitlines()
                    actual = {name: sha(location / name) for name in set(names) if (location / name).is_file()}
                    if actual != source['files']:
                        changed.append(f'{ident}/{role}')
            except subprocess.CalledProcessError:
                errors.append(f'{ident}/{role}: source object unavailable')
    selected = data.get('selected_qualification')
    if 'selected_qualification' in data:
        if (not isinstance(selected, dict) or set(selected) != {'version', 'record'}
                or type(selected.get('version')) is not int or selected.get('version') != 1
                or not isinstance(selected.get('record'), str) or selected.get('record') not in record_ids):
            errors.append('invalid selected source-bound qualification record')
        elif next(r for r in data['records'] if r['id'] == selected['record'])['result'] == 'PASS':
            chosen = next(r for r in data['records'] if r['id'] == selected['record'])
            if not chosen.get('report', {}).get('bounds_pointer'):
                errors.append('selected PASS requires report-bound bounds')
    if 'baseline_record' in data:
        baseline_record = next((r for r in data['records'] if r['id'] == data['baseline_record']), None)
        if baseline_record is None:
            errors.append('missing baseline record')
        else:
            for name in ['kernel', 'compiled_userspace', 'executed_tools']:
                if data['baseline'][name] != baseline_record['sources'][name]['commit']:
                    errors.append(f'baseline/source mismatch: {name}')
            if data['baseline']['report_commit'] != baseline_record['report_commit']:
                errors.append('baseline/report commit mismatch')
    if not set(data['overall_required_records']).issubset(record_ids):
        errors.append('unknown overall required record')
    # Loss/corruption must not leave a historical PASS in the current view.
    # Preserve exact original metadata from git, and replace its requirement
    # with an explicitly required, non-PASS incident. This is not a waiver or
    # a way to bless replacement bytes under the original digest.
    retired_ids = set()
    for retirement in data.get('retirements', []):
        incident = next((r for r in data['records'] if r['id'] == retirement.get('incident_record')), None)
        if (incident is None or incident['id'] not in data['overall_required_records'] or
                incident['result'] not in ('FAIL', 'UNPROVED') or not retirement.get('reason')):
            errors.append('retirement requires a required non-PASS incident')
        revision = retirement.get('original_registry_commit', '')
        if not re.fullmatch(r'[a-f0-9]{40}', revision):
            errors.append('retirement requires original registry revision')
            continue
        try:
            original = json.loads(git(repo, 'show', f'{revision}:project/qualification-records.json'))
        except (subprocess.CalledProcessError, ValueError):
            errors.append('retirement original registry unavailable')
            continue
        originals = {r['id']: r for r in original['records']}
        if not retirement.get('records') or not retirement.get('materials'):
            errors.append('retirement must preserve records and damaged material metadata')
        for old in retirement.get('records', []):
            ident = old['id']
            if ident in retired_ids or ident in record_ids or old != originals.get(ident):
                errors.append(f'{ident}: invalid/changed/active retired record')
            retired_ids.add(ident)
        for ident, old in retirement.get('materials', {}).items():
            if ident in materials or old != original['materials'].get(ident):
                errors.append(f'{ident}: original damaged material metadata changed or still active')
    if require_current and mode != 'local':
        errors.append('current qualification requires local material verification')
    if changed:
        errors.append('source changed since qualification: ' + ', '.join(changed))
    complete = all(r['result'] == 'PASS' for r in data['records'] if r['id'] in data['overall_required_records'])
    return {'errors': errors, 'unavailable_private_materials': unavailable,
            'unavailable_source_checkouts': unavailable_sources,
            'verification': 'INVALID' if errors else ('METADATA_ONLY_NOT_REVERIFIED' if unavailable or unavailable_sources else 'ACTIVE_BYTES_VERIFIED_RETIRED_EVIDENCE_UNAVAILABLE_NOT_REPLAYED' if retired_ids else 'RETAINED_BYTES_VERIFIED_NOT_REPLAYED'),
            'retired_evidence_unavailable': [r['incident_record'] for r in data.get('retirements', [])],
            'current': 'NOT_CHECKED' if not require_current else ('NOT_QUALIFIED' if errors else 'SCOPED_SOURCE_AND_BYTES_MATCH_NOT_REPLAYED'),
            'overall': 'RECORDED_REQUIRED_RESULTS_PASS' if complete else 'INCOMPLETE'}


def summary(data):
    return {'registry': 'project/qualification-records.json', 'schema_version': data['schema_version'],
            'baseline': data['baseline'], 'current_tree_qualification': 'NOT_REVALIDATED',
            'private_evidence_in_ci': 'METADATA_ONLY_NOT_REVERIFIED',
            'records': {r['id']: {'level': r['level'], 'result': r['result']} for r in data['records']},
            'overall': 'INCOMPLETE', 'current_batch': data['batch'],
            **({'selected_qualification': data['selected_qualification']} if 'selected_qualification' in data else {})}


def render(data):
    lines = ['<!-- qualification-summary:start -->',
             '以下摘要由 `project/qualification-records.json` 生成；不以文档提交替代编译身份。', '',
             '| 契约（仅所列范围） | 证据层级 | 记录结果 |', '|---|---|---|']
    if 'selected_qualification' in data:
        choice = data['selected_qualification']
        if choice.get('version') != 1:
            raise ValueError('unsupported selected qualification version')
        record = next(r for r in data['records'] if r['id'] == choice['record'])
        selection = ['选定保留产物（不是当前工作树整体资格）：**'+record['title']+'**。',
                     '仅记录范围：`'+record['level']+'` / `'+record['result']+'`。']
        selection += [name+' `'+source['commit']+'`。'
                      for name, source in record['sources'].items()]
        if record.get('report'):
            material = data['materials'][record['report']['material']]
            selection += ['[准确范围与剩余条件](../'+material['path']+')。']
        selection += ['', '限定边界由同一记录生成；计数不代替必需门禁、假设或范围：',
                      '```json', json.dumps(record['bounds'], ensure_ascii=False,
                                           indent=2, sort_keys=True), '```']
        lines[2:2] = ['']+selection+['', '以下为全部限定/历史记录索引；旧 PASS 不转授选定产物。', '']
    for record in data['records']:
        lines.append(f'| {record["title"]} | `{record["level"]}` | `{record["result"]}` |')
    lines += ['', '历史registry基线（非当前资格）：K `' + data['baseline']['kernel'] + '`；编译 U `' + data['baseline']['compiled_userspace'] +
              '`；执行工具 `' + data['baseline']['executed_tools'] + '`。', '',
              '**当前工作树整体资格：NOT_REVALIDATED；完整范围：INCOMPLETE。** 分项按各自准确源码记录。',
              '公开 CI 只验证元数据（METADATA_ONLY_NOT_REVERIFIED）；私有原材料不可取得时不授予当前 PASS。',
              '本地完整性核对也不等于重放、独立空口解码或实现证明。层级、假设及门禁见',
              '[资格契约 ADR](../docs/decisions/0005-qualification-and-quality-gates.md)。',
              '<!-- qualification-summary:end -->']
    if 'guest_tools' in data['baseline']:
        lines.insert(-1, '预备/guest 工具 `' + data['baseline']['guest_tools'] + '`；上列执行工具为 Host 校验工具，分别记录。')
    return '\n'.join(lines)


def sync_views(data, repo, write=False):
    errors = []
    for name in ['current-capabilities.md', 'implementation-plan.md']:
        path = repo / 'project' / name
        text = path.read_text()
        pattern = r'<!-- qualification-summary:start -->.*?<!-- qualification-summary:end -->'
        matches = re.findall(pattern, text, flags=re.S)
        if len(matches) != 1:
            errors.append(f'{name}: expected one generated summary')
        elif matches[0] != render(data):
            if write:
                path.write_text(re.sub(pattern, lambda _: render(data), text, flags=re.S))
            else:
                errors.append(f'{name}: stale qualification summary')
    path = repo / 'project/goal-execution-state.json'
    state = json.loads(path.read_text())
    if state.get('qualification_view') != summary(data):
        if write:
            state['qualification_view'] = summary(data)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
        else:
            errors.append('goal: stale qualification view')
    for legacy in ['current_heads', 'current_qualification', 'current_batch', 'current_batch_exit', 'qualified_source_heads', 'current_qualified_subsets']:
        if legacy in state:
            errors.append(f'goal: independently maintained {legacy}')
    architecture = state.get('architecture_retirement_current_batch', {})
    if not isinstance(architecture, dict):
        errors.append('goal: invalid architecture execution state')
    elif 'qualification_reference' in architecture:
        # Execution history is not a second place to maintain compiled IDs.
        # Never silently rewrite a stale independent claim, even in write mode.
        reference = {'source': 'qualification_view.selected_qualification',
                     'scope': 'Selected retained artifact only;whole current tree not revalidated'}
        if architecture['qualification_reference'] != reference:
            errors.append('goal: independent architecture qualification_reference')
    # Optional only for generic fixture/downstream checkouts without a physical
    # allocation. An allocated lab has one current topology authority; old
    # device qualifications must not remain an alternative operational map.
    if 'hardware_resource_allocation' in state:
        from ws73_lab_resources import execution_state_errors
        allocation = repo / 'project/lab-resource-policy.json'
        if not allocation.is_file():
            errors.append('goal: missing hardware allocation policy')
        else:
            errors.extend(execution_state_errors(state, json.loads(allocation.read_text())))
    return errors


def write_report(path, value):
    """Replace atomically; an interrupted run must not retain a success verdict."""
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['metadata', 'local'], default='metadata')
    parser.add_argument('--require-current', action='store_true')
    parser.add_argument('--write-views', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        write_report(args.output, {'verification': 'RUNNING_NOT_QUALIFIED',
                                   'completed': False, 'errors': ['checker has not completed']})
    try:
        data = json.loads((ROOT / 'project/qualification-records.json').read_text())
        result = validate(data, mode=args.mode, require_current=args.require_current)
        # Never write a success view after failed validation.
        result['errors'].extend(sync_views(data, ROOT, args.write_views and not result['errors']))
    except (KeyError, ValueError, OSError, TypeError, IndexError) as exc:
        result = {'errors': [f'invalid qualification data: {exc}'], 'verification': 'INVALID'}
    if result['errors']:
        result['verification'] = 'INVALID'
    result['completed'] = True
    output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        write_report(args.output, result)
    print(output, end='')
    raise SystemExit(bool(result['errors']))


if __name__ == '__main__':
    main()
