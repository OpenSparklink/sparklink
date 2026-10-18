import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_early_fault import validate_fault, validate_core_snapshot, validate_core_absent, validate_bus_registration


class EarlyBootstrapFault(unittest.TestCase):
    def test_core_binding_proof_requires_real_fault_fields_and_ordinary_absence(self):
        c=self.sample()['credentials']
        s={'credentials':c,'snapshot':dict(version=1,dev_index=2,generation=3,state=2,profile=1,bus=4,phase=3,error=-2,reserved_byte=0,reserved=[0]*8)}
        validate_core_snapshot(s,2,3,2)
        for field,value in [('generation',4),('state',3),('bus',6),('phase',0),('error',0),('reserved_byte',1)]:
            bad=copy.deepcopy(s);bad['snapshot'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_core_snapshot(bad,2,3,2)
        absent={'credentials':c,'errno':19};validate_core_absent(absent)
        for value in [{'credentials':c,'errno':0},{'credentials':c,'errno':19,'snapshot':{}},{'credentials':dict(c,uids=[0]*4),'errno':19}]:
            with self.assertRaises(ValueError):validate_core_absent(value)

    def test_bus_proof_requires_exact_live_generation_and_default_observer_policy(self):
        path='/org/sparklink/slk2_g3'
        text=f'Registration {path}: index=2 generation=3 state=Fault profile=1 bus=4 phase=3 error=-2\n'
        sample={'user':'observer','credentials':dict(self.sample()['credentials'],uids=[1001]*4),'kernel_access':False,'commands':[{'args':['/bin/slctl','registration',path],'exit':0,'stdout':text},{'args':['/bin/slctl','registrations'],'exit':0,'stdout':text}]}
        validate_bus_registration(sample,2,3,'Fault')
        for mutation in ['root','kernel','wrong-generation','missing-listing']:
            bad=copy.deepcopy(sample)
            if mutation=='root':bad['credentials']['uids']=[0]*4
            if mutation=='kernel':bad['kernel_access']=True
            if mutation=='wrong-generation':bad['commands'][0]['stdout']=text.replace('generation=3','generation=4')
            if mutation=='missing-listing':bad['commands'][1]['stdout']=''
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_bus_registration(bad,2,3,'Fault')
        gone=copy.deepcopy(sample);gone['commands'][0]['exit']=1;gone['commands'][1]['stdout']=''
        validate_bus_registration(gone,2,3,None)
        with self.assertRaises(ValueError):validate_bus_registration(sample,2,3,None)

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

class CoreRegistrationCountContract(unittest.TestCase):
    def test_current_count_parser_separates_pending_from_installed(self):
        from ws73_early_fault import registration_counts
        rows = "\n".join(f"Registration /org/sparklink/slk{i}_g{i+1}: index={i} generation={i+1} state={state} profile=1 bus=4 phase=0 error=0" for i,state in enumerate(['Installed','Fault','Installed']))
        self.assertEqual(registration_counts(rows), {'Devices':3,'Reserved only':1,'Runtimes':2})
        with self.assertRaises(ValueError):registration_counts(rows+'\n'+rows.splitlines()[0])
        with self.assertRaises(ValueError):registration_counts(rows.replace('slk0_g1','slk0_g9'))
