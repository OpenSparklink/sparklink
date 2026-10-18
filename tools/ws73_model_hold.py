# SPDX-License-Identifier: GPL-2.0-only
"""QMP retention in usb-ws73-test only; never real host/libusb IN proof."""
import json
import re
import time

from ws73_diagnostic_hold import write_marker

PROPERTIES = ['model-terminal-hold-once','model-terminal-held',
              'model-terminal-holds','model-terminal-releases',
              'model-terminal-bounded-releases','model-terminal-drops']
SELECTOR_PROPERTIES=['model-terminal-skip-count','model-terminal-skipped']


class ModelHoldCoordinator:
    def __init__(self, share, record, initialization_step=0):
        if type(initialization_step) is not int or not 0<=initialization_step<=2:raise ValueError('bounded explicit model initialization step required')
        self.step=initialization_step;self.properties=PROPERTIES+(SELECTOR_PROPERTIES if self.step else [])
        self.folder=share/'managed-partial';self.record=record
        if self.step:record.update(initialization_step=self.step)
        record.update(method='QMP_RETAIN_SIMULATED_TERMINAL_FRAME',observations=[],
                      complete=False,physical_acceptance=False,automatic_fault_recovery_acceptance=False)
        self.path='/machine/peripheral/ws73_0';self.phase='arm_ready';self.deadline=None

    def poll(self, monitor):
        if self.phase=='done':return
        marker=self.folder/f'hold-{self.phase}.json'
        if not marker.exists():return
        request=json.loads(marker.read_text())
        if set(request)!={'hold_phase','wall_ns'} or request['hold_phase']!=self.phase or type(request['wall_ns']) is not int or request['wall_ns']<=0:
            raise ValueError('exact model hold marker required')
        if self.deadline is None:self.deadline=time.monotonic()+5
        if time.monotonic()>self.deadline:raise TimeoutError('bounded model hold coordination')
        def snapshot():
            state={key:monitor.execute('qom-get',{'path':self.path,'property':key}) for key in self.properties}
            if any(type(state[k]) is not t or t is int and not 0<=state[k]<1<<64 for k,t in zip(self.properties,[bool,bool,int,int,int,int]+([int,int] if self.step else []))):
                raise ValueError('exact model QMP state types required')
            return state
        base=dict(zip(self.properties,[False,False,0,0,0,0]+([0,0] if self.step else [])));state=snapshot()
        if self.phase=='arm_ready':
            if state!=base:raise ValueError('fresh unconsumed model budget required')
            armable=monitor.execute('qom-get',{'path':self.path,'property':'model-terminal-armable'})
            if type(armable) is not bool:raise ValueError('typed model armability required')
            if not armable:return
            if self.step:
                monitor.execute('qom-set',{'path':self.path,'property':SELECTOR_PROPERTIES[0],'value':self.step})
                base[SELECTOR_PROPERTIES[0]]=self.step
            monitor.execute('qom-set',{'path':self.path,'property':PROPERTIES[0],'value':True})
            base[PROPERTIES[0]]=True;ack='armed';next_phase='wait_held'
        elif self.phase=='wait_held':
            base[PROPERTIES[1]]=True;base[PROPERTIES[2]]=1
            if self.step:
                base[SELECTOR_PROPERTIES[0]]=base[SELECTOR_PROPERTIES[1]]=self.step
                waiting=dict(base);waiting[PROPERTIES[0]]=True;waiting[PROPERTIES[1]]=False;waiting[PROPERTIES[2]]=0
                waiting[SELECTOR_PROPERTIES[1]]=state[SELECTOR_PROPERTIES[1]]
                if 0<=state[SELECTOR_PROPERTIES[1]]<=self.step and state==waiting:return
            elif state==dict(zip(PROPERTIES,[True,False,0,0,0,0])):return
            if state!=base:raise ValueError('one retained simulated terminal frame required')
            ack='held';next_phase='release_ready'
        else:
            base[PROPERTIES[1]]=True;base[PROPERTIES[2]]=1
            if self.step:base[SELECTOR_PROPERTIES[0]]=base[SELECTOR_PROPERTIES[1]]=self.step
            if state!=base:raise ValueError('retained frame expired or dropped before explicit release')
            monitor.execute('qom-set',{'path':self.path,'property':'model-terminal-release','value':True})
            base[PROPERTIES[1]]=False;base[PROPERTIES[3]]=1;ack='released';next_phase='done'
        if snapshot()!=base:raise ValueError('exact model arm/release readback required')
        response=dict(stage=ack,host_wall_ns=time.time_ns(),request=request,state=base)
        self.record['observations'].append(response)
        write_marker(self.folder/f'hold-{ack}-ack.json',response)
        self.phase=next_phase;self.deadline=None;self.record['complete']=self.phase=='done'


