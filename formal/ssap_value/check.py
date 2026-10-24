#!/usr/bin/env python3
"""Direct-production bounded checks; timeout/unsupported/incomplete is unproved."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import resource
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from run_formal import kani_export_verdict
from build_resources import build_lock,environment,workspace

BASE={
 'proofs::exact_valid_decode_reencode':['assertion'],
 'proofs::failed_encode_is_atomic':['assertion'],
}
FRAGMENTS={
 'fragment_proofs::actual_fragment_encode_is_atomic_and_wire_bounded':[
  'fragment count within declared budget','fragment encoded output within wire MTU','fragment refusal is atomic'],
 'fragment_proofs::actual_fragment_completion_keeps_first_identity_and_deadline':[
  'fragment completion has original identity before expiry','fragment original context and deadline never renewed','fragment completion preserves whole logical bytes','fragment error discards partial state'],
 'fragment_proofs::actual_fragment_arbitrary_next_packet_cannot_change_qualification':[
  'arbitrary fragment cannot acquire new epoch or renewed deadline','arbitrary fragment keeps original bound','partial fragment never renews expiry','rejected fragment cannot retain work'],
}

# Kani0.68 vacuous safety checks, individually reviewed against the original
# exports. Required named properties must all be Success, never Unreachable.
# Primary semantics: https://model-checking.github.io/kani/verification-results.html
ALLOWED_UNREACHABLE=(('alloc::raw_vec::RawVecInner::grow_amortized', 'assertion', 'attempt to multiply with overflow'), ('core::num::<impl usize>::abs_diff', 'assertion', 'attempt to subtract with overflow'), ('core::num::<impl usize>::div_ceil', 'assertion', 'attempt to add with overflow'), ('core::ub_checks::is_valid_allocation_size', 'assertion', 'attempt to divide by zero'), ("fragments::Plan::<'_>::encode", 'assertion', 'index out of bounds: the length is less than or equal to the given index'), ("fragments::Plan::<'_>::new", 'assertion', 'index out of bounds: the length is less than or equal to the given index'), ('fragments::Reassembly::<u8, u64>::apply', 'assertion', 'attempt to add with overflow'), ('fragments::Reassembly::<u8, u64>::apply', 'assertion', 'attempt to subtract with overflow'), ('fragments::Reassembly::<u8, u64>::apply', 'assertion', 'index out of bounds: the length is less than or equal to the given index'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'Cannot compute offset of a ZST'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'attempt to calculate the remainder with a divisor of zero'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'attempt to calculate the remainder with overflow'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'attempt to divide by zero'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'attempt to divide with overflow'), ('std::alloc::Global::grow_impl_runtime', 'assertion', 'attempt to subtract with overflow'), ("std::fmt::Arguments::<'_>::from_str", 'assertion', 'attempt to shift left with overflow'), ('std::ptr::const_ptr::<impl *const ()>::is_aligned_to', 'assertion', 'attempt to subtract with overflow'), ('std::vec::Vec::<u8>::append_elements_unreserved', 'assertion', 'attempt to add with overflow'))

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--fragments',action='store_true');p.add_argument('--layout',action='store_true');p.add_argument('--negative-layout',action='store_true');p.add_argument('--budget-seconds',type=int,default=120);a=p.parse_args()
 if sum([a.layout,a.fragments,a.negative_layout])>1:p.error('choose one proof scope')
 if not 1<=a.budget_seconds<=600:p.error('bounded tool budget1..600 seconds per harness')
 a.output.mkdir(parents=True,exist_ok=False);a.output=a.output.resolve()
 files=['crates/slk-protocol/src/ssap/fragments.rs','crates/slk-protocol/src/ssap/value.rs','crates/slk-protocol/src/ssap/read_uuid.rs','crates/slk-protocol/src/ssap/updates.rs','crates/slkd/src/ssap_database/budget.rs','formal/ssap_value/src/lib.rs','formal/ssap_value/Cargo.toml','formal/ssap_value/Cargo.lock','formal/ssap_value/check.py','tools/run_formal.py','tools/build_resources.py','project/build-resource-policy.json']
 result=dict(schema_version=2,status='NOT_PROVEN',accepted_proof=False,scope=('Deliberately false claim on actual Layout(2047,2042);expected unique counterexample only,not a positive feature proof.'if a.negative_layout else'Actual production Layout::new/bounds for arbitrary usize length/index and u16 MTU;full2048-byte local layout (value2047/update2048),15-part local budget. No buffer-copy,allocator,Reassembly/actor/kernel/RF proof.'if a.layout else'Actual Plan/Reassembly production code;encode raw0..16/arbitrary u16 MTU/index/output0..24;fixed2-fragment write with arbitrary payload/epoch/time;valid2-or3-part read prefix plus arbitrary next0..8byte packet. Unwind40;local15-part limit. Not full2047-byte payload exploration,actor/allocator/kernel/clock/locking/refinement/RF proof.'if a.fragments else'Original production value codec0..16,unwind20;two explicit original harnesses only,not all other proof modules.'),reviewed_unreachable_checks=ALLOWED_UNREACHABLE if a.fragments else(),source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),sources={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest()for f in files},steps=[])
 snapshot=a.output/'source-snapshot'
 for f in files:
  q=snapshot/f;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/f,q)
 out=a.output/'report.json';out.write_text(json.dumps(result,indent=2)+'\n')
 selected=({'fragment_layout_negative::actual_layout_must_reject_the_false_single_wire_claim':[]}if a.negative_layout else{'fragment_layout_proof::actual_production_layout_bounds_all_lengths_mtu_and_indices':['layout logical length stays bounded','layout count stays bounded','layout slice and wire bounds hold','layout last body ends at exact logical boundary','layout rejects only invalid part index']}if a.layout else FRAGMENTS if a.fragments else BASE)
 with build_lock()as lock:
  env,budget=environment();env.update(CARGO_NET_OFFLINE='true',CARGO_TARGET_DIR=str(workspace()/'.dev/formal-ssap-value-target'));result['budget']=budget
  version=subprocess.run(['cargo','kani','--version'],env=env,capture_output=True,text=True,timeout=15);result['tool_version']=version.stdout+version.stderr
  for number,(harness,properties)in enumerate(selected.items()):
   exported=a.output/f'harness-{number}.json';log=a.output/f'harness-{number}.log';cmd=['cargo','kani','-Z','unstable-options','--manifest-path','formal/ssap_value/Cargo.toml','--harness',harness,'--exact','--export-json',str(exported)]
   step=dict(harness=harness,required_properties=properties,command=cmd,start_ns=time.time_ns(),status='NOT_PROVEN');result['steps'].append(step)
   with log.open('xb')as stream:
    memory=8*1024**3;step['address_space_limit_bytes']=memory
    child=subprocess.Popen(cmd,cwd=ROOT,env=env,pass_fds=(lock,),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_AS,(memory,memory)))
    try:step['exit']=child.wait(timeout=a.budget_seconds)
    except subprocess.TimeoutExpired:step['timeout']=True
    finally:
     # Only the isolated process group created above, never an unrelated job.
     try:os.killpg(child.pid,signal.SIGTERM)
     except ProcessLookupError:pass
     try:child.wait(timeout=2)
     except subprocess.TimeoutExpired:
      os.killpg(child.pid,signal.SIGKILL);child.wait()
   step.update(end_ns=time.time_ns(),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
   if(step.get('exit')==0 or a.negative_layout and step.get('exit')==1)and not step.get('timeout')and exported.exists():
    step['export_sha256']=hashlib.sha256(exported.read_bytes()).hexdigest();step['status']=kani_export_verdict(json.loads(exported.read_text()),harness,properties,negative_marker='CONTROL_OVERSIZE_LOGICAL_PDU_IS_ONE_WIRE_PACKET'if a.negative_layout else None,allowed_unreachable=ALLOWED_UNREACHABLE if a.fragments else())
   out.write_text(json.dumps(result,indent=2)+'\n');print(harness,step['status'],flush=True)
 result['source_changed_during_check']=any(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=h for f,h in result['sources'].items())
 result['accepted_proof']=not result['source_changed_during_check']and len(result['steps'])==len(selected)and all(s['status']=='PROVED_SCOPED'for s in result['steps'])
 if result['accepted_proof']:result['status']='BOUNDED_DIRECT_PRODUCTION_PROOF_PASS'
 result['accepted_negative_control']=a.negative_layout and not result['source_changed_during_check']and len(result['steps'])==1 and result['steps'][0]['status']=='EXPECTED_REJECTION_NEGATIVE_CONTROL'
 if result['accepted_negative_control']:result['status']='EXPECTED_NEGATIVE_REJECTION'
 out.write_text(json.dumps(result,indent=2)+'\n');return 0 if result['accepted_proof']or result['accepted_negative_control']else 1

if __name__=='__main__':raise SystemExit(main())
