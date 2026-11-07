"""Independent finite command/Read byte fixtures, not controller or RF proof.

Uses the actual ACB reassembler and paired evidence verifier. USB bytes, clocks,
owners and the exact-lookup closure are fixtures; no firmware, Native runtime,
credit-return event, negotiated peer or application execution is simulated as
successful. Negotiation/lifetime/owner/receipt checks and residual auditing belong
to the surrounding gate and are deliberately not qualified by these cases.
"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError, reassemble_acb
from ws73_ssap_value import fragment_parts, pair_wire, physical_sends, valid_wire


def fixture(size=2042, sender=0, out_budgets=(254, 254)):
    owners = [dict(owner=dict(index=i, generation=7, bus=1, device=10+i),
                   object=dict(generation=7, lifetime=21+i, handle=3+i)) for i in (0, 1)]
    source, target = owners[sender], owners[1-sender]
    value = bytes((i % 251 for i in range(size)))
    command = b'\x0c\x03\x11\0\0'+value
    read = b'\x08\x03\x11\0\0'
    response = b'\x09\x03'+value
    capture = dict(acb_packets=[], native_events=[])
    group = dict(start_wall_ns=500, end_wall_ns=5000)
    read_window = None
    for n, (origin, destination, pdu) in enumerate(((source, target, command),
                                                   (source, target, read),
                                                   (target, source, response))):
        if n == 1:
            read_window = dict(start_wall_ns=1000+len(capture['acb_packets'])+1,
                               end_wall_ns=group['end_wall_ns'])
        # Fixed independently authored expected SSAP vectors, without invoking
        # the production Rust encoder or the verifier's fragment_parts helper.
        if len(pdu) <= 2042:
            parts = [pdu]
        elif n == 0:
            parts = [b'\x8c\x08\x02\0'+pdu[2:2040],
                     b'\x8c\x02\x02\0'+pdu[2040:]]
        else:
            parts = [b'\x89\0\x02\0'+pdu[2:2040],
                     b'\x89\x02\x02\0'+pdu[2040:]]
        for part in parts:
            frame = b'\x0a\0'+len(part).to_bytes(2, 'little')+part
            for owner, direction in ((origin, 'out'), (destination, 'in')):
                maximum = out_budgets[owner['owner']['index']] if direction == 'out' else 253
                chunks = [frame[start:start+maximum] for start in range(0, len(frame), maximum)]
                for index, chunk in enumerate(chunks):
                    record = len(capture['acb_packets'])+1
                    boundary = 0 if len(chunks) == 1 else 1 if index == 0 else 3 if index == len(chunks)-1 else 2
                    capture['acb_packets'].append(dict(bus=owner['owner']['bus'], device=owner['owner']['device'],
                        handle=owner['object']['handle'], direction=direction, boundary=boundary,
                        data=chunk.hex(), record=record, wall_ns=1000+record))
    packets = reassemble_acb(capture)

    def matched(owner, direction, raw, window):
        found = [p for p in packets if (p['bus'], p['device'], p['handle'], p['direction'], p['data']) ==
                 (owner['owner']['bus'], owner['owner']['device'], owner['object']['handle'], direction, raw.hex())
                 and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
        if len(found) != 1:
            raise CaptureError('one exact retained endpoint packet required by fixture matcher')
        packets.remove(found[0])
        return found[0]

    return dict(ssap_write_command_contract=1), source, target, (command, read, response), group, read_window, matched, packets


def complete(case):
    row, source, target, pdus, group, read_window, matched, _ = case
    return [pair_wire(row, matched, source, target, pdus[0], group),
            pair_wire(row, matched, source, target, pdus[1], read_window),
            pair_wire(row, matched, target, source, pdus[2], read_window)]


class WriteCommandCapture(unittest.TestCase):
    def test_independent_vectors_both_directions_and_per_endpoint_acb_counts(self):
        for sender in (0, 1):
            for size in (0, 32, 2037, 2038, 2042):
                with self.subTest(sender=sender, size=size):
                    case = fixture(size, sender)
                    legs = complete(case)
                    self.assertFalse(case[-1])
                    self.assertTrue(all(valid_wire(leg) for leg in legs))
                    self.assertTrue(all(leg['ssap_write_command_contract'] == 1 for leg in legs))
                    counts = {sender: physical_sends(legs[0]['tx'])+physical_sends(legs[1]['tx']),
                              1-sender: physical_sends(legs[2]['tx'])}
                    if size <= 32:
                        self.assertEqual(counts, {sender: 2, 1-sender: 1})
                    if size == 2042:
                        self.assertEqual(counts, {sender: 11, 1-sender: 10})
                        for side in ('tx', 'rx'):
                            parts = [bytes.fromhex(p['data'])[4:] for p in legs[0][side]['ssap_fragments']]
                            self.assertEqual([len(v) for v in parts], [2042, 11])
                            self.assertEqual([v[:4] for v in parts], [b'\x8c\x08\x02\0', b'\x8c\x02\x02\0'])
                            self.assertEqual(b'\x0c\x03'+b''.join(v[4:] for v in parts), case[3][0])
        case = fixture(out_budgets=(254, 128))
        legs = complete(case)
        self.assertEqual([physical_sends(leg['tx']) for leg in legs], [10, 1, 17])

    def test_short_and_long_commands_cannot_borrow_old_contracts(self):
        for size in (0, 32, 2042):
            for old in ({}, {'ssap_value_lengths_version': 4}, {'ssap_update_delivery_version': 2}):
                case = list(fixture(size)); case[0] = old
                before = copy.deepcopy(case[-1])
                with self.subTest(size=size, old=old), self.assertRaises(CaptureError):
                    complete(case)
                self.assertEqual(case[-1], before)
        for value in (True, False, None, 0, 2, '1'):
            case = list(fixture()); case[0] = dict(ssap_write_command_contract=value)
            with self.subTest(value=value), self.assertRaises(CaptureError):
                complete(case)

    def test_missing_or_wrong_or_duplicate_physical_command_never_matches(self):
        for kind in ('missing-tx', 'missing-rx', 'missing-last', 'wrong-opcode', 'wrong-payload',
                     'wrong-sequence', 'wrong-partial', 'wrong-handle', 'wrong-direction',
                     'double-command', 'late-last', 'early-first', 'reversed-parts'):
            case = fixture(); packets = case[-1]
            first = packets[0]
            last_rx = packets[3]
            if kind == 'missing-tx': packets.pop(0)
            elif kind == 'missing-rx': packets.pop(1)
            elif kind == 'missing-last': packets.pop(3)
            elif kind in ('wrong-opcode', 'wrong-payload', 'wrong-sequence', 'wrong-partial'):
                raw = bytearray.fromhex(first['data'])
                raw[{'wrong-opcode': 4, 'wrong-payload': 20, 'wrong-sequence': 6, 'wrong-partial': 5}[kind]] ^= 1
                first['data'] = raw.hex()
            elif kind == 'wrong-handle': first['handle'] += 1
            elif kind == 'wrong-direction': first['direction'] = 'in'
            elif kind == 'double-command': packets.extend(copy.deepcopy(packets[:4]))
            elif kind == 'late-last': last_rx['wall_ns'] = case[4]['end_wall_ns']+1
            elif kind == 'early-first': first['fragments'][0]['wall_ns'] = case[4]['start_wall_ns']-1
            else:
                packets[2]['fragments'][0]['record'] = 0
            with self.subTest(kind=kind), self.assertRaises(CaptureError):
                complete(case)

    def test_following_read_needs_both_real_legs_and_exact_value(self):
        for kind in ('request-tx', 'request-rx', 'response-tx', 'response-rx', 'value', 'late'):
            case = fixture(32); packets = case[-1]
            if kind in ('request-tx', 'request-rx', 'response-tx', 'response-rx'):
                packets.pop({'request-tx': 2, 'request-rx': 3, 'response-tx': 4, 'response-rx': 5}[kind])
            elif kind == 'value': packets[-1]['data'] = packets[-1]['data'][:-2]+'ff'
            else: packets[-1]['wall_ns'] = case[5]['end_wall_ns']+1
            with self.subTest(kind=kind), self.assertRaises(CaptureError):
                complete(case)

    def test_proof_mutation_rejects_contract_sequence_partial_bytes_time_and_credit_shape(self):
        legs = complete(fixture())
        for kind in ('marker', 'marker-missing', 'expected', 'logical', 'missing-part', 'sequence',
                     'partial', 'PB-data', 'PB-boundary', 'PB-order', 'PB-empty', 'late', 'window'):
            bad = copy.deepcopy(legs[0]); first = bad['rx']['ssap_fragments'][0]
            if kind == 'marker': bad['ssap_write_command_contract'] = True
            elif kind == 'marker-missing': bad.pop('ssap_write_command_contract')
            elif kind == 'expected': bad['expected_pdu'] = '0d'+bad['expected_pdu'][2:]
            elif kind == 'logical': bad['logical_pdu'] = bad['logical_pdu'][:-2]+'ff'
            elif kind == 'missing-part': bad['rx']['ssap_fragments'].pop()
            elif kind in ('sequence', 'partial'):
                raw = bytearray.fromhex(first['data']); raw[6 if kind == 'sequence' else 5] ^= 1; first['data'] = raw.hex()
            elif kind == 'PB-data': first['fragments'][0]['data'] = '00'
            elif kind == 'PB-boundary': first['fragments'][0]['boundary'] = 0
            elif kind == 'PB-order': first['fragments'][1]['record'] = first['fragments'][0]['record']
            elif kind == 'PB-empty': first['fragments'] = []
            elif kind == 'late': first['fragments'][0]['wall_ns'] = bad['capture_window']['end_wall_ns']+1
            else: bad['capture_window']['end_wall_ns'] = bad['capture_window']['start_wall_ns']-1
            with self.subTest(kind=kind):
                self.assertFalse(valid_wire(bad))
        short = complete(fixture(32))[0]
        short.pop('ssap_write_command_contract')
        self.assertFalse(valid_wire(short))

    def test_new_contract_rejects_bad_complete_shapes_before_consuming_capture(self):
        case = fixture()
        row, source, target, pdus, window, _, matched, packets = case
        command = pdus[0]
        bad = (b'\x8c\x08\x02\0', command+b'\0', b'\x0c\x0b'+command[2:],
               b'\x0c\x03\0\0\0', b'\x0c\x03\x11\0\x01',
               b'\x08\x03\x11\0\0\0', b'\x09\x03'+bytes(2043))
        before = copy.deepcopy(packets)
        for raw in bad:
            with self.subTest(raw=raw[:6]), self.assertRaises(CaptureError):
                pair_wire(row, matched, source, target, raw, window)
        self.assertEqual(packets, before)
        with self.assertRaises(CaptureError): fragment_parts(command)
        self.assertEqual(fragment_parts(command, ssap_write_command_contract=1)[0][:4], b'\x8c\x08\x02\0')


if __name__ == '__main__':
    unittest.main()
