"""Verdict fixtures only; actual Cargo closure is checked by the CLI/CI."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_production_dependencies import check_tree


class DependencyBoundary(unittest.TestCase):
    internal={'slkd','libsparklink','slk-protocol','slctl','slktest','slk-experimental','slk-channel','slk-native','slk-contract'}

    def test_native_daemon_direction_and_external_libraries(self):
        output='slkd v0.1.0\nslk-native v0.1.0\nslk-protocol v0.1.0\nzbus v5.14.0\n'
        self.assertEqual(check_tree('slkd',output,self.internal),['slk-native','slk-protocol','slkd'])

    def test_test_backend_application_client_and_reverse_direction_fail(self):
        for root,dependency in [('slktest','slk-native'),('slctl','slk-native'),('slkd','libsparklink'),('slkd','slk-experimental'),('slkd','slctl'),('slkd','slktest'),('libsparklink','slkd'),('libsparklink','slk-native'),('slk-protocol','libsparklink'),('slk-protocol','slk-channel'),('slk-channel','libsparklink'),('slk-channel','slkd'),('slk-channel','slk-native'),('slk-native','libsparklink'),('slk-native','slkd'),('slk-native','slk-channel'),('slk-contract','libsparklink'),('slk-contract','slkd'),('slk-contract','slk-native'),('slk-contract','slk-channel')]:
            with self.subTest(root=root,dependency=dependency),self.assertRaises(ValueError):
                check_tree(root,f'{root} v0.1.0\n{dependency} v0.1.0\n',self.internal)

    def test_cli_uses_same_application_sdk_without_native_authority(self):
        output='slctl v0.1.0\nlibsparklink v0.1.0\nslk-channel v0.1.0\nslk-contract v0.1.0\nslk-protocol v0.1.0\n'
        self.assertEqual(check_tree('slctl',output,self.internal),['libsparklink','slctl','slk-channel','slk-contract','slk-protocol'])

    def test_channel_has_only_protocol_not_management_authority(self):
        output='slk-channel v0.1.0\nslk-protocol v0.1.0\nnix v0.30.1\n'
        self.assertEqual(check_tree('slk-channel',output,self.internal),['slk-channel','slk-protocol'])

    def test_missing_truncated_or_unrecognized_cargo_output_fails(self):
        for output in ['', 'cargo failed', 'slkd v0.1.0\ntruncated line', 'libsparklink v0.1.0\n']:
            with self.subTest(output=output),self.assertRaises(ValueError):check_tree('slkd',output,self.internal)


if __name__=='__main__':unittest.main()
