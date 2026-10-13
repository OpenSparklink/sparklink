#!/usr/bin/env python3
"""Check dispositions, authoritative sources, navigation and public output."""
from collections import Counter
from pathlib import Path
import argparse
import re
import tomllib
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
    legacy = {str(p.relative_to(ROOT)) for p in DOCS.glob('*.md') if p.name != 'index.md'}
    legacy.update(str(p.relative_to(ROOT)) for p in (DOCS / 'decisions').glob('*.md') if p.name != 'index.md')
    for path in legacy - set(paths):
        errors.append(f'unmapped original: {path}')
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
        if item['publication'] == 'html' and owners[item['path']] != 1:
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
    print(f'Documentation inventory PASS: {len(items)} original documents; explicit dispositions; canonical sources retained.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
