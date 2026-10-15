# SPDX-License-Identifier: GPL-2.0-only
"""Disposable VM coordinator for the installed CLI, not an Agent or wire Engine.

Test decisions are written only after the real human-facing CLI prompt. USB,
peer relay RX, installation and application delivery are checked separately.
"""
from pathlib import Path
import json
import os
import re
import selectors
import subprocess
import time
from ws73_capture import CaptureError

METHOD = 'sdk111-no-mitm'
PROMPT = re.compile(r'AgentPrompt: request=(\d+) path=(\S+) generation=(\d+) lifetime=(\d+) handle=(\d+) role=(\d+) address_type=(\d+) address=(\S+) method=(\S+) deadline_monotonic_ns=(\d+)')
ALLOCATION = re.compile(r'ReferenceSecurityAllocated: request=(\d+) path=(\S+) deadline_monotonic_ns=(\d+)')

def fullmatch(pattern, text):
    value = pattern.fullmatch(text)
    if value is None:
        raise CaptureError('invalid actual CLI transcript field')
    return value.groups()

def credentials(raw):
    fields = dict(line.split(':', 1) for line in raw.splitlines() if ':' in line)
    if (list(map(int, fields['Uid'].split())) != [1000]*4
            or list(map(int, fields['Gid'].split())) != [1002]*4
            or any(int(fields[k], 16) for k in ['CapEff', 'CapPrm', 'CapInh', 'CapAmb'])):
        raise CaptureError('actual ordinary control-group CLI credentials required')

def prompt_fields(line, obj):
    p = fullmatch(PROMPT, line)
    expected = (obj['path'], str(obj['generation']), str(obj['lifetime']), str(obj['handle']),
                str(obj['role']), str(obj['address_type']), obj['address'], METHOD)
    if p[1:9] != expected or int(p[0]) <= 0:
        raise CaptureError('actual CLI prompt must match original physical reference')
    return dict(request_id=int(p[0]), deadline_monotonic_ns=int(p[9]), path=p[1])

