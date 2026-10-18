"""Test the actual guest verifier; fixtures do not qualify a real installation."""
import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'tools/testing/deployment/debian_lifecycle_probe.py'
spec = importlib.util.spec_from_file_location('debian_lifecycle_probe', SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class LifecycleVerifier(unittest.TestCase):
    def test_gate_set_requires_each_stage_not_a_reinstall(self):
        self.assertEqual(len(probe.REQUIRED), len(set(probe.REQUIRED)))
        gates = [dict(name=n, exit=0) for n in probe.REQUIRED]
        self.assertTrue(probe.complete(gates))
        for stage in probe.STAGES:
            bad = [g for g in gates if not g['name'].startswith(stage + '-')]
            self.assertFalse(probe.complete(bad))
        for bad in [gates[:-1], gates + [gates[0]], gates + [dict(name='unknown', exit=0)]]:
            self.assertFalse(probe.complete(bad))
        for value in [1, False, None, '0', 'SKIP']:
            bad = copy.deepcopy(gates)
            bad[0]['exit'] = value
            self.assertFalse(probe.complete(bad))

    def test_installed_files_checked_independently_of_package_database(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / 'usr/bin/fixture'
            path.parent.mkdir(parents=True)
            path.write_text('actual fixture\n')
            path.chmod(0o755)
            link = path.with_name('alias')
            link.symlink_to('fixture')
            files = {'usr/bin/fixture': dict(sha256=probe.digest(path), mode=0o755),
                     'usr/bin/alias': dict(symlink='fixture')}
            probe.verify_files(files, root)
            for mutation in ['content', 'mode', 'missing', 'symlink', 'traversal']:
                with self.subTest(mutation=mutation):
                    if mutation == 'content':
                        path.write_text('corrupt\n')
                    elif mutation == 'mode':
                        path.chmod(0o600)
                    elif mutation == 'missing':
                        link.unlink()
                    elif mutation == 'symlink':
                        link.unlink()
                        link.symlink_to('other')
                    else:
                        files['usr/../outside'] = dict(sha256='0' * 64, mode=0o755)
                    with self.assertRaises(ValueError):
                        probe.verify_files(files, root)
                    path.write_text('actual fixture\n')
                    path.chmod(0o755)
                    if link.is_symlink():
                        link.unlink()
                    link.symlink_to('fixture')

    def test_reuses_actual_existing_consumers_and_their_assertions(self):
        scripts = probe.actual_scripts(ROOT)
        self.assertEqual(len(scripts), 4)
        self.assertIn('CapEff:', scripts['import dbus,'])
        self.assertIn('EBADF', scripts['import sparklink,'])
        self.assertIn('memcmp', scripts['#include <sparklink.h>'])
        self.assertIn('ENOTTY', scripts['#include <sparklink_native.h>'])
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            p = root / 'tools/testing/deployment/guest_probe.py'
            p.parent.mkdir(parents=True)
            p.write_text('"import dbus, sys"\n"import dbus, os"\n')
            with self.assertRaises(ValueError):
                probe.actual_scripts(root)

    @unittest.skipIf(os.geteuid() == 0, 'normal developer only; never invoke destructive main as root')
    def test_unmarked_host_refuses_before_any_package_action(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--disposable-guest-only'],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no action taken', result.stderr)


if __name__ == '__main__':
    unittest.main()
