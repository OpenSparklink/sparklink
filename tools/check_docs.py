#!/usr/bin/env python3
"""Check dispositions, authoritative sources, navigation and public output."""
from collections import Counter
from pathlib import Path
import argparse
import json
import re
import tomllib
import subprocess
import hashlib
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "id" in data:
            self.ids.add(data["id"])
        for attr in ("href", "src"):
            if attr in data:
                self.links.append(data[attr])


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
    tracked = set(subprocess.check_output(
        ['git', 'ls-files', '*.md'], cwd=ROOT, text=True).splitlines())
    # Include new untracked docs while preparing a reviewable commit. Generated
    # HTML, caches and external worktrees are not repository documentation.
    tracked.update(str(p.relative_to(ROOT)) for p in DOCS.rglob('*.md')
                   if '_build' not in p.parts)
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
            ['git', 'ls-files', 'Documentation/*',
             'tools/testing/selftests/sparklink/*.md'], cwd=kernel,
            text=True).splitlines()
        scoped = {p for p in kernel_sources
                  if ('sparklink' in p or 'ws73' in p)
                  and p.endswith(('.rst', '.md'))}
        for path in sorted(scoped - {x['path'] for x in entries}):
            errors.append(f'unmapped kernel document: {path}')
    canonical = {x['path'] for x in items if x['status'] == 'canonical'}
    if canonical != {'docs/ARCHITECTURE.md', 'docs/IMPLEMENTATION_PLAN.md', 'docs/CURRENT_CAPABILITIES.md'}:
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
        html_root = args.html.resolve()
        parsed = {}
        for page in html_root.rglob('*.html'):
            parser = HtmlLinks()
            parser.feed(page.read_text())
            parsed[page] = parser
        for page, parser in parsed.items():
            for link in parser.links:
                url = urlsplit(link)
                if url.scheme or url.netloc:
                    continue
                target = (page.parent / unquote(url.path)).resolve() if url.path else page
                if target.is_dir():
                    target /= 'index.html'
                if not target.is_relative_to(html_root) or not target.is_file():
                    errors.append(f'broken local resource: {page.name}: {link}')
                elif url.fragment and target in parsed and unquote(url.fragment) not in parsed[target].ids:
                    errors.append(f'broken local anchor: {page.name}: {link}')
        for page in parsed:
            if re.search(r'/home/[^\s<]+|file://', page.read_text()):
                errors.append(f'private path in public HTML: {page.name}')
        if (args.html / 'evidence').exists():
            extra = [p for p in (args.html / 'evidence').rglob('*') if p.is_file() and p.suffix not in {'.html'}]
            if extra:
                errors.append('raw evidence copied to public site')
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
