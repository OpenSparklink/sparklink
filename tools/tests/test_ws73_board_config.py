# SPDX-License-Identifier: GPL-2.0-only
"""Board exporter tests use an explicit synthetic INI, never real RF input."""
import configparser
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'ws73-board-config.py'
spec = importlib.util.spec_from_file_location('ws73_board_config', SCRIPT)
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)


def fixture():
    values = {
        'bt_coex_mode': 1, 'ble_disable_ll_privacy': 0, 'bsle_suspend_mode': 0,
        'bsle_suspend_scan_interval': 300, 'bsle_suspend_scan_window': 30,
        'bsle_front_switch': 0, 'bt_maxpower': 7, 'bt_cali_txpwr_pa_ref_num': 8,
        'bt_srrc_switch': 1, 'bsle_use_flash': 0,
    }
    for i, freq in enumerate((6, 15, 26, 39, 60, 68, 72, 76), 1):
        values[f'bt_cali_txpwr_pa_ref_band{i}'] = 20
        values[f'bt_cali_txpwr_pa_fre{i}'] = freq
    for i, freq in enumerate((10, 20, 32, 50, 64, 70, 74), 1):
        values[f'bt_cali_txpwr_pa_fre_block{i}'] = freq
    for i, (freq, ref) in enumerate(zip((0, 75, 76, 77, 78, 255, 255, 255),
                                       (10, 6, 6, 6, 14, 255, 255, 255)), 1):
        values[f'bt_srrc_pa_ref_val{i}'] = ref
        values[f'bt_srrc_pa_fre{i}'] = freq
    return ('[DEVICE_BT]\n' + ''.join(f'{k}={v}\n' for k, v in values.items()) +
            '[HOST_PLAT]\ndevice_plt_pm_enable=1\ndevice_awake_host_gpio_idx=10\n'
            'device_awake_host_gpio_level=1\n')


