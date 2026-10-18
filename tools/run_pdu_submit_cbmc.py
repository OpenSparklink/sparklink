#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify actual production C Session commit consent, not a second state engine."""
import argparse,hashlib,json,os,re,subprocess,tempfile,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--timeout',type=int,default=180);a=p.parse_args()
root=Path(__file__).resolve().parents[1];kernel=Path(os.environ.get('SPARKLINK_KERNEL_SOURCE',root.parent/'linux'));net=kernel/'net/sparklink'
sys.path.insert(0,str(kernel/'tools/testing/selftests/sparklink'));from run_session_dispatch import function
harness=root/'formal/channel/pdu_submit_cbmc.c';source=net/'sle_channel_socket.c'
files=[source,harness,*[net/name for name in ['sle_channel_state.h','sle_channel_grant.h','sle_fragment_cursor.h']]];inputs={f:f.read_bytes() for f in files}
s=inputs[source].decode();structures=s[s.index('struct sl_basic_channel {'):s.index('static struct proto sl_channel_proto;')]
bodies='\n'.join(function(s,name) for name in ['sl_sk','sl_permits','sl_session_submit'])
code=inputs[harness].decode().replace('/* @@STRUCTS@@ */',structures).replace('/* @@FUNCTIONS@@ */',bodies)
with tempfile.TemporaryDirectory(prefix='sparklink-pdu-consent-') as d:
 f=Path(d)/'consent.c';f.write_text(code)
 command=['cbmc',str(f),'-I'+str(net),'--bounds-check','--pointer-check','--signed-overflow-check','--unsigned-overflow-check','--conversion-check','--unwinding-assertions','--trace']
 try:
  x=subprocess.run(command,capture_output=True,text=True,timeout=a.timeout);log=x.stdout+x.stderr;status='NOT_PROVEN'
  if x.returncode==0 and 'VERIFICATION SUCCESSFUL' in log and not re.search(r'unsupported|warning:|: FAILURE|: UNKNOWN',log,re.I):status='SCALAR_CONSENT_PASS'
 except subprocess.TimeoutExpired as e:
  x=None;log=(e.stdout or b'').decode()+(e.stderr or b'').decode();status='NOT_PROVEN_TIMEOUT'
assert all(f.read_bytes()==b for f,b in inputs.items())
a.output.with_suffix('.cbmc.log').write_text(log)
record=dict(kernel_tree_clean=not subprocess.check_output(['git','status','--porcelain'],cwd=kernel),userspace_tree_clean=not subprocess.check_output(['git','status','--porcelain'],cwd=root),status=status,exit=x.returncode if x else None,kernel_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=kernel,text=True).strip(),userspace_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),sources={str(f.relative_to(kernel) if f.is_relative_to(kernel) else f.relative_to(root)):hashlib.sha256(b).hexdigest() for f,b in inputs.items()},production_functions=['sl_sk','sl_permits','sl_session_submit'],production_bodies_sha256=hashlib.sha256(bodies.encode()).hexdigest(),generated_harness_sha256=hashlib.sha256(code.encode()).hexdigest(),version=subprocess.check_output(['cbmc','--version'],text=True).strip(),checks=re.findall(r'(\d+) of (\d+) failed',log),log_sha256=hashlib.sha256(log.encode()).hexdigest(),scope='Actual structures/functions, two channel slots, arbitrary scalar identities/grants/phase, current/foreign valid packet objects, started/retired, arbitrary expiry and USB result; exact first-submit authorization and frozen begun operation consent; no sequence unwind',assumptions=['Objects valid and retained for call; no concurrent mutation inside this serialized consent region','Spinlock, kernel sock/work/kref layouts and clock arithmetic are dependencies; expiry explores both outcomes','Native Runtime still holds Host/data/gate and rechecks epoch/lifetime before this callback; not proved by this harness'],trusted_base=['CBMC frontend/solver and C semantics'],not_proved=['Whole worker/reference/close/credit composition or C/Rust refinement','Runtime grant revocation, USB callbacks/HCD lifetime and NOCP hardware accuracy','Real hardware delivery, complete VFS dup/SCM_RIGHTS matrix or long-term liveness'],real_acceptance=False)
a.output.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
raise SystemExit(0 if status=='SCALAR_CONSENT_PASS' else 1)
