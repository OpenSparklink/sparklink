#!/usr/bin/env python3
"""Offline production-code gate: unsupported/timeout never becomes PASS."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True, help='New private report directory')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
command = ['cargo', 'kani', '--manifest-path', 'formal/ssap_value/Cargo.toml']
result = {'schema_version': 1, 'status': 'NOT_PROVEN', 'accepted_proof': False,
          'command': command, 'scope': 'Production ValuePdu base single-value codec only, raw length0..16, arbitrary u16 MTU, capacity0..16, unwind20; no32-byte payload/database/actor/lifetime/RF proof',
          'sources': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in [
              'crates/slk-protocol/src/ssap/value.rs', 'formal/ssap_value/src/lib.rs',
              'formal/ssap_value/Cargo.toml', 'formal/ssap_value/Cargo.lock']}}
try:
    process = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=120)
    raw = process.stdout
    text = raw.decode(errors='replace')
    result['exit_code'] = process.returncode
    result['unsupported_diagnostic'] = 'unsupported constructs' in text.lower()
    result['complete_harness_summary'] = 'Complete - 2 successfully verified harnesses, 0 failures, 2 total.' in text
    if process.returncode == 0 and not result['unsupported_diagnostic'] and result['complete_harness_summary']:
        result['status'] = 'BOUNDED_CODEC_PROOF_PASS'
        result['accepted_proof'] = True
except subprocess.TimeoutExpired as error:
    raw = error.output or b''
    result['reason'] = 'tool timeout; not proved'
except OSError as error:
    raw = str(error).encode()
    result['reason'] = 'tool invocation failed; not proved'
result['source_changed_during_check'] = any(
    hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != original
    for name, original in result['sources'].items())
if result['source_changed_during_check']:
    result['status'] = 'NOT_PROVEN'
    result['accepted_proof'] = False
(args.output / 'kani.log').write_bytes(raw)
result['log_sha256'] = hashlib.sha256(raw).hexdigest()
(args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'status': result['status'], 'accepted_proof': result['accepted_proof']}))
raise SystemExit(0 if result['accepted_proof'] else 1)