class BoardConfigTests(unittest.TestCase):
    def test_complete_golden_layout(self):
        data, word, selected = board.read_values(fixture().encode())
        # Hand-written byte oracle from the SDK's offsets and field values,
        # including reversed channel block halfwords and the inactive tail.
        golden = bytes.fromhex(
            '01000000 00000000 00000000 2c010000 1e000000 00000000 07000000 08000000 '
            '14000600 14000f00 14001a00 14002700 14003c00 14004400 14004800 14004c00 '
            '14000a00 32002000 46004000 4a000000 01000000 '
            '0a000000 06004b00 06004c00 06004d00 0e004e00 ff00ff00 ff00ff00 ff00ff00 '
            '00000000 00000000 00000000 00000000 00000000 00000000')
        self.assertEqual(data, golden)
        self.assertEqual(len(data), 140)
        self.assertEqual(word, 0x215)
        self.assertEqual(selected['DEVICE_BT.bt_cali_txpwr_pa_fre_block1'], 10)

    def test_utf8_bom_hex_and_comments(self):
        text = fixture().replace('bt_coex_mode=1', 'bt_coex_mode=0x01 ; annotation')
        self.assertEqual(board.read_values(('\ufeff' + text).encode())[0],
                         board.read_values(fixture().encode())[0])

    def test_required_values_never_default(self):
        for line in fixture().splitlines():
            if '=' not in line:
                continue
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, 'explicit integer'):
                board.read_values(fixture().replace(line + '\n', '').encode())

    def test_non_integer_rejected(self):
        with self.assertRaisesRegex(ValueError, 'explicit integer'):
            board.read_values(fixture().replace('bt_maxpower=7', 'bt_maxpower=unknown').encode())

    def test_unrelated_vendor_fragments_are_not_board_fields(self):
        text = fixture() + '[WIFI_NVRAM]\nC;\nnot-a-board-setting\n'
        self.assertEqual(board.read_values(text.encode()), board.read_values(fixture().encode()))

    def test_selected_section_syntax_remains_strict(self):
        with self.assertRaises(configparser.ParsingError):
            board.read_values((fixture() + 'C;\n').encode())
        with self.assertRaisesRegex(ValueError, 'malformed section boundary'):
            board.read_values((fixture() + '[BROKEN\n').encode())

    def test_overflow_rejected_without_masking(self):
        for old, new in [('bt_coex_mode=1', 'bt_coex_mode=256'),
                         ('bt_cali_txpwr_pa_ref_band1=20', 'bt_cali_txpwr_pa_ref_band1=65536'),
                         ('device_awake_host_gpio_idx=10', 'device_awake_host_gpio_idx=256'),
                         ('device_awake_host_gpio_level=1', 'device_awake_host_gpio_level=-1')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                board.read_values(fixture().replace(old, new).encode())

    def test_active_calibration_range_rejected(self):
        for old, new in [('bt_cali_txpwr_pa_ref_band1=20', 'bt_cali_txpwr_pa_ref_band1=0'),
                         ('bt_cali_txpwr_pa_fre1=6', 'bt_cali_txpwr_pa_fre1=255')]:
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, 'active calibration'):
                board.read_values(fixture().replace(old, new).encode())

    def test_window_cannot_exceed_interval(self):
        with self.assertRaisesRegex(ValueError, 'window exceeds interval'):
            board.read_values(fixture().replace('bsle_suspend_scan_window=30',
                                               'bsle_suspend_scan_window=301').encode())

    def test_channel_blocks_increasing(self):
        with self.assertRaisesRegex(ValueError, 'strictly increasing'):
            board.read_values(fixture().replace('fre_block2=20', 'fre_block2=10').encode())

    def test_srrc_sentinel_must_be_a_pair(self):
        with self.assertRaisesRegex(ValueError, 'sentinel pair'):
            board.read_values(fixture().replace('bt_srrc_pa_fre6=255', 'bt_srrc_pa_fre6=0').encode())

    def test_flash_requires_per_device_calibration(self):
        with self.assertRaisesRegex(ValueError, 'flash mode requires per-device'):
            board.read_values(fixture().replace('bsle_use_flash=0', 'bsle_use_flash=1').encode())

    def test_duplicates_rejected(self):
        with self.assertRaises(configparser.DuplicateOptionError):
            board.read_values(fixture().replace('bt_coex_mode=1',
                                               'bt_coex_mode=1\nbt_coex_mode=0').encode())

    def test_inherited_defaults_rejected(self):
        with self.assertRaisesRegex(ValueError, 'DEFAULT inheritance'):
            board.read_values(('[DEFAULT]\nbt_coex_mode=1\n' + fixture()).encode())

    def test_export_binds_actual_bytes_and_explicit_build_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ini = root / 'synthetic.ini'
            ini.write_text(fixture())
            for flag in (0, 1):
                out = root / str(flag)
                manifest = board.export(ini, out, 'synthetic-board', flag)
                self.assertEqual(manifest, json.loads((out / 'ws73-board-config.json').read_text()))
                self.assertEqual(manifest['source']['sha256'], board.sha256(ini.read_bytes()))
                self.assertEqual(manifest['exporter']['sha256'], board.sha256(SCRIPT.read_bytes()))
                for name, record in manifest['images'].items():
                    self.assertEqual(record['sha256'], board.sha256((out / name).read_bytes()))
                    self.assertEqual(record['size'], (out / name).stat().st_size)
                self.assertEqual(struct.unpack('<I', (out / 'pm_config.bin').read_bytes())[0],
                                 0x215 | flag << 10)
                self.assertFalse(manifest['verification']['board_compatibility'])
                self.assertFalse(manifest['verification']['USB_BSLE_DLI_RF'])
                self.assertEqual(manifest['status'], 'configuration-candidate')

    def test_existing_directory_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ini = root / 'synthetic.ini'
            ini.write_text(fixture())
            out = root / 'existing'
            out.mkdir()
            (out / 'keep').write_text('prior evidence')
            with self.assertRaises(FileExistsError):
                board.export(ini, out, 'synthetic-board', 0)
            self.assertEqual((out / 'keep').read_text(), 'prior evidence')
            self.assertEqual(list(out.iterdir()), [out / 'keep'])

    def test_invalid_input_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ini = root / 'synthetic.ini'
            ini.write_text(fixture().replace('bsle_use_flash=0', 'bsle_use_flash=1'))
            out = root / 'candidate'
            with self.assertRaises(ValueError):
                board.export(ini, out, 'synthetic-board', 0)
            self.assertFalse(out.exists())

    def test_flag_and_board_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ini = root / 'synthetic.ini'
            ini.write_text(fixture())
            for flag in (None, True, 2, -1):
                with self.subTest(flag=flag), self.assertRaises(ValueError):
                    board.export(ini, root / 'bad', 'synthetic-board', flag)
            with self.assertRaises(ValueError):
                board.export(ini, root / 'bad', ' ', 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
