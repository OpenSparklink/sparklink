"""Load actual runtime ELFs without relying on development .so links.

The supplied artifacts remain the caller's exact ABI test inputs. This tests
the Python loader and pure exports, not kernel calls, deployment or RF.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RuntimeLibraryLoading(unittest.TestCase):
    def test_runtime_majors_and_explicit_failure_without_fallback(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            for variable, name in [('LIBSPARKLINK_PATH', 'libsparklink.so.0'),
                                   ('LIBSLK_NATIVE_PATH', 'libslk_native.so.0')]:
                artifact = Path(os.environ[variable]).resolve(strict=True)
                (Path(folder) / name).symlink_to(artifact)
            env = dict(os.environ, PYTHONPATH=str(root), LD_LIBRARY_PATH=folder)
            for variable in ['LIBSPARKLINK_PATH', 'LIBSLK_NATIVE_PATH']:
                env.pop(variable, None)
            code = '''
import ctypes, errno, os
from sparklink._library import load_library
for stem, variable in [('sparklink', 'LIBSPARKLINK_PATH'), ('slk_native', 'LIBSLK_NATIVE_PATH')]:
    lib = load_library(stem, variable)
    if stem == 'sparklink':
        f = lib.slk_ssap_access_error
        f.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        f.restype = ctypes.c_int
        assert f(0, 0, 0) == 0
    else:
        f = lib.slk_device_count
        f.argtypes = [ctypes.c_void_p]
        f.restype = ctypes.c_int
        assert f(None) == -errno.EINVAL
    os.environ[variable] = '/not-a-library/invalid.so'
    try:
        load_library(stem, variable)
    except OSError:
        pass
    else:
        raise AssertionError('invalid explicit override fell back')
'''
            result = subprocess.run([sys.executable, '-c', code], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
