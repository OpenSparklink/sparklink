# SPDX-License-Identifier: GPL-2.0-only
"""Test-only hold of an actual SDK111 G installation acceptance, never a reply.

The original generic hold/callback ownership remains in QEMU. Opcode selection
is not a lifetime proof; independent capture and original author witness follow.
"""
import hashlib
import json
from pathlib import Path
import time

from ws73_diagnostic_hold import HoldCoordinator, PROPERTIES, write_marker, corroborate_host_hold

QEMU_SHA256 = 'dea80cfc383881b83b16744904be1fff82a8e4d523dfa65f2d96d5268e885e68'
METHOD = 'REAL_SDK111_INSTALL_ACCEPTANCE_HOLD'
SELECTORS = ['test-runtime-install-opcode','test-runtime-in-skip-requested',
             'test-runtime-in-skip-remaining','test-runtime-in-skipped']


def validate_qemu(path):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != QEMU_SHA256:
        raise ValueError('exact reviewed installation-selector QEMU required')


def arm(run, phase, row):
    number = len(run.data['security_agent'])-1
    if number not in (0,1):raise ValueError('exactly two connection role phases required')
    target = next(v for v in phase['typed_objects'] if v['object']['role']==0)
    index = target['owner']['index'];obj=target['object']
    if type(index) is not int or index not in (0,1):raise ValueError('original native controller required')
    folder = run.output/'security-install-hold'/f'phase-{number}'
    folder.parent.mkdir(exist_ok=True);folder.mkdir(mode=0o700)
    selection = dict(phase=number,index=index,opcode=0x1c03,**{k:obj[k] for k in ['generation','lifetime','handle','path']})
    write_marker(folder/'selection.json',selection)
    marker=dict(hold_phase='arm_ready',wall_ns=time.time_ns())
    write_marker(folder/'hold-arm_ready.json',marker)
    limit=time.monotonic()+3;reply=folder/'hold-armed-ack.json'
    while not reply.exists():
        if time.monotonic()>=limit:raise TimeoutError('installation acceptance hold arm acknowledgment')
        time.sleep(.005)
    ack=json.loads(reply.read_text())
    if ack['stage']!='armed' or ack['request']!=marker:raise ValueError('exact original arm acknowledgment required')
    row['install_hold']=dict(selection=selection,arm_receipt_wall_ns=time.time_ns())
    run.save();return folder


def collect(row,folder):
    row['install_hold']['markers']=[json.loads((folder/f'hold-{p}.json').read_text()) for p in ['arm_ready','wait_held','release_ready']]
    row['install_hold']['acks']=[json.loads((folder/f'hold-{p}-ack.json').read_text()) for p in ['armed','held','released']]


class SelectedHold(HoldCoordinator):
    def snapshot(self,monitor):
        for key,want in zip(SELECTORS,[0x1c03,0,0,0]):
            value=monitor.execute('qom-get',{'path':self.path,'property':key})
            if type(value) is not int or value!=want:raise ValueError('exact install-only selector required')
        if monitor.execute('qom-get',{'path':self.path,'property':'test-enumeration-reset-once'}) is not False:
            raise ValueError('enumeration reset experiment must be disabled')
        return super().snapshot(monitor)


class InstallCoordinator:
    def __init__(self,share,record,qemu):
        validate_qemu(qemu)
        self.root=Path(share)/'application/passthrough-control/security-install-hold';self.record=record
        record.update(method=METHOD,qemu_sha256=QEMU_SHA256,phases=[],complete=False,
                      physical_acceptance=False,automatic_fault_recovery_acceptance=False)
        self.child=None;self.used=[]

    def poll(self,monitor,owner):
        if self.record['complete']:return
        number=len(self.used)
        if self.child is None:
            folder=self.root/f'phase-{number}';path=folder/'selection.json'
            if not path.exists() or not (folder/'hold-arm_ready.json').exists():return
            selection=json.loads(path.read_text());index=selection.get('index')
            if (set(selection)!={'phase','index','opcode','generation','lifetime','handle','path'}
                    or selection['phase']!=number or type(index) is not int or index not in (0,1)
                    or index in self.used or selection['opcode']!=0x1c03
                    or type(selection['generation']) is not int or selection['generation']<1
                    or type(selection['lifetime']) is not int or selection['lifetime']<1
                    or type(selection['handle']) is not int or not 0<=selection['handle']<=0xffff):
                raise ValueError('fresh original two-role native selection required')
            child=SelectedHold(folder,{})
            child.folder=folder;child.path=f'/machine/peripheral/ws73_{index}'
            if monitor.execute('qom-get',{'path':child.path,'property':SELECTORS[0]})!=0:
                raise ValueError('fresh disabled installation selector required')
            identity=owner(index)
            monitor.execute('qom-set',{'path':child.path,'property':'test-runtime-install-g','value':True})
            child.record.update(selection=selection,host_identity_at_arm=identity,hold_budget_ms=2000)
            self.record['phases'].append(child.record);self.child=child
        self.child.poll(monitor)
        if self.child.phase=='done':
            self.used.append(self.child.record['selection']['index']);self.child=None
            self.record['complete']=len(self.used)==2


