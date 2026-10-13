import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_early_fault import validate_fault


class EarlyBootstrapFault(unittest.TestCase):
    def sample(self):
        return {'credentials':{'uids':[1000]*4,'cap_eff':'0','cap_prm':'0','cap_amb':'0'},'attributes':{'native_runtime':'id=-1 generation=0 streaming=0 broken=0 unsupported=0 last_event=0000 controller_error=100 reserved=1 pending_id=2 pending_generation=3 core_pending_ret=0 core_phase=3 core_error=-2','metadata_valid':'0','boot_stage':'failed','boot_error':'-2'}}

    def test_original_core_pending_error(self):
        self.assertEqual(validate_fault(self.sample()),{'id':2,'generation':3,'phase':3})

    def test_success_unqueried_error_or_mismatched_error_cannot_pass(self):
        for key,value in [('metadata_valid','1'),('boot_stage','native-ready'),('boot_error','0')]:
            row=self.sample();row['attributes'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_fault(row)
        for source,target in [('id=-1','id=2'),('streaming=0','streaming=1'),('reserved=1','reserved=0'),('core_error=-2','core_error=0'),('core_pending_ret=0','core_pending_ret=-19'),('pending_id=2','pending_id=16'),('pending_generation=3','pending_generation=0')]:
            row=self.sample();row['attributes']['native_runtime']=row['attributes']['native_runtime'].replace(source,target)
            with self.subTest(target=target),self.assertRaises(ValueError):validate_fault(row)

    def test_root_or_capability_bearing_read_is_not_ordinary(self):
        row=self.sample();row['credentials']['uids']=[0]*4
        with self.assertRaises(ValueError):validate_fault(row)
        for name in ['cap_eff','cap_prm','cap_amb']:
            row=self.sample();row['credentials'][name]='1'
            with self.subTest(name=name),self.assertRaises(ValueError):validate_fault(row)
