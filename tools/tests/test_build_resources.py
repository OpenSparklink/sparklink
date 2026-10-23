# SPDX-License-Identifier: GPL-2.0-only
"""Resource policy and real OS lock exclusion; no compiler or device access."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_resources as build


class BuildResources(unittest.TestCase):
    def test_shared_vm_budget_lease_including_inherited_child(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build,'workspace',return_value=Path(directory)):
            self.assertFalse(build.real_vm_active())
            with build.real_device_vm() as fd:
                self.assertTrue(build.real_vm_active())
                with patch.object(build.os,'sched_getaffinity',return_value=set(range(16))):
                    self.assertEqual(build.environment({})[1]['jobs'],8)
                    with self.assertRaises(ValueError):build.environment({'SPARKLINK_BUILD_JOBS':'12'})
                child=subprocess.Popen([sys.executable,'-c','print("armed",flush=True);input()'],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,pass_fds=(fd,))
                self.assertEqual(child.stdout.readline(),'armed\n')
                with build.real_device_vm():pass
            try:self.assertTrue(build.real_vm_active())
            finally:child.communicate('done\n',timeout=5)
            self.assertFalse(build.real_vm_active())
            with build.build_lock():
                with self.assertRaises(RuntimeError):
                    with build.real_device_vm():self.fail('VM launch stole existing build')

    def test_solo_vm_affinity_and_explicit_budget_share_one_cargo_limit(self):
        # These explicit-mode cases need their own empty lease directory.
        # The separate real-flock test above checks VM detection and inheritance.
        with tempfile.TemporaryDirectory() as directory, patch.object(build,'workspace',return_value=Path(directory)), patch.object(build.os, 'sched_getaffinity', return_value=set(range(16))):
            for supplied, expected in [({}, 12), ({'SPARKLINK_BUILD_WITH_VM': '1'}, 8),
                                       ({'SPARKLINK_BUILD_JOBS': '6', 'CARGO_BUILD_JOBS': '6'}, 6)]:
                env, record = build.environment(supplied)
                self.assertEqual(record['jobs'], expected)
                self.assertEqual(env['CARGO_BUILD_JOBS'], str(expected))
            for supplied in [{'SPARKLINK_BUILD_WITH_VM': '1', 'SPARKLINK_BUILD_JOBS': '12'},
                             {'CARGO_BUILD_JOBS': '4'}, {'SPARKLINK_BUILD_JOBS': '0'},
                             {'SPARKLINK_BUILD_WITH_VM': 'yes'}]:
                with self.assertRaises(ValueError): build.environment(supplied)
        with patch.object(build.os, 'sched_getaffinity', return_value={0, 1}):
            self.assertEqual(build.environment({})[1]['jobs'], 2)

    def test_top_level_command_and_stale_jobserver_do_not_create_another_pool(self):
        env, record = build.environment({'MAKEFLAGS': 'private value not recorded', 'CARGO_MAKEFLAGS': 'stale'})
        self.assertNotIn('MAKEFLAGS', env)
        self.assertEqual(record['inherited_top_level_jobserver_cleared'], ['MAKEFLAGS', 'CARGO_MAKEFLAGS'])
        self.assertEqual(build.command_with_jobs(['cargo', '+1.96.1', 'test', '--workspace', '--', '--nocapture'], 8),
                         ['cargo', '+1.96.1', 'test', '--workspace', '--jobs', '8', '--locked', '--', '--nocapture'])
        self.assertEqual(build.command_with_jobs(['make', 'bzImage'], 12), ['make', '-j12', 'bzImage'])
        for command in [['make', '-j4'], ['cargo', 'build', '--jobs=16'], ['python3', 'legacy.py']]:
            with self.assertRaises(ValueError): build.command_with_jobs(command, 12)

    def test_real_lock_rejects_a_second_process_then_releases(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, 'workspace', return_value=Path(directory)):
            path = Path(directory) / '.dev/main-build.lock'
            script = ('import fcntl,sys\n'
                      'with open(sys.argv[1], "a+") as f:\n'
                      ' try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\n'
                      ' except BlockingIOError: sys.exit(17)\n')
            with build.build_lock():
                self.assertEqual(subprocess.run([sys.executable, '-c', script, str(path)]).returncode, 17)
                with self.assertRaises(RuntimeError):
                    with build.build_lock(): self.fail('second build admitted')
            self.assertEqual(subprocess.run([sys.executable, '-c', script, str(path)]).returncode, 0)

    def test_child_keeps_lock_after_supervisor_descriptor_closes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, 'workspace', return_value=Path(directory)):
            with build.build_lock() as fd:
                child = subprocess.Popen([sys.executable, '-c', 'print("armed",flush=True);input()'],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, pass_fds=(fd,))
                self.assertEqual(child.stdout.readline(), 'armed\n')
            try:
                with self.assertRaises(RuntimeError):
                    with build.build_lock(): self.fail('live child lost exclusion')
            finally:
                child.communicate('finish\n', timeout=5)
            with build.build_lock(): pass

    def test_busy_observation_preserves_inode_metadata_and_exclusion(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, 'workspace', return_value=Path(directory)):
            path = Path(directory) / '.dev/main-build.lock'
            with build.build_lock() as fd:
                inode = path.stat().st_ino
                original = path.read_bytes()
                metadata = json.loads(original)
                self.assertEqual(metadata['supervisor_pid'], build.os.getpid())
                self.assertNotIn('command', metadata)
                self.assertNotIn('environment', metadata)
                with self.assertRaises(build.BuildLockBusy) as busy:
                    with build.build_lock(): self.fail('occupied lock admitted')
                self.assertFalse(busy.exception.observation['metadata_authoritative'])
                self.assertEqual(busy.exception.observation['last_acquisition'], metadata)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(path.stat().st_ino, inode)
                self.assertEqual(build.os.fstat(fd).st_ino, inode)
            # Old text is not a lock: reuse the exact same inode, never unlink.
            with build.build_lock(): self.assertEqual(path.stat().st_ino, inode)

    def test_invalid_metadata_and_unavailable_proc_do_not_bypass_real_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, 'workspace', return_value=Path(directory)):
            path = Path(directory) / '.dev/main-build.lock'
            with build.build_lock() as fd:
                build.os.ftruncate(fd, 0)
                build.os.write(fd, b'not JSON')
                real_open = Path.open
                def restricted_open(path, *args, **kwargs):
                    if str(path) == '/proc/locks':
                        raise PermissionError('namespace fixture')
                    return real_open(path, *args, **kwargs)
                with patch.object(Path, 'open', restricted_open):
                    with self.assertRaises(build.BuildLockBusy) as busy:
                        with build.build_lock(): self.fail('invalid text bypassed flock')
                self.assertEqual(busy.exception.observation['last_acquisition'], 'unavailable_or_invalid')
                self.assertEqual(busy.exception.observation['kernel_lock_rows_unavailable'], 'PermissionError')
            with build.build_lock(): self.assertEqual(json.loads(path.read_text())['schema_version'], 1)

    def test_exited_supervisor_metadata_does_not_release_inherited_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, 'workspace', return_value=Path(directory)):
            root = Path(directory)
            release = root/'release-child'
            child_code = ('from pathlib import Path;import time\n'
                          f'p=Path({str(release)!r});end=time.monotonic()+5\n'
                          'while not p.exists() and time.monotonic()<end: time.sleep(0.01)\n')
            script = ('import sys,subprocess\nfrom pathlib import Path\n'
                      f'sys.path.insert(0,{str(Path(build.__file__).parent)!r})\n'
                      f'import build_resources as b;b.workspace=lambda:Path({directory!r})\n'
                      'with b.build_lock() as fd:\n'
                      f' subprocess.Popen([sys.executable,"-c",{child_code!r}],pass_fds=(fd,),'
                      'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n')
            supervisor = subprocess.run([sys.executable, '-c', script], timeout=3, check=True)
            self.assertEqual(supervisor.returncode, 0)
            try:
                with self.assertRaises(build.BuildLockBusy) as busy:
                    with build.build_lock(): self.fail('exited supervisor caused premature admission')
                self.assertFalse(busy.exception.observation['metadata_authoritative'])
                self.assertEqual(busy.exception.observation['last_acquisition']['entrypoint'], '-c')
            finally:
                release.touch()
            deadline = time.monotonic()+3
            while True:
                try:
                    with build.build_lock(): break
                except build.BuildLockBusy:
                    if time.monotonic() >= deadline: self.fail('child did not release real flock')
                    time.sleep(0.01)


if __name__ == '__main__': unittest.main()
