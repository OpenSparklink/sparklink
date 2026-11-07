"""Finite offline verifier controls, not SDK/kernel/firmware qualification.

Wire bytes and CLI receipts are authored independently here. Only the original
bounded-output fixture helper and exact endpoint matcher are shared with the
positive gate tests; that matcher calls the actual ACB reassembler and consumes
real-shaped fragments. No production encoder or successful transport stub is
used. These controls do not prove packet-capture completeness on hardware.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ws73_ssap_command as positive
import ws73_ssap_command_policy as gate
from ws73_capture import CaptureError
from test_ws73_ssap_command import credentials, fixture as positive_fixture, matcher, output


PREFIX = 'ssap_command_policy'
ENV = dict(PYTHONPATH='/usr/share/sparklink/python:/usr/share/sparklink/tools',
           LIBSPARKLINK_PATH='/usr/lib/libsparklink.so.0')


def receipt_change(app, **changes):
    lines = app['stdout'].splitlines()
    label, encoded = lines[1].split(': ', 1)
    value = json.loads(encoded); value.update(changes)
    app['stdout'] = lines[0] + '\n' + label + ': ' + json.dumps(value) + '\n'
    output(app)


def add_pair(capture, source, target, pdu, stamp):
    # Independent short DTAP/SSAP fixture; PB complete=0, not a production encoder.
    frame = b'\x0a\x00' + len(pdu).to_bytes(2, 'little') + pdu
    for endpoint, direction, offset in ((source, 'out', 0), (target, 'in', 1)):
        capture['acb_packets'].append(dict(bus=endpoint['owner']['bus'],
            device=endpoint['owner']['device'], handle=endpoint['object']['handle'],
            direction=direction, boundary=0, data=frame.hex(),
            record=len(capture['acb_packets']) + 1, wall_ns=stamp + offset))



def replace_prompt_line(owner, ordinal):
    """Keep a mutated event/stdout coherent to exercise semantic identity checks."""
    event = owner['policy_decisions'][ordinal-1]
    prompt = dict(event['prompt'], write=str(event['prompt']['write']).lower())
    replacement = ("SsapAuthorizationPrompt: token={token} request={request} index={index} generation={generation} "
        "lifetime={lifetime} handle={handle} epoch={epoch} security={security} property={property} data_type={data_type} "
        "write={write} bytes={bytes} deadline_ns={deadline_ns}; answer 'yes {yes}' or 'no {no}'").format(**prompt)
    lines = owner['stdout'].splitlines()
    indices = [i for i, line in enumerate(lines) if line.startswith('SsapAuthorizationPrompt: ')]
    lines[indices[ordinal-1]] = replacement
    if ordinal == 2:
        # Also keep the daemon decision's request namespace coherent. A replay
        # must fail monotonicity, not merely a stale rendering comparison.
        decisions = [i for i, line in enumerate(lines) if line.startswith('SsapAuthorizationDecision: ')]
        lines[decisions[ordinal-1]] = (f'SsapAuthorizationDecision: request={prompt["request"]} property={owner["handle"]} '
            'data_type=0 write=true security=0 approved=false; local policy only')
    owner['stdout'] = '\n'.join(lines)+'\n'; output(owner)

def fixture(phase=0):
    row, capture = positive_fixture(phase)
    row.update(ssap_command_policy_required=True, ssap_command_policy_contract=1,
               ssap_command_policy_cases=[], ssap_command_policy_publishers=[])
    for sender in (0, 1):
        for api in ('c', 'python'):
            ordinal = len(row[PREFIX + '_cases']); sequence = phase * 4 + ordinal
            handle = 80 + ordinal
            clock = phase * 1_000_000_000 + 100_000_000 + ordinal * 30_000_000
            digest = lambda key: hashlib.sha256(f'policy/{phase}/{ordinal}/{key}'.encode()).digest()
            source, target = row['owners'][sender], row['owners'][1 - sender]
            owner = dict(sender=sender, target=1-sender, api=api, operations=3, policy='ask',
                handle=handle, start=handle-1, end=handle, secret=digest('initial').hex(),
                service=digest('service')[:16].hex(), uuid=digest('uuid')[:16].hex(),
                start_wall_ns=clock-10, pid=4000+ordinal, exit=0, stderr='',
                credentials=credentials(), policy_decisions=[], value_snapshots=[])
            owner['args'] = ['/bin/slctl', '--adapter', target['owner']['path'], 'ssap-serve',
                            owner['service'], owner['uuid'], '3', '36', owner['secret'], 'ask']
            owner['stdout'] = f'SsapOwnedService: start={handle-1} end={handle} property={handle}; local registration only\n'
            case = dict(sequence=sequence, sender=sender, target=1-sender, api=api,
                publisher=ordinal, handle=handle, before=owner['secret'], start_wall_ns=clock,
                status='ACTUAL_COMMAND_POLICY_PENDING_PAIRED_CAPTURE')

            def snapshot(value, stamp):
                snap = dict(handle=handle, value=value, start_wall_ns=stamp, end_wall_ns=stamp+1,
                    start_monotonic_ns=stamp, end_monotonic_ns=stamp+1,
                    ordinal=len(owner['value_snapshots'])+1)
                owner['value_snapshots'].append(snap)
                owner['stdout'] += f'SsapOwnedValue: handle={handle} value={value}\n'
                return snap

            def decision(write, approve, stamp):
                number = len(owner['policy_decisions']) + 1
                prompt = dict(token=number, request=100+ordinal*10+number,
                    index=target['owner']['index'], generation=target['owner']['generation'],
                    lifetime=target['object']['lifetime'], handle=target['object']['handle'], epoch=42,
                    security=0, property=handle, data_type=0, write=write, bytes=32 if write else 0,
                    deadline_ns=stamp+1_000_000_000, yes=number, no=number)
                rendered = dict(prompt, write=str(write).lower())
                owner['stdout'] += ("SsapAuthorizationPrompt: token={token} request={request} index={index} generation={generation} "
                    "lifetime={lifetime} handle={handle} epoch={epoch} security={security} property={property} data_type={data_type} "
                    "write={write} bytes={bytes} deadline_ns={deadline_ns}; answer 'yes {yes}' or 'no {no}'\n").format(**rendered)
                owner['stdout'] += (f'SsapAuthorizationDecision: request={prompt["request"]} property={handle} '
                    f'data_type=0 write={str(write).lower()} security=0 approved={str(approve).lower()}; local policy only\n')
                event = dict(prompt=prompt, approved=approve, observed_wall_ns=stamp,
                    observed_monotonic_ns=stamp, sent=('yes' if approve else 'no')+f' {number}',
                    sent_monotonic_ns=stamp+1, completed_wall_ns=stamp+2, completed_monotonic_ns=stamp+2)
                owner['policy_decisions'].append(event)
                return event

            case['local_before'] = snapshot(owner['secret'], clock+1)
            for index, name in enumerate(('oversized', 'denied', 'allowed')):
                stamp = clock + 1000 + index * 5_000_000
                size = 2043 if index == 0 else 32
                value = (sequence.to_bytes(4, 'little') + bytes([index]) + (digest(name)*64)[:size-5]).hex()
                step = dict(sequence=sequence, api=api, handle=handle, value=value, start_wall_ns=stamp)
                mode = 'ssap-command-reject' if index == 0 else 'ssap-command'
                prefix = ['/bin/ws73-application-client-c'] if api == 'c' else [
                    '/bin/python3', '/usr/share/sparklink/tools/ws73-application-client.py']
                app = dict(api=api, args=prefix+[mode, str(source['owner']['index']),
                    str(source['owner']['generation']), source['object']['path'], str(handle), value, '0'],
                    environment=ENV.copy(), credentials=credentials(), exit=0, stderr='',
                    start_wall_ns=stamp+10, end_wall_ns=stamp+60,
                    barrier_wall_ns=stamp+20, release_wall_ns=stamp+30,
                    start_monotonic_ns=stamp+10, barrier_monotonic_ns=stamp+20,
                    release_monotonic_ns=stamp+30)
                barrier = dict(stage='ssap_command_start_barrier', api=api,
                               deadline_ns=stamp+1_000_000_000, client_closed=True)
                result = dict(api=api, handle=handle, value=value, minimum=0,
                    peer_delivery_confirmed=False, deadline_ns=barrier['deadline_ns'],
                    call_ns=stamp+40, returned_ns=stamp+50)
                label = 'SSAP_COMMAND_ADMITTED'
                if index == 0:
                    barrier.update(schema_version=1, mode=mode)
                    result.update(schema_version=1, mode=mode, method='WriteSsapCommand',
                        index=source['owner']['index'], generation=source['owner']['generation'],
                        path=source['object']['path'], application_bytes=2043, sdk_entered=True,
                        errno=22, operation_success=False)
                    label = 'SSAP_COMMAND_REJECTED'
                else:
                    result['admission_only'] = True
                app['stdout'] = json.dumps(barrier)+'\n'+label+': '+json.dumps(result)+'\n'
                output(app); step['command'] = app
                if index:
                    step['decision'] = decision(True, index == 2, stamp+100)
                    add_pair(capture, source, target,
                             b'\x0c\x03'+handle.to_bytes(2, 'little')+b'\x00'+bytes.fromhex(value), stamp+75)
                expected = value if index == 2 else owner['secret']
                step['read_decision'] = decision(False, True, stamp+300)
                step['read'] = dict(args=['/bin/slctl', '--adapter', source['owner']['path'],
                    'ssap-read', source['object']['path'], str(handle), '0'],
                    credentials=credentials(), exit=0, stderr='', start_wall_ns=stamp+200, end_wall_ns=stamp+400,
                    start_monotonic_ns=stamp+200, end_monotonic_ns=stamp+400,
                    stdout=f'SsapPeerValue: operation=ssap-read path={source["object"]["path"]} handle={handle} value={expected}\n')
                add_pair(capture, source, target, b'\x08\x03'+handle.to_bytes(2, 'little')+b'\x00', stamp+210)
                add_pair(capture, target, source, b'\x09\x03'+bytes.fromhex(expected), stamp+350)
                step['local_after'] = snapshot(expected, stamp+500)
                step['end_wall_ns'] = stamp+600; case[name] = step
            case['end_wall_ns'] = stamp+610
            owner['removal'] = dict(exit=0, stdout='SsapLocalServices: []\n', stderr='',
                                   start_wall_ns=stamp+620, end_wall_ns=stamp+630)
            owner['end_wall_ns'] = stamp+640; output(owner)
            row[PREFIX+'_cases'].append(case); row[PREFIX+'_publishers'].append(owner)
    return row, capture


def corroborated():
    result = dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED', proofs=[])
    for phase in (0, 1):
        row, capture = fixture(phase); matched, packets = matcher(capture)
        original, original_credit = positive.corroborate(row, matched)
        proof, credit = gate.corroborate(row, matched, packets)
        assert not packets and original_credit == {0:54, 1:54} and credit == {0:16, 1:16}
        result['proofs'].append(dict(phase=phase, owners=row['owners'],
                                   ssap_write_commands=original, ssap_command_policy=proof))
    return result


def manifest(summary):
    source = Path(gate.__file__).resolve()
    return dict(ssap_write_command_requested=True, ssap_write_command_contract_version=1,
        ssap_write_command_acceptance=True, status='PASSTHROUGH_SUPPORT_PASS', qemu_exit=0,
        ordinary_channel_socket_acceptance=True,
        qemu_args=['qemu', '-append', 'ws73.ssap_write_command=1 ws73.ssap_command_policy=1'],
        channel_socket_corroboration=summary, ssap_command_policy_requested=True,
        ssap_command_policy_acceptance=True, ssap_command_policy_contract_version=1,
        ssap_command_policy_verifier=dict(path=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest()))


class PolicyGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = corroborated()

    def test_full_matrix_preserves_original_positive_cases_and_real_shaped_fragments(self):
        rows = [fixture(phase)[0] for phase in (0, 1)]
        gate.validate_rows(rows, True)
        for row in rows:
            for case, owner in zip(row[PREFIX+'_cases'], row[PREFIX+'_publishers'], strict=True):
                self.assertEqual(len(gate.case_contract(row, case, owner)), 8)
        self.assertTrue(positive.valid_summary(self.summary))
        self.assertTrue(gate.valid_summary(self.summary))
        self.assertTrue(gate.valid_manifest(manifest(self.summary)))
        self.assertEqual(sum(len(r['ssap_write_commands']) for r in self.summary['proofs']), 24)
        self.assertEqual(sum(len(r[PREFIX]) for r in self.summary['proofs']), 8)
        for row in self.summary['proofs']:
            for item in row[PREFIX]:
                self.assertEqual(len(item['window_packets']), 16)
                self.assertEqual(len(item['wire']), 8)
                self.assertTrue(all(p['fragments'] for p in item['window_packets']))
                self.assertFalse(item['apps_only_qualification'])

    def test_raw_contract_refuses_missing_roles_and_boolean_versions(self):
        for name in ('phase', 'case', 'publisher', 'required', 'contract', 'unrequested', 'old-positive-case'):
            rows = [fixture(phase)[0] for phase in (0, 1)]; selected = True
            if name == 'phase': rows.pop()
            elif name == 'case': rows[0][PREFIX+'_cases'].pop()
            elif name == 'publisher': rows[0][PREFIX+'_publishers'].pop()
            elif name == 'required': rows[0][PREFIX+'_required'] = 1
            elif name == 'contract': rows[0][PREFIX+'_contract'] = True
            elif name == 'unrequested': selected = False
            else: rows[0]['ssap_write_commands'].pop()
            with self.subTest(name=name), self.assertRaises(CaptureError):
                gate.validate_rows(rows, selected)

    def test_receipts_identity_original_deadline_and_no_mutation_are_enforced(self):
        names = ('sdk-errno', 'sdk-not-entered', 'sdk-success', 'sdk-schema', 'sdk-deadline',
                 'sdk-arbitrary-error', 'prompt-token', 'prompt-generation', 'prompt-lifetime',
                 'prompt-replay', 'prompt-deadline', 'prompt-renewed', 'prompt-missing',
                 'wrong-answer-token', 'deny-approved', 'denied-owner-mutated', 'allowed-owner-stale',
                 'read-old', 'read-denied-new', 'replaced-registration', 'owner-not-removed',
                 'uid', 'owner-api', 'late-read', 'late-read-monotonic', 'typed-read-monotonic',
                 'decision-before-read-monotonic', 'typed-sequence', 'lost-output', 'capabilities')
        for name in names:
            row, capture = fixture(); case = row[PREFIX+'_cases'][0]; owner = row[PREFIX+'_publishers'][0]
            app = case['oversized']['command']; event = owner['policy_decisions'][1]
            if name == 'sdk-errno': receipt_change(app, errno=5)
            elif name == 'sdk-not-entered': receipt_change(app, sdk_entered=False)
            elif name == 'sdk-success': receipt_change(app, operation_success=True)
            elif name == 'sdk-schema': receipt_change(app, schema_version=True)
            elif name == 'sdk-deadline': receipt_change(app, returned_ns=json.loads(app['stdout'].splitlines()[0])['deadline_ns'])
            elif name == 'sdk-arbitrary-error': app['exit'] = 1
            elif name == 'prompt-token': event['prompt']['token'] = 99
            elif name == 'prompt-generation': event['prompt']['generation'] += 1
            elif name == 'prompt-lifetime': event['prompt']['lifetime'] += 1
            elif name == 'prompt-replay': event['prompt']['request'] = owner['policy_decisions'][0]['prompt']['request']
            elif name == 'prompt-deadline': event['completed_monotonic_ns'] = event['prompt']['deadline_ns']
            elif name == 'prompt-renewed': event['prompt']['deadline_ns'] = event['observed_monotonic_ns'] + 5_000_000_001
            elif name == 'prompt-missing': owner['policy_decisions'].pop()
            elif name == 'wrong-answer-token': event['sent'] = 'no 3'
            elif name == 'deny-approved': event['approved'] = True
            elif name == 'denied-owner-mutated': case['denied']['local_after']['value'] = case['denied']['value']
            elif name == 'allowed-owner-stale': case['allowed']['local_after']['value'] = owner['secret']
            elif name == 'read-old': case['allowed']['read']['stdout'] = case['allowed']['read']['stdout'].replace(case['allowed']['value'], owner['secret'])
            elif name == 'read-denied-new': case['denied']['read']['stdout'] = case['denied']['read']['stdout'].replace(owner['secret'], case['denied']['value'])
            elif name == 'replaced-registration': owner['stdout'] += owner['stdout'].splitlines()[0]+'\n'; output(owner)
            elif name == 'owner-not-removed': owner['removal']['stdout'] = f'SsapLocalServices: [[{owner["start"]},{owner["end"]}]]\n'
            elif name == 'uid': app['credentials']['uids'] = [0]*4
            elif name == 'owner-api': owner['api'] = 'python'
            elif name == 'late-read': case['denied']['read']['start_wall_ns'] = case['denied']['decision']['observed_wall_ns']-1
            elif name == 'late-read-monotonic': case['denied']['read']['end_monotonic_ns'] = case['denied']['read']['start_monotonic_ns']+7_000_000_001
            elif name == 'typed-read-monotonic': case['denied']['read']['start_monotonic_ns'] = True
            elif name == 'decision-before-read-monotonic': case['denied']['read_decision']['observed_monotonic_ns'] = case['denied']['read']['start_monotonic_ns']-1
            elif name == 'typed-sequence': case['sequence'] = False
            elif name == 'lost-output': owner['output_collection']['complete'] = False
            else: owner['credentials']['capabilities']['CapEff'] = '1'
            if name in ('prompt-token', 'prompt-generation', 'prompt-lifetime', 'prompt-replay', 'prompt-renewed'):
                replace_prompt_line(owner, 2)
            with self.subTest(name=name), self.assertRaises((CaptureError, ValueError)):
                # Full corroboration also checks the strict case/role numerical types.
                matched, packets = matcher(capture)
                gate.corroborate(row, matched, packets)

    def test_wire_missing_changed_extra_and_renegotiation_are_rejected(self):
        for name in ('missing-rx', 'changed-peer-value', 'duplicate-command', 'command-response',
                     'error-response', 'extra-exchange', 'old-endpoint', 'outside-window', 'empty-capture',
                     'read-before-command', 'corrupt-read-response'):
            row, capture = fixture(); case = row[PREFIX+'_cases'][0]
            group = [p for p in capture['acb_packets'] if case['start_wall_ns'] <= p['wall_ns'] <= case['end_wall_ns']]
            # Wire order: Read/Reply, denied Command/Read/Reply, allowed Command/Read/Reply.
            command_tx, command_rx = group[4], group[5]
            if name == 'missing-rx': capture['acb_packets'].remove(command_rx)
            elif name == 'changed-peer-value': command_rx['data'] = command_rx['data'][:-2]+'ff'
            elif name == 'duplicate-command':
                extra = copy.deepcopy(command_tx); extra['record'] = len(capture['acb_packets'])+1; capture['acb_packets'].append(extra)
            elif name in ('command-response', 'error-response', 'extra-exchange'):
                pdu = {'command-response':b'\x0e\x03', 'error-response':b'\x01\x03\x0c\x00\x00\x01',
                       'extra-exchange':b'\x02\x07\xfa\x07\x01\x02\x04\x00\x00\x00'}[name]
                add_pair(capture, row['owners'][1], row['owners'][0], pdu, case['denied']['start_wall_ns']+380)
            elif name == 'old-endpoint': command_rx['device'] += 100
            elif name == 'outside-window': command_rx['wall_ns'] = case['end_wall_ns']+1
            elif name == 'empty-capture': capture['acb_packets'] = []
            elif name == 'read-before-command': command_rx['record'] = group[7]['record']+1
            else: group[9]['data'] = group[9]['data'][:-2]+'ff'
            match, packets = matcher(capture)
            with self.subTest(name=name), self.assertRaises(CaptureError):
                gate.corroborate(row, match, packets)

    def test_retained_summary_rechecks_full_fragment_content_not_only_packet_key(self):
        for name in ('missing-case', 'missing-end', 'missing-window', 'fragment-data', 'fragment-record',
                     'fragment-time', 'fragment-pb', 'top-value', 'old-lifetime', 'typed-phase',
                     'typed-contract', 'typed-sender', 'typed-handle', 'global-scope', 'absence-claim'):
            summary = copy.deepcopy(self.summary); item = summary['proofs'][0][PREFIX][0]
            # JSON round-trip deliberately removes Python aliasing between inventories and legs.
            item['window_packets'] = json.loads(json.dumps(item['window_packets']))
            if name == 'missing-case': summary['proofs'][1][PREFIX].pop()
            elif name == 'missing-end': del item['wire'][0]['rx']
            elif name == 'missing-window': item['window_packets'].pop()
            elif name.startswith('fragment-'):
                field = {'fragment-data':'data', 'fragment-record':'record', 'fragment-time':'wall_ns', 'fragment-pb':'boundary'}[name]
                item['window_packets'][0]['fragments'][0][field] = 'ff' if field == 'data' else 999
            elif name == 'top-value': item['window_packets'][0]['data'] = '0a0002000e03'
            elif name == 'old-lifetime': summary['proofs'][0]['owners'][1]['object']['lifetime'] += 1
            elif name == 'typed-phase': item['phase'] = False
            elif name == 'typed-contract': item['contract'] = True
            elif name == 'typed-sender': item['case']['sender'] = False
            elif name == 'typed-handle': item['case']['handle'] = True
            elif name == 'global-scope': item['apps_only_qualification'] = True
            else: item['bounded_absence_only'] = False
            with self.subTest(name=name): self.assertFalse(gate.valid_summary(summary))

    def test_manifest_selection_verifier_and_original_positive_gate_are_mandatory(self):
        for name in ('unrequested', 'acceptance', 'contract', 'missing-boot', 'duplicate-boot',
                     'missing-positive', 'missing-positive-case', 'qemu', 'socket', 'proof',
                     'verifier-missing', 'verifier-hash', 'verifier-path'):
            record = manifest(copy.deepcopy(self.summary))
            if name == 'unrequested': record[PREFIX+'_requested'] = False
            elif name == 'acceptance': record[PREFIX+'_acceptance'] = False
            elif name == 'contract': record[PREFIX+'_contract_version'] = True
            elif name == 'missing-boot': record['qemu_args'][-1] = 'ws73.ssap_write_command=1'
            elif name == 'duplicate-boot': record['qemu_args'][-1] += ' ws73.ssap_command_policy=1'
            elif name == 'missing-positive': record['ssap_write_command_requested'] = False
            elif name == 'missing-positive-case': record['channel_socket_corroboration']['proofs'][0]['ssap_write_commands'].pop()
            elif name == 'qemu': record['qemu_exit'] = 1
            elif name == 'socket': record['ordinary_channel_socket_acceptance'] = False
            elif name == 'proof': record['channel_socket_corroboration']['proofs'][0][PREFIX].pop()
            elif name == 'verifier-missing': del record[PREFIX+'_verifier']
            elif name == 'verifier-hash': record[PREFIX+'_verifier']['sha256'] = 'not-a-sha256'
            else: record[PREFIX+'_verifier']['path'] = ''
            with self.subTest(name=name): self.assertFalse(gate.valid_manifest(record))
        self.assertTrue(gate.valid_manifest({}))
        self.assertFalse(gate.valid_manifest({PREFIX+'_acceptance':True}))
        self.assertFalse(gate.valid_manifest({PREFIX+'_requested':1}))

    def test_original_positive_gate_can_run_without_policy(self):
        for phase in (0, 1):
            row, capture = positive_fixture(phase); match, packets = matcher(capture)
            self.assertEqual(gate.corroborate(row, match, packets), ([], {0:0, 1:0}))
            proof, _ = positive.corroborate(row, match)
            self.assertEqual(len(proof), 12)
            self.assertFalse(packets)
        gate.validate_rows([{}, {}], False)


if __name__ == '__main__':
    unittest.main()
