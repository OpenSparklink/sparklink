# SPDX-License-Identifier: GPL-2.0-only
"""Independent evidence fixtures; these tests do not qualify a VM or device."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from ws73_application_client import application_environment, ssap_commands
from ws73_capture import CaptureError, reassemble_acb
from ws73_ssap_owned import OUTPUT_MAXIMUM
import ws73_ssap_read_provider as gate


class PublisherCredentials(unittest.TestCase):
    def test_actual_collector_records_and_rejects_inheritable_capabilities(self):
        # Exercise the real shared collector. A missing field is not evidence
        # of zero, even when all three historically recorded sets are empty.
        from ws73_channel_socket import credentials
        base = 'Uid:\t1000\t1000\t1000\t1000\nCapEff:\t0\nCapPrm:\t0\nCapAmb:\t0\n'
        with patch.object(Path, 'read_text', return_value=base+'CapInh:\t0\n'):
            value = credentials(17)
        self.assertEqual(value['capabilities'],
                         dict(CapEff='0', CapPrm='0', CapAmb='0', CapInh='0'))
        with patch.object(Path, 'read_text', return_value=base+'CapInh:\t1\n'):
            with self.assertRaises(CaptureError): credentials(17)
        with patch.object(Path, 'read_text', return_value=base):
            with self.assertRaises(KeyError): credentials(17)


def fixture(phase=0):
    owners = [dict(owner=dict(index=i, generation=4, bus=1, device=10+i, path=f'/a{i}'),
                   object=dict(generation=4, lifetime=100+phase*2+i, handle=3+i,
                               path=f'/a{i}/peer_0/link_{100+phase*2+i}')) for i in (0, 1)]
    row = dict(phase=phase, owners=owners, ssap_receipts=[dict(args=['slctl'])],
               ssap_owned_required=True,
               ssap_owned=[dict(sender=s, policy=p) for s in (0, 1) for p in ('allow', 'deny')],
               ssap_read_provider_required=True, ssap_read_provider_version=1,
               ssap_read_provider_tools={}, ssap_read_provider_cases=[])
    capture = dict(acb_packets=[], native_events=[])
    for sender in (0, 1):
        target = 1-sender; source = owners[sender]; dest = owners[target]
        seed = lambda name: hashlib.sha256(f'{phase}/{sender}/{name}'.encode()).hexdigest()
        value, secret, service, uuid = seed('dynamic'), seed('secret'), seed('service')[:32], seed('uuid')[:32]
        h = 17; base = 100000*(phase+1)+10000*sender
        stamp = lambda n: base+n*100
        mono = 1_000_000_000+phase*1_000_000+sender*10000
        data = dict(token=1, request=9, index=target, generation=4, lifetime=dest['object']['lifetime'],
                    handle=dest['object']['handle'], epoch=41, security=0, local_tcid=10,
                    remote_tcid=10, pi=0, property=h, deadline_ns=mono+5_000_000_000, maximum_bytes=2042)
        line = ('SsapReadProviderPrompt: token=p1 request=9 '
                f'index={target} generation=4 lifetime={data["lifetime"]} handle={data["handle"]} '
                f'epoch=41 security=0 local_tcid=10 remote_tcid=10 pi=0 property=17 deadline_ns={data["deadline_ns"]} '
                "maximum_bytes=2042; answer 'provide p1 HEX' ('-' for empty) or 'provider-error p1 AF..FF'")
        stdout = ('SsapOwnedService: start=16 end=17 property=17; local registration only\n'
                  'SsapReadProviderBound: handle=17; stored value discarded, no rebind or fallback\n'
                  'SsapAuthorizationDecision: request=9 property=17 data_type=0 write=false security=0 approved=true; local policy only\n'
                  +line+'\n')
        api = 'c' if (phase+sender)%2 == 0 else 'python'
        prefix = ['/bin/ws73-application-client-c'] if api == 'c' else ['/bin/python3', '/usr/share/sparklink/tools/ws73-application-client.py']
        path = source['object']['path']
        credentials = dict(uids=[1000]*4, capabilities={k:'0' for k in ('CapEff', 'CapPrm', 'CapAmb', 'CapInh')})
        app = dict(api=api, exit=0, stderr='', environment=application_environment(), credentials=copy.deepcopy(credentials),
                   args=prefix+['ssap', str(sender), '4', path, 'ssap-read', '17', value],
                   ssap_operation='ssap-read', ssap_path=path, ssap_handle=h, ssap_expected=value,
                   start_wall_ns=stamp(4), ssap_released_wall_ns=stamp(6), end_wall_ns=stamp(10),
                   ssap_release_monotonic_ns=mono,
                   stdout=json.dumps(dict(stage='ssap_start_barrier', api=api, client_closed=True))+'\n'
                       +f'SsapPeerValue: operation=ssap-read path={path} handle=17 value={value}\n')
        removed = dict(args=['slctl', '--adapter', source['owner']['path'], 'ssap-read', path, str(h), '0'],
                       exit=1, stderr='peer read error 4', stdout='', start_wall_ns=stamp(14), end_wall_ns=stamp(16))
        item = dict(sender=sender, target=target, policy='allow', operations=1, start=16, end=17, handle=h,
                    pid=200+sender, bytes=32, dynamic_value=value, secret=secret, value=seed('unused'), uuid=uuid, service=service,
                    args=['slctl', '--adapter', dest['owner']['path'], 'ssap-serve', service, uuid, '1', '36', secret, 'allow'],
                    start_wall_ns=stamp(1), prepared_wall_ns=stamp(2), bound_wall_ns=stamp(3),
                    quit_wall_ns=stamp(11), owner_exit_wall_ns=stamp(12), end_wall_ns=stamp(17),
                    exit=0, stderr='', stdout=stdout, credentials=credentials,
                    output_collection=dict(method='bounded-child-pipes', maximum_bytes_per_stream=OUTPUT_MAXIMUM, complete=True),
                    captured_bytes=dict(stdout=len(stdout.encode()), stderr=0),
                    callback=dict(prompt=data, publisher_pid=200+sender, observed_wall_ns=stamp(7), replied_wall_ns=stamp(8),
                                  observed_monotonic_ns=mono+100, replied_monotonic_ns=mono+200,
                                  reply_before_wall_ns=stamp(7)+50, reply_before_monotonic_ns=mono+150,
                                  supervisor_deadline_ns=mono+7_000_000_000),
                    reply_command='provide p1 '+value, read=app, retired_read=removed,
                    cleanup=dict(args=['slctl', '--adapter', dest['owner']['path'], 'ssap-list'],
                                 exit=0, stderr='', stdout='SsapLocalServices: []\n',
                                 start_wall_ns=stamp(13), end_wall_ns=stamp(13)+1))
        row['ssap_read_provider_cases'].append(item)
        for window, response in [(app, b'\x09\x03'+bytes.fromhex(value)), (removed, b'\x09\x0b\x04\0')]:
            request = b'\x08\x03\x11\0\0'
            for a, b, pdu in [(sender, target, request), (target, sender, response)]:
                frame = b'\x0a\0'+len(pdu).to_bytes(2, 'little')+pdu
                for endpoint, direction in [(a, 'out'), (b, 'in')]:
                    record = len(capture['acb_packets'])+1
                    wall_ns = stamp(9)+record if window is app and a == target else window['start_wall_ns']+record
                    capture['acb_packets'].append(dict(bus=1, device=10+endpoint,
                        handle=3+endpoint, direction=direction, data=frame.hex(), boundary=0,
                        record=record, wall_ns=wall_ns))
    packets = reassemble_acb(capture)
    def matched(owner, direction, frame, window):
        key = (owner['owner']['bus'], owner['owner']['device'], owner['object']['handle'], direction, frame.hex())
        found = [p for p in packets if tuple(p[k] for k in ('bus', 'device', 'handle', 'direction', 'data')) == key
                 and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
        if len(found) != 1:
            raise CaptureError('one exact original fixture leg required')
        packets.remove(found[0]); return found[0]
    return row, matched, packets


def summary():
    rows = []
    for phase in (0, 1):
        row, match, packets = fixture(phase)
        providers, credit = gate.corroborate(row, match)
        assert not packets and credit == {0:4, 1:4}
        rows.append(dict(phase=phase, owners=row['owners'], ssap_read_providers=providers))
    return dict(proofs=rows)


class ReadProviderEvidence(unittest.TestCase):
    def test_explicit_selector_requires_owned_dedicated_original_workload(self):
        good = dict(ssap_read_provider_verify=True, passthrough=True, ssap_owned_verify=True,
                    channel_socket_verify=True, channel_socket_rounds=4, channel_socket_bytes=61)
        self.assertTrue(gate.requested(SimpleNamespace(**good)))
        self.assertFalse(gate.requested(SimpleNamespace()))
        for key, value in [('ssap_read_provider_verify', 1), ('ssap_owned_verify', False),
                           ('passthrough', False), ('channel_socket_rounds', 5), ('channel_socket_bytes', 32),
                           ('ssap_description_verify', True), ('security_agent', 'numeric-approve')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.requested(SimpleNamespace(**dict(good, **{key:value})))
        self.assertTrue(gate.boot_requested([gate.TOKEN, 'ws73.ssap_owned=1']))
        for tokens in [[gate.TOKEN], [gate.TOKEN, gate.TOKEN, 'ws73.ssap_owned=1'],
                       ['ws73.ssap_read_provider=0'], ['ws73.ssap_read_provider']]:
            with self.subTest(tokens=tokens), self.assertRaises(ValueError): gate.boot_requested(tokens)

    def test_original_two_phases_and_base_owned_matrix_are_required(self):
        rows = [fixture(phase)[0] for phase in (0, 1)]
        gate.validate_rows(rows, True)
        for change in ('base', 'cases', 'version', 'phase', 'selected'):
            bad = copy.deepcopy(rows)
            if change == 'base': bad[0]['ssap_owned'].pop()
            elif change == 'cases': bad[0]['ssap_read_provider_cases'].pop()
            elif change == 'version': bad[0]['ssap_read_provider_version'] = True
            elif change == 'phase': bad[0]['phase'] = True
            else: bad[0]['ssap_read_provider_required'] = False
            with self.subTest(change=change), self.assertRaises(CaptureError): gate.validate_rows(bad, True)
        with self.assertRaises(CaptureError): gate.validate_rows(rows, False)

    def test_actual_reassembler_evidence_and_both_language_roles_replay(self):
        proof = summary()
        self.assertTrue(gate.valid_summary(proof))
        self.assertEqual([[p['api'] for p in r['ssap_read_providers']] for r in proof['proofs']],
                         [['c', 'python'], ['python', 'c']])

    def test_missing_or_modified_application_callback_owner_or_usb_evidence_fails(self):
        cases = ('missing-peer', 'payload', 'pid', 'lifetime', 'deadline', 'token', 'approval',
                 'no-bound', 'stored', 'read-failed', 'cleanup', 'exit', 'capability', 'foreign-fragment',
                 'bool-time', 'bool-prompt', 'late-reply', 'repeat-prompt', 'order', 'partial-output',
                 'missing-caps', 'early-cleanup', 'foreign-cleanup', 'foreign-retired', 'registration',
                 'request-after-callback', 'response-before-answer')
        for kind in cases:
            row, matched, packets = fixture(); item = row['ssap_read_provider_cases'][0]
            if kind == 'missing-peer': packets.pop(0)
            elif kind == 'payload': item['read']['ssap_expected'] = '11'*32
            elif kind == 'pid': item['callback']['publisher_pid'] += 1
            elif kind == 'lifetime': item['callback']['prompt']['lifetime'] += 1
            elif kind == 'deadline': item['callback']['supervisor_deadline_ns'] += 1
            elif kind == 'token': item['reply_command'] = 'provide p2 '+item['dynamic_value']
            elif kind == 'approval': item['stdout'] = item['stdout'].replace('approved=true', 'approved=false')
            elif kind == 'no-bound': item['stdout'] = item['stdout'].replace('SsapReadProviderBound:', 'missing:')
            elif kind == 'stored': item['dynamic_value'] = item['secret']
            elif kind == 'read-failed': item['read']['exit'] = 1
            elif kind == 'cleanup': item['cleanup']['stdout'] = 'SsapLocalServices: [[16]]\n'
            elif kind == 'exit': item['exit'] = -9
            elif kind == 'capability': item['credentials']['capabilities']['CapEff'] = '1'
            elif kind == 'foreign-fragment': packets[0]['fragments'][0]['device'] = 99
            elif kind == 'bool-time': item['prepared_wall_ns'] = True
            elif kind == 'bool-prompt': item['callback']['prompt']['token'] = True
            elif kind == 'late-reply': item['callback']['replied_monotonic_ns'] = item['callback']['prompt']['deadline_ns']
            elif kind == 'repeat-prompt': item['stdout'] += next(l for l in item['stdout'].splitlines() if l.startswith('SsapReadProviderPrompt:'))+'\n'
            elif kind == 'order': item['bound_wall_ns'] = item['read']['end_wall_ns']
            elif kind == 'missing-caps': item['credentials']['capabilities'] = {}
            elif kind == 'early-cleanup': item['cleanup']['start_wall_ns'] = item['bound_wall_ns']
            elif kind == 'foreign-cleanup': item['cleanup']['args'][2] = '/foreign'
            elif kind == 'foreign-retired': item['retired_read']['args'][4] = '/foreign/link'
            elif kind == 'registration': item['stdout'] = item['stdout'].replace('start=16', 'start=15')
            elif kind in ('request-after-callback', 'response-before-answer'):
                packet = packets[1 if kind == 'request-after-callback' else 2]
                wall = item['callback']['observed_wall_ns']+1 if kind == 'request-after-callback' else item['callback']['reply_before_wall_ns']-1
                packet['wall_ns'] = wall
                for fragment in packet['fragments']: fragment['wall_ns'] = wall
            else: item['output_collection']['complete'] = False
            item['captured_bytes']['stdout'] = len(item['stdout'].encode())
            with self.subTest(kind=kind), self.assertRaises((CaptureError, ValueError)):
                gate.corroborate(row, matched)

    def test_manifest_cannot_upgrade_pending_or_skip_base_acceptance(self):
        record = dict(ssap_read_provider_requested=True, ssap_read_provider_version=1,
                      ssap_read_provider_acceptance=True, ssap_owned_acceptance=True,
                      ordinary_channel_socket_acceptance=True, status='PASSTHROUGH_SUPPORT_PASS', qemu_exit=0,
                      qemu_args=[gate.TOKEN+' ws73.ssap_owned=1'], channel_socket_corroboration=summary())
        self.assertTrue(gate.valid_manifest(record))
        for key, value in [('ssap_owned_acceptance', False), ('ssap_read_provider_acceptance', False),
                           ('qemu_exit', True), ('status', gate.PENDING)]:
            with self.subTest(key=key): self.assertFalse(gate.valid_manifest(dict(record, **{key:value})))
        corrupted = copy.deepcopy(record)
        corrupted['channel_socket_corroboration']['proofs'][0]['ssap_read_providers'][0]['wire'][0]['rx']['data'] = '00'
        self.assertFalse(gate.valid_manifest(corrupted))

    def test_after_start_hook_rejects_unbounded_or_paired_use_before_launch(self):
        for calls, callback in [([None], 1), ([None, None], lambda app, deadline: None)]:
            with self.assertRaises(CaptureError): ssap_commands(None, None, calls, after_start=callback)


if __name__ == '__main__':
    unittest.main()
