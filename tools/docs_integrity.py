"""Fail-closed checks shared by Sphinx publication and its independent audit.

These checks cover file/link integrity, not semantic completeness or hardware
qualification. Source-only Markdown anchors use GitHub heading syntax; rendered
MyST anchors are checked against the actual HTML instead.
"""
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

READER_SECTIONS = frozenset({'tutorials', 'how-to', 'reference', 'explanation'})
ROOT_HTML = frozenset({'index.html', 'search.html', 'genindex.html'})


def reader_source(path):
    path = Path(path)
    return str(path) == 'docs/index.md' or (
        len(path.parts) > 2 and path.parts[0] == 'docs' and path.parts[1] in READER_SECTIONS)


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if 'id' in data:
            self.ids.add(data['id'])
        for attr in ('href', 'src', 'poster'):
            if attr in data:
                self.links.append(data[attr])


def source_target(root, source_file, target, check_anchor=False):
    """Resolve a repository link, refusing missing or unlabelled private files."""
    url = urlsplit(target)
    if url.scheme or url.netloc:
        raise ValueError('source_target expects a repository-relative link')
    absolute = (source_file.parent / unquote(url.path)).resolve()
    if not absolute.is_relative_to(root.resolve()):
        raise ValueError(f'{source_file.name}: private material must have an explicit access/hash/replay description, not a file link: {target}')
    if not absolute.is_file():
        raise ValueError(f'{source_file.name}: missing repository source: {target}')
    if check_anchor and url.fragment and absolute.suffix == '.md':
        ids, counts = set(), {}
        in_fence = False
        for line in absolute.read_text().splitlines():
            if line.startswith(('```', '~~~')):
                in_fence = not in_fence
            if in_fence:
                continue
            if match := re.match(r'^#{1,6}\s+(.+?)\s*#*$', line):
                title = match[1].lower()
                title = re.sub(r'[^\w\-\s\u0080-\uffff]', '', title)
                slug = re.sub(r'\s', '-', title)
                count = counts.get(slug, 0)
                counts[slug] = count + 1
                ids.add(slug + (f'-{count}' if count else ''))
            ids.update(re.findall(r'(?:id|name)=[\"\x27]([^\"\x27]+)', line))
        if unquote(url.fragment) not in ids:
            raise ValueError(f'{source_file.name}: unknown source anchor: {target}')
    return absolute


def html_stamp(outdir, revision):
    return {
        'schema_version': 1, 'source_revision': revision,
        'scope': 'Documentation output integrity only; not browser or functional qualification.',
        'pages': {str(p.relative_to(outdir)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(outdir.rglob('*.html'))},
    }


def audit_html(html_root, expected_pages, revision):
    html_root = html_root.resolve()
    if not html_root.is_dir():
        return [f'HTML root does not exist: {html_root}']
    errors, parsed = [], {}
    try:
        stamp = json.loads((html_root / 'documentation-build.json').read_text())
    except (OSError, ValueError) as exc:
        return [f'missing or invalid HTML build identity: {exc}']
    if stamp.get('schema_version') != 1 or stamp.get('source_revision') != revision:
        errors.append('HTML source revision mismatch')
    for relative in expected_pages:
        page = html_root / relative
        if not page.is_file():
            errors.append(f'missing expected HTML page: {relative}')
        elif not page.read_text().strip() or '<html' not in page.read_text().lower():
            errors.append(f'empty or incomplete HTML page: {relative}')
    for page in html_root.rglob('*.html'):
        relative = page.relative_to(html_root)
        if str(relative) not in ROOT_HTML and relative.parts[0] not in READER_SECTIONS:
            errors.append(f'non-reader HTML must not be built: {relative}')
        content = page.read_text()
        if not content.strip():
            errors.append(f'empty HTML page: {page.name}')
        parser = HtmlLinks()
        parser.feed(content)
        parsed[page] = parser
        if re.search(r'/home/[^\s<]+|file://', content):
            errors.append(f'private path in public HTML: {page.name}')
    actual = html_stamp(html_root, revision)['pages']
    if actual != stamp.get('pages'):
        errors.append('HTML pages differ from sealed build output')
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
    extra = [p for p in (html_root / 'evidence').rglob('*')
             if p.is_file() and p.suffix != '.html']
    if extra:
        errors.append('raw evidence copied to public site')
    return errors