def corroborate_model_hold(record, probe, reply, stderr):
    if (record.get('method')!='QMP_RETAIN_SIMULATED_TERMINAL_FRAME' or record.get('complete') is not True
            or record.get('physical_acceptance') is not False or record.get('automatic_fault_recovery_acceptance') is not False
            or probe.get('synthetic_support') is not True or record['observations']!=probe['hold_acknowledgements']):
        raise ValueError('explicit completed model-only hold required')
    step=probe.get('initialization_step',0)
    if type(step) is not int or not 0<=step<=2 or record.get('initialization_step',0)!=step:raise ValueError('exact model selector step required')
    properties=PROPERTIES+(SELECTOR_PROPERTIES if step else [])
    observations=record['observations'];previous=0
    if len(observations)!=3 or len(probe['markers'])!=3:raise ValueError('three model hold observations required')
    for i,(row,marker) in enumerate(zip(observations,probe['markers'])):
        values=[i==0,i==1,int(i>0),int(i==2),0,0]+([step,0 if i==0 else step] if step else [])
        if (row['stage']!=['armed','held','released'][i] or row['request']!=marker
                or row['state']!=dict(zip(properties,values))
                or any(type(row['state'][k]) is not type(v) for k,v in zip(properties,values))
                or type(row['host_wall_ns']) is not int or row['host_wall_ns']<=previous):
            raise ValueError('model causal state/readback mismatch')
        previous=row['host_wall_ns']
    skipped=re.findall(r'WS73_MODEL_TERMINAL_SKIP: serial=(\d+) bytes=(\d+) skipped=(\d+) sha256=([0-9a-f]{64})',stderr)
    if len(skipped)!=step or [int(v[2]) for v in skipped]!=list(range(1,step+1)) or any(v[0]!='1' for v in skipped):raise ValueError('exact earlier original terminal count required')
    held=re.findall(r'WS73_MODEL_TERMINAL_HOLD: serial=(\d+) bytes=(\d+) sha256=([0-9a-f]{64})',stderr)
    released=re.findall(r'WS73_MODEL_TERMINAL_RELEASE: serial=(\d+) bytes=(\d+) bounded=(\d+) sha256=([0-9a-f]{64})',stderr)
    if (len(held)!=1 or len(released)!=1 or held[0][0]!='1'
            or released[0]!=(held[0][0],held[0][1],'0',held[0][2])
            or reply['usb_sha256']!=held[0][2] or reply['usb_length']!=int(held[0][1])):
        raise ValueError('original simulated terminal queue bytes and delivered USB record must match')
    return dict(status='SIMULATED_TERMINAL_FRAME_CORROBORATED',usb_record=reply['record'],
                original_model_frame_sha256=held[0][2],skipped_original_frames=[dict(serial=int(v[0]),bytes=int(v[1]),ordinal=int(v[2]),sha256=v[3]) for v in skipped],physical_acceptance=False,
                actual_host_libusb_hold_acceptance=False)
