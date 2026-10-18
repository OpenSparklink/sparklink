# SPDX-License-Identifier: GPL-2.0-only
"""Bounded diagnostic Session observation, never credit/Ready or physical drain.

The test requires terminal known CMTC entries and empty Native debt/queues, then
still independently corroborates real USB/NOCP. No reset, refund or new Engine.
"""
import re
import time
from ws73_capture import CaptureError

FIELDS='index generation lifetime handle capacity outstanding debt queued active open pending retired failed allocated flags'.split()
PATTERN=r'^SessionTxStatus: '+r' '.join(n+r'=(\d+)' for n in FIELDS)+r'$'
BUDGET_NS=5_000_000_000
MAX_SAMPLES=64


def decode(receipt, entry):
    if type(receipt['exit']) is not int:raise CaptureError('typed process exit required')
    for key in ['start_monotonic_ns','end_monotonic_ns','start_wall_ns','end_wall_ns']:
        if type(receipt[key]) is not int or receipt[key]<0:raise CaptureError('typed nonnegative receipt clocks required')
    if receipt['start_monotonic_ns']>receipt['end_monotonic_ns'] or receipt['start_wall_ns']>receipt['end_wall_ns']:
        raise CaptureError('ordered original query interval required')
    matches=re.findall(PATTERN,receipt['stdout'],re.M)
    if receipt['exit'] or len(matches)!=1 or receipt['stdout'].count('SessionTxStatus:')!=1:
        raise CaptureError('one successful actual Session observation required')
    values=dict(zip(FIELDS,map(int,matches[0])));owner,obj=entry['owner'],entry['object']
    if any(type(v) is not int for v in [owner['index'],owner['generation'],obj['lifetime'],obj['handle'],owner['buffers'][1]]):raise CaptureError('typed original Session identity required')
    if tuple(values[k] for k in FIELDS[:4])!=(owner['index'],owner['generation'],obj['lifetime'],obj['handle']):
        raise CaptureError('Session observation generation/lifetime mismatch')
    if (values['capacity']!=owner['buffers'][1] or not 0<=values['debt']<=values['outstanding']<=values['capacity']
            or values['queued']+values['active']>48 or values['active']>1 or values['flags']&~15
            or values['allocated']>4 or sum(values[k] for k in ['open','pending','retired','failed'])!=values['allocated']):
        raise CaptureError('Session observation budget/state invariant')
    if receipt['args'][1:]!=['--adapter',owner['path'],'transport-status',obj['path']]:
        raise CaptureError('original typed transport query arguments required')
    return values


def settled(values, index):
    return (all(values[k]==0 for k in ['outstanding','debt','queued','active','open','pending','flags'])
            and values['retired']==3 and values['failed']==(1 if index==0 else 0)
            and values['allocated']==(4 if index==0 else 3))


def queries(run, owners, deadline_ns=None):
    rows=[]
    for entry in owners:
        timeout=1.25 if deadline_ns is None else min(1.25,(deadline_ns-time.monotonic_ns())/1e9)
        if timeout<=0:raise CaptureError('Session drain original observation deadline')
        receipt=run.command([str(run.args.slctl),'--adapter',entry['owner']['path'],'transport-status',entry['object']['path']],timeout,collection='dynamic_transport_queries')
        values=decode(receipt,entry);rows.append(dict(receipt=receipt,values=values))
    return rows


