# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_native_build_check import EXPORTS, REQUIRED, boot_image, completed_build, configuration, elf_header, native_exports, release_name


class NativeBuildCheck(unittest.TestCase):
    def test_live_failed_or_changed_build_cannot_be_accepted(self):
        good={'status':'BUILD_PASSED','build_exit':0,'source_head':'head','normalized_config_sha256':'config',
              'source_unchanged':True,'config_unchanged':True}
        completed_build(good,'head','config')
        for update in [{'status':'BUILDING'},{'status':'BUILD_FAILED'},{'build_exit':2},
                       {'source_head':'other'},{'normalized_config_sha256':'other'},
                       {'source_unchanged':False},{'config_unchanged':False}]:
            with self.assertRaises(ValueError): completed_build(good | update,'head','config')

    def test_qemu_builtin_image_is_not_native_module_build(self):
        text='\n'.join('CONFIG_'+k+'='+v for k,v in REQUIRED.items())+'\n'
        self.assertEqual(configuration(text)['SPARKLINK_WS73_USB'], 'm')
        with self.assertRaises(ValueError): configuration(text.replace('CONFIG_SPARKLINK_WS73_USB=m','CONFIG_SPARKLINK_WS73_USB=y'))
        with self.assertRaises(ValueError): configuration(text+'CONFIG_SPARKLINK_VIRTUAL=m\n')
        with self.assertRaises(ValueError): configuration(text.replace('CONFIG_RUST=y','CONFIG_RUST=n'))

    def test_invisible_disabled_symbols_are_not_missing_requirements(self):
        text='\n'.join('CONFIG_'+k+'='+v for k,v in REQUIRED.items())+'\n'
        self.assertEqual(configuration(text), configuration(text+'# CONFIG_SPARKLINK_VIRTUAL is not set\n'))
        with self.assertRaises(ValueError): configuration(text.replace('CONFIG_USB_MON=y\n',''))

    def test_release_cannot_escape_staging_directory(self):
        self.assertEqual(release_name('7.0.0-rc6-opensparklink-native-lab+\n'), '7.0.0-rc6-opensparklink-native-lab+')
        for text in ['', '../other', '7.0/other', '7.0\nother', '7.0;cmd', '-7.0']:
            with self.assertRaises(ValueError): release_name(text)

    def test_module_and_kernel_elf_are_not_interchangeable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'binary';header=bytearray(64);header[:6]=b'\x7fELF\x02\x01'
            struct.pack_into('<HH',header,16,1,62);path.write_bytes(header);elf_header(path,{1})
            with self.assertRaises(ValueError): elf_header(path,{2,3})
            struct.pack_into('<HH',header,16,1,183);path.write_bytes(header)
            with self.assertRaises(ValueError): elf_header(path,{1})
            path.write_bytes(header[:16])
            with self.assertRaises(ValueError): elf_header(path,{1})

    def test_generic_elf_is_not_boot_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'bzImage';header=bytearray(0x206);header[0x1fe:0x200]=b'\x55\xaa';header[0x202:0x206]=b'HdrS'
            path.write_bytes(header);boot_image(path)
            header[0x202]=0;path.write_bytes(header)
            with self.assertRaises(ValueError): boot_image(path)

    def test_export_from_foreign_module_or_missing_health_is_rejected(self):
        lines=['0x0 '+name+' vmlinux EXPORT_SYMBOL_GPL' for name in sorted(EXPORTS)]
        text='\n'.join(lines);native_exports(text)
        for invalid in [text.replace('vmlinux','foreign'),text.replace('EXPORT_SYMBOL_GPL','EXPORT_SYMBOL'),
                        '\n'.join(line for line in lines if 'sparklink_native_health ' not in line),text+'\n'+lines[0]]:
            with self.assertRaises(ValueError): native_exports(invalid)
