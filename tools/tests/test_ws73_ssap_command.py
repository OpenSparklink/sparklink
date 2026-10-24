"""Finite verdict/argument fixtures, never actual SDK, Native or RF qualification.

The production verifier receives independently authored stdout/ACB vectors.
The matcher performs exact original endpoint/window lookup and consumes retained
packets; it is not an always-success transport or protocol dependency.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError, reassemble_acb
import ws73_ssap_command as gate
from ws73_ssap_owned import OUTPUT_MAXIMUM, publisher


def output(record):
    record['output_collection'] = dict(method='bounded-child-pipes', maximum_bytes_per_stream=OUTPUT_MAXIMUM, complete=True)
    record['captured_bytes'] = {k: len(record[k].encode()) for k in ('stdout', 'stderr')}


def credentials():
    return dict(uids=[1000] * 4, capabilities=dict(CapEff='0', CapPrm='0', CapAmb='0', CapInh='0'))


def fixture(phase=0):
    row = dict(phase=phase, start_wall_ns=1, end_wall_ns=3_000_000_000,
        ssap_write_command_required=True, ssap_write_command_contract=1, ssap_exchange_contract=2,
        security_requirement=0, owners=[], ssap_receipts=[], ssap_write_commands=[], ssap_write_command_publishers=[])
    for i in (0, 1):
        base = f'/org/sparklink/slk{i}_g7'
        row['owners'].append(dict(owner=dict(index=i, generation=7, bus=1, device=10+i, path=base),
            object=dict(generation=7, lifetime=21+i, handle=3+i, path=base+f'/peer_t00_01020304050{i}/link_{21+i:016x}')))
        row['ssap_receipts'].append(dict(args=['/bin/slctl'], exit=0,
            stdout=f'SsapExchangeInfo: index={i} generation=7 lifetime={21+i} handle={3+i} local_mtu=2042 negotiated_mtu=2042 request=0207fa07010204000000 peer_reply=0307fa07010204000000 peer_request=0207fa07010204000000 response=0307fa07010204000000\n'))
    capture = dict(acb_packets=[], native_events=[])
    for sender in (0, 1):
        for api in gate.APIS:
            pindex = len(row[gate.COLLECTION]); handle = 17 + pindex
            token = lambda field: hashlib.sha256(f'{phase}/{sender}/{api}/{field}'.encode()).digest()
            owner = dict(sender=sender, target=1-sender, api=api, operations=3, policy='allow',
                handle=handle, start=handle-1, end=handle, secret=token('secret').hex(),
                service=token('service')[:16].hex(), uuid=token('uuid')[:16].hex(),
                exit=0, stderr='', credentials=credentials(), value_snapshots=[])
            target = row['owners'][1-sender]
            owner['args'] = ['/bin/slctl', '--adapter', target['owner']['path'], 'ssap-serve', owner['service'], owner['uuid'], '3', '36', owner['secret'], 'allow']
            owner['stdout'] = f'SsapOwnedService: start={handle-1} end={handle} property={handle}; local registration only\n'
            row[gate.COLLECTION].append(owner)
            before = owner['secret']
            for size in gate.LENGTHS:
                ordinal = len(row['ssap_write_commands']); sequence = phase * 12 + ordinal
                base = phase * 1_000_000_000 + (ordinal+1) * 1_000_000
                payload = (sequence.to_bytes(4, 'little')+(token(str(size))*64)[:size-4]) if size else b''
                value = payload.hex()
                if size == 0:
                    owner['start_wall_ns'] = base-100
                case = dict(sequence=sequence, sender=sender, target=1-sender, api=api,
                    application_bytes=size, handle=handle, publisher=pindex, before=before, value=value,
                    start_wall_ns=base, end_wall_ns=base+700_000, status=gate.STATUS)
                for key, val, start, end in [('local_before', before, base+1, base+2),
                                           ('local_after', value, base+600_000, base+600_001)]:
                    snap = dict(handle=handle, value=val, start_wall_ns=start, end_wall_ns=end,
                        start_monotonic_ns=start, end_monotonic_ns=end, ordinal=len(owner['value_snapshots'])+1)
                    case[key] = snap; owner['value_snapshots'].append(snap)
                for write in ('true', 'false'):
                    request = len(owner['value_snapshots'])-1 + (write=='false')
                    owner['stdout'] += f'SsapAuthorizationDecision: request={request} property={handle} data_type=0 write={write} security=0 approved=true; local policy only\n'
                for key in ('local_before', 'local_after'):
                    owner['stdout'] += f'SsapOwnedValue: handle={handle} value={case[key]["value"]}\n'
                barrier = dict(stage='ssap_command_start_barrier', api=api, deadline_ns=base+5_000_000, client_closed=True)
                receipt = dict(api=api, handle=handle, value=value, minimum=0, admission_only=True,
                    peer_delivery_confirmed=False, deadline_ns=barrier['deadline_ns'], call_ns=base+6, returned_ns=base+90_000)
                app = dict(api=api, args=gate.command_arguments(api, row['owners'][sender], handle, value),
                    environment=gate.application_environment(), credentials=credentials(), exit=0, stderr='',
                    stdout=json.dumps(barrier)+'\nSSAP_COMMAND_ADMITTED: '+json.dumps(receipt)+'\n',
                    start_wall_ns=base+3, end_wall_ns=base+100_000, barrier_wall_ns=base+4, release_wall_ns=base+5,
                    start_monotonic_ns=base+3, barrier_monotonic_ns=base+4, release_monotonic_ns=base+5)
                output(app); case['command'] = app
                source = row['owners'][sender]
                case['read'] = dict(args=['/bin/slctl', '--adapter', source['owner']['path'], 'ssap-read', source['object']['path'], str(handle), '0'],
                    exit=0, stderr='', credentials=credentials(), start_wall_ns=base+100_001, end_wall_ns=base+500_000,
                    stdout=f'Selected {source["owner"]["path"]}\nSsapPeerValue: operation=ssap-read path={source["object"]["path"]} handle={handle} value={value}\n')
                row['ssap_write_commands'].append(case); before = value
                pdus = [b'\x0c\x03'+handle.to_bytes(2, 'little')+b'\0'+payload,
                        b'\x08\x03'+handle.to_bytes(2, 'little')+b'\0', b'\x09\x03'+payload]
                for n, (origin, destination, pdu) in enumerate(((source, target, pdus[0]), (source, target, pdus[1]), (target, source, pdus[2]))):
                    if len(pdu) <= 2042:
                        parts = [pdu]
                    else:
                        parts = [bytes([0x8c if n==0 else 0x89, 8 if n==0 else 0, 2, 0])+pdu[2:2040],
                                 bytes([0x8c if n==0 else 0x89, 2, 2, 0])+pdu[2040:]]
                    for part in parts:
                        frame = b'\x0a\0'+len(part).to_bytes(2, 'little')+part
                        for endpoint, direction in ((origin, 'out'), (destination, 'in')):
                            chunks = [frame[i:i+253] for i in range(0, len(frame), 253)]
                            for index, chunk in enumerate(chunks):
                                rec = len(capture['acb_packets'])+1
                                boundary = 0 if len(chunks)==1 else 1 if index==0 else 3 if index==len(chunks)-1 else 2
                                # The peer command RX deliberately follows the sender admission return.
                                stamp = base + (150_000 if n==0 and direction=='in' else (50_000, 200_000, 300_000)[n]) + rec
                                capture['acb_packets'].append(dict(bus=1, device=endpoint['owner']['device'], handle=endpoint['object']['handle'],
                                    direction=direction, boundary=boundary, data=chunk.hex(), record=rec, wall_ns=stamp))
            owner['end_wall_ns'] = base+700_100
            owner['removal'] = dict(exit=0, stdout='SsapLocalServices: []\n', stderr='', start_wall_ns=base+700_010, end_wall_ns=base+700_020)
            output(owner)
    return row, capture


def matcher(capture):
    packets = reassemble_acb(capture)
    def match(entry, direction, frame, window):
        wanted = entry['owner']['bus'], entry['owner']['device'], entry['object']['handle'], direction, frame.hex()
        found = [p for p in packets if (p['bus'], p['device'], p['handle'], p['direction'], p['data']) == wanted
                 and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
        if len(found) != 1:
            raise CaptureError('one exact fixture endpoint packet inside original window required')
        packets.remove(found[0]); return found[0]
    return match, packets


class CommandGate(unittest.TestCase):
    def test_boot_and_raw_row_selectors_cannot_smuggle_unrequested_evidence(self):
        self.assertFalse(gate.boot_requested(['console=ttyS0']))
        self.assertTrue(gate.boot_requested(['console=ttyS0', 'ws73.ssap_write_command=1']))
        for tokens in (['ws73.ssap_write_command'], ['ws73.ssap_write_command=0'],
                       ['ws73.ssap_write_command=2'], ['ws73.ssap_write_command='],
                       ['ws73.ssap_write_command=1'] * 2,
                       ['ws73.ssap_write_command=1', 'ws73.ssap_write_command=0'],
                       'ws73.ssap_write_command=1', [1]):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                gate.boot_requested(tokens)
        rows = [fixture(phase)[0] for phase in (0, 1)]
        gate.validate_rows(rows, True)
        gate.validate_rows([{}, {'ssap_write_command_required': False}], False)
        for name in ('missing-phase', 'phase', 'typed-phase', 'typed-request', 'required',
                     'version', 'missing-contract', 'missing-case', 'missing-publisher', 'unrequested'):
            bad = copy.deepcopy(rows); requested = True
            if name == 'missing-phase': bad.pop()
            elif name == 'phase': bad[1]['phase'] = 0
            elif name == 'typed-phase': bad[1]['phase'] = True
            elif name == 'typed-request': requested = 1
            elif name == 'required': bad[0]['ssap_write_command_required'] = 1
            elif name == 'version': bad[0]['ssap_write_command_contract'] = True
            elif name == 'missing-contract': del bad[0]['ssap_write_command_contract']
            elif name == 'missing-case': bad[0]['ssap_write_commands'].pop()
            elif name == 'missing-publisher': bad[0][gate.COLLECTION].pop()
            else: requested = False
            with self.subTest(name=name), self.assertRaises(CaptureError):
                gate.validate_rows(bad, requested)
        for key in ('ssap_write_command_contract', 'ssap_write_commands', 'ssap_write_command_proof'):
            with self.subTest(key=key), self.assertRaises(CaptureError):
                gate.validate_rows([{key: None}], False)

    def test_manifest_requires_original_selection_and_complete_paired_proof(self):
        proof = dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED', proofs=[])
        for phase in (0, 1):
            row, capture = fixture(phase)
            commands, _ = gate.corroborate(row, matcher(capture)[0])
            proof['proofs'].append(dict(phase=phase, owners=row['owners'], ssap_write_commands=commands))
        record = dict(ssap_write_command_requested=True, ssap_write_command_contract_version=1,
            ssap_write_command_acceptance=True, status='PASSTHROUGH_SUPPORT_PASS', qemu_exit=0,
            ordinary_channel_socket_acceptance=True, qemu_args=['qemu', '-append', 'ws73.ssap_write_command=1'],
            channel_socket_corroboration=proof)
        self.assertTrue(gate.valid_manifest(record))
        self.assertTrue(gate.valid_manifest({}))
        self.assertTrue(gate.valid_manifest(dict(ssap_write_command_requested=False, ssap_write_command_acceptance=False)))
        for name in ('request', 'missing-boot', 'duplicate-boot', 'unknown-boot', 'acceptance', 'version',
                     'status', 'qemu', 'typed-qemu', 'socket', 'missing-proof', 'missing-rx', 'unselected'):
            bad = copy.deepcopy(record)
            if name == 'request': bad['ssap_write_command_requested'] = 1
            elif name == 'missing-boot': bad['qemu_args'] = []
            elif name == 'duplicate-boot': bad['qemu_args'][-1] += ' ws73.ssap_write_command=1'
            elif name == 'unknown-boot': bad['qemu_args'][-1] = 'ws73.ssap_write_command=2'
            elif name == 'acceptance': bad['ssap_write_command_acceptance'] = 1
            elif name == 'version': bad['ssap_write_command_contract_version'] = True
            elif name == 'status': bad['status'] = 'SUPPORT_PASS'
            elif name == 'qemu': bad['qemu_exit'] = 1
            elif name == 'typed-qemu': bad['qemu_exit'] = False
            elif name == 'socket': bad['ordinary_channel_socket_acceptance'] = False
            elif name == 'missing-proof': bad['channel_socket_corroboration']['proofs'].pop()
            elif name == 'missing-rx': del bad['channel_socket_corroboration']['proofs'][0]['ssap_write_commands'][0]['wire'][0]['rx']
            else: bad['ssap_write_command_requested'] = False; bad['qemu_args'] = []
            with self.subTest(name=name): self.assertFalse(gate.valid_manifest(bad))
        for bad in (dict(ssap_write_command_acceptance=True), dict(ssap_write_command_contract_version=None),
                    dict(channel_socket_corroboration=dict(proofs=[dict(ssap_write_commands=[])])),
                    dict(ssap_write_command_requested=0), dict(qemu_args=['ws73.ssap_write_command=0'])):
            with self.subTest(bad=bad): self.assertFalse(gate.valid_manifest(bad))

    def test_complete_two_phase_matrix_preserves_late_peer_rx_and_all_sends(self):
        result = dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED', proofs=[])
        for phase in (0, 1):
            row, capture = fixture(phase); match, packets = matcher(capture)
            proof, credit = gate.corroborate(row, match)
            self.assertEqual(len(proof), 12); self.assertFalse(packets)
            self.assertEqual(credit, {0: 54, 1: 54})
            result['proofs'].append(dict(phase=phase, owners=row['owners'], ssap_write_commands=proof))
        self.assertTrue(gate.valid_summary(result))
        for name in ('missing', 'api', 'value', 'owner', 'wire', 'version', 'admission', 'source',
                     'wire-owner', 'fragment-owner', 'wire-direction', 'typed-wire-owner'):
            bad=copy.deepcopy(result); item=bad['proofs'][0]['ssap_write_commands'][1]
            if name=='missing':bad['proofs'][1]['ssap_write_commands'].pop()
            elif name=='api':item['api']='python'
            elif name=='value':item['value']='00'*32
            elif name=='owner':item['owner_value']=''
            elif name=='wire':item['wire'].pop()
            elif name=='version':item['contract']=True
            elif name=='admission':item['admission']['peer_delivery_confirmed']=True
            elif name=='wire-owner':item['wire'][0]['rx']['device']+=1
            elif name=='fragment-owner':item['wire'][0]['rx']['fragments'][0]['handle']+=1
            elif name=='wire-direction':item['wire'][0]['tx']['direction']='in'
            elif name=='typed-wire-owner':item['wire'][0]['tx']['bus']=True
            else:item['source']['lifetime']+=1
            with self.subTest(name=name):self.assertFalse(gate.valid_summary(bad))

    def test_missing_and_modified_materials_cannot_pass(self):
        for name in ('missing-case','wrong-api','wrong-process-api','version','no-negotiation','uid','dirty-output',
                     'deadline','barrier','payload','owner-before','owner-after','read','opcode','missing-rx',
                     'duplicate-tx','late-rx','lifetime','wrong-publisher','lost-policy','retired-removal','group-overlap'):
            row, capture=fixture(); case=row['ssap_write_commands'][1]; app=case['command']
            if name=='missing-case':row['ssap_write_commands'].pop()
            elif name=='wrong-api':case['api']='python'
            elif name=='wrong-process-api':app['api']='python'
            elif name=='version':row['ssap_write_command_contract']=True
            elif name=='no-negotiation':row['ssap_receipts'][0]['stdout']=row['ssap_receipts'][0]['stdout'].replace('04000000','00000000')
            elif name=='uid':app['credentials']['uids']=[0]*4
            elif name=='dirty-output':app['output_collection']['complete']=False
            elif name=='deadline':app['release_monotonic_ns']+=6_000_000_000
            elif name=='barrier':app['stdout']=app['stdout'].replace('client_closed": true','client_closed": false');output(app)
            elif name=='payload':case['value']='ab'*32
            elif name=='owner-before':case['local_before']['value']='12'
            elif name=='owner-after':case['local_after']['value']='12'
            elif name=='read':case['read']['stdout']=case['read']['stdout'].replace('SsapPeerValue','SsapCommandAdmission')
            elif name=='opcode':capture['acb_packets'][0]['data']=capture['acb_packets'][0]['data'].replace('0c03','0d03')
            elif name=='missing-rx':capture['acb_packets'].pop(1)
            elif name=='duplicate-tx':capture['acb_packets'].append(copy.deepcopy(capture['acb_packets'][0]))
            elif name=='late-rx':capture['acb_packets'][1]['wall_ns']=row['end_wall_ns']+1
            elif name=='lifetime':row['owners'][0]['object']['generation']=8
            elif name=='wrong-publisher':case['publisher']=2
            elif name=='lost-policy':row[gate.COLLECTION][0]['stdout']=row[gate.COLLECTION][0]['stdout'].replace('approved=true','approved=false');output(row[gate.COLLECTION][0])
            elif name=='retired-removal':row[gate.COLLECTION][0]['removal']['stdout']='SsapLocalServices: [[16,17]]\n'
            else:case['start_wall_ns']=row['ssap_write_commands'][0]['start_wall_ns']
            with self.subTest(name=name),self.assertRaises((CaptureError, ValueError, KeyError)):
                gate.corroborate(row,matcher(capture)[0])

    def test_summary_numeric_contract_rejects_boolean_integer_aliases(self):
        summary = dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED', proofs=[])
        for phase in (0, 1):
            row, capture = fixture(phase)
            proof, _ = gate.corroborate(row, matcher(capture)[0])
            summary['proofs'].append(dict(phase=phase, owners=row['owners'], ssap_write_commands=proof))
        self.assertTrue(gate.valid_summary(summary))
        for key in ('phase', 'sequence', 'sender', 'target', 'application_bytes', 'uid'):
            bad = copy.deepcopy(summary)
            bad['proofs'][0]['ssap_write_commands'][0][key] = False
            with self.subTest(key=key): self.assertFalse(gate.valid_summary(bad))
        for section, key in (('source', 'index'), ('source', 'generation'), ('destination', 'bus'),
                             ('admission', 'minimum'), ('admission', 'deadline_ns'),
                             ('admission', 'call_ns'), ('admission', 'returned_ns')):
            bad = copy.deepcopy(summary)
            bad['proofs'][0]['ssap_write_commands'][0][section][key] = key not in ('index', 'minimum')
            with self.subTest(section=section, key=key): self.assertFalse(gate.valid_summary(bad))
        bad = copy.deepcopy(summary); bad['proofs'][0]['phase'] = False
        self.assertFalse(gate.valid_summary(bad))

    def test_selector_fails_closed_and_keeps_old_mode_unselected(self):
        self.assertFalse(gate.requested(SimpleNamespace()))
        args=dict(ssap_write_command_verify=True, channel_socket_verify=True, passthrough=True)
        self.assertTrue(gate.validate(SimpleNamespace(**args)))
        for changes in (dict(ssap_write_command_verify=1),dict(passthrough=False),dict(channel_socket_bytes=2042),
                        dict(channel_socket_rounds=20),dict(ssap_value_lengths_verify=True),dict(security_agent='numeric-approve')):
            with self.subTest(changes=changes),self.assertRaises(ValueError):gate.requested(SimpleNamespace(**(args|changes)))

    def test_publisher_operations_reject_incompatible_modes_before_any_spawn(self):
        for options in (dict(operations=True),dict(operations=7),dict(operations=3,sdk_api='c')):
            with patch('ws73_ssap_owned.observed_process') as spawn,self.subTest(options=options):
                with self.assertRaises(CaptureError):
                    with publisher(None,None,0,'allow',**options):pass
                spawn.assert_not_called()


if __name__=='__main__':unittest.main()
