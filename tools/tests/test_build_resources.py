# SPDX-License-Identifier: GPL-2.0-only
"""Resource policy and real OS lock exclusion; no compiler or device access."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_resources as build


class BuildResources(unittest.TestCase):
    def test_solo_vm_affinity_and_explicit_budget_share_one_cargo_limit(self):
        with patch.object(build.os, 'sched_getaffinity', return_value=set(range(16))):
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


if __name__ == '__main__': unittest.main()