def execute(run, phase, row):
    if str(run.args.slctl) != '/bin/slctl': raise CaptureError('sealed staged production CLI path required')
    entries = sorted(phase['typed_objects'], key=lambda e: -e['object']['role'])
    if [e['object']['role'] for e in entries] != [1, 0]:
        raise CaptureError('passive T before active G required')
    row['cli_processes'] = records = []
    live = {}
    selector = selectors.DefaultSelector()
    decision = row['mode'].removeprefix('cli-')
    all_ready = set()
    requests_started = False
    stop_sent = False
    deadline = time.monotonic() + 18
    def start(kind, entry):
        owner, obj = entry['owner'], entry['object']
        args = [str(run.args.slctl), '--adapter', owner['path']]
        args += ['agent'] if kind == 'agent' else ['security-request', obj['path'], '5000']
        record = dict(kind=kind, controller=owner['path'], path=obj['path'], args=args,
                      start_wall_ns=time.time_ns(), stdout='', stderr='', decisions=[])
        records.append(record); run.save()
        p = subprocess.Popen(args, stdin=subprocess.PIPE if kind == 'agent' else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        live[p.pid] = (p, record, entry)
        record['pid'] = p.pid
        record['process_status'] = Path(f'/proc/{p.pid}/status').read_text()
        credentials(record['process_status'])
        for name in ['stdout', 'stderr']:
            stream = getattr(p, name); os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, (p.pid, name, bytearray()))
        run.save()
    try:
        for entry in entries: start('agent', entry)
        while True:
            if time.monotonic() >= deadline:
                raise CaptureError('actual CLI coordinator original bounded watchdog')
            for key, _ in selector.select(.02):
                pid, name, buffer = key.data
                p, record, entry = live[pid]
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    if buffer: raise CaptureError('truncated CLI output line')
                    continue
                record[name] += chunk.decode('utf-8')
                if len(record[name]) > 65536: raise CaptureError('CLI transcript budget exceeded')
                buffer.extend(chunk)
                while b'\n' in buffer:
                    raw, _, rest = buffer.partition(b'\n'); buffer[:] = rest
                    line = raw.decode('utf-8')
                    if name != 'stdout' or record['kind'] != 'agent': continue
                    if line.startswith('AgentReady:'):
                        expected = f"AgentReady: controller={record['controller']} daemon={run.data['bus_before']['owner']} method={METHOD}; explicit per-request consent only; unauthenticated, no Bond"
                        if line != expected or pid in all_ready: raise CaptureError('wrong/duplicate CLI owner registration')
                        record['ready_wall_ns'] = time.time_ns()
                        all_ready.add(pid)
                    if line.startswith('AgentPrompt:'):
                        values = prompt_fields(line, entry['object'])
                        if record['decisions'] or not time.monotonic_ns() < values['deadline_monotonic_ns'] <= time.monotonic_ns()+5_000_000_000:
                            raise CaptureError('bounded original prompt required')
                        answer = f"{decision} {values['request_id']}\n".encode()
                        issued = time.time_ns()
                        if os.write(p.stdin.fileno(), answer) != len(answer): raise CaptureError('partial explicit decision')
                        record['decisions'].append(dict(**values, text=answer.decode(), wall_ns=issued, monotonic_ns=time.monotonic_ns()))
                run.save()
            if len(all_ready) == 2 and not requests_started:
                requests_started = True
                for entry in entries: start('request', entry)
            requests = [(p, r) for p, r, _ in live.values() if r['kind'] == 'request']
            if len(requests) == 2 and all(p.poll() is not None for p, _ in requests) and not stop_sent:
                stop_sent = True
                for p, r, _ in live.values():
                    if r['kind'] == 'agent': os.write(p.stdin.fileno(), b'quit\n')
            if stop_sent and all(p.poll() is not None for p, _, _ in live.values()) and not selector.get_map():
                break
        for p, record, _ in live.values():
            record.update(exit=p.wait(), end_wall_ns=time.time_ns())
        row['end_wall_ns'] = time.time_ns()
        row['status'] = 'PENDING_USB_AND_APPLICATION_CORROBORATION'
        run.save()
        witness(row, phase, run.data['bus_before'])
    finally:
        # Reap every subprocess on failure too; cleanup is never a positive verdict.
        for p, record, _ in live.values():
            if p.poll() is None: p.kill()
            p.wait()
            record.setdefault('exit', p.returncode)
            record.setdefault('end_wall_ns', time.time_ns())
            if p.stdin: p.stdin.close()
            for name in ['stdout', 'stderr']:
                stream = getattr(p, name)
                rest = stream.read() or b''
                record[name] += rest.decode('utf-8', errors='replace')
                stream.close()
        selector.close(); run.save()

