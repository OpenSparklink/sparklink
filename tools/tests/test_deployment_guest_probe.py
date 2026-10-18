"""Preflight actual embedded probe syntax; no VM, package or permission proof."""
import ast
from pathlib import Path
from textwrap import dedent
import unittest


class EmbeddedGuestScripts(unittest.TestCase):
    def test_actual_policy_and_installed_python_consumers_compile(self):
        path = Path(__file__).resolve().parents[1] / 'testing/deployment/guest_probe.py'
        tree = ast.parse(path.read_text(), filename=str(path))
        scripts = [node.value for node in ast.walk(tree)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and node.value.lstrip().startswith(('import dbus,', 'import sparklink,'))]
        self.assertEqual(len(scripts), 2)
        for index, script in enumerate(scripts):
            compile(dedent(script), f'guest-embedded-{index}.py', 'exec')

    def test_old_extraction_error_is_rejected(self):
        with self.assertRaises(IndentationError):
            compile('import dbus\n    mode = "observer"\n', 'old-extraction.py', 'exec')
