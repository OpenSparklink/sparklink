"""Runtime rendering/packaging checks. No service/device or deploy qualification."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import install_layout as layout


class LayoutContract(unittest.TestCase):
    def test_runtime_prefix_config_and_pc_are_consistent_and_have_no_staging_root(self):
        for prefix in ['/usr', '/usr/local', '/opt/sparklink']:
            libdir = prefix + '/lib/x86_64-linux-gnu'
            files = layout.render(prefix + '/sbin', libdir, prefix + '/include',
                                  '/etc/site', '/var/lib/sparklink', prefix)
            for file, marker in [('sparklink.service', 'ExecStart='), ('org.sparklink.service', 'Exec=')]:
                command = next(x.removeprefix(marker) for x in files[file].splitlines() if x.startswith(marker))
                self.assertEqual(shlex.split(command), [prefix + '/sbin/slkd', '--config', '/etc/site/sparklink/main.conf'])
            for name in ['sparklink.pc', 'sparklink-native.pc']:
                self.assertIn('libdir=' + libdir, files[name])
                self.assertIn('includedir=' + prefix + '/include', files[name])
                self.assertIn('Cflags: -I${includedir}\n', files[name])
                self.assertNotIn('/include/sparklink', files[name])
            self.assertIn('StateDirectoryMode=0700', files['sparklink.service'])
            custom = layout.render(prefix + '/sbin', libdir, prefix + '/include', '/etc/site', '/srv/private-state', prefix)
            self.assertNotIn('StateDirectory=', custom['sparklink.service'])
            self.assertIn('ReadWritePaths=/srv/private-state', custom['sparklink.service'])

    def test_unrepresentable_or_noncanonical_runtime_paths_fail_before_render(self):
        for path in ['relative', '/usr/../etc', '/usr/', '//usr', '/opt/a b', '/opt/%i', '/opt/$X', '/opt/semicolon;', '/opt/line\nbreak']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                layout.render(path, '/usr/lib', '/usr/include', '/etc', '/var/lib/sparklink', '/usr')

    def test_changed_template_fails_instead_of_leaving_a_stale_success_path(self):
        with patch.object(Path, 'read_text', return_value='[Service]\nExecStart=/wrong/path\n'):
            with self.assertRaises(ValueError):
                layout.render('/usr/sbin', '/usr/lib', '/usr/include', '/etc', '/var/lib/sparklink', '/usr')

    def test_missing_or_missing_soname_artifacts_are_not_installable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError): layout.check_artifacts(root)
            # Deliberately malformed ELF inputs are parser-negative fixtures,
            # never successful SDK/binary substitutes or service qualification.
            for name in (*layout.PROGRAMS, *layout.LIBRARIES): (root / name).write_bytes(b'\x7fELF-invalid')
            with patch('install_layout.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')):
                with self.assertRaises(ValueError): layout.check_artifacts(root)
            with patch('install_layout.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '(SONAME) [wrong.so.9]', '')):
                with self.assertRaises(ValueError): layout.check_artifacts(root)

    def test_debian_reuses_locked_make_layout_and_one_compat_declaration(self):
        rules = (layout.ROOT / 'debian/rules').read_text()
        self.assertIn('$(MAKE) build CARGO=cargo', rules)
        self.assertIn('$(MAKE) install-files PREFIX=/usr', rules)
        self.assertIn('$(MAKE) test CARGO=cargo', rules)
        self.assertNotIn('target/release/', rules)
        self.assertNotIn('install -', rules)
        self.assertFalse((layout.ROOT / 'debian/compat').exists())
        self.assertIn('debhelper-compat (= 13)', (layout.ROOT / 'debian/control').read_text())
        self.assertIn('--locked', (layout.ROOT / 'Makefile').read_text())

    def test_install_cannot_silently_build_debug_then_copy_old_release(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'install',
                                 'CARGO_FLAGS=--workspace', 'DESTDIR=/unused-stage'],
                                cwd=layout.ROOT, capture_output=True, text=True, check=True)
        builds = [line for line in result.stdout.splitlines() if 'build_resources.py -- ' in line and ' build ' in line]
        self.assertEqual(len(builds), 1)
        self.assertIn('build --locked --release --workspace', builds[0])
        self.assertIn('/release"', result.stdout)

    def test_group_policy_stays_separate_and_generic_rules_do_not_grant_raw_usb(self):
        import xml.etree.ElementTree as xml
        names = {line.split()[1] for line in (layout.ROOT / 'data/sysusers/sparklink.conf').read_text().splitlines() if line.startswith('g ')}
        groups = {p.attrib['group'] for p in xml.fromstring((layout.ROOT / 'data/dbus/sparklink.conf').read_text()).findall('policy') if 'group' in p.attrib}
        self.assertEqual(names, groups)
        rules = (layout.ROOT / 'data/udev/99-sparklink.rules').read_text()
        self.assertIn('KERNEL=="sparklink", GROUP="sparklink", MODE="0660"', rules)
        self.assertNotIn('SUBSYSTEM=="usb"', rules)
