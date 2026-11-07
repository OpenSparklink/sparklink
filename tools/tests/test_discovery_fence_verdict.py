"""Verifier-result boundary only, not a scanner or proof implementation."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_formal import kani_export_verdict

class ExportVerdict(unittest.TestCase):
    def fixture(self):
        return {'metadata':{'version':'1.0','kani_version':'0.68.0'}, 'error_details':[{'harness_id':'proofs::actual','has_errors':False}], 'verification_results':{
            'summary':{'total_harnesses':1,'executed':1,'status':'completed','successful':1,'failed':0},
            'results':[{'harness_id':'proofs::actual','status':'Success','checks':[
                {'status':'Success','category':'assertion','description':'old epoch rejected'},
                {'status':'Success','category':'arithmetic_overflow','description':'counter overflow checked'}]}]}}
    def test_complete_properties_required_not_just_exit_or_count(self):
        d=self.fixture();self.assertEqual(kani_export_verdict(d,'proofs::actual',['old epoch rejected']),'PROVED_SCOPED')
        self.assertEqual(kani_export_verdict(d,'proofs::actual'),'NOT_PROVEN_MISSING_PROPERTY_SPEC')
        for edit in range(8):
            bad=copy.deepcopy(d)
            if edit==0:bad['verification_results']['summary']['executed']=0
            elif edit==1:bad['verification_results']['results'][0]['checks'].pop(0)
            elif edit==2:bad['verification_results']['results'][0]['harness_id']='wrong'
            elif edit==3:bad['verification_results']['results'][0]['checks'][0]['status']='Unknown'
            elif edit==4:bad['verification_results']['results'][0]['checks'][1]['category']='unsupported_construct'
            elif edit==5:bad['verification_results']['results'][0]['checks'][0]['status']='Failure'
            elif edit==6:bad['metadata']['kani_version']='unknown'
            else:bad['verification_results']['results'][0]['checks']=[]
            self.assertNotEqual(kani_export_verdict(bad,'proofs::actual',['old epoch rejected']),'PROVED_SCOPED')
        for bad in [None,{},[],{'metadata':None}]:
            self.assertEqual(kani_export_verdict(bad,'proofs::actual'),'NOT_PROVEN_INVALID_EXPORT')
    def test_wrong_failure_cannot_satisfy_negative_control(self):
        d=self.fixture();r=d['verification_results'];r['summary'].update(successful=0,failed=1)
        d['error_details'][0].update(has_errors=True,error_type='assertion_failure')
        r['results'][0]['status']='Failure';c=r['results'][0]['checks'][0];c.update(status='Failure',description='CONTROL_STALE')
        self.assertEqual(kani_export_verdict(d,'proofs::actual',negative_marker='CONTROL_STALE'),'EXPECTED_REJECTION_NEGATIVE_CONTROL')
        for change in ['description','category','status']:
            bad=copy.deepcopy(d);bad['verification_results']['results'][0]['checks'][0][change]='wrong'
            self.assertNotEqual(kani_export_verdict(bad,'proofs::actual',negative_marker='CONTROL_STALE'),'EXPECTED_REJECTION_NEGATIVE_CONTROL')
    def test_unreachable_safety_checks_need_exact_opt_in_and_never_replace_required_properties(self):
        d=self.fixture();checks=d['verification_results']['results'][0]['checks']
        extra=dict(function='core::num::<impl usize>::abs_diff',category='assertion',description='attempt to subtract with overflow',status='Unreachable')
        checks.append(extra);allow=[(extra['function'],extra['category'],extra['description'])]
        self.assertNotEqual(kani_export_verdict(d,'proofs::actual',['old epoch rejected']),'PROVED_SCOPED')
        self.assertEqual(kani_export_verdict(d,'proofs::actual',['old epoch rejected'],allowed_unreachable=allow),'PROVED_SCOPED')
        for field in ['function','category','description','status']:
            bad=copy.deepcopy(d);bad['verification_results']['results'][0]['checks'][-1][field]='unknown'
            self.assertNotEqual(kani_export_verdict(bad,'proofs::actual',['old epoch rejected'],allowed_unreachable=allow),'PROVED_SCOPED')
        checks[0].update(function='proofs::actual',status='Unreachable')
        allow.append(('proofs::actual','assertion','old epoch rejected'))
        self.assertEqual(kani_export_verdict(d,'proofs::actual',['old epoch rejected'],allowed_unreachable=allow),'NOT_PROVEN_UNREACHABLE_REQUIRED_PROPERTY')
    def test_division_by_zero_is_a_checked_failure_not_an_unknown_or_ignored_property(self):
        d=self.fixture();checks=d['verification_results']['results'][0]['checks'];checks.append(dict(status='Success',category='division-by-zero',description='division by zero'))
        self.assertEqual(kani_export_verdict(d,'proofs::actual',['old epoch rejected']),'PROVED_SCOPED')
        checks[-1]['status']='Failure'
        self.assertNotEqual(kani_export_verdict(d,'proofs::actual',['old epoch rejected']),'PROVED_SCOPED')
