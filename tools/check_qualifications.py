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
        if binding:
            report = documents.get(binding['material'])
            if report is not None:
                if binding['verdict_results'].get(select(report, binding['verdict_pointer'])) != record['result']:
                    errors.append(f'{ident}: report/result mismatch')
                if select(report, binding['scope_pointer']) != record['excluded']:
                    errors.append(f'{ident}: scope mismatch')
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
    if require_current and mode != 'local':
        errors.append('current qualification requires local material verification')
    if changed:
        errors.append('source changed since qualification: ' + ', '.join(changed))
    complete = all(r['result'] == 'PASS' for r in data['records'] if r['id'] in data['overall_required_records'])
    return {'errors': errors, 'unavailable_private_materials': unavailable,
            'unavailable_source_checkouts': unavailable_sources,
            'verification': 'INVALID' if errors else ('METADATA_ONLY_NOT_REVERIFIED' if unavailable or unavailable_sources else 'RETAINED_BYTES_VERIFIED_NOT_REPLAYED'),
            'current': 'NOT_CHECKED' if not require_current else ('NOT_QUALIFIED' if errors else 'SCOPED_SOURCE_AND_BYTES_MATCH_NOT_REPLAYED'),
            'overall': 'RECORDED_REQUIRED_RESULTS_PASS' if complete else 'INCOMPLETE'}


def summary(data):
    return {'registry': 'project/qualification-records.json', 'schema_version': data['schema_version'],
            'baseline': data['baseline'], 'current_tree_qualification': 'NOT_REVALIDATED',
            'private_evidence_in_ci': 'METADATA_ONLY_NOT_REVERIFIED',
            'records': {r['id']: {'level': r['level'], 'result': r['result']} for r in data['records']},
            'overall': 'INCOMPLETE', 'current_batch': data['batch']}


def render(data):
    lines = ['<!-- qualification-summary:start -->',
             '以下摘要由 `project/qualification-records.json` 生成；不以文档提交替代编译身份。', '',
             '| 契约（仅所列范围） | 证据层级 | 记录结果 |', '|---|---|---|']
    for record in data['records']:
        lines.append(f'| {record["title"]} | `{record["level"]}` | `{record["result"]}` |')
    lines += ['', '保留镜像：K `' + data['baseline']['kernel'] + '`；编译 U `' + data['baseline']['compiled_userspace'] +
              '`；执行工具 `' + data['baseline']['executed_tools'] + '`。', '',
              '**当前工作树：NOT_REVALIDATED；完整范围：INCOMPLETE。** Agent 接线不继承旧实机资格。',
              '公开 CI 只验证元数据（METADATA_ONLY_NOT_REVERIFIED）；私有原材料不可取得时不授予当前 PASS。',
              '本地完整性核对也不等于重放、独立空口解码或实现证明。层级、假设及门禁见',
              '[资格契约 ADR](../docs/decisions/0005-qualification-and-quality-gates.md)。',
              '<!-- qualification-summary:end -->']
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
