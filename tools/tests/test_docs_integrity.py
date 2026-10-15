"""Negative controls for the actual documentation publication/audit helpers."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from check_doc_examples import check_python_examples
from docs_integrity import audit_html, html_stamp, source_target

ROOT = Path(__file__).resolve().parents[2]


class Integrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'html'
        self.out.mkdir()
        (self.out / 'reference').mkdir()
        (self.out / 'index.html').write_text('<html><a href="reference/index.html#contract">read</a></html>')
        (self.out / 'reference/index.html').write_text('<html><h1 id="contract">Contract</h1></html>')
        self.pages = {'index.html', 'reference/index.html'}
        self.seal()

    def seal(self):
        (self.out / 'documentation-build.json').write_text(json.dumps(html_stamp(self.out, 'a' * 40)))

    def audit(self):
        return audit_html(self.out, self.pages, 'a' * 40)

    def test_valid_nonempty_site(self):
        self.assertEqual(self.audit(), [])

    def test_missing_root(self):
        self.assertTrue(audit_html(self.root / 'absent', self.pages, 'a' * 40))

    def test_empty_directory(self):
        empty = self.root / 'empty'; empty.mkdir()
        self.assertTrue(audit_html(empty, self.pages, 'a' * 40))

    def test_missing_expected_page_even_after_reseal(self):
        (self.out / 'reference/index.html').unlink(); self.seal()
        self.assertTrue(self.audit())

    def test_empty_page_even_after_reseal(self):
        (self.out / 'reference/index.html').write_text('  \n'); self.seal()
        self.assertTrue(self.audit())

    def test_bad_anchor(self):
        (self.out / 'index.html').write_text('<html><a href="reference/index.html#wrong">read</a></html>'); self.seal()
        self.assertTrue(any('anchor' in e for e in self.audit()))

    def test_missing_resource(self):
        (self.out / 'index.html').write_text('<html><img src="wrong/image.png"></html>'); self.seal()
        self.assertTrue(any('resource' in e for e in self.audit()))

    def test_wrong_version(self):
        self.assertTrue(audit_html(self.out, self.pages, 'b' * 40))

    def test_replaced_page(self):
        (self.out / 'reference/index.html').write_text('<html>old artifact</html>')
        self.assertTrue(any('sealed' in e for e in self.audit()))

    def test_non_reader_page_rejected_even_after_reseal(self):
        (self.out / 'project').mkdir()
        (self.out / 'project/index.html').write_text('<html>internal plan</html>')
        self.seal()
        self.assertTrue(any('non-reader HTML' in e for e in self.audit()))

    def test_source_only_qualification_links_to_canonical_file(self):
        hook = runpy.run_path(str(ROOT / 'docs/conf.py'))['_public_source']
        source = ['[qualification](../../project/current-capabilities.md)']
        hook(None, 'reference/interfaces', source)
        self.assertIn('https://github.com/OpenSparklink/sparklink/blob/', source[0])
        self.assertIn('/project/current-capabilities.md)', source[0])
        self.assertNotIn('/docs/project/', source[0])

    def test_source_link_and_anchor(self):
        source = self.root / 'source.md'; source.write_text('# Good heading\n')
        self.assertEqual(source_target(self.root, source, 'source.md#good-heading', True), source)
        with self.assertRaises(ValueError):
            source_target(self.root, source, 'absent.md')
        with self.assertRaises(ValueError):
            source_target(self.root, source, 'source.md#wrong', True)
        with self.assertRaises(ValueError):
            source_target(self.root, source, '../private.md')

    def test_actual_sphinx_hook_rejects_missing_repo_source(self):
        hook = runpy.run_path(str(ROOT / 'docs/conf.py'))['_public_source']
        with self.assertRaisesRegex(ValueError, 'missing repository source'):
            hook(None, 'reference/interfaces', ['[missing](definitely-not-a-source.md)'])

    def test_real_readme_and_old_adapter_negative(self):
        text = (ROOT / 'bindings/python/README.md').read_text()
        self.assertEqual(check_python_examples(text), [])
        bad = '```python\nfrom sparklink import Adapter\nwith Adapter() as adpt:\n    adpt.poll_event()\n```\n'
        self.assertTrue(any('Adapter.poll_event' in e for e in check_python_examples(bad)))

    def test_missing_example(self):
        self.assertTrue(check_python_examples('# No example\n'))


if __name__ == '__main__':
    unittest.main()
