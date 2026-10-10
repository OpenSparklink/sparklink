# SPDX-License-Identifier: GPL-2.0-only
"""Explicit test-only QMP coordination; never generate USB or DLI replies."""
import json
from pathlib import Path
import time
import re


PROPERTIES = ['test-runtime-in-hold-once','test-runtime-in-held','test-runtime-in-holds',
              'test-runtime-in-releases','test-runtime-in-bounded-releases','test-runtime-in-hold-drops',
              'test-runtime-in-error-once','test-runtime-in-errors']


def write_marker(path, value):
    """Publish a complete JSON marker; the 9P peer must never see a prefix."""
    path=Path(path)
    if path.exists():
        raise ValueError('stale/duplicate hold coordination marker')
    temporary=path.with_name(path.name+'.tmp')
    with temporary.open('x') as out:
        json.dump(value,out);out.write('\n')
    temporary.rename(path)


class HoldCoordinator:
    def __init__(self, share, record):
        self.folder = Path(share)/'diagnostic'
        self.record = record
        self.record.update(method='QMP_HOLD_ACTUAL_SUCCESSFUL_IN81', observations=[], complete=False,
                           physical_acceptance=False, automatic_fault_recovery_acceptance=False)
        self.path = '/machine/peripheral/ws73_0'
        self.phase = 'arm_ready'
        self.wait_deadline = None

    def snapshot(self, monitor):
        state={key:monitor.execute('qom-get',{'path':self.path,'property':key}) for key in PROPERTIES}
        for key, kind in zip(PROPERTIES,[bool,bool,int,int,int,int,bool,int]):
            if type(state[key]) is not kind or kind is int and not 0 <= state[key] < 1 << 64:
                raise ValueError('typed bounded QMP hold state required')
        return state

    def poll(self, monitor):
        if self.phase == 'done':
            return
        marker = self.folder/f'hold-{self.phase}.json'
        if not marker.exists():
            return
        request = json.loads(marker.read_text())
        if (set(request) != {'hold_phase','wall_ns'} or request['hold_phase'] != self.phase
                or type(request['wall_ns']) is not int or request['wall_ns'] <= 0):
            raise ValueError('invalid hold coordination marker')
        state = self.snapshot(monitor)
        base = dict(zip(PROPERTIES,[False,False,0,0,0,0,False,0]))
        if any(type(state[key]) is not type(value) for key,value in base.items()):
            raise ValueError('typed QMP hold state required')
        if self.phase == 'arm_ready':
            if state != base:
                raise ValueError('fresh disabled hold/error counters required')
            if monitor.execute('qom-get',{'path':self.path,'property':'attached'}) is not True:
                raise ValueError('hold requires actual attached USB owner')
            for key in ['host-reset','kernel-driver-detach','guest-reset','guest-resets-all']:
                if monitor.execute('qom-get',{'path':self.path,'property':key}) is not False:
                    raise ValueError('hold requires all reset/detach opt-outs')
            monitor.execute('qom-set',{'path':self.path,'property':'test-runtime-in-hold-once','value':True})
            base['test-runtime-in-hold-once'] = True
            if self.snapshot(monitor) != base:
                raise ValueError('hold did not arm exactly once')
            ack, next_phase = 'armed','wait_held'
        elif self.phase == 'wait_held':
            if self.wait_deadline is None:
                self.wait_deadline = time.monotonic()+5
            base['test-runtime-in-holds']=1; base['test-runtime-in-held']=True
            if state != base:
                waiting = dict(zip(PROPERTIES,[True,False,0,0,0,0,False,0]))
                if state == waiting and time.monotonic() < self.wait_deadline:
                    return
                raise ValueError('one actual held transfer required before cancel acknowledgment')
            ack, next_phase = 'held','release_ready'
        else:
            base['test-runtime-in-holds']=1; base['test-runtime-in-held']=True
            if state != base:
                raise ValueError('hold expired/dropped/released before explicit release')
            monitor.execute('qom-set',{'path':self.path,'property':'test-runtime-in-release','value':True})
            base['test-runtime-in-held']=False; base['test-runtime-in-releases']=1
            if self.snapshot(monitor) != base:
                raise ValueError('explicit release must deliver once, with zero bounded releases/drops')
            ack, next_phase = 'released','done'
        response={'stage':ack,'host_wall_ns':time.time_ns(),'request':request,'state':base}
        self.record['observations'].append(response)
        write_marker(self.folder/f'hold-{ack}-ack.json',response)
        self.phase = next_phase
        self.record['complete'] = self.phase == 'done'


def corroborate_host_hold(record, diagnostic, proofs, stderr, expected):
    if (record.get('method')!='QMP_HOLD_ACTUAL_SUCCESSFUL_IN81' or record.get('complete') is not True
            or record.get('physical_acceptance') is not False
            or record.get('automatic_fault_recovery_acceptance') is not False
            or record.get('observations')!=diagnostic.get('host_hold_acknowledgements')):
        raise ValueError('completed host/guest hold handshake required')
    observations=record['observations']
    if [r['stage'] for r in observations]!=['armed','held','released']:
        raise ValueError('exact one ordered host hold handshake required')
    markers=[r for r in diagnostic['records'] if 'hold_phase' in r]
    if len(markers)!=3:
        raise ValueError('exact three guest hold coordination markers required')
    previous=0
    for i,(row,marker) in enumerate(zip(observations,markers)):
        values=[i==0,i==1,int(i>0),int(i==2),0,0,False,0]
        # The first two entries are booleans, counters remain exact integers.
        if (row['request']!=marker or row['state']!=dict(zip(PROPERTIES,values))
                or any(type(row['state'][key]) is not type(value) for key,value in zip(PROPERTIES,values))
                or type(row['host_wall_ns']) is not int or row['host_wall_ns']<=previous):
            raise ValueError('host hold readbacks/causal acknowledgments differ')
        previous=row['host_wall_ns']
    holds=re.findall(r'WS73_TEST_RUNTIME_HOLD: dev (\d+):(\d+) bytes=(\d+) host_status=0 holds=(\d+) sha256=([0-9a-f]{64})',stderr)
    releases=re.findall(r'WS73_TEST_RUNTIME_HOLD_RELEASE: dev (\d+):(\d+) bytes=(\d+) bounded=(\d+) releases=(\d+)',stderr)
    if (len(holds)!=1 or len(releases)!=1 or tuple(map(int,holds[0][:2]))!=(expected['bus'],expected['address'])
            or holds[0][:3]!=releases[0][:3] or holds[0][3]!='1' or releases[0][3:]!=('0','1')):
        raise ValueError('one target-only actual successful host hold and explicit release required')
    old=next(p['reply'] for p in proofs if p.get('caller')=='C held active cancel')
    if old.get('usb_sha256')!=holds[0][4] or old.get('usb_length')!=int(holds[0][2]):
        raise ValueError('released old reply does not match original host transfer hash/length')
    return {'status':'ACTUAL_HOST_HOLD_CORROBORATED','host_transfer_sha256':holds[0][4],
            'host_transfer_bytes':int(holds[0][2]),'delivered_usb_record':old['record'],
            'physical_acceptance':False,'automatic_fault_recovery_acceptance':False}
