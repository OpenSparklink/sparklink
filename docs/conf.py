"""SparkLink documentation: Markdown sources remain authoritative."""
project = "SparkLink"
author = "OpenSparklink contributors"
copyright = "OpenSparklink contributors"
release = "development"
language = "zh_CN"
extensions = ["myst_parser", "sphinxcontrib.mermaid", "sphinx_copybutton"]
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
root_doc = "index"
exclude_patterns = ["_build", "_extensions", "evidence/**"]
nitpicky = True
show_warning_types = True
myst_heading_anchors = 6
myst_enable_extensions = ["colon_fence", "deflist", "fieldlist"]
myst_fence_as_directive = ["mermaid"]
html_theme = "sphinx_book_theme"
html_title = "SparkLink 文档"
html_static_path = ["_static"]
html_css_files = ["sparklink.css"]
html_theme_options = {
    "show_navbar_depth": 2,
    "show_toc_level": 2,
    "toc_title": "本页内容",
    "navigation_with_keys": False,
    "home_page_in_toc": False,
    "use_download_button": False,
    "use_fullscreen_button": False,
    "logo": {"text": "SparkLink"},
}
html_show_sourcelink = True
html_last_updated_fmt = None
# HTML builds do not fetch remote references. Mermaid rendering currently uses a
# pinned upstream JS asset at viewing time; see reference/documentation-build.md.
mermaid_version = "11.12.1"
mermaid_include_elk = False
mermaid_include_zenuml = False
linkcheck_anchors = False
linkcheck_timeout = 15
linkcheck_retries = 1
linkcheck_workers = 5


# Only curated reader pages plus original canonical sources are published.
# Other originals keep their GitHub URLs; they are not silently recommended.
from pathlib import Path
import os
import re
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit

_docs = Path(__file__).parent
sys.path.insert(0, str(_docs.parent / 'tools'))
from docs_integrity import source_target, html_stamp, reader_source
_inventory = tomllib.loads((_docs / 'documentation-map.toml').read_text())
exclude_patterns = ['_build', '_extensions', 'evidence/**']
exclude_patterns.remove('evidence/**')
exclude_patterns += ['evidence/' + p.name for p in (_docs / 'evidence').iterdir() if p.name != 'index.md']
exclude_patterns += [x['path'][5:] for x in _inventory['documents']
                     if x['path'].startswith('docs/') and x['publication'] != 'html']
_source_revision = os.environ.get('SPARKLINK_DOCS_REVISION') or subprocess.check_output(
    ['git', 'rev-parse', 'HEAD'], cwd=_docs, text=True).strip()
release = _source_revision[:12] + ' (development; qualification is separate)'
html_title = 'SparkLink · ' + _source_revision[:12]
html_theme_options['logo'] = {'text': 'SparkLink · ' + _source_revision[:8]}
# No raw reST/Markdown download exposing workstation paths; repository originals
# remain linked at their immutable revision.
html_copy_source = False
html_show_sourcelink = False
_published = {x['path'] for x in _inventory['documents'] if x['publication'] == 'html'}
if any(not reader_source(p) for p in _published):
    raise ValueError('Only the four reader categories and the home page may be built')
import json
_paths = json.loads((_docs / 'documentation-paths.json').read_text())
_projections = _paths['canonical_projections']
_projection_sources = {page[5:-3]: original for original, page in _projections.items()}