def await_closed(run, channel):
    start=channel['close_start_monotonic_ns'];deadline=start+BUDGET_NS
    observation=dict(version=1,start_monotonic_ns=start,deadline_monotonic_ns=deadline,
                     fd_reaped_wall_ns=channel['end_wall_ns'],samples=[],status='RUNNING_NOT_QUALIFIED')
    channel['session_drain']=observation;run.save()
    try:
        for sequence in range(MAX_SAMPLES):
            rows=queries(run,channel['owners'],deadline)
            sample=dict(sequence=sequence,observations=rows,wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
            observation['samples'].append(sample);run.save()
            if sample['monotonic_ns']>=deadline:raise CaptureError('Session drain original observation deadline')
            if all(settled(v['values'],i) for i,v in enumerate(rows)):
                observation.update(status='NATIVE_TERMINAL_AND_ZERO_DEBT_OBSERVED_NOT_CALLBACK_DRAIN',end_wall_ns=sample['wall_ns'],end_monotonic_ns=sample['monotonic_ns'])
                # New v4 boundary is tied to observed terminal/credit state, never
                # app exit, an arbitrary sleep or a fixed capture-window extension.
                channel['end_wall_ns']=sample['wall_ns'];run.save();return
            time.sleep(min(.002,max(0,(deadline-time.monotonic_ns())/1e9)))
        raise CaptureError('Session drain finite sample budget exceeded')
    except BaseException as e:
        observation.update(status='FAIL',error=str(e));run.save();raise


def corroborate(channel,capture):
    row=channel['session_drain'];owners=channel['owners'];samples=row['samples']
    if (type(row.get('version')) is not int or row.get('version')!=1 or row.get('status')!='NATIVE_TERMINAL_AND_ZERO_DEBT_OBSERVED_NOT_CALLBACK_DRAIN'
            or not 1<=len(samples)<=MAX_SAMPLES or row['start_monotonic_ns']!=channel['close_start_monotonic_ns']
            or row['deadline_monotonic_ns']!=row['start_monotonic_ns']+BUDGET_NS
            or not channel['close_start_wall_ns']<=row['fd_reaped_wall_ns']<=row['end_wall_ns']==channel['end_wall_ns']):
        raise CaptureError('original bounded post-close observation required')
    clocks=[row[k] for k in ['start_monotonic_ns','deadline_monotonic_ns','fd_reaped_wall_ns','end_wall_ns','end_monotonic_ns']]
    if any(type(v) is not int for v in clocks):raise CaptureError('integer original clocks required')
    previous=row['start_monotonic_ns'];first_settled=None
    for n,sample in enumerate(samples):
        if any(type(sample[k]) is not int for k in ['sequence','monotonic_ns','wall_ns']):raise CaptureError('integer sample identity/clocks required')
        if sample['sequence']!=n or not previous<=sample['monotonic_ns']<row['deadline_monotonic_ns'] or len(sample['observations'])!=2:
            raise CaptureError('bounded ordered two-endpoint sampling required')
        for i,entry in enumerate(sample['observations']):
            receipt=entry['receipt'];values=decode(receipt,owners[i])
            if any(type(v) is not int for v in entry['values'].values()) or values!=entry['values'] or not previous<=receipt['start_monotonic_ns']<=receipt['end_monotonic_ns']<=sample['monotonic_ns'] or not row['fd_reaped_wall_ns']<=receipt['start_wall_ns']<=receipt['end_wall_ns']<=sample['wall_ns']:
                raise CaptureError('same original typed snapshot and request interval required')
            previous=receipt['end_monotonic_ns']
        if all(settled(v['values'],i) for i,v in enumerate(sample['observations'])) and first_settled is None:first_settled=n
        previous=sample['monotonic_ns']
    if first_settled!=len(samples)-1 or (row['end_monotonic_ns'],row['end_wall_ns'])!=(samples[-1]['monotonic_ns'],samples[-1]['wall_ns']):
        raise CaptureError('seal at first terminal zero-debt observation;no cherry-picked extension')
    before=channel['before_close_status']
    if len(before)!=2:raise CaptureError('two real open-channel positive controls required')
    for i,entry in enumerate(before):
        receipt=entry['receipt'];v=decode(receipt,owners[i])
        if v!=entry['values'] or v['open']!=1 or v['retired']!=2 or v['failed']!=(1 if i==0 else 0) or settled(v,i) or receipt['end_wall_ns']>channel['close_start_wall_ns']:
            raise CaptureError('actual open positive control must not count as closed')
        owner=owners[i]['owner'];start,end=receipt['start_wall_ns'],receipt['end_wall_ns']
        if any((p['bus'],p['device'])==(owner['bus'],owner['device']) and start<=p['wall_ns']<=end
               for p in capture['commands']+[v for v in capture['acb_packets'] if v['direction']=='out']):
            raise CaptureError('metadata-only observation unexpectedly submitted controller traffic')
    return dict(status='POST_CLOSE_NATIVE_TERMINAL_AND_DEBT_ZERO_CORROBORATED',samples=len(samples),
                elapsed_ns=row['end_monotonic_ns']-row['start_monotonic_ns'],
                callback_drain_proved=False,nocp_accuracy_proved=False,safe_reuse=False,
                scope='Instantauthorized Native counts plus independentoriginalUSB/NOCP oracle;noFree/refdrain,firmwaretruth orfutureidleness')
