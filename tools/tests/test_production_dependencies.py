"""Verdict fixtures only; actual Cargo closure is checked by the CLI/CI."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_production_dependencies import check_tree


class DependencyBoundary(unittest.TestCase):
    internal={'slkd','libsparklink','slk-protocol','slctl','slktest','slk-experimental'}

    def test_current_native_wrapper_direction_and_external_libraries(self):
        output='slkd v0.1.0\nlibsparklink v0.1.0\nslk-protocol v0.1.0\nzbus v5.14.0\n'
        self.assertEqual(check_tree('slkd',output,self.internal),['libsparklink','slk-protocol','slkd'])

    def test_test_backend_application_client_and_reverse_direction_fail(self):
        for root,dependency in [('slkd','slk-experimental'),('slkd','slctl'),('slkd','slktest'),('libsparklink','slkd'),('slk-protocol','libsparklink')]:
            with self.subTest(root=root,dependency=dependency),self.assertRaises(ValueError):
                check_tree(root,f'{root} v0.1.0\n{dependency} v0.1.0\n',self.internal)

    def test_missing_truncated_or_unrecognized_cargo_output_fails(self):
        for output in ['', 'cargo failed', 'slkd v0.1.0\ntruncated line', 'libsparklink v0.1.0\n']:
            with self.subTest(output=output),self.assertRaises(ValueError):check_tree('slkd',output,self.internal)


if __name__=='__main__':unittest.main()
