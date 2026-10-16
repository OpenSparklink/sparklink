# SPDX-License-Identifier: GPL-2.0-only
"""Test-only causal barrier using the existing bounded real IN81 hold.

No packets, completions or credit are generated. The independent prefix oracle
still rejects a completed PDU or any submit after Managed withdrawal.
"""
import hashlib
import json
from pathlib import Path
import time

from ws73_diagnostic_hold import HoldCoordinator, PROPERTIES, write_marker, corroborate_host_hold
from ws73_capture import CaptureError

METHOD = 'BOUNDED2S_REAL_IN81_INCOMPLETE_PDU_BARRIER'
# The existing immutable two-second fixture, not the separate eight-second
# original-deadline fixture. Changing this requires a fresh fixture review.
QEMU_SHA256 = '05a3b654eb2801ed1ddb60fc6c6fa9bd5cd48eefa8194f999170eab90b26185a'


class PrefixCoordinator(HoldCoordinator):
    def __init__(self, share, record, index, qemu):
        if index not in (0, 1) or hashlib.sha256(Path(qemu).read_bytes()).hexdigest() != QEMU_SHA256:
            raise ValueError('pinned bounded2s real-IN81 fixture required')
        super().__init__(share, record)
        self.folder = Path(share)/'channel-prefix-hold'
        self.path = '/machine/peripheral/ws73_' + str(index)
        self.record.update(method=METHOD, index=index, hold_budget_ms=2000, qemu_sha256=QEMU_SHA256)


class PrefixBarrier:
    def __init__(self, record, save, folder=Path('/evidence/channel-prefix-hold')):
        self.folder = Path(folder)
        self.folder.mkdir(exist_ok=False)
        self.row = dict(markers=[], acks=[], ack_receipts=[])
        record['prefix_hold'] = self.row
        self.save = save

    def stage(self, phase, ack):
        marker = dict(hold_phase=phase, wall_ns=time.time_ns())
        write_marker(self.folder/f'hold-{phase}.json', marker)
        self.row['markers'].append(marker)
        self.save()
        limit = time.monotonic()+3
        path = self.folder/f'hold-{ack}-ack.json'
        while not path.exists():
            if time.monotonic() > limit:
                raise TimeoutError('real prefix hold acknowledgment ' + ack)
            time.sleep(.005)
        value = json.loads(path.read_text())
        if value['stage'] != ack or value['request'] != marker:
            raise ValueError('prefix hold acknowledgment identity mismatch')
        self.row['acks'].append(value)
        self.row['ack_receipts'].append(dict(stage=ack, wall_ns=time.time_ns()))
        self.save()

    def arm(self, grant):
        # Drain prior business completions before arming the one-shot hold.
        time.sleep(.15)
        self.stage('arm_ready', 'armed')
        grant.arm(sample_before_block=True)
        self.stage('wait_held', 'held')

    def release(self):
        self.stage('release_ready', 'released')


