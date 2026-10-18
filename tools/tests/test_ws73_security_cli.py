"""Synthetic transcript controls, not real CLI, kernel or hardware evidence."""
import json
import unittest
from ws73_capture import CaptureError
from ws73_security_cli import witness,validate_binary
from ws73_security_agent import wire
from test_ws73_security_agent import fixture


BINARY=dict(path='/usr/libexec/opensparklink/native-lab/0123456789ab/slctl',sha256='a'*64)

def cli_fixture(mode='cli-approve'):
    row, phase, daemon, capture = fixture(mode.removeprefix('cli-'))
    row.pop('command'); events = row.pop('events')
    status = next(e['process_status'] for e in events if e['stage']=='probe_identity')
    row.update(mode=mode,cli_processes=[],cli_binary=dict(BINARY))
    for e in phase['typed_objects']:
        obj=e['object']; controller=obj['path'].split('/peer_t')[0]; e['owner']['path']=controller
        ready=f"AgentReady: controller={controller} daemon={daemon['owner']} method=sdk111-no-mitm; explicit per-request consent only; unauthenticated, no Bond"
        prompt=f"AgentPrompt: request=1 path={obj['path']} generation=7 lifetime=13 handle=1 role={obj['role']} address_type=0 address={obj['address']} method=sdk111-no-mitm deadline_monotonic_ns=5000000000"
        decision=mode.removeprefix('cli-')
        decision_text=f"AgentDecision: request=1 approved={'true' if decision=='approve' else 'false'}; policy result only"
        result=next(e for e in events if e.get('stage')=='policy_result' and e['path']==obj['path']).copy()
        result.pop('path');result.pop('stage');result['kernel_flags']=7 if decision=='approve' else 0
        common=dict(controller=controller,path=obj['path'],process_status=status,start_wall_ns=11,end_wall_ns=99)
        row['cli_processes'].append(dict(**common,ready_wall_ns=11,kind='agent',args=[BINARY['path'],'--adapter',controller,'agent'],stdout='\n'.join([ready,prompt,decision_text]),stderr='',exit=0,
            decisions=[dict(request_id=1,path=obj['path'],deadline_monotonic_ns=5000000000,text=f'{decision} 1\n',wall_ns=20,monotonic_ns=1000000000)]))
        output=f"ReferenceSecurityAllocated: request=1 path={obj['path']} deadline_monotonic_ns=5000000000\nReferenceSecurityResult: {json.dumps(result)}\n"
        if decision=='approve':output+='ReferenceSecurityCompleted: unauthenticated SDK111 reference only; not peer identity, trusted Grant or Bond; peer application delivery requires its own test\n'
        row['cli_processes'].append(dict(**common,kind='request',args=[BINARY['path'],'--adapter',controller,'security-request',obj['path'],'5000'],stdout=output,stderr='' if decision=='approve' else 'error: reference security did not complete successfully (phase=5)\n',exit=0 if decision=='approve' else 1,decisions=[]))
    return row,phase,daemon,capture


class CliWitnessControls(unittest.TestCase):
    def test_both_decisions_have_separate_actual_wire_requirements(self):
        for mode in ['cli-approve','cli-reject']:
            row,phase,daemon,capture=cli_fixture(mode);witness(row,phase,daemon,BINARY);wire(row,phase,capture)

    def test_missing_clients_prompt_decision_result_or_process_identity_fails(self):
        for field in ['process_status','stdout','stderr','exit','args','decisions','controller','path']:
            row,phase,daemon,_=cli_fixture();row['cli_processes'][0][field]='bad'
            with self.assertRaises((CaptureError,KeyError,TypeError,ValueError,IndexError),msg=field):witness(row,phase,daemon,BINARY)
        for n in range(4):
            row,phase,daemon,_=cli_fixture();row['cli_processes'].pop(n)
            with self.assertRaises(CaptureError):witness(row,phase,daemon,BINARY)

    def test_changed_ids_deadline_owner_flags_and_complete_are_rejected(self):
        for original,replacement in [('request=1','request=2'),('deadline_monotonic_ns=5000000000','deadline_monotonic_ns=5000000001'),('daemon=:1.10','daemon=:1.11'),('approved=true','approved=false')]:
            row,phase,daemon,_=cli_fixture();row['cli_processes'][0]['stdout']=row['cli_processes'][0]['stdout'].replace(original,replacement)
            with self.assertRaises(CaptureError):witness(row,phase,daemon,BINARY)
        for original,replacement in [('"kernel_flags": 7','"kernel_flags": 3'),('"native_admitted": true','"native_admitted": false'),('"cleanup_error": 0','"cleanup_error": -5')]:
            row,phase,daemon,_=cli_fixture();row['cli_processes'][1]['stdout']=row['cli_processes'][1]['stdout'].replace(original,replacement)
            with self.assertRaises(CaptureError):witness(row,phase,daemon,BINARY)

    def test_cli_success_cannot_replace_opposite_rx_or_install_event(self):
        for event in [0x14,0x11]:
            row,phase,daemon,capture=cli_fixture();witness(row,phase,daemon,BINARY)
            capture['native_events']=[e for e in capture['native_events'] if e['event']!=event]
            with self.assertRaises(CaptureError):wire(row,phase,capture)

    def test_reject_cannot_hide_success_receipt_or_native_submission(self):
        row,phase,daemon,_=cli_fixture('cli-reject');row['cli_processes'][1]['stdout']+='ReferenceSecurityCompleted: wrong\n'
        with self.assertRaises(CaptureError):witness(row,phase,daemon,BINARY)
        reject,phase,_,_=cli_fixture('cli-reject');_,_,_,positive=cli_fixture('cli-approve')
        with self.assertRaises(CaptureError):wire(reject,phase,positive)

    def test_sealed_binary_mismatch_is_rejected(self):
        import tempfile
        import hashlib
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);artifact=root/BINARY['path'].lstrip('/');artifact.parent.mkdir(parents=True);artifact.write_bytes(b'explicit synthetic CLI fixture')
            binary=dict(path=BINARY['path'],sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
            files=[dict(path=str(artifact),sha256=binary['sha256'])]
            validate_binary(binary,root,files)
            for wrong in [dict(binary,path='/bin/other'),dict(binary,sha256='b'*64)]:
                with self.assertRaises(CaptureError):validate_binary(wrong,root,files)
            with self.assertRaises(CaptureError):validate_binary(binary,root,[])
            artifact.write_bytes(b'replaced')
            with self.assertRaises(CaptureError):validate_binary(binary,root,files)
