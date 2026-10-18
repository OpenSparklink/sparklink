import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from check_public_symbols import compare, declarations, dynamic_symbols, inspect


class PublicSymbols(unittest.TestCase):
    def test_exact_current_namespace_and_comments(self):
        header = '/* slk_old(void) */ int slk_one(void);\n// slk_stale()\nvoid slk_two(int);'
        self.assertEqual(compare(header, 'slk_one T 100 20\nslk_two T 120 30\n'), [])
        self.assertEqual(declarations(header), {'slk_one', 'slk_two'})

    def test_missing_extra_and_foreign_exports_fail(self):
        for output in ['slk_other T 100 20\n', 'slk_one T 100 20\nslk_extra T 120 30\n',
                       'slk_one T 100 20\nforeign T 120 30\n']:
            with self.subTest(output=output):
                self.assertTrue(compare('int slk_one(void);', output))

    def test_empty_truncated_duplicate_versioned_and_undefined_fail(self):
        for output in ['', '\n', 'slk_one', 'slk_one T 100\nslk_one T 100\n',
                       'slk_one@@V1 T 100 20', 'slk_one U 100 20',
                       'slk_one D 100 20', 'slk_one T not_hex 20', 'slk_one T 100 20 extra']:
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    dynamic_symbols(output)
        for header in ['', '/* int slk_one(void); */', 'int slk_one(void); int slk_one(void);']:
            with self.assertRaises(ValueError):
                declarations(header)

    def test_failed_command_and_diagnostic_cannot_publish_success(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = Path(directory)/'lib.so'; lib.write_bytes(b'not ELF')
            header = Path(directory)/'api.h'; header.write_text('int slk_one(void);')
            with patch('check_public_symbols.subprocess.run', side_effect=subprocess.CalledProcessError(1, ['nm'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    inspect(lib, header)
            result = subprocess.CompletedProcess(['nm'], 0, 'slk_one T 100 20\n', 'warning')
            with patch('check_public_symbols.subprocess.run', return_value=result):
                with self.assertRaises(ValueError):
                    inspect(lib, header)

    def test_header_or_binary_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = Path(directory)/'lib.so'; lib.write_bytes(b'original')
            header = Path(directory)/'api.h'; header.write_text('int slk_one(void);')
            for target in [lib, header]:
                def run(*args, **kwargs):
                    target.write_bytes(target.read_bytes()+b'\n')
                    return subprocess.CompletedProcess(['nm'], 0, 'slk_one T 100 20\n', '')
                with patch('check_public_symbols.subprocess.run', side_effect=run):
                    with self.assertRaises(ValueError):
                        inspect(lib, header)
