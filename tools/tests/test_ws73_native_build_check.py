# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import struct
import hashlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_native_build_check import EXPORTS, REQUIRED, boot_image, build_diagnostics, checked_build_diagnostics, completed_build, configuration, elf_header, native_exports, release_name


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
                        '\n'.join(line for line in lines if 'sparklink_native_health ' not in line),'\n'.join(line for line in lines if 'sparklink_native_link_event ' not in line),
                        '\n'.join(line for line in lines if 'sparklink_native_acb_send ' not in line),
                        '\n'.join(line for line in lines if 'sparklink_native_acb_take ' not in line),text+'\n'+lines[0],
                        text+'\n0x0 sparklink_native_register vmlinux EXPORT_SYMBOL_GPL',
                        text.replace('sparklink_backend_register', 'sparklink_native_register')]:
            with self.assertRaises(ValueError): native_exports(invalid)


class BuildDiagnosticAccounting(unittest.TestCase):
    def test_rust_summary_is_not_a_second_warning(self):
        v=build_diagnostics('warning: unused import: `MAX_PAYLOAD_LEN`\nwarning: 1 warning emitted\n')
        self.assertEqual(v['compiler_warning_count'],1)
        self.assertEqual(v['unclassified_warning_count'],0)
        self.assertFalse(v['warning_free_log'])

    def test_chinese_and_english_make_notices_are_separate(self):
        v=build_diagnostics('make[4]: 警告: jobserver 不可用\nmake[1]: warning: jobserver unavailable\n')
        self.assertEqual(v['compiler_warning_count'],0)
        self.assertEqual(v['make_warning_count'],2)
        self.assertFalse(v['warning_free_log'])

    def test_clang_locations_colors_and_summaries(self):
        v=build_diagnostics('\x1b[33mwarning[unused_imports]: import\x1b[0m\n/src/a.c:12:3: warning: unused variable [-Wunused-variable]\n2 warnings generated.\n')
        self.assertEqual(v['compiler_warning_count'],2)
        self.assertEqual(v['unclassified_warning_count'],0)

    def test_unrecognized_producer_cannot_be_claimed_warning_free(self):
        v=build_diagnostics('bindgen warning: opaque type\n')
        self.assertEqual(v['compiler_warning_count'],0)
        self.assertEqual(v['unclassified_warning_count'],1)
        self.assertFalse(v['warning_free_log'])
        self.assertTrue(build_diagnostics('RUSTC net/sparklink/core.o\n')['warning_free_log'])

    def test_live_failed_missing_and_tampered_logs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'build.log';data=b'warning: one\n';path.write_bytes(data)
            good={'status':'BUILD_PASSED','build_exit':0,'build_log':{'path':str(path),'sha256':hashlib.sha256(data).hexdigest()}}
            self.assertEqual(checked_build_diagnostics(good)['compiler_warning_count'],1)
            for bad in [good|{'status':'BUILD_RUNNING'},good|{'build_exit':2},good|{'build_log':{}},good|{'build_log':{'path':str(path),'sha256':'0'*64}}]:
                with self.assertRaises(ValueError): checked_build_diagnostics(bad)
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError): checked_build_diagnostics(good)

    def test_complete_record_reports_all_three_warning_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'log';data=b'warning: one\nwarning: 1 warning emitted\nmake[2]: warning: jobserver unavailable\ntool warning: other\n';path.write_bytes(data)
            good={'status':'BUILD_PASSED','build_exit':0,'build_log':{'path':str(path),'sha256':hashlib.sha256(data).hexdigest()}}
            v=checked_build_diagnostics(good)
            self.assertEqual((v['compiler_warning_count'],v['make_warning_count'],v['unclassified_warning_count']),(1,1,1))
            self.assertEqual(v['log_sha256'],hashlib.sha256(data).hexdigest())
