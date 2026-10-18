"""Staged uninstall of actual Makefile; not a VM deployment qualification."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class StagedUninstall(unittest.TestCase):
    def test_package_files_removed_but_admin_configuration_and_state_preserved(self):
        for symlink in (False,True):
            with self.subTest(config_symlink=symlink),tempfile.TemporaryDirectory() as folder:
                stage=Path(folder)
                config=stage/'etc/sparklink'
                if symlink:
                    actual=stage/'admin-config';actual.mkdir()
                    config.parent.mkdir();config.symlink_to(actual,target_is_directory=True)
                else:config.mkdir(parents=True)
                sentinels=[config/'main.conf',config/'admin-subdirectory/local.conf',stage/'var/lib/sparklink/history.toml',stage/'usr/bin/unrelated']
                for path in sentinels:
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_text('administrator-owned\n')
                installed=['usr/sbin/slkd',*[f'usr/bin/{name}' for name in ['slctl','slktest','slkconfig','slkmon','slkdump']],'usr/lib/libsparklink.so.0','usr/include/sparklink.h','usr/share/man/man1/slktest.1','usr/share/dbus-1/system-services/org.sparklink.service','usr/share/dbus-1/system.d/sparklink.conf','usr/lib/systemd/system/sparklink.service']
                for name in installed:
                    path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('package fixture\n')
                result=subprocess.run(['make','--no-print-directory','-f',str(ROOT/'Makefile'),'uninstall','PREFIX=/usr','DESTDIR='+str(stage)],cwd=ROOT,env=dict(os.environ,MAKEFLAGS=''),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                for name in installed:self.assertFalse((stage/name).exists(),name)
                for path in sentinels:self.assertEqual(path.read_text(),'administrator-owned\n')
                if symlink:self.assertTrue(config.is_symlink())


if __name__=='__main__':unittest.main()