def witness(row, phase, daemon):
    if row['status'] != 'PENDING_USB_AND_APPLICATION_CORROBORATION' or row['mode'] not in ['cli-approve', 'cli-reject']:
        raise CaptureError('actual CLI evidence pending independent proof required')
    records = row['cli_processes']
    if len(records) != 4: raise CaptureError('two real Agents and two original request clients required')
    for entry in phase['typed_objects']:
        obj, owner = entry['object'], entry['owner']
        pair = {kind: [r for r in records if r['kind'] == kind and r['path'] == obj['path']]
                for kind in ['agent', 'request']}
        if any(len(v) != 1 for v in pair.values()): raise CaptureError('one client of each kind per original object')
        agent, request = pair['agent'][0], pair['request'][0]
        for record in [agent, request]:
            credentials(record['process_status'])
            if (record['args'][0] != '/bin/slctl' or record['controller'] != owner['path'] or not row['start_wall_ns'] <= record['start_wall_ns'] <= record['end_wall_ns'] <= row['end_wall_ns']
                    or record['args'] != [record['args'][0], '--adapter', owner['path']] + (['agent'] if record['kind']=='agent' else ['security-request',obj['path'],'5000'])):
                raise CaptureError('CLI source/arguments/time/reference mismatch')
        ready = [l for l in agent['stdout'].splitlines() if l.startswith('AgentReady:')]
        expected = f"AgentReady: controller={owner['path']} daemon={daemon['owner']} method={METHOD}; explicit per-request consent only; unauthenticated, no Bond"
        if ready != [expected] or daemon['uid'] != 0 or agent['exit'] != 0 or agent['stderr']:
            raise CaptureError('original root daemon and clean CLI Agent required')
        prompts = [l for l in agent['stdout'].splitlines() if l.startswith('AgentPrompt:')]
        allocations = [l for l in request['stdout'].splitlines() if l.startswith('ReferenceSecurityAllocated:')]
        results = [l for l in request['stdout'].splitlines() if l.startswith('ReferenceSecurityResult: ')]
        if len(prompts)!=1 or len(allocations)!=1 or len(results)!=1 or len(agent['decisions'])!=1:
            raise CaptureError('one complete CLI prompt/allocation/decision/result required')
        values = prompt_fields(prompts[0], obj)
        a = fullmatch(ALLOCATION, allocations[0])
        issued = agent['decisions'][0]
        decision = row['mode'].removeprefix('cli-')
        if (a != (str(values['request_id']), obj['path'], str(values['deadline_monotonic_ns']))
                or issued != dict(**values, text=f"{decision} {values['request_id']}\n", wall_ns=issued['wall_ns'], monotonic_ns=issued['monotonic_ns'])
                or not agent['start_wall_ns'] <= agent['ready_wall_ns'] <= request['start_wall_ns'] <= issued['wall_ns'] <= agent['end_wall_ns']
                or not 0 < values['deadline_monotonic_ns'] - issued['monotonic_ns'] <= 5_000_000_000):
            raise CaptureError('original CLI request identity/deadline/explicit answer mismatch')
        decisions = [l for l in agent['stdout'].splitlines() if l.startswith('AgentDecision:')]
        expected_decision = f"AgentDecision: request={values['request_id']} approved={'true' if decision=='approve' else 'false'}; policy result only"
        if decisions != [expected_decision]: raise CaptureError('actual CLI decision receipt required')
        result = json.loads(results[0].split(': ',1)[1])
        if any(result[k] != v for k,v in dict(**{k:values[k] for k in ['request_id','deadline_monotonic_ns']},generation=obj['generation'],lifetime=obj['lifetime']).items()):
            raise CaptureError('CLI result original identity mismatch')
        terminal = 4 if decision == 'approve' else 5
        if result['phase'] != terminal: raise CaptureError('wrong actual CLI policy terminal')
        success_lines = [l for l in request['stdout'].splitlines() if l.startswith('ReferenceSecurityCompleted:')]
        if decision == 'approve':
            if (request['exit']!=0 or request['stderr'] or success_lines!=['ReferenceSecurityCompleted: unauthenticated SDK111 reference only; not peer identity, trusted Grant or Bond; peer application delivery requires its own test'] or not result['agent_approved'] or not result['native_admitted']
                    or result['kernel_state']!=9 or result['kernel_flags'] & 7 != 7 or any(result[k] for k in ['error','kernel_error','kernel_status','cleanup_error'])):
                raise CaptureError('complete actual CLI native observations required; IPC success insufficient')
        elif (request['exit']!=1 or success_lines or result['agent_approved'] or result['native_admitted'] or result['kernel_state']
                or result['error']!=-125 or request['stderr']!='error: reference security did not complete successfully (phase=5)\n'):
            raise CaptureError('CLI rejection must not submit security mechanism or report success')
    return dict(scope='actual installed CLI subprocesses, explicit test-fixture decisions after prompts; not default automated consent')
