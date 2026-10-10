# SPDX-License-Identifier: GPL-2.0-only
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_target import board_files, config_required, opened_usb_node, prepared, usb_properties
from ws73_north_star import file_record, healthy_native_runtime, registration


class TargetEnvironment(unittest.TestCase):
    def test_physical_registration_uses_actual_no_error_sentinel(self):
        # Filesystem fixture only. This is not a hardware/RF acceptance record.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);device=root/'1-2';device.mkdir();interface=root/'1-2:1.0';interface.mkdir()
            driver=root/'drivers/sparklink_ws73_usb';driver.mkdir(parents=True);(interface/'driver').symlink_to(driver)
            for name,value in {'idVendor':'ffff','idProduct':'3733','busnum':'1','devnum':'7','manufacturer':'vendor','product':'WS73'}.items():
                (device/name).write_text(value+'\n')
            native='id=0 generation=5 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error=100'
            attrs={'metadata_valid':'1','runtime_transport':'1','boot_error':'0','native_runtime':native,
                   'controller_information':'version=0201000120 features=01010101010101010101 address=02:73:00:00:00:01 acb=254/5 icb=0/0 bootstrap_credits=0'}
            for name,value in attrs.items():(interface/name).write_text(value+'\n')
            selected=registration('1-2',root)
            self.assertEqual((selected['path'],selected['features'],selected['bus'],selected['device']),('/org/sparklink/slk0_g5','01'*10,1,7))
            (interface/'native_runtime').write_text(native.replace('controller_error=100','controller_error=0'))
            with self.assertRaises(ValueError):registration('1-2',root)
    def test_live_owned_fd_matches_current_device_not_deleted_handle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fd=root/'10/fd';fd.mkdir(parents=True)
            (fd/'3').symlink_to('/dev/bus/usb/001/003 (deleted)')
            self.assertFalse(opened_usb_node(10,'/dev/bus/usb/001/003',root))
            (fd/'4').symlink_to('/dev/bus/usb/001/004')
            self.assertTrue(opened_usb_node(10,'/dev/bus/usb/001/004',root))
            self.assertFalse(opened_usb_node(11,'/dev/bus/usb/001/004',root))
    def test_native_error_sentinel_is_not_a_controller_status(self):
        base='id=0 generation=1 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error='
        self.assertEqual(healthy_native_runtime(base+'100')[2],'1')
        for status in ['0','01','ff','101']:
            with self.subTest(status=status),self.assertRaises(ValueError):healthy_native_runtime(base+status)
    def test_broken_or_retired_native_runtime_is_not_ready(self):
        good='id=0 generation=1 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error=100'
        for value in [good.replace('broken=0','broken=1'),good.replace('streaming=1','streaming=0'),good.replace('generation=1','generation=0'),good.replace('id=0','id=16')]:
            with self.subTest(value=value),self.assertRaises(ValueError):healthy_native_runtime(value)
    def test_ports_pin_topology_not_transient_address(self):
        p=usb_properties('1-2.1.3',1)
        self.assertEqual((p['hostbus'],p['hostport'],p['port'],p['guest-reset']),(1,'2.1.3','2',False))
        self.assertNotIn('hostaddr',p)
    def test_reject_nonphysical_port_names(self):
        for name in ['usb0','1-0','0-1','1-2:1.0','1-2.0','1-2,hostaddr=3','1-2\n']:
            with self.subTest(name=name),self.assertRaises(ValueError):usb_properties(name,0)
    def test_requires_capture_and_export_before_launch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config';p.write_text('CONFIG_RUST=y\nCONFIG_SPARKLINK=y\nCONFIG_SPARKLINK_SLE=y\nCONFIG_SPARKLINK_WS73_USB=y\n')
            with self.assertRaisesRegex(ValueError,'USB_MON'):config_required(p)
    def test_board_inputs_are_explicit_raw_exact_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'bsle_custom.bin').write_bytes(bytes(140));(p/'pm_config.bin').write_bytes(bytes(4))
            self.assertEqual(set(board_files(p)),{'bsle_custom.bin','pm_config.bin'})
            (p/'bsle_custom.bin').write_bytes(bytes(139))
            with self.assertRaises(ValueError):board_files(p)
    def test_prepared_artifact_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);image=p/'bzImage';image.write_bytes(b'original');qemu=p/'qemu';qemu.write_bytes(b'program')
            for name in ['kernel.config','initramfs.cpio.gz']:(p/name).write_bytes(b'original')
            (p/'manifest.json').write_text(json.dumps({'status':'PREPARED','physical_acceptance':False,'artifacts':[file_record(p/name) for name in ['bzImage','kernel.config','initramfs.cpio.gz']],'qemu':file_record(qemu)}))
            image.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'artifact changed'):prepared(p)
    def test_manifest_cannot_validate_different_files_from_launched_guest(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);old=p/'old';new=p/'new';old.mkdir();new.mkdir();qemu=p/'qemu';qemu.write_bytes(b'program')
            for name in ['bzImage','kernel.config','initramfs.cpio.gz']:(old/name).write_bytes(b'original')
            (new/'manifest.json').write_text(json.dumps({'status':'PREPARED','physical_acceptance':False,'artifacts':[file_record(old/name) for name in ['bzImage','kernel.config','initramfs.cpio.gz']],'qemu':file_record(qemu)}))
            with self.assertRaisesRegex(ValueError,'path differs'):prepared(new)
    def test_success_label_cannot_claim_physical_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'manifest.json').write_text(json.dumps({'status':'PREPARED','physical_acceptance':True}))
            with self.assertRaises(ValueError):prepared(p)


if __name__=='__main__':unittest.main()
