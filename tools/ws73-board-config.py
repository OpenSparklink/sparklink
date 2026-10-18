#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Export a WS73 SDK efuse configuration candidate, with exact provenance.

Layout facts: customize_bsle_ext.h, customize_bsle.c, customize.h and
customize_wifi.c. This is an independent exporter, not a vendor-driver copy.
No firmware upload, radio operation, or hardware acceptance is performed.
"""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_values(data):
    # Some unrelated SDK Wi-Fi tables contain non-INI fragments. Parse only
    # the two sections that supply this payload, while hashing the full input.
    # Keep strict syntax/duplicate checks inside those selected sections.
    lines = []
    section = None
    for line in data.decode('utf-8-sig').splitlines():
        text = line.strip()
        if text.startswith('['):
            match = re.fullmatch(r'\[([^\]]+)\]\s*(?:[#;].*)?', text)
            if match is None:
                if section in ('DEVICE_BT', 'HOST_PLAT'):
                    raise ValueError('malformed section boundary in board configuration')
                section = None
                continue
            section = match[1]
            if section == 'DEFAULT':
                raise ValueError('DEFAULT inheritance is not permitted for board configuration')
        if section in ('DEVICE_BT', 'HOST_PLAT'):
            lines.append(line)
    parser = configparser.ConfigParser(interpolation=None, strict=True,
                                       inline_comment_prefixes=('#', ';'))
    parser.read_string('\n'.join(lines))
    if parser.defaults():
        raise ValueError('DEFAULT inheritance is not permitted for board configuration')
    selected = {}

    def value(section, name, minimum, maximum):
        try:
            text = parser[section][name].strip()
            result = int(text, 16 if text.lower().startswith('0x') else 10)
        except (KeyError, ValueError) as error:
            raise ValueError(f'{section}.{name}: explicit integer required') from error
        if not minimum <= result <= maximum:
            raise ValueError(f'{section}.{name}: expected {minimum}..{maximum}')
        selected[f'{section}.{name}'] = result
        return result

    def bt(name, minimum, maximum):
        return value('DEVICE_BT', name, minimum, maximum)

    words = [
        bt('bt_coex_mode', 0, 7),
        bt('ble_disable_ll_privacy', 0, 1),
        bt('bsle_suspend_mode', 0, 1),
        bt('bsle_suspend_scan_interval', 3, 10240),
        bt('bsle_suspend_scan_window', 3, 10240),
        bt('bsle_front_switch', 0, 1),
        bt('bt_maxpower', 1, 7),
        bt('bt_cali_txpwr_pa_ref_num', 0, 8),
    ]
    if words[4] > words[3]:
        raise ValueError('suspend scan window exceeds interval')
    for i in range(1, 9):
        ref = bt(f'bt_cali_txpwr_pa_ref_band{i}', 0, 65535)
        freq = bt(f'bt_cali_txpwr_pa_fre{i}', 0, 65535)
        if i <= words[7] and not (18 <= ref <= 22 and freq <= 78):
            raise ValueError(f'active calibration band {i}: invalid reference/frequency')
        words.append(ref | freq << 16)
    blocks = [bt(f'bt_cali_txpwr_pa_fre_block{i}', 0, 78) for i in range(1, 8)]
    if blocks != sorted(set(blocks)):
        raise ValueError('calibration channel blocks must be strictly increasing')
    words.extend((blocks[i] << 16 | blocks[i + 1]) for i in (0, 2, 4))
    words.append(blocks[6])
    words.append(bt('bt_srrc_switch', 0, 1))
    for i in range(1, 9):
        ref = bt(f'bt_srrc_pa_ref_val{i}', 0, 255)
        freq = bt(f'bt_srrc_pa_fre{i}', 0, 255)
        if (ref, freq) != (255, 255) and not (ref <= 14 and freq <= 78):
            raise ValueError(f'SRRC band {i}: invalid reference/frequency or sentinel pair')
        words.append(ref | freq << 16)
    use_flash = bt('bsle_use_flash', 0, 1)
    if use_flash:
        raise ValueError('flash mode requires per-device flash calibration and addresses; '
                         'this efuse exporter cannot supply them')
    words.append(use_flash)
    # SDK efuse mode leaves the inactive flash fields/MAC region and ABI
    # padding zero. Active calibration values above always come from the INI.
    custom = struct.pack('<30I', *words) + bytes(20)
    pm_enable = value('HOST_PLAT', 'device_plt_pm_enable', 0, 1)
    gpio = value('HOST_PLAT', 'device_awake_host_gpio_idx', 0, 255)
    level = value('HOST_PLAT', 'device_awake_host_gpio_level', 0, 1)
    pm_word = pm_enable | gpio << 1 | level << 9
    return custom, pm_word, selected


def export(ini, output, board, usb_link_check):
    if type(usb_link_check) is not int or usb_link_check not in (0, 1):
        raise ValueError('usb_link_check must be explicitly 0 or 1')
    if not board or not board.strip():
        raise ValueError('board identity/provenance label is required')
    data = ini.read_bytes()
    custom, pm_word, selected = read_values(data)
    blobs = {'bsle_custom.bin': custom,
             'pm_config.bin': struct.pack('<I', pm_word | usb_link_check << 10)}
    # Reserve a fresh directory, preserving previous configurations/evidence.
    output.mkdir(parents=True, exist_ok=False)
    for name, blob in blobs.items():
        with (output / name).open('xb') as target:
            target.write(blob)
    manifest = dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        profile='ws73-sdk-efuse-customization-v1', board=board,
        status='configuration-candidate',
        verification={'layout_checked': True, 'board_compatibility': False,
                      'USB_BSLE_DLI_RF': False},
        source={'path': str(ini.resolve()), 'size': len(data), 'sha256': sha256(data)},
        exporter={'path': str(Path(__file__).resolve()),
                  'sha256': sha256(Path(__file__).read_bytes())},
        usb_link_check={'value': usb_link_check,
                        'origin': 'explicit argument; SDK compile-time configuration'},
        selected_values=selected,
        images={name: {'size': len(blob), 'sha256': sha256(blob)}
                for name, blob in blobs.items()},
        inactive_fields='efuse mode: flash-specific fields and addresses are unused zeros',
    )
    with (output / 'ws73-board-config.json').open('x') as target:
        json.dump(manifest, target, indent=2, ensure_ascii=False)
        target.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ini', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--board', required=True, help='board/source identity, not an acceptance claim')
    parser.add_argument('--usb-link-check', type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    try:
        manifest = export(args.ini, args.output_dir, args.board, args.usb_link_check)
    except (OSError, ValueError, configparser.Error) as error:
        parser.exit(2, f'ws73-board-config: {error}\n')
    print(f'{args.output_dir / "ws73-board-config.json"}: {manifest["status"]}')


if __name__ == '__main__':
    main()
