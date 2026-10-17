#!/usr/bin/env python3
"""Kani on exact production SSAP access predicate, not Engine/Host refinement."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

PROPERTIES = [
    'access reserved bits are rejected', 'access valid mask is exact',
    'access authorization never fabricated', 'access success needs bounded receipt',
    'access authentication requires original level2', 'access encryption requires original level1',
    'access directions remain independent',
    'approval only discharges selected authorization bit',
    'denial preserves original access predicate',
    'authorization metadata matches six-bit requirements',
]
HARNESS = r'''pub mod access;
#[kani::proof]
fn verify_access() {

 let bits:u32=kani::any();let level:u32=kani::any();let write:bool=kani::any();
 match access::SsapAccess::from_bits(bits) {
  Err(_)=>assert!(bits&!63!=0,"access reserved bits are rejected"),
  Ok(p)=>{
   assert!(bits&!63==0&&p.bits()==bits,"access valid mask is exact");
   let wanted=if write{bits&7}else{(bits>>3)&7};let result=p.check(level,write);
   assert!(wanted&4==0||result==Err(9),"access authorization never fabricated");
   assert!(result.is_err()||level<=2,"access success needs bounded receipt");
   assert!(result.is_err()||wanted&2==0||level>=2,"access authentication requires original level2");
   assert!(result.is_err()||wanted&1==0||level>=1,"access encryption requires original level1");
   let same=match access::SsapAccess::from_bits(bits^(if write{56}else{7})) {
    Ok(other)=>result==other.check(level,write),Err(_)=>false,
   };
   assert!(same,"access directions remain independent");
   let allowed:bool=kani::any();
   let approved=p.check_authorization_result(level,write,allowed);
   let without=access::SsapAccess::from_bits(bits&!(if write{4}else{32})).unwrap();
   assert!(!allowed||approved==without.check(level,write),"approval only discharges selected authorization bit");
   assert!(allowed||approved==result,"denial preserves original access predicate");
   assert!(p.needs_local_authorization()==(bits&36!=0),"authorization metadata matches six-bit requirements");
  }
 }

}
'''


def inspect(log, code):
    # Regular output includes every property status, not only a summary count.
    checks=re.findall(r'- Status: (\w+)',log)
    inventory=all(p in log for p in PROPERTIES)
    diagnostics=[s for s in log.splitlines() if re.search(r'warning:|unsupported|unwinding assertion.*FAIL',s,re.I)]
    terminal='VERIFICATION:- SUCCESSFUL' in log and re.search(r'1 successfully verified harnesses, 0 failures, 1 total',log) is not None
    passed=code==0 and terminal and inventory and checks and set(checks)=={'SUCCESS'} and not diagnostics
    return dict(status='BOUNDED_PREDICATE_PASS' if passed else 'NOT_PROVEN', raw_properties_success=bool(code==0 and terminal and inventory and checks and set(checks)=={'SUCCESS'}),complete_inventory=inventory,properties=len(checks),terminal=bool(terminal),diagnostics=diagnostics)


def run(out):
    if not __debug__:raise RuntimeError('verification cannot disable assertions')
    repo=Path(__file__).resolve().parents[1];source=repo/'crates/slk-protocol/src/ssap/access.rs';original=source.read_bytes()
    out.mkdir(parents=True,exist_ok=False)
    result=dict(status='RUNNING_NOT_PROVEN',source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),source_tree_clean=not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip(),source=str(source.relative_to(repo)),source_sha256=hashlib.sha256(original).hexdigest(),harness_sha256=hashlib.sha256(HARNESS.encode()).hexdigest(),tool=subprocess.check_output(['cargo','kani','--version'],text=True).strip(),properties=PROPERTIES,scope='Exact production pure SsapAccess constructor/check, arbitrary full32bit flags/receipt level andbooldirection; no assumptions excluding bad inputs. One predicate evaluation,not actualKernel/receiptTruth/SSAPEngine/DBmutation/Grant/USB/RF/security protocol proof.',assumptions=['Rust/compiler/Kani/CBMC semantics and truthful native receipt production remain trusted foundations outside this proof'],runs=[])
    path=out/'report.json'
    def save():path.write_text(json.dumps(result,indent=2)+'\n')
    save()
    try:
        for kind in ['production','authorization-negative','authentication-negative','empty-inventory-negative']:
            folder=out/kind;(folder/'src').mkdir(parents=True)
            body=original.decode()
            if kind=='authorization-negative':
                assert 'bits & 4 != 0' in body;body=body.replace('bits & 4 != 0','false')
            if kind=='authentication-negative':
                assert 'level < 2' in body;body=body.replace('level < 2','level < 1')
            (folder/'src/access.rs').write_text(body)
            harness=HARNESS if kind!='empty-inventory-negative' else 'pub mod access; #[kani::proof] fn verify_access(){assert!(true,"empty inventory");}\n'
            (folder/'src/lib.rs').write_text(harness)
            (folder/'Cargo.toml').write_text('[package]\nname="sparklink-access-proof"\nversion="0.0.0"\nedition="2021"\n[workspace]\n')
            (folder/'Cargo.lock').write_text('version = 4\n[[package]]\nname = "sparklink-access-proof"\nversion = "0.0.0"\n')
            command=['cargo','kani','--manifest-path',str(folder/'Cargo.toml'),'--harness','verify_access','--output-format','regular']
            raw=folder/'output.log'
            subprocess.run(['cargo','generate-lockfile','--offline','--manifest-path',str(folder/'Cargo.toml')],check=True,capture_output=True,env=os.environ|{'CARGO_NET_OFFLINE':'true'})
            lock=(folder/'Cargo.lock').read_bytes()
            with raw.open('x') as stream:done=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,env=os.environ|{'CARGO_BUILD_JOBS':'1','CARGO_NET_OFFLINE':'true'},timeout=180)
            assert (folder/'Cargo.lock').read_bytes()==lock, 'verifier lock changed'
            result['dependency_contract']='Dependency-free generated crate; retained lock checked byte-identical and CARGO_NET_OFFLINE=true; cargo-kani does not expose Cargo --locked'
            result['lock_sha256']=hashlib.sha256(lock).hexdigest()
            log=raw.read_text();verdict=inspect(log,done.returncode);result['runs'].append(dict(kind=kind,command=command,exit=done.returncode,log_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),**verdict));save()
            if kind=='production':assert verdict['raw_properties_success']
            elif kind=='empty-inventory-negative':assert done.returncode==0 and not verdict['complete_inventory'] and verdict['status']=='NOT_PROVEN'
            else:assert done.returncode!=0 and 'VERIFICATION:- FAILED' in log and verdict['status']=='NOT_PROVEN'
        assert source.read_bytes()==original
        result['status']='PRODUCTION_ACCESS_PREDICATE_AND_THREE_NEGATIVES_PASS' if result['runs'][0]['status']=='BOUNDED_PREDICATE_PASS' else 'NOT_PROVEN_TOOL_DIAGNOSTICS_RETAINED'
    except BaseException as error:
        result.update(status='NOT_PROVEN',error_type=type(error).__name__,error=str(error));raise
    finally:result['wall_ns']=time.time_ns();save()
    print(result['status'])
    if result['status']!='PRODUCTION_ACCESS_PREDICATE_AND_THREE_NEGATIVES_PASS':raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);run(p.parse_args().output.resolve())
