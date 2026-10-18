#!/usr/bin/env python3
"""Check dispositions, authoritative sources, navigation and public output."""
from collections import Counter
from pathlib import Path
import argparse
import os
import json
import re
import tomllib
import subprocess
import hashlib


from docs_integrity import audit_html, source_target, reader_source
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--html', type=Path)
    parser.add_argument('--report', type=Path,
                        help='Write current source hashes and dispositions; baseline hashes remain unchanged.')
    args = parser.parse_args()
    inventory = tomllib.loads((DOCS / 'documentation-map.toml').read_text())
    errors = []
    items = inventory['documents']
    paths = [x['path'] for x in items]
    if inventory['schema_version'] != 2 or len(paths) != len(set(paths)):
        errors.append('invalid inventory schema or duplicate entry')
    required = {'reader', 'purpose', 'section', 'validity', 'applicable_version',
                'authority', 'disposition', 'source_sha256', 'publication'}
    for item in items:
        if not required.issubset(item) or not all(item[k] for k in required):
            errors.append(f"incomplete disposition: {item['path']}")
        if not (ROOT / item['path']).is_file():
            errors.append(f"missing original: {item['path']}")
        if item['publication'] == 'html' and not reader_source(item['path']):
            errors.append(f"only four reader categories may be published: {item['path']}")
    # HTML originals are checked by the actual Sphinx hook. Also check active
    # source-only pages explicitly reviewed in this batch; historical originals
    # retain their old links as evidence, not current recommendations.
    published = {x['path'] for x in items if x['publication'] == 'html'}
    for item in items:
        if not item.get('reviewed_source_commit') or not item['path'].endswith('.md'):
            continue
        page = ROOT / item['path']
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', page.read_text()):
            if urlsplit(target).scheme or target.startswith('#'):
                continue
            try:
                absolute = source_target(ROOT, page, target)
                relative = str(absolute.relative_to(ROOT))
                source_target(ROOT, page, target, check_anchor=relative not in published)
            except ValueError as exc:
                errors.append(str(exc))
    tracked = set(subprocess.check_output(
        ['git', 'ls-files'], cwd=ROOT, text=True).splitlines())
    # Include new untracked docs while preparing a reviewable commit. Generated
    # HTML, caches and external worktrees are not repository documentation.
    for directory in [DOCS, ROOT / 'project', ROOT / 'history']:
        tracked.update(str(p.relative_to(ROOT)) for p in directory.rglob('*.md')
                       if '_build' not in p.parts)
    path_map = json.loads((DOCS / 'documentation-paths.json').read_text())
    for old, new in path_map['migrations'].items():
        if (ROOT / old).exists() or not (ROOT / new).is_file():
            errors.append(f'physical migration incomplete: {old} -> {new}')
    if any(p.stem.upper() == p.stem for p in DOCS.glob('*.md')):
        errors.append('uppercase Markdown remains in docs root')
    for source, page in path_map['canonical_projections'].items():
        expected = '```{include} ' + str(Path(os.path.relpath(ROOT/source, (ROOT/page).parent))) + '\n```'
        if (ROOT/page).read_text().strip() != expected:
            errors.append(f'canonical projection duplicates or replaces source: {page}')

    tracked = {path for path in tracked if (ROOT/path).is_file() and (
        Path(path).suffix in {'.md', '.rst'} or Path(path).name == 'README'
        or path.startswith(('data/man/', 'data/config/')))}
    for path in sorted(tracked - set(paths)):
        errors.append(f'unmapped document: {path}')
    kernel_map = json.loads((DOCS / 'kernel-documentation-map.json').read_text())
    fields = {'repo', 'path', 'reader', 'purpose', 'section', 'validity',
              'applicable_version', 'authority', 'disposition',
              'source_sha256', 'original_url'}
    entries = kernel_map['documents']
    if len({x['path'] for x in entries}) != len(entries):
        errors.append('duplicate kernel disposition')
    for item in entries:
        if not fields.issubset(item) or not all(item[k] for k in fields):
            errors.append('incomplete kernel disposition')
    # The downloaded user repository builds independently. When the sibling
    # kernel is present, also reject silently omitted kernel documentation.
    kernel = ROOT.parent / 'linux'
    if (kernel / '.git').exists():
        kernel_sources = subprocess.check_output(
            ['git', 'ls-files', 'Documentation/*', 'net/sparklink/*',
             'tools/testing/selftests/sparklink/*'], cwd=kernel,
            text=True).splitlines()
        scoped = {p for p in kernel_sources
                  if ('sparklink' in p or 'ws73' in p)
                  and (p.endswith(('.rst', '.md')) or Path(p).name == 'README')}
        for path in sorted(scoped - {x['path'] for x in entries}):
            errors.append(f'unmapped kernel document: {path}')
    canonical = {x['path'] for x in items if x['status'] == 'canonical'}
    if canonical != {'project/architecture.md', 'project/implementation-plan.md', 'project/current-capabilities.md'}:
        errors.append('canonical architecture/plan/capabilities changed')
    owners = Counter()
    for page in DOCS.rglob('*.md'):
        if '_build' in page.parts:
            continue
        for block in re.findall(r'```\{toctree\}\n(.*?)\n```', page.read_text(), re.S):
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith(':'):
                    continue
                target = (page.parent / (line + '.md')).resolve()
                if not target.is_relative_to(DOCS) or not target.is_file():
                    errors.append(f'{page}: invalid navigation {line}')
                owners[str(target.relative_to(ROOT))] += 1
    for item in items:
        if item['publication'] == 'html' and item['path'] != 'docs/index.md' and owners[item['path']] != 1:
            errors.append(f"expected one canonical navigation home: {item['path']}")
    if args.html:
        expected = {x['path'][5:].rsplit('.', 1)[0] + '.html' for x in items
                    if x['publication'] == 'html' and x['path'].startswith('docs/')}
        expected.update({'index.html', 'search.html'})
        revision = os.environ.get('SPARKLINK_DOCS_REVISION') or subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        errors.extend(audit_html(args.html, expected, revision))
    if errors:
        print('\n'.join(errors))
        return 1
    if args.report:
        current = [{**item, 'current_sha256': hashlib.sha256(
                    (ROOT / item['path']).read_bytes()).hexdigest()}
                   for item in items]
        report = {
            'schema_version': 1,
            'source_revision': subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'working_tree_changes': subprocess.check_output(
                ['git', 'status', '--porcelain'], cwd=ROOT, text=True).splitlines(),
            'inventory_baseline': inventory['baseline'],
            'scope': 'Documentation inventory and optional local HTML integrity only; not browser or hardware qualification.',
            'html_checked': args.html is not None,
            'documents': current,
            'kernel_documents': entries,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'Documentation inventory PASS: {len(items)} documents (originals and reader pages); explicit dispositions; canonical sources retained.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
