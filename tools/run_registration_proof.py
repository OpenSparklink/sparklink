#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Kani checks the actual SDK registration validator over arbitrary ABI fields.

Does not model Core locking, producer correctness, device presence, Ready,
callbacks, authorization or hardware. No alternate validator is implemented.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from run_formal import classify


def block(source, start):
    opening = source.index('{', start)
    depth = 1
    pos = opening + 1
    while depth:
        depth += (source[pos] == '{') - (source[pos] == '}')
        pos += 1
    return source[start:pos]


def verdict(code, log, timed_out, weak_control):
    result = classify('kani', code, log, timed_out)
    if not weak_control:
        return result
    if result == 'PROVED_SCOPED':
        return 'NOT_PROVEN_WEAK_CONTROL_UNEXPECTED_PASS'
    if result == 'NOT_PROVEN_FAILED_OR_INCOMPLETE' and code != 0 and 'VERIFICATION:- FAILED' in log and re.search(r'\*\* 1 of \d+ failed',log) and 'Failed Checks: assertion failed: generation == 0 || s.generation == generation' in log and '0 successfully verified harnesses, 1 failures, 1 total' in log:
        return 'EXPECTED_COUNTEREXAMPLE_WEAK_VALIDATOR'
    return result


def run(output, budget, weak_control=False):
    repo = Path(__file__).resolve().parents[1]
    source = repo/'crates/slk-protocol/src/types.rs'
    original = source.read_text()
    start = original.index('pub struct SleRegistrationSnapshot {')
    declaration = block(original, original.rfind('#[derive', 0, start))
    constants = '\n'.join(re.findall(r'^pub const REGISTRATION_\w+[^\n]+', original, re.M))
    implementation = block(original, original.index('impl SleRegistrationSnapshot {'))
    effective = implementation
    if weak_control:
        guard = '&& (generation == 0 || self.generation == generation)'
        assert effective.count(guard) == 1
        effective = effective.replace(guard, '&& (generation == generation)')
    output.mkdir(parents=True, exist_ok=False)
    (output/'src').mkdir()
    (output/'Cargo.toml').write_text('[package]\nname="sparklink-registration-validator-proof"\nversion="0.0.0"\nedition="2021"\npublish=false\n\n[workspace]\n')
    harness = '''
#[kani::proof]
fn accepted_observation_preserves_identity_and_diagnostics() {
    let s: SleRegistrationSnapshot = kani::any();
    let index: u16 = kani::any();
    let generation: u64 = kani::any();
    if s.valid_for(index, generation) {
        assert!(index < 16 && s.dev_index == index);
        assert!(s.generation != 0);
        assert!(generation == 0 || s.generation == generation);
        assert!(s.version == 1 && s.bus <= 6);
        assert!(s.reserved_byte == 0 && s.reserved == [0; 8]);
        match s.state {
            1 => { assert!(s.error == 0); },
            2 => { assert!(s.error < 0); },
            3 | 4 => { assert!(s.phase == 0 && s.error == 0); },
            _ => panic!("unknown registration state accepted"),
        }
    }
}
'''
    generated = '#[derive(kani::Arbitrary)]\n'+declaration+'\n'+constants+'\n'+effective+'\n'+harness
    (output/'src/lib.rs').write_text(generated)
    command = ['cargo','kani','--manifest-path',str(output/'Cargo.toml'),'--harness','accepted_observation_preserves_identity_and_diagnostics']
    started = time.time_ns()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    timed_out = False
    try:
        log, _ = process.communicate(timeout=budget)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        log, _ = process.communicate()
    (output/'kani.log').write_text(log)
    assert source.read_text() == original
    record = dict(status=classify('kani',process.returncode,log,timed_out),source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),source_path=str(source),source_sha256=hashlib.sha256(original.encode()).hexdigest(),actual_declaration=declaration,actual_constants=constants,actual_implementation=implementation,generated_sha256=hashlib.sha256(generated.encode()).hexdigest(),command=command,tool_version=subprocess.check_output(['cargo','kani','--version'],text=True).strip(),exit=process.returncode,timed_out=timed_out,budget_seconds=budget,started_ns=started,finished_ns=time.time_ns(),state_space='All bit patterns of every ABI field, full u16 index and u64 generation; no assumptions or unwinding loops',properties='Accepted decoded observations preserve requested index/generation, nonzero identity, version, reserved bytes, known bus/state and pending/fault/installed/retiring diagnostic constraints',scope='Actual production SDK valid_for predicate only. Not Core producer/mutex/lifetime/availability/Ready, wire parser, C/Python wrapper, authorization, callback or hardware proof',physical_acceptance=False)
    record['tool_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    record['classifier_sha256']=hashlib.sha256((repo/'tools/run_formal.py').read_bytes()).hexdigest()
    record['weak_control']=weak_control
    record['effective_implementation']=effective
    record['status']=verdict(process.returncode,log,timed_out,weak_control)
    record['production_proof']=not weak_control
    record['counterexample_mapping']='SDK registration_tests::core_observation_requires_exact_identity_and_consistent_diagnostics, generation=7/index=2 rejects expected generation=8; hypothetical weak validator, not a Core or hardware fault'
    (output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    print(record['status'],output/'manifest.json')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--budget-seconds',type=int,default=60)
    p.add_argument('--weak-control',action='store_true',help='deliberately remove expected-generation guard from the extracted validator; never a production proof')
    a=p.parse_args()
    if not 1<=a.budget_seconds<=60:p.error('budget must be 1..60 seconds')
    run(a.output.resolve(),a.budget_seconds,a.weak_control)