def verify(r):
    from sparklink.structs import SleChannelTxStatus
    g = r['channel_grant']; d = r['prefix_hold']; i = r['index']
    markers, acks, receipts = d['markers'], d['acks'], d['ack_receipts']
    if len(markers) != 3 or len(acks) != 3 or len(receipts) != 3:
        raise ValueError('complete causal prefix hold handshake required')
    states = [[True, False, 0, 0, 0, 0, False, 0],
              [False, True, 1, 0, 0, 0, False, 0],
              [False, False, 1, 1, 0, 0, False, 0]]
    for j, (phase, ack) in enumerate(zip(['arm_ready', 'wait_held', 'release_ready'], ['armed', 'held', 'released'])):
        state = dict(zip(PROPERTIES, states[j]))
        if (markers[j]['hold_phase'] != phase or acks[j]['stage'] != ack
                or acks[j]['request'] != markers[j] or acks[j]['state'] != state
                or any(type(acks[j]['state'][key]) is not type(value) for key, value in state.items())
                or receipts[j]['stage'] != ack or receipts[j]['wall_ns'] < markers[j]['wall_ns']):
            raise ValueError('exact one explicit hold/release without expiry, drops or error required')
        if j and receipts[j-1]['wall_ns'] >= markers[j]['wall_ns']:
            raise ValueError('ordered guest causal hold receipts required')
    armed = g['armed']; owner = g['owners'][i]
    tx = SleChannelTxStatus.from_buffer_copy(bytes.fromhex(armed['pre_block_tx_status']))
    if ((tx.version, tx.size, tx.controller, tx.generation, tx.lifetime, tx.handle,
         tx.packet_maximum, tx.capacity, tx.outstanding, tx.connection_debt, tx.flags,
         tx.active_pdu_bytes, tx.active_pdu_offset)
            != (1, 64, i, owner['generation'], owner['lifetime'], owner['handle'],
                254, 5, 5, 5, 3, 2047, 1270) or tx.reserved or not tx.pool_exhaustions):
        raise ValueError('actual exhausted pool5 and incomplete1270/2047 PDU required')
    admission = g['revoke_prefix']['admission_before_wall_ns']
    before = r['data_link_down']['submit_before_wall_ns'] if 'data_link_down' in r else r['release_before_wall_ns']
    after = r['data_link_down']['submit_after_wall_ns'] if 'data_link_down' in r else r['release_after_wall_ns']
    if not (receipts[0]['wall_ns'] < admission <= armed['pre_block_tx_status_wall_ns']
            <= armed['wall_ns'] < receipts[1]['wall_ns'] < before <= after
            <= markers[2]['wall_ns'] < receipts[2]['wall_ns']):
        raise ValueError('hold before admission, full pool before withdrawal, release after withdrawal required')
    return d


def corroborate(r, capture, hold, stderr, expected):
    d = verify(r); g = r['channel_grant']; i = r['index']
    if (not hold or hold.get('method') != METHOD or hold.get('index') != i
            or hold.get('hold_budget_ms') != 2000 or hold.get('qemu_sha256') != QEMU_SHA256):
        raise CaptureError('target-only pinned bounded prefix fixture required')
    start = g['revoke_prefix']['admission_before_wall_ns']
    end = g['armed']['pre_block_tx_status_wall_ns']
    usb = r['usb'][i]
    same = lambda v: (v['bus'], v['device']) == (usb['bus'], usb['device'])
    packets = [v for v in capture['acb_packets'] if same(v) and v['direction'] == 'out'
               and v['handle'] == g['owners'][i]['handle'] and start <= v['wall_ns'] <= end]
    payload = bytes.fromhex(g['revoke_prefix']['payload'])
    wire = b'\x1f\0\xfb\x07\xf1' + payload
    if (len(packets) != 5 or any(v['boundary'] != (1 if n == 0 else 2)
            or not v.get('completion') or len(bytes.fromhex(v['data'])) != 254
            for n, v in enumerate(packets))
            or b''.join(bytes.fromhex(v['data']) for v in packets) != wire[:1270]):
        raise CaptureError('five actual original fragments before exhausted-pool snapshot required')
    nocp = [e for e in capture['native_events'] if same(e) and e['event'] == 9
            and start <= e['wall_ns'] <= r['end_wall_ns']]
    if not nocp or any(e['wall_ns'] <= d['markers'][2]['wall_ns'] for e in nocp):
        raise CaptureError('real NOCP must remain withheld until explicit release')
    proof = corroborate_host_hold(hold, dict(records=d['markers'], host_hold_acknowledgements=d['acks']),
                                  [], stderr, expected, held_reply=nocp[0], expected_method=METHOD)
    return dict(status='REAL_INCOMPLETE_PDU_BARRIER_CORROBORATED', host_hold=proof,
                full_pool_snapshot=g['armed']['pre_block_tx_status'], submitted_before_snapshot=5,
                scope='Controlled delay only;not natural recovery, full reuse safety or independent peer business after link loss')