def _public_source(app, docname, source):
    source_file = _docs / (docname + '.md')
    if docname in _projection_sources:
        original = _projection_sources[docname]
        source_file = _docs.parent / original
        expected = '```{include} ' + os.path.relpath(source_file, (_docs / docname).parent) + '\n```'
        if source[0].strip() != expected:
            raise ValueError('canonical projection must contain only its include directive: ' + docname)
        source[0] = source_file.read_text()
    def link(match):
        label, target = match.groups()
        if urlsplit(target).scheme or target.startswith('#'):
            return match.group(0)
        path, sep, anchor = target.partition('#')
        root = _docs.parent.resolve()
        absolute = source_target(root, source_file, target)
        if absolute.is_relative_to(root):
            relative = str(absolute.relative_to(root))
            if relative in _projections and _projections[relative] in _published:
                relative = _projections[relative]
            if relative in _published:
                return '[' + label + '](' + os.path.relpath(root / relative, (_docs / docname).parent) + sep + anchor + ')'
            source_target(root, source_file, target, check_anchor=True)
            return f'[{label}](https://github.com/OpenSparklink/sparklink/blob/{_source_revision}/{relative}{sep}{anchor})'
        raise ValueError('unresolved repository source: ' + target)
    source[0] = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, source[0])
    source[0] = re.sub(r'/opt/opensparklink-verification-tools[^\s`]+', '$VERIFICATION_TOOLS', source[0])
    source[0] = re.sub(r'/home/[^/\s`]+/(?:Documents/opensparklink/)?', '$WORKSPACE/', source[0])


def _legacy_redirects(app, exception):
    if exception or app.builder.format != 'html':
        return
    import html
    # Book Theme 1.4 / PyData 0.20 also ship two Jinja macro inputs inside
    # their static directories. Sphinx copies them verbatim, but the browser
    # never requests them. Do not publish raw build templates as HTML pages.
    for name in ('webpack-macros.html', 'sbt-webpack-macros.html'):
        template = Path(app.outdir) / '_static' / name
        if template.is_file():
            content = template.read_text()
            if '{% macro ' not in content or 'pathto(' not in content:
                raise ValueError('unexpected theme template content: ' + name)
            template.unlink()
    # Preserve the redistributed themes' own license texts alongside assets.
    from importlib.metadata import distribution
    import shutil
    licenses = Path(app.outdir) / '_static' / 'licenses'
    licenses.mkdir(exist_ok=True)
    for name in ('sphinx-book-theme', 'pydata-sphinx-theme'):
        dist = distribution(name)
        entries = [p for p in dist.files or [] if '.dist-info/licenses/' in str(p)
                   and p.name in ('LICENSE', 'LICENSE.txt', 'LICENSE.md')]
        if not entries:
            raise ValueError('missing installed theme license: ' + name)
        for entry in entries:
            shutil.copyfile(dist.locate_file(entry), licenses / (name + '-' + entry.name))
    for old, target in _paths['legacy_html_redirects'].items():
        destination = Path(app.outdir) / old
        # The current user-visible site is strictly four categories. Preserve
        # repository URL mappings, but emit only redirects within that scope.
        if not reader_source('docs/' + old[:-5] + '.md'):
            continue
        resolved = (destination.parent / target).resolve()
        if not resolved.is_relative_to(Path(app.outdir).resolve()) or not resolved.is_file():
            continue
        destination.write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=' + html.escape(target, quote=True) + '"><title>Document moved</title><a href="' + html.escape(target, quote=True) + '">Document moved</a>')
    (Path(app.outdir) / 'documentation-build.json').write_text(
        json.dumps(html_stamp(Path(app.outdir), _source_revision), indent=2) + '\n')


def setup(app):
    # Sphinx 9.1 SearchChinese uses english-stemmer.js, while the emitted
    # constructor name comes from language_name (ChineseStemmer does not
    # exist). Keep its Chinese tokenizer and Python English stemming intact;
    # name the actual JS constructor. Scoped to this documentation build.
    from sphinx.search.zh import SearchChinese

    class ChineseSearchCompatible(SearchChinese):
        language_name = 'English'

    app.add_search_language(ChineseSearchCompatible)
    app.connect('source-read', _public_source)
    app.connect('build-finished', _legacy_redirects)
    return {'parallel_read_safe': True, 'parallel_write_safe': True}

# Bounded independent network check; rate limits remain visible failures.
linkcheck_rate_limit_timeout = 30
