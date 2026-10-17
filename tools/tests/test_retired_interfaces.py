import copy
import json
from pathlib import Path
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_retired_interfaces import check

ROOT=Path(__file__).resolve().parents[2]


class RetiredEntryGuard(unittest.TestCase):
    def setUp(self):
        self.policy=json.loads((ROOT/'project/retired-interface-contract.json').read_text())
        paths=['crates/slk-native/src/adapter.rs','crates/slk-native/src/ioctl.rs',
               'crates/slk-native/include/sparklink_native.h','crates/slkd/src/controller.rs',
               'crates/slkd/src/dbus_iface.rs','bindings/python/sparklink/structs.py',
               'crates/slctl/src/commands.rs','crates/slkconfig/src/main.rs']
        self.files={p:(ROOT/p).read_text() for p in paths}

    def test_actual_current_sources_and_test_fixtures_do_not_restore_entries(self):
        self.assertEqual(check(self.policy,self.files),[])
        self.assertTrue((ROOT/'bindings/python/tests/retired_structs.py').is_file())

    def test_each_retired_surface_and_missing_source_fail_closed(self):
        cases=[
            ('crates/slk-native/src/adapter.rs','\npub fn start_scan() {}'),
            ('crates/slk-native/src/ioctl.rs','\nnix::ioctl_none!(sl_start_scan, SL_MAGIC,0x12);'),
            ('crates/slk-native/include/sparklink_native.h','\nint slk_connect(void);'),
            ('crates/slkd/src/controller.rs','\nasync fn get_role() {}'),
            ('crates/slkd/src/dbus_iface.rs','\nasync fn connect() {}'),
            ('bindings/python/sparklink/structs.py','\nclass SleConnInfo(ctypes.Structure): pass'),
            ('crates/slctl/src/commands.rs','\n"role" => facade(),'),
        ]
        for path,addition in cases:
            with self.subTest(path=path):
                files=copy.deepcopy(self.files);files[path]+=addition
                self.assertTrue(check(self.policy,files))
        files=copy.deepcopy(self.files)
        files['crates/slkconfig/src/main.rs']=files['crates/slkconfig/src/main.rs'].replace('enum Command {','enum Command {\n    Scan,')
        self.assertTrue(check(self.policy,files))
        for path in self.policy['absent_files']:
            files=copy.deepcopy(self.files);files[path]='// no-op facade'
            self.assertTrue(check(self.policy,files))
        for path in self.files:
            files=copy.deepcopy(self.files);del files[path]
            self.assertTrue(check(self.policy,files))
        with self.assertRaises(ValueError):check({'schema':0},self.files)
