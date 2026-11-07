# SPDX-License-Identifier: GPL-2.0-only
"""Actual cleanup evidence functions with synthetic CLI/USB byte fixtures.

No successful dependency stub replaces the production decoder or journal.
These tests establish neither actual USB/firmware behavior, VM ownership,
filesystem crash durability, protocol drain nor successful restoration.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_address_cleanup import inspect_setup, material, terminal_setters
from ws73_capture import CaptureError
from ws73_runtime_address import corroborate
from test_ws73_runtime_address import ADDRESSES, fixture, stage_record
from test_ws73_north_star import aggregate, command_payload, pcap


def partial(count=1):
    record, capture = fixture()
    record.update(status='FAIL', setters=[])
    record['commands'] = record['commands'][:2+count*3]
    end = record['commands'][-1]['end_wall_ns']
    for key in ('commands', 'complete'):
        capture[key] = [v for v in capture[key] if v['wall_ns'] <= end]
    capture['failures'] = []
    return record, capture


def raw_fixture(record, capture):
    """Use existing test-only HCC/pcap encoders; production read_capture parses."""
    record = copy.deepcopy(record)
    for row in record['commands']:
        row['start_wall_ns'] *= 1_000_000
        row['end_wall_ns'] *= 1_000_000
    records = []
    for command in capture['commands']:
        reply = next(v for v in capture['complete'] if v['record'] == command['record']+1)
        wire = command_payload(command['opcode'], bytes.fromhex(command['params']))
        bus, device, start = command['bus'], command['device'], command['wall_ns']*1_000_000
        value = bytes.fromhex(reply['value'])
        complete = (b'\xa2\x02\x00' + (4+len(value)).to_bytes(2, 'little')
                    + command['opcode'].to_bytes(2, 'little') + b'\x01\x00' + value)
        records.extend([(bus, device, start, wire, 'S', 1, -115),
                        (bus, device, start+1_000_000, wire, 'C', 1, 0),
                        (bus, device, start+2_000_000, aggregate(complete), 'C', 0x81, 0)])
    return record, pcap(records, nano=True), len(records)


class TerminalSetterEvidence(unittest.TestCase):
    def test_zero_one_two_setters_and_summary_append_loss_never_award_restoration(self):
        for count in (0, 1, 2):
            with self.subTest(count=count):
                record, capture = partial(count)
                before = copy.deepcopy((record, capture))
                proof = terminal_setters(record, capture, ADDRESSES)
                self.assertEqual(len(proof['terminal_setters']), count)
                self.assertEqual(proof['classification'], 'ALL_OBSERVED_SETTERS_COMPLETE_AND_READ_BACK'
                                 if count else 'NO_SETTER_OBSERVED')
                for field in ('restoration_confirmed', 'firmware_drain_proved', 'original_request_deadline_qualified'):
                    self.assertIs(proof[field], False)
                self.assertEqual((record, capture), before)
                with self.assertRaises(CaptureError):
                    corroborate(record, capture, ADDRESSES)  # Original success verifier stays strict.

    def test_later_cli_failure_keeps_proven_physical_setter_and_original_failure(self):
        record, capture = partial()
        record['commands'][3].update(exit=1, stderr='fixture lease cleanup failed')
        proof = terminal_setters(record, capture, ADDRESSES)
        self.assertEqual(proof['terminal_setters'][0]['cli_exit'], 1)
        self.assertEqual(record['status'], 'FAIL')

    def test_unknown_missing_or_misassociated_evidence_is_not_eligible(self):
        changes = {
            'timeout': lambda r, c: r['commands'][3].update(timed_out=True, physical_outcome='unknown'),
            'missing-exit': lambda r, c: r['commands'][3].pop('exit'),
            'unfinished': lambda r, c: r['commands'][3].pop('end_wall_ns'),
            'no-progress-attempt': lambda r, c: r['commands'].pop(3),
            'no-out': lambda r, c: c['commands'].pop(4),
            'no-complete': lambda r, c: c['complete'].pop(4),
            'failed-complete': lambda r, c: c['complete'][4].update(status=1),
            'late-extra-complete': lambda r, c: c['complete'].append(dict(c['complete'][4], record=999, wall_ns=900)),
            'missing-readback': lambda r, c: c['complete'].pop(5),
            'wrong-readback': lambda r, c: c['complete'][5].update(value='00'*6),
            'wrong-original': lambda r, c: c['complete'][0].update(value='00'*6),
            'wrong-params': lambda r, c: c['commands'][4].update(params='00'*6),
            'wrong-generation': lambda r, c: r['owners'][0].update(generation=999),
            'repeated-index': lambda r, c: r['owners'][1].update(index=r['owners'][0]['index']),
            'repeated-usb': lambda r, c: r['owners'][1].update(device=r['owners'][0]['device']),
            'wrong-model': lambda r, c: r['owners'][0]['hcc_chip'].update(model='U'),
            'wrong-cli-value': lambda r, c: r['commands'][3]['args'].__setitem__(-1, ADDRESSES[1]),
            'overlapping-rows': lambda r, c: r['commands'][3].update(start_wall_ns=301),
            'lost-peer-query': lambda r, c: r['commands'].pop(),
            'changed-peer': lambda r, c: c['complete'][-1].update(value='00'*6),
            'peer-query-failed': lambda r, c: r['commands'][-1].update(exit=1),
            'usb-failure': lambda r, c: c['failures'].append(dict(status=-110)),
            'foreign-command': lambda r, c: c['commands'].append(dict(c['commands'][0], device=99)),
            'rf-command': lambda r, c: c['commands'].append(dict(c['commands'][0], opcode=0x0c05)),
            'unknown-status': lambda r, c: r.update(status='PASS'),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                record, capture = partial(); change(record, capture)
                before = copy.deepcopy((record, capture))
                with self.assertRaises((ValueError, KeyError, IndexError)):
                    terminal_setters(record, capture, ADDRESSES)
                self.assertEqual((record, capture), before)

    def test_extra_attempt_without_wire_or_reused_registration_rejected(self):
        for count in (0, 1):
            record, capture = partial(count)
            attempt = copy.deepcopy(fixture()[0]['commands'][3])
            attempt.update(start_wall_ns=1000, end_wall_ns=1100)
            record['commands'].append(attempt)
            with self.assertRaises(ValueError): terminal_setters(record, capture, ADDRESSES)

    def test_observed_interval_bound_does_not_qualify_original_admission_deadline(self):
        for elapsed in (4_999_999_999, 5_000_000_000):
            record, capture = partial()
            end = capture['commands'][4]['wall_ns']+elapsed
            capture['commands'][5].update(wall_ns=end-2, completion=dict(wall_ns=end-1))
            capture['complete'][5]['wall_ns'] = end
            record['commands'][3]['end_wall_ns'] = end+1
            record['commands'][4].update(start_wall_ns=end+10, end_wall_ns=end+50)
            capture['commands'][6].update(wall_ns=end+20, completion=dict(wall_ns=end+21))
            capture['complete'][6]['wall_ns'] = end+22
            with self.subTest(elapsed=elapsed):
                if elapsed < 5_000_000_000:
                    self.assertFalse(terminal_setters(record, capture, ADDRESSES)['original_request_deadline_qualified'])
                else:
                    with self.assertRaisesRegex(ValueError, 'interval exceeded'):
                        terminal_setters(record, capture, ADDRESSES)


class CleanupFileEvidence(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.share = Path(temp.name)
        record, capture = partial()
        self.record, raw, count = raw_fixture(record, capture)
        self.bindings = []
        for slot, owner in enumerate(self.record['owners']):
            serial = 'synthetic-cleanup-leaf-'+str(slot)
            owner['descriptors'] = dict(serial=serial)
            self.bindings.append(dict(host_port='synthetic-port-'+str(slot), guest_port=owner['port'],
                                      serial_sha256=hashlib.sha256(serial.encode()).hexdigest()))
        stage_record(self.share, self.record)
        (self.share/'ws73.pcap').write_bytes(raw)
        (self.share/'capture-stats.txt').write_text(f'{count} packets captured\n0 packets dropped by kernel\n')

    def inspect(self):
        return inspect_setup(self.share, addresses=ADDRESSES, bindings=self.bindings,
                             expected_sources=self.record['sources'])

    def test_actual_byte_decoder_journal_and_pin_checks_preserve_failed_setup(self):
        before = {str(p): p.read_bytes() for p in self.share.rglob('*') if p.is_file()}
        proof = self.inspect()
        self.assertEqual(proof['status'], 'ORIGINALS_VALIDATED_CLEANUP_ELIGIBLE_NOT_RESTORED')
        self.assertEqual(proof['original_setup_status'], 'FAIL')
        self.assertEqual(len(proof['proof']['terminal_setters']), 1)
        self.assertTrue(proof['owned_vm_exit_and_live_ownership_required'])
        self.assertTrue(proof['current_policy_recheck_required'])
        self.assertFalse(proof['natural_recovery_qualified'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.share.rglob('*') if p.is_file()})

    def test_wrong_sources_leaf_mapping_or_serial_rejected(self):
        for kind in ('source', 'serial', 'order', 'duplicate-host', 'duplicate-serial'):
            with self.subTest(kind=kind):
                sources = copy.deepcopy(self.record['sources']); bindings = copy.deepcopy(self.bindings)
                if kind == 'source': sources[0]['sha256'] = '0'*64
                elif kind == 'serial': bindings[0]['serial_sha256'] = '0'*64
                elif kind == 'order': bindings.reverse()
                elif kind == 'duplicate-host': bindings[0]['host_port'] = bindings[1]['host_port']
                else: bindings[0]['serial_sha256'] = bindings[1]['serial_sha256']
                with self.assertRaises(ValueError):
                    inspect_setup(self.share, addresses=ADDRESSES, bindings=bindings, expected_sources=sources)

    def test_missing_changed_truncated_and_lossy_files_reject_without_mutation(self):
        cases = [('runtime-address/originals.json', b'{}'), ('runtime-address/run.json', b'{'),
                 ('ws73.pcap', b'not-a-capture'), ('capture-stats.txt', b'24 packets captured\n1 packets dropped by kernel\n'),
                 ('capture-stats.txt', b'1 packets captured\n0 packets dropped by kernel\n')]
        for name, invalid in cases:
            path = self.share/name; old = path.read_bytes(); mode = path.stat().st_mode
            with self.subTest(name=name, invalid=invalid):
                path.chmod(0o600); path.write_bytes(invalid)
                with self.assertRaises((ValueError, OSError)): self.inspect()
                self.assertEqual(path.read_bytes(), invalid)
            path.write_bytes(old); path.chmod(mode)
        path = self.share/'runtime-address/run.json'; path.unlink()
        with self.assertRaises(OSError): self.inspect()
        self.assertTrue((self.share/'runtime-address/originals.json').is_file())

    def test_symlink_and_changed_during_actual_decode_reject(self):
        path = self.share/'ws73.pcap'; raw = path.read_bytes(); target = self.share/'actual.pcap'
        path.rename(target); path.symlink_to(target)
        with self.assertRaises(OSError): self.inspect()
        path.unlink(); target.rename(path)
        from ws73_address_cleanup import read_capture
        def decode_then_change(*args):
            result = read_capture(*args)  # Real production decoder executes first.
            path.write_bytes(raw+b'changed-after-parse')
            return result
        with patch('ws73_address_cleanup.read_capture', side_effect=decode_then_change):
            with self.assertRaisesRegex(ValueError, 'changed during validation'): self.inspect()

    def test_material_record_uses_actual_bytes(self):
        path = self.share/'ws73.pcap'
        self.assertEqual(material(path), dict(path=str(path.resolve()), bytes=path.stat().st_size,
                                             sha256=hashlib.sha256(path.read_bytes()).hexdigest()))


if __name__ == '__main__':
    unittest.main()
