#!/usr/bin/env python3
"""Direct-production bounded checks; timeout/unsupported/incomplete is unproved."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import resource
import re
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
DISCOVERY={
 'discovery_proofs::actual_find_request_preserves_bytes_and_refuses_atomically':[
  'find request encoded length stays exact and bounded','find request preserves bytes and untouched tail','find request refusal is atomic'],
 'discovery_proofs::actual_member_page_binds_original_schema_range_and_budget':[
  'member page result is nonempty and input budget bounded','member page preserves ordered original handle range','member page category follows original request schema','member page UUID respects original class','member page metadata remains valid and bounded'],
 'discovery_proofs::actual_member_page_roundtrip_or_exact_capacity_refusal':[
  'member encoder admits one exact bounded entry','member roundtrip preserves entry count','member roundtrip preserves all scalar metadata and lengths','member roundtrip preserves every UUID byte','member roundtrip preserves every descriptor byte','valid member is refused only for exact capacity'],
}
DISCOVERY_NEGATIVE={'discovery_proofs::wrong_claim_page_for_unfiltered_request_completes_uuid_query':[]}
DISCOVERY_LOOP_INPUT_SHA256='981c6e9e2f064420ba0fce84369587c19c42303fde1e98e0a28e175a01ee4dfa'
DISCOVERY_SCOPE='Actual production FindRequest decoder/encoder over arbitrary0..22 bytes,all u16 MTU/output0..22;method/event page decoder over arbitrary0..32 bytes,all u16 range/MTU and three entry classes;single member encode/decode over arbitrary2/16-byte UUID,0..4 descriptor bytes,valid operation bits and nonzero handle. Unwind26/40;no stubs. Not full MTU/page80 exploration,peer semantic truth,UUID-query matching semantics,actor/allocator/OS/USB/refinement/RF proof;same response opcode is interpreted under original schema,not proof of peer intent.'
# Exact Kani0.68 standard-library safety branches already reviewed in the
# fragment scope: no overflowing subtraction in unsigned abs_diff,constant
# valid pointer alignment,and literal formatting. This is not permission to
# omit any discovery assertion or to accept a reachable unsupported construct.
# Page opt-ins below are separate and tied to the exact production source.
DISCOVERY_REQUEST_UNREACHABLE=(
 ("std::fmt::Arguments::<'_>::from_str",'assertion','attempt to shift left with overflow'),
 ('std::ptr::const_ptr::<impl *const ()>::is_aligned_to','assertion','attempt to subtract with overflow'),
 ('core::num::<impl usize>::abs_diff','assertion','attempt to subtract with overflow'),
)
DISCOVERY_PAGE_UNREACHABLE=DISCOVERY_REQUEST_UNREACHABLE+(
 ('std::alloc::Global::grow_impl_runtime','assertion','attempt to subtract with overflow'),
 # The real Entry is non-ZST with a positive constant size;these signed
 # division/remainder error branches cannot execute for its pointer stride.
 ('kani::rustc_intrinsics::ptr_offset_from::<ssap::discovery::Entry>','assertion','attempt to calculate the remainder with a divisor of zero'),
 ('kani::rustc_intrinsics::ptr_offset_from::<ssap::discovery::Entry>','assertion','attempt to calculate the remainder with overflow'),
 ('kani::rustc_intrinsics::ptr_offset_from::<ssap::discovery::Entry>','assertion','attempt to divide by zero'),
 ('kani::rustc_intrinsics::ptr_offset_from::<ssap::discovery::Entry>','assertion','attempt to divide with overflow'),
 # Only Methods/Events in this harness:not the Structure category-byte path
 # at line194. The operations bytes at line220 follow checked bytes(...,4).
 ('ssap::discovery::decode_page','assertion','index out of bounds: the length is less than or equal to the given index'),
)

def discovery_unreachable(harness):
 if harness=='discovery_proofs::actual_member_page_binds_original_schema_range_and_budget':return DISCOVERY_PAGE_UNREACHABLE
 return DISCOVERY_REQUEST_UNREACHABLE if harness in (
  'discovery_proofs::actual_find_request_preserves_bytes_and_refuses_atomically',
  'discovery_proofs::wrong_claim_page_for_unfiltered_request_completes_uuid_query')else ()

def discovery_unwindset(path,root=ROOT):
 """No input assumptions or disabled checks:only source-bound loop limits.

 Any insufficient limit still fails an actual CBMC unwinding assertion.
 Mangled identifiers come from the compiled Kani0.68 program,not a substitute
 parser. Unknown identities/changed sources cannot reuse this input silently.
 """
 path=path.resolve(strict=True);relative=str(path.relative_to(root))
 value=json.loads(path.read_text())
 # Only the reviewed symbol/limit mapping,not merely any syntactically valid
 # function name. Revisit this pin with its actual compiled symbol evidence
 # when the production source,harness,compiler or bound contract changes.
 if hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=DISCOVERY_LOOP_INPUT_SHA256:
  raise ValueError('reviewed discovery loop mapping required;unknown or changed symbols refused')
 if(set(value)!={'version','kani_version','sources','harnesses','bound_rationale'}or value['version']!=1 or value['kani_version']!='0.68.0'
    or set(value['sources'])!={'crates/slk-protocol/src/ssap.rs','crates/slk-protocol/src/ssap/discovery.rs','formal/ssap_value/src/discovery_proofs.rs'}
    or any(hashlib.sha256((root/f).read_bytes()).hexdigest()!=h for f,h in value['sources'].items())
    or set(value['harnesses'])!=set(DISCOVERY)or not value['bound_rationale']):
  raise ValueError('exact discovery source/tool/harness loop-bound contract required')
 for bounds in value['harnesses'].values():
  if not isinstance(bounds,dict)or any(not isinstance(k,str)or not re.fullmatch(r'[A-Za-z0-9_]+\.[0-9]+',k)or type(n)is not int or not 1<=n<=40 for k,n in bounds.items()):
   raise ValueError('positive loop limits only;no CBMC flag overrides')
 return relative,value

# Kani0.68 vacuous safety checks, individually reviewed against the original
# exports. Required named properties must all be Success, never Unreachable.
# Primary semantics: https://model-checking.github.io/kani/verification-results.html
ALLOWED_UNREACHABLE=(('alloc::raw_vec::RawVecInner::grow_amortized', 'assertion', 'attempt to multiply with overflow'), ('core::num::<impl usize>::abs_diff', 'assertion', 'attempt to subtract with overflow'), ('core::num::<impl usize>::div_ceil', 'assertion', 'attempt to add with overflow'), ('core::ub_checks::is_valid_allocation_size', 'assertion', 'attempt to divide by zero'), ("fragments::Plan::<'_>::encode", 'assertion', 'index out of bounds: the length is less than or equal to the given index'), ("fragments::Plan::<'_>::new", 'assertion', 'index out of bounds: the length is less than or equal to the given index'), ('fragments::Reassembly::<u8, u64>::apply', 'assertion', 'attempt to add with overflow'), ('fragments::Reassembly::<u8, u64>::apply', 'assertion', 'attempt to subtract with overflow'), ('fragments::Reassembly::<u8, u64>::apply', 'assertion', 'index out of bounds: the length is less than or equal to the given index'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'Cannot compute offset of a ZST'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'attempt to calculate the remainder with a divisor of zero'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'attempt to calculate the remainder with overflow'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'attempt to divide by zero'), ('kani::rustc_intrinsics::ptr_offset_from::<u8>', 'assertion', 'attempt to divide with overflow'), ('std::alloc::Global::grow_impl_runtime', 'assertion', 'attempt to subtract with overflow'), ("std::fmt::Arguments::<'_>::from_str", 'assertion', 'attempt to shift left with overflow'), ('std::ptr::const_ptr::<impl *const ()>::is_aligned_to', 'assertion', 'attempt to subtract with overflow'), ('std::vec::Vec::<u8>::append_elements_unreserved', 'assertion', 'attempt to add with overflow'))

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--fragments',action='store_true');p.add_argument('--layout',action='store_true');p.add_argument('--negative-layout',action='store_true');p.add_argument('--discovery',action='store_true');p.add_argument('--negative-discovery',action='store_true');p.add_argument('--discovery-unwindset',type=Path);p.add_argument('--budget-seconds',type=int,default=120);a=p.parse_args()
 if sum([a.layout,a.fragments,a.negative_layout,a.discovery,a.negative_discovery])>1:p.error('choose one proof scope')
 if not 1<=a.budget_seconds<=600:p.error('bounded tool budget1..600 seconds per harness')
 if a.discovery_unwindset and not a.discovery:p.error('loop-bound input only applies to explicit positive discovery scope')
 loop_input=discovery_unwindset(a.discovery_unwindset)if a.discovery_unwindset else None
 a.output.mkdir(parents=True,exist_ok=False);a.output=a.output.resolve()
 files=['crates/slk-protocol/src/ssap/fragments.rs','crates/slk-protocol/src/ssap/value.rs','crates/slk-protocol/src/ssap/read_uuid.rs','crates/slk-protocol/src/ssap/updates.rs','crates/slkd/src/ssap_database/budget.rs','formal/ssap_value/src/lib.rs','formal/ssap_value/Cargo.toml','formal/ssap_value/Cargo.lock','formal/ssap_value/check.py','tools/run_formal.py','tools/build_resources.py','project/build-resource-policy.json']
 if a.discovery or a.negative_discovery:
  files=sorted(set(files+['crates/slk-protocol/src/ssap.rs','formal/ssap_value/src/discovery_proofs.rs']+[str(f.relative_to(ROOT))for f in (ROOT/'crates/slk-protocol/src/ssap').rglob('*.rs')]))
 if loop_input:files.append(loop_input[0])
 result=dict(schema_version=2,status='NOT_PROVEN',accepted_proof=False,scope=('Deliberately false claim on actual Layout(2047,2042);expected unique counterexample only,not a positive feature proof.'if a.negative_layout else'Actual production Layout::new/bounds for arbitrary usize length/index and u16 MTU;full2048-byte local layout (value2047/update2048),15-part local budget. No buffer-copy,allocator,Reassembly/actor/kernel/RF proof.'if a.layout else'Actual Plan/Reassembly production code;encode raw0..16/arbitrary u16 MTU/index/output0..24;fixed2-fragment write with arbitrary payload/epoch/time;valid2-or3-part read prefix plus arbitrary next0..8byte packet. Unwind40;local15-part limit. Not full2047-byte payload exploration,actor/allocator/kernel/clock/locking/refinement/RF proof.'if a.fragments else'Original production value codec0..16,unwind20;two explicit original harnesses only,not all other proof modules.'),reviewed_unreachable_checks=ALLOWED_UNREACHABLE if a.fragments else(),source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),sources={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest()for f in files},steps=[])
 if a.discovery or a.negative_discovery:result['scope']=('Deliberately false wrong-response-opcode claim on actual UUID-query decoder;expected unique counterexample,not positive qualification.'if a.negative_discovery else DISCOVERY_SCOPE)
 if loop_input:result['loop_bound_contract']=loop_input[1]
 snapshot=a.output/'source-snapshot'
 for f in files:
  q=snapshot/f;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/f,q)
 out=a.output/'report.json';out.write_text(json.dumps(result,indent=2)+'\n')
 selected=(DISCOVERY_NEGATIVE if a.negative_discovery else DISCOVERY if a.discovery else{'fragment_layout_negative::actual_layout_must_reject_the_false_single_wire_claim':[]}if a.negative_layout else{'fragment_layout_proof::actual_production_layout_bounds_all_lengths_mtu_and_indices':['layout logical length stays bounded','layout count stays bounded','layout slice and wire bounds hold','layout last body ends at exact logical boundary','layout rejects only invalid part index']}if a.layout else FRAGMENTS if a.fragments else BASE)
 negative=a.negative_layout or a.negative_discovery
 negative_marker=('CONTROL_WRONG_FIND_OPCODE_COMPLETES_UUID_QUERY'if a.negative_discovery else'CONTROL_OVERSIZE_LOGICAL_PDU_IS_ONE_WIRE_PACKET')if negative else None
 with build_lock()as lock:
  env,budget=environment();env.update(CARGO_NET_OFFLINE='true',CARGO_TARGET_DIR=str(workspace()/'.dev/formal-ssap-value-target'));result['budget']=budget
  version=subprocess.run(['cargo','kani','--version'],env=env,capture_output=True,text=True,timeout=15);result['tool_version']=version.stdout+version.stderr
  for number,(harness,properties)in enumerate(selected.items()):
   exported=a.output/f'harness-{number}.json';log=a.output/f'harness-{number}.log';cmd=['cargo','kani','-Z','unstable-options','--manifest-path','formal/ssap_value/Cargo.toml','--harness',harness,'--exact','--export-json',str(exported)]
   if loop_input and loop_input[1]['harnesses'][harness]:
    cmd+=['--cbmc-args','--unwindset',','.join(f'{k}:{n}'for k,n in loop_input[1]['harnesses'][harness].items())]
   step=dict(harness=harness,required_properties=properties,command=cmd,start_ns=time.time_ns(),status='NOT_PROVEN');result['steps'].append(step)
   with log.open('xb')as stream:
    memory=8*1024**3;step['address_space_limit_bytes']=memory
    child=subprocess.Popen(cmd,cwd=ROOT,env=env,pass_fds=(lock,),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_AS,(memory,memory)))
    try:step['exit']=child.wait(timeout=a.budget_seconds)
    except subprocess.TimeoutExpired:step.update(timeout=True,status='NOT_PROVEN_TIMEOUT')
    finally:
     # Only the isolated process group created above, never an unrelated job.
     try:os.killpg(child.pid,signal.SIGTERM)
     except ProcessLookupError:pass
     try:child.wait(timeout=2)
     except subprocess.TimeoutExpired:
      os.killpg(child.pid,signal.SIGKILL);child.wait()
   step.update(end_ns=time.time_ns(),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
   if(step.get('exit')==0 or negative and step.get('exit')==1)and not step.get('timeout')and exported.exists():
    allowed=ALLOWED_UNREACHABLE if a.fragments else discovery_unreachable(harness)if a.discovery or a.negative_discovery else()
    step['reviewed_unreachable_checks']=allowed
    step['export_sha256']=hashlib.sha256(exported.read_bytes()).hexdigest();step['status']=kani_export_verdict(json.loads(exported.read_text()),harness,properties,negative_marker=negative_marker,allowed_unreachable=allowed)
   out.write_text(json.dumps(result,indent=2)+'\n');print(harness,step['status'],flush=True)
 result['source_changed_during_check']=any(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=h for f,h in result['sources'].items())
 result['accepted_proof']=not result['source_changed_during_check']and len(result['steps'])==len(selected)and all(s['status']=='PROVED_SCOPED'for s in result['steps'])
 if result['accepted_proof']:result['status']='BOUNDED_DIRECT_PRODUCTION_PROOF_PASS'
 result['accepted_negative_control']=negative and not result['source_changed_during_check']and len(result['steps'])==1 and result['steps'][0]['status']=='EXPECTED_REJECTION_NEGATIVE_CONTROL'
 if result['accepted_negative_control']:result['status']='EXPECTED_NEGATIVE_REJECTION'
 out.write_text(json.dumps(result,indent=2)+'\n');return 0 if result['accepted_proof']or result['accepted_negative_control']else 1

if __name__=='__main__':raise SystemExit(main())
