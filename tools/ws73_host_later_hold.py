# SPDX-License-Identifier: GPL-2.0-only
"""Retain a later actual successful host frame; never construct USB/DLI bytes."""
import json
import re
import time
from ws73_diagnostic_hold import HoldCoordinator,PROPERTIES,write_marker,corroborate_host_hold

SELECTORS=['test-runtime-in-skip-requested','test-runtime-in-skip-remaining','test-runtime-in-skipped']


class LaterHostCoordinator(HoldCoordinator):
    def __init__(self,share,record,step):
        if type(step) is not int or step not in [1,2]:raise ValueError('bounded actual host selector required')
        super().__init__(share,record);self.folder=self.folder.parent/'managed-partial';self.step=step
        self.record.update(method='QMP_HOLD_LATER_ACTUAL_SUCCESSFUL_IN81',initialization_step=step)

    def snapshot(self,monitor):
        state=super().snapshot(monitor)
        for key in SELECTORS:
            value=monitor.execute('qom-get',{'path':self.path,'property':key})
            if type(value) is not int or not 0<=value<=2:raise ValueError('bounded typed original frame counters required')
            state[key]=value
        return state

    def poll(self,monitor):
        if self.phase=='done':return
        marker=self.folder/f'hold-{self.phase}.json'
        if not marker.exists():return
        request=json.loads(marker.read_text())
        if set(request)!={'hold_phase','wall_ns'} or request['hold_phase']!=self.phase or type(request['wall_ns']) is not int or request['wall_ns']<=0:raise ValueError('exact real host hold marker required')
        base=dict(zip(PROPERTIES,[False,False,0,0,0,0,False,0]));base.update(dict.fromkeys(SELECTORS,0));state=self.snapshot(monitor)
        if self.phase=='arm_ready':
            if state!=base or monitor.execute('qom-get',{'path':self.path,'property':'attached'}) is not True:raise ValueError('fresh attached actual USB owner required')
            for key in ['host-reset','kernel-driver-detach','guest-reset','guest-resets-all','test-enumeration-reset-once']:
                if monitor.execute('qom-get',{'path':self.path,'property':key}) is not False:raise ValueError('all reset/detach experiments must be disabled')
            monitor.execute('qom-set',{'path':self.path,'property':'test-runtime-in-skip-'+('one' if self.step==1 else 'two'),'value':True})
            base[SELECTORS[0]]=self.step
            if self.snapshot(monitor)!=base:raise ValueError('exact idle selector configuration required')
            monitor.execute('qom-set',{'path':self.path,'property':PROPERTIES[0],'value':True})
            base[PROPERTIES[0]]=True;base[SELECTORS[1]]=self.step
            if self.snapshot(monitor)!=base:raise ValueError('exact original frame budget arm required')
            ack,next_phase='armed','wait_held'
        else:
            base[PROPERTIES[1]]=True;base[PROPERTIES[2]]=1
            base[SELECTORS[0]]=base[SELECTORS[2]]=self.step
            if self.phase=='wait_held' and state!=base:
                if self.wait_deadline is None:self.wait_deadline=time.monotonic()+5
                waiting=dict(base);waiting[PROPERTIES[0]]=True;waiting[PROPERTIES[1]]=False;waiting[PROPERTIES[2]]=0
                waiting[SELECTORS[1]]=state[SELECTORS[1]];waiting[SELECTORS[2]]=state[SELECTORS[2]]
                if state==waiting and state[SELECTORS[1]]+state[SELECTORS[2]]==self.step and time.monotonic()<self.wait_deadline:return
                raise ValueError('one later actual held frame after bounded original deliveries required')
            if state!=base:raise ValueError('original hold expired/dropped/released before cancellation')
            if self.phase=='wait_held':ack,next_phase='held','release_ready'
            else:
                monitor.execute('qom-set',{'path':self.path,'property':'test-runtime-in-release','value':True})
                base[PROPERTIES[1]]=False;base[PROPERTIES[3]]=1
                if self.snapshot(monitor)!=base:raise ValueError('exact explicit original frame delivery required')
                ack,next_phase='released','done'
        response=dict(stage=ack,host_wall_ns=time.time_ns(),request=request,state=base)
        self.record['observations'].append(response);write_marker(self.folder/f'hold-{ack}-ack.json',response)
        self.phase=next_phase;self.record['complete']=self.phase=='done'


def verify_selector_rows(rows,step):
    if type(step) is not int or step not in [1,2] or len(rows)!=3:raise ValueError('bounded later original host handshake required')
    for i,row in enumerate(rows):
        expected=dict(zip(PROPERTIES,[i==0,i==1,int(i>0),int(i==2),0,0,False,0]))
        expected.update(dict(zip(SELECTORS,[step,step if i==0 else 0,0 if i==0 else step])))
        if row['state']!=expected or any(type(row['state'][k]) is not type(v) for k,v in expected.items()):raise ValueError('exact original skip/hold state readbacks required')


def corroborate(record,partial,replies,stderr,expected):
    step=partial['initialization_step'];verify_selector_rows(record['observations'],step)
    if record.get('method')!='QMP_HOLD_LATER_ACTUAL_SUCCESSFUL_IN81' or record.get('initialization_step')!=step:raise ValueError('explicit later successful actual host method required')
    # Reuse the first-frame hash/callback invariant with only the canonical
    # selector projection removed. Never replace the original serialized rows.
    observations=[dict(v,state={k:v['state'][k] for k in PROPERTIES}) for v in record['observations']]
    guest=dict(records=partial['markers'],host_hold_acknowledgements=[dict(v,state={k:v['state'][k] for k in PROPERTIES}) for v in partial['hold_acknowledgements']])
    if record['observations']!=partial['hold_acknowledgements']:raise ValueError('exact original host/guest selector acknowledgements required')
    proof=corroborate_host_hold(dict(record,method='QMP_HOLD_ACTUAL_SUCCESSFUL_IN81',observations=observations),guest,[],stderr,expected,held_reply=replies[step])
    skips=re.findall(r'WS73_TEST_RUNTIME_SKIP: dev (\d+):(\d+) bytes=(\d+) host_status=0 skipped=(\d+) sha256=([0-9a-f]{64})',stderr)
    wanted=[(str(expected['bus']),str(expected['address']),str(v['usb_length']),str(i+1),v['usb_sha256']) for i,v in enumerate(replies[:step])]
    if skips!=wanted:raise ValueError('every earlier original successful host frame must match actual captured Complete')
    proof.update(status='ACTUAL_LATER_HOST_HOLD_CORROBORATED',initialization_step=step,skipped_original_frames=[dict(bytes=v['usb_length'],ordinal=i+1,sha256=v['usb_sha256']) for i,v in enumerate(replies[:step])]);return proof