def corroborate(record,control,capture,stderr):
    rows=control['security_agent'];phases=control['connection_control']['phases']
    if (record.get('method')!=METHOD or record.get('qemu_sha256')!=QEMU_SHA256
            or not record.get('complete') or len(record.get('phases',[]))!=2
            or record.get('physical_acceptance') is not False
            or record.get('automatic_fault_recovery_acceptance') is not False):
        raise ValueError('both exact real installation hold handshakes required')
    proofs=[];used=[]
    if 'WS73_TEST_RUNTIME_HOLD_DROP:' in stderr or 'WS73_TEST_RUNTIME_IN_ERROR:' in stderr:raise ValueError('no hold drops or synthetic transport errors allowed')
    import re
    holds=re.findall(r'WS73_TEST_RUNTIME_HOLD: dev (\d+):(\d+) bytes=(\d+) host_status=0 holds=(\d+) sha256=([0-9a-f]{64})',stderr)
    releases=re.findall(r'WS73_TEST_RUNTIME_HOLD_RELEASE: dev (\d+):(\d+) bytes=(\d+) bounded=(\d+) releases=(\d+)',stderr)
    if len(holds)!=2 or len(releases)!=2:raise ValueError('exactly two real original holds/releases required')
    for n,(host,row,phase) in enumerate(zip(record['phases'],rows,phases,strict=True)):
        target=next(v for v in phase['typed_objects'] if v['object']['role']==0)
        obj=target['object'];owner=target['owner']
        if owner['index'] in used:raise ValueError('G role must exchange physical controllers')
        used.append(owner['index'])
        selection=dict(phase=n,index=owner['index'],opcode=0x1c03,**{k:obj[k] for k in ['generation','lifetime','handle','path']})
        guest=row['install_hold']
        if host.get('selection')!=selection or guest.get('selection')!=selection:raise ValueError('original full lifetime/role/host selection mismatch')
        events=[e for e in row['events'] if e['stage']=='install_barrier']
        if [e['ack'] for e in events]!=guest['acks'][1:] or [e['request'] for e in events]!=guest['markers'][1:]:raise ValueError('actual ordinary witness and coordinator handshake differ')
        accept=[e for e in capture['native_events'] if (e['bus'],e['device'])==(owner['bus'],owner['device'])
                and row['start_wall_ns']<=e['wall_ns']<=row['end_wall_ns'] and e['event'] in (1,2)
                and e['params']=='031c0100']
        if len(accept)!=1:raise ValueError('one exact actual G acceptance required')
        event=accept[0]
        stages={e['stage']:e for e in row['events'] if e['stage'] in ['install_before_cancel','install_cancelled','install_terminal_stable']}
        before,withdrawn,late=[stages[k] for k in ['install_before_cancel','install_cancelled','install_terminal_stable']]
        allocations=[e['start_wall_ns'] for e in row['events'] if e['stage']=='allocated']
        if len(allocations)!=2 or not row['start_wall_ns']<=guest['markers'][0]['wall_ns']<=guest['arm_receipt_wall_ns']<min(allocations):raise ValueError('actual hold arm must precede both original allocations')
        if not (guest['arm_receipt_wall_ns']<before['wall_ns']<=withdrawn['wall_ns']<guest['markers'][2]['wall_ns']
                <=event['wall_ns']<=late['wall_ns']):raise ValueError('actual late acceptance must follow cancellation and precede final stable read')
        # Shared generic oracle receives only this physical owner's log lines;
        # the complete two-owner log count is independently checked above.
        h=holds[n];rel=releases[n]
        subset=f'WS73_TEST_RUNTIME_HOLD: dev {h[0]}:{h[1]} bytes={h[2]} host_status=0 holds={h[3]} sha256={h[4]}\n'
        subset+=f'WS73_TEST_RUNTIME_HOLD_RELEASE: dev {rel[0]}:{rel[1]} bytes={rel[2]} bounded={rel[3]} releases={rel[4]}\n'
        proof=corroborate_host_hold(host,dict(records=guest['markers'],host_hold_acknowledgements=guest['acks']),[],subset,host['host_identity_at_arm'],held_reply=event)
        commands=[e for e in capture['commands'] if (e['bus'],e['device'])==(owner['bus'],owner['device']) and row['start_wall_ns']<=e['wall_ns']<=row['end_wall_ns'] and e['opcode']==0x1c03]
        if len(commands)!=1 or commands[0]['completion']['wall_ns']>=before['wall_ns']:raise ValueError('actual installation USB submit/complete before withdrawal required')
        if any(e['opcode'] in (0x1812,0x1c03,0x1c05) and (e['bus'],e['device'])==(owner['bus'],owner['device']) and withdrawn['wall_ns']<=e['wall_ns']<=row['end_wall_ns'] for e in capture['commands']):raise ValueError('withdrawn operation must not newly submit security commands')
        proofs.append(dict(selection=selection,hold=proof,cancelled_operation_not_hardware_key_erasure=True))
    return dict(status='TWO_ROLE_ACTUAL_INSTALL_WITHDRAWAL_LATE_REPLY_SCOPED_PASS',phases=proofs,
                key_erasure_or_reuse_proof=False,natural_recovery_acceptance=False)
