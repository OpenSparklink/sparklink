#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded existing QEMU request metadata; logical cancel is not physical drain."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from ws73_capture import CaptureError

REQUIRED = {'usb_host_req_data', 'usb_host_req_complete', 'usb_host_req_canceled',
            'usb_host_req_control', 'usb_host_req_emulated'}
BYTE_LIMIT = 32*1024*1024
LINE_LIMIT = 250000
REQUEST_LIMIT = 100000
PENDING_LIMIT = 64
REPORT_LIMIT = 64*1024*1024
HEADER = re.compile(r'^(\d+)@(\d+)\.(\d{6}):([a-z0-9_]+) (.*)$')
DEVICE = r'dev (\d+):(\d+), packet (0x[0-9a-f]+)'
DATA = re.compile(DEVICE+r', in ([01]), ep (\d+), size (\d+)$')
COMPLETE = re.compile(DEVICE+r', status (-?\d+), length (\d+)$')
CANCEL = re.compile(DEVICE+r'$')
CONTROL = re.compile(DEVICE+r', req (0x[0-9a-f]+), value (-?\d+), index (-?\d+)$')
EMULATED = re.compile(DEVICE+r', status (-?\d+)$')
NATIVE_MARKER = 'WS73_USB_OBSERVE_V1 '
NATIVE_KEYS = set(('bus device sample phase mono_ns wall_ns allocated freed pending '
    'pending_rx1 pending_tx1 pending_int3 pending_dead overflow data_cb ctrl_cb dead_cb '
    'rx1_cb rx1_bytes tx1_cb int3_cb last_cb_ns last_rx1_ns pump_calls pump_returns '
    'pump_errors pump_begin_ns pump_end_ns pump_max_ns').split())
NATIVE_COUNTERS = set(('allocated freed data_cb ctrl_cb dead_cb rx1_cb rx1_bytes '
    'tx1_cb int3_cb pump_calls pump_returns pump_errors pump_max_ns').split())
POLL_MARKER = 'WS73_USB_POLL_V1 '
POLL_KEYS = set('bus device sample before_ns after_ns wall_ns count result errno error fds'.split())


REQUEST_MARKER = 'WS73_USB_REQUEST_V1 '
REQUEST_KEYS = set('ordinal id bus device ep phase mono_ns live result requested actual status'.split())


def parse_requests(text, targets):
    """Finite observed prefix, never a terminal/drain or delivery verdict.

    Saved bus/address identify the allocation, not the current device number or
    Native generation. Caller must bind targets and logs to an exact VM manifest.
    Cancellation return is not completion. Free means entry before deallocation.
    """
    if (not targets or len(text.encode()) > BYTE_LIMIT or not text.endswith('\n')
            or len(text.splitlines()) > LINE_LIMIT):
        raise CaptureError('bounded complete request log and explicit targets required')
    requests = {}; events = []; last_ns = 0
    for line in text.splitlines():
        if 'WS73_TEST_' in line or 'WS73_USB_REQUEST_BUDGET' in line:
            raise CaptureError('injection or exhausted observation budget')
        if 'WS73_USB_REQUEST' not in line:
            continue
        if line.count(REQUEST_MARKER) != 1 or len(line) > 1024:
            raise CaptureError('complete bounded request marker required')
        row = {}
        for token in line.split(REQUEST_MARKER, 1)[1].split():
            if token.count('=') != 1:
                raise CaptureError('typed request metadata required')
            key, value = token.split('=')
            if key not in REQUEST_KEYS or key in row:
                raise CaptureError('duplicate/unknown request field')
            if key != 'phase':
                if not re.fullmatch(r'0|-?[1-9][0-9]{0,19}', value):
                    raise CaptureError('bounded request integer required')
                value = int(value)
            row[key] = value
        if set(row) != REQUEST_KEYS:
            raise CaptureError('all request fields required')
        phase = row['phase']; ident = row['id']
        if (phase not in ('alloc', 'submit', 'cancel', 'callback', 'free')
                or row['ordinal'] != len(events) + 1 or row['ordinal'] > 4096
                or not 0 < ident < 2**64 - 1
                or (row['bus'], row['device']) not in targets
                or not (0 <= row['ep'] <= 15 or 129 <= row['ep'] <= 143)
                or row['live'] not in (0, 1)
                or not last_ns <= row['mono_ns'] < 2**63 or row['mono_ns'] <= 0
                or not 0 <= row['requested'] < 2**31):
            raise CaptureError('request identity/order/clock/budget required')
        if phase == 'alloc':
            if ident != len(requests) + 1 or row['live'] != 1 or row['requested'] != 0:
                raise CaptureError('fresh contiguous allocation identity required')
            requests[ident] = dict(allocation=row, events=[], submit=None,
                                   callback=False, released=False, detached=False)
        if ident not in requests:
            raise CaptureError('request transition without allocation')
        state = requests[ident]; origin = state['allocation']
        if (state['released'] or any(row[k] != origin[k] for k in ('bus','device','ep'))
                or state['detached'] and row['live']):
            raise CaptureError('retired/detached request or identity changed')
        if phase in ('submit', 'cancel'):
            if row['result'] not in (0, -1, -2, -3, -4, -5, -6, -7, -8, -9, -10, -11, -12, -99):
                raise CaptureError('known libusb return required')
        elif row['result'] != 0:
            raise CaptureError('unexpected request result')
        if phase == 'callback':
            if (state['submit'] != 0 or state['callback']
                    or not row['live'] and not state['detached']
                    or not 0 <= row['status'] <= 6
                    or not 0 <= row['actual'] < 2**31
                    or row['status'] == 0 and row['actual'] > row['requested']):
                raise CaptureError('actual submitted callback required')
            state['callback'] = True
        elif row['actual'] != -1 or row['status'] != -1:
            raise CaptureError('only callback has native status/actual length')
        if phase == 'submit':
            if state['submit'] is not None or not row['live'] or len(state['events']) != 1:
                raise CaptureError('one original submit return required')
            state['submit'] = row['result']; state['requested'] = row['requested']
        elif phase in ('callback', 'cancel', 'free') and state['submit'] is not None:
            if row['requested'] != state['requested']:
                raise CaptureError('submitted request length changed')
        if phase == 'cancel':
            if state['submit'] != 0 or state['callback'] or state['detached'] or row['live']:
                raise CaptureError('cancel is detached submitted obligation, not callback')
        if phase == 'free':
            if state['submit'] == 0 and not state['callback']:
                raise CaptureError('submitted obligation freed without native callback')
            state['released'] = True
        state['detached'] |= not row['live']
        state['events'].append(row); events.append(row); last_ns = row['mono_ns']
    if not events or {(s['allocation']['bus'],s['allocation']['device']) for s in requests.values()} != targets:
        raise CaptureError('each declared allocation must be observed')
    result = dict(version=1, status='FINITE_REQUEST_OBSERVATIONS_NOT_QUALIFIED',
        events=events, pending=[i for i,s in requests.items() if not s['released']],
        pending_callbacks=[i for i,s in requests.items() if s['submit']==0 and not s['callback']],
        submit_errors=[i for i,s in requests.items() if s['submit'] not in (None,0)],
        detached_callbacks=[i for i,s in requests.items() if any(e['phase']=='callback' and not e['live'] for e in s['events'])],
        physical_drain_qualified=False, recovery_qualified=False, business_delivery_qualified=False,
        scope='Observed process-local IDs and call-site metadata only. Unclosed requests remain explicit. Free records precede deallocation; logs alone cannot prove final drain, host-kernel callback order, firmware consumption, Native generation, RF or peer delivery.')
    encoded_report(result)
    return result


def parse_native_poll(text, targets):
    return _parse_native_poll(text,targets,terminal_required=True)


def parse_live_native_poll(text, targets):
    """Explicit bounded live prefix; never a terminal or qualification proof."""
    return _parse_native_poll(text,targets,terminal_required=False)


def _parse_native_poll(text, targets, *, terminal_required):
    """Pair bounded non-consuming poll snapshots with native heartbeat rows.

    Discrete readiness bits are not continuous USB completion availability,
    endpoint attribution, hardware liveness or a controller/generation grant.
    """
    native=_parse_native(text,targets,terminal_required=terminal_required)
    snapshots={(r['bus'],r['device']):r['samples']for r in native['devices']}
    rows={target:[]for target in targets}
    pending_pair=None
    for line in text.splitlines():
        if NATIVE_MARKER in line:
            if pending_pair is not None:raise CaptureError('native sample missing its original following poll observation')
            fields=dict(token.split('=')for token in line.split(NATIVE_MARKER,1)[1].split())
            pending_pair=int(fields['bus']),int(fields['device']),int(fields['sample'])
            continue
        if POLL_MARKER not in line:continue
        if len(line)>2048 or line.count(POLL_MARKER)!=1:raise CaptureError('poll observer record bound')
        row={}
        for token in line.split(POLL_MARKER,1)[1].split():
            if token.count('=')!=1:raise CaptureError('typed poll observer fields required')
            key,value=token.split('=')
            if key not in POLL_KEYS or key in row:raise CaptureError('duplicate/unknown poll observer field')
            if key=='fds':row[key]=value
            else:
                if not re.fullmatch(r'0|-?[1-9][0-9]{0,19}',value)or not -2**63<int(value)<2**64:
                    raise CaptureError('bounded poll observer integer required')
                row[key]=int(value)
        if set(row)!=POLL_KEYS:raise CaptureError('complete poll observer record required')
        key=row['bus'],row['device']
        if key not in rows:raise CaptureError('poll observer outside declared leaf identities')
        if pending_pair!=(row['bus'],row['device'],row['sample']):
            raise CaptureError('poll snapshot must follow its original native sample')
        pending_pair=None
        history=rows[key];index=len(history)
        if row['sample']!=index+1 or index>=len(snapshots[key]):
            raise CaptureError('contiguous native/poll snapshot pairing required')
        current=snapshots[key][index]
        if (row['error']or row['errno']or not 1<=row['count']<=8
                or not 0<=row['result']<=row['count']):
            raise CaptureError('poll lookup/syscall/identity/budget failure is not no-readiness')
        if (not current['mono_ns']<=row['before_ns']<=row['after_ns']<2**63
                or not 0<row['wall_ns']<2**63 or row['wall_ns']<current['wall_ns']
                or(index and row['before_ns']<history[-1]['after_ns'])
                or(index+1<len(snapshots[key])and row['after_ns']>snapshots[key][index+1]['mono_ns'])):
            raise CaptureError('same-host poll snapshot clock/pairing bounds')
        fds=[];identities=set();numbers=set()
        for item in row['fds'].split(';'):
            if not re.fullmatch(r'[0-9]+:[0-9]+:[0-9]+:[0-9]+:[0-9]+',item):
                raise CaptureError('complete typed poll fd observations required')
            fd,events,revents,bus,device=map(int,item.split(':'))
            if (not 0<=fd<2**31 or fd in numbers or events not in(1,4,5)
                    or not 0<=revents<65536 or revents&~0x3d):
                raise CaptureError('unique finite Linux poll descriptor/profile required')
            numbers.add(fd)
            if (bus,device)!=(0,0):
                if (bus,device)not in targets or(bus,device)in identities:
                    raise CaptureError('unique observed USB fd within declared identities required')
                identities.add((bus,device))
            fds.append(dict(fd=fd,events=events,revents=revents,bus=bus,device=device))
        if len(fds)!=row['count']or key not in identities or sum(v['revents']!=0 for v in fds)!=row['result']:
            raise CaptureError('complete original fd/readiness cardinality and own USB identity required')
        row['fds']=fds;row['native_phase']=current['phase'];history.append(row)
    if pending_pair is not None or any(len(rows[k])!=len(snapshots[k])for k in rows):
        raise CaptureError('missing native/poll pair or declared endpoint')
    result=dict(version=1,status=('FINITE_LIBUSB_POLL_METADATA_OBSERVED'if terminal_required else'LIVE_LIBUSB_POLL_PREFIX_NOT_QUALIFIED'),native=native,
        poll_devices=[dict(bus=b,device=d,samples=r)for(b,d),r in sorted(rows.items())],
        continuous_completion_availability_proved=False,physical_drain_qualified=False,
        credit_truth_qualified=False,performance_qualified=False,
        scope='Discrete same-process poll(0)/proc/stat metadata paired with finite native snapshots only. Non-consuming, no USB operation. Unknown host-kernel implementation, snapshot blind intervals, endpoint attribution and firmware/RF behavior remain explicit limits;no peer delivery, generation authenticity, physical/ref drain or performance proof.')
    encoded_report(result)
    return result


def parse_native(text, targets):
    return _parse_native(text,targets,terminal_required=True)


def _parse_native(text, targets, *, terminal_required):
    """Dedicated QEMU fixture metadata only, never physical drain/RF proof.

    The extra 100ms heartbeat changes scheduling. Callback-entry counters are
    meaningful only with the separately checked real no-injection execution.
    They describe libusb delivery to QEMU, not kernel controller readiness.
    """
    if (not isinstance(text,str) or len(text.encode())>BYTE_LIMIT or not text.endswith('\n')
            or not targets or len(targets)>4
            or any(type(b)is not int or type(d)is not int or not 0<b<65536 or not 0<d<128 for b,d in targets)):
        raise CaptureError('bounded closed native observer log and explicit identities required')
    lines=text.splitlines()
    if len(lines)>LINE_LIMIT:raise CaptureError('native observer line budget')
    rows={target:[]for target in targets}
    for line in lines:
        if 'WS73_TEST_RUNTIME_'in line or 'WS73_TEST_ENUMERATION_RESET'in line:
            raise CaptureError('injected or held native callbacks excluded')
        if NATIVE_MARKER not in line:continue
        if len(line)>2048 or line.count(NATIVE_MARKER)!=1:raise CaptureError('native observer record bound')
        tokens=line.split(NATIVE_MARKER,1)[1].split();row={}
        for token in tokens:
            if token.count('=')!=1:raise CaptureError('typed native observer fields required')
            key,value=token.split('=')
            if key not in NATIVE_KEYS or key in row:raise CaptureError('missing/duplicate native observer field')
            if key=='phase':
                if value not in('tick','closing','drained'):raise CaptureError('native observer budget or phase failure')
                row[key]=value
            else:
                if not re.fullmatch(r'0|[1-9][0-9]{0,19}',value)or int(value)>=2**64:
                    raise CaptureError('bounded unsigned native observation required')
                row[key]=int(value)
        if set(row)!=NATIVE_KEYS:raise CaptureError('complete native observer record required')
        key=row['bus'],row['device']
        if key not in rows:raise CaptureError('native observer outside declared leaf identities')
        history=rows[key];previous=history[-1]if history else None
        if row['sample']!=len(history)+1 or row['sample']>4098 or row['overflow']:
            raise CaptureError('finite contiguous native observer sequence required')
        if row['freed']>row['allocated']or row['pending']!=row['allocated']-row['freed']or row['pending']>128:
            raise CaptureError('native request allocation/free observations inconsistent')
        if (any(row[k]>row['pending']for k in('pending_rx1','pending_tx1','pending_int3','pending_dead'))
                or row['pending_rx1']+row['pending_tx1']+row['pending_int3']>row['pending']
                or row['dead_cb']>row['ctrl_cb']+row['data_cb']
                or row['rx1_cb']+row['tx1_cb']+row['int3_cb']>row['data_cb']
                or row['ctrl_cb']+row['data_cb']>row['allocated']
                or row['pump_returns']>row['pump_calls']or row['pump_errors']>row['pump_returns']):
            raise CaptureError('native callback/endpoint/pump counter bounds')
        if (not 0<row['mono_ns']<2**63 or not 0<row['wall_ns']<2**63
                or any(row[k]>row['mono_ns']for k in('last_cb_ns','last_rx1_ns','pump_begin_ns','pump_end_ns'))):
            raise CaptureError('same-host native clock observation bounds')
        if previous:
            if (row['mono_ns']<previous['mono_ns']or row['wall_ns']<previous['wall_ns']
                    or any(row[k]<previous[k]for k in NATIVE_COUNTERS)
                    or previous['phase']=='drained'
                    or(previous['phase']=='closing'and row['phase']!='drained')):
                raise CaptureError('native observer counter/clock/close regression')
        if row['phase']=='drained'and(not previous or previous['phase']!='closing'):
            raise CaptureError('drain-loop snapshot must follow timer retirement')
        history.append(row)
    if any(len(r)<2 or r[-1]['phase']!=('drained'if terminal_required else'tick')for r in rows.values()):
        raise CaptureError('missing native observer terminal or endpoint')
    result=dict(version=1,status=('FINITE_NATIVE_CALLBACK_METADATA_OBSERVED'if terminal_required else'LIVE_NATIVE_PREFIX_NOT_QUALIFIED'),
        devices=[dict(bus=b,device=d,samples=r)for(b,d),r in sorted(rows.items())],
        physical_drain_qualified=False,credit_truth_qualified=False,performance_qualified=False,
        scope='Original callbacks/free/event-pump counters plus finite heartbeat, not physical USB/RF readiness, implementation refinement, payload delivery, performance or full reference drain. Logical cancellation and native callback are distinct.')
    encoded_report(result)
    return result


def encoded_report(value):
    """Bound the actual normative CLI bytes, including indentation/newline."""
    text=json.dumps(value,indent=2)+'\n'
    if len(text.encode())>REPORT_LIMIT:raise CaptureError('QEMU request report byte budget')
    return text


def parse(text, targets):
    if (not isinstance(text,str) or len(text.encode())>BYTE_LIMIT or not text.endswith('\n')
            or not targets or any(type(b)is not int or type(d)is not int or not 0<b<65536 or not 0<d<128 for b,d in targets)):
        raise CaptureError('bounded closed trace and explicit USB identities required')
    lines=text.splitlines()
    if len(lines)>LINE_LIMIT:raise CaptureError('QEMU lifecycle line budget')
    pending={};rows=[];unmapped=Counter();peaks=Counter()
    for ordinal,line in enumerate(lines,1):
        if len(line)>2048:raise CaptureError('QEMU lifecycle line length budget')
        h=HEADER.fullmatch(line)
        if h is None:raise CaptureError('complete original QEMU trace record required')
        pid,sec,usec,event,body=h.groups();stamp=int(sec)*1000000000+int(usec)*1000
        if int(pid)<=0 or not 0<stamp<2**63:raise CaptureError('bounded original host trace clock required')
        # Trace backend can interleave emitting threads. Do not sort records or
        # invent cross-thread happens-before from their wall-clock timestamps.
        if event not in REQUIRED:continue
        match={'usb_host_req_data':DATA,'usb_host_req_complete':COMPLETE,'usb_host_req_canceled':CANCEL, 'usb_host_req_control':CONTROL, 'usb_host_req_emulated':EMULATED}[event].fullmatch(body)
        if match is None:raise CaptureError('typed QEMU data request record required')
        bus,device,packet=match.groups()[:3];bus,device=int(bus),int(device)
        if (bus,device)not in targets:raise CaptureError('QEMU request outside the declared owner set')
        if int(packet,16)==0:raise CaptureError('nonnull QEMU packet identity required')
        key=bus,device,packet
        point=dict(line=ordinal,host_wall_ns=stamp,thread=int(pid))
        if event in ('usb_host_req_data','usb_host_req_control'):
            if key in pending:raise CaptureError('request pointer reused before an observed logical terminal')
            if len(rows)>=REQUEST_LIMIT or len(pending)>=PENDING_LIMIT:raise CaptureError('finite request/pending budget')
            row=dict(id=len(rows),bus=bus,device=device,packet=packet,begin=point,
                     terminal=None,physical_drain_qualified=False)
            if event=='usb_host_req_data':
                direction,ep,size=map(int,match.groups()[3:])
                if not 1<=ep<=15 or not 0<size<=16*1024*1024:raise CaptureError('bounded endpoint request size required')
                row.update(kind='DATA',direction=direction,endpoint=ep,size=size)
            else:
                request,value,index=match.groups()[3:];request=int(request,16);value,index=int(value),int(index)
                if not 0<=request<65536 or not all(-2**31<=v<2**31 for v in(value,index)):
                    raise CaptureError('bounded control request metadata required')
                row.update(kind='CONTROL',request=request,value=value,index=index)
            rows.append(row);pending[key]=row
            if row['kind']=='DATA':
                endpoint=(bus,device,row['direction'],row['endpoint'])
                peaks[endpoint]=max(peaks[endpoint],sum(r['kind']=='DATA'and(r['bus'],r['device'],r['direction'],r['endpoint'])==endpoint for r in pending.values()))
            continue
        row=pending.pop(key,None)
        if row is None:
            # Preserve missing/duplicate terminals as unknown. Never guess a
            # control submission or silently grant a closed request proof.
            unmapped[event]+=1
            continue
        if point['host_wall_ns']<row['begin']['host_wall_ns']:
            raise CaptureError('same request terminal predates its recorded admission')
        if event=='usb_host_req_canceled':
            row['terminal']=point|dict(kind='LOGICAL_CANCEL',physical_obligation_closed=False)
        elif event=='usb_host_req_emulated':
            status=int(match.groups()[3])
            if row['kind']!='CONTROL' or not -4096<=status<=0:
                raise CaptureError('emulated control return is not a physical data completion')
            row['terminal']=point|dict(kind='EMULATED_CONTROL_RETURN',status=status,physical_obligation_closed=False)
        else:
            status,length=map(int,match.groups()[3:])
            if not -4096<=status<=0 or not 0<=length<=row.get('size',65535):
                raise CaptureError('bounded observed USB completion required')
            row['terminal']=point|dict(kind='QEMU_COMPLETION',status=status,length=length,
                                      physical_obligation_closed=False)
    terminal_counts=Counter(r['terminal']['kind']if r['terminal']is not None else'PENDING'for r in rows)
    if not rows:raise CaptureError('nonempty original data request observations required')
    if sum(terminal_counts.values())!=len(rows):raise CaptureError('request accounting mismatch')
    result=dict(version=1,status=('LOGICAL_USB_REQUESTS_CLOSED'if not pending and not unmapped
                                        else'INCOMPLETE_PENDING_OR_UNMAPPED_LOGICAL_REQUESTS'),
                lines=len(lines),requests=rows,terminal_counts=dict(terminal_counts),
                pending=len(pending),unmapped_without_observed_request=dict(unmapped),
                endpoint_logical_peaks=[dict(bus=b,device=d,direction=i,endpoint=e,peak=n)for(b,d,i,e),n in sorted(peaks.items())],
                physical_drain_qualified=False,credit_truth_qualified=False,
                scope=['Each typed request incarnation uses its original trace admission and at most one observed logical terminal.',
                       'Cancel ends packet association only; libusb callback/free/physical obligation may remain unobserved.',
                       'Completion is QEMU callback or synchronous return metadata, not peer protocol/application delivery or full drain.',
                       'Emulated standard USB control returns are not physical data, DLI Complete or application success; unmapped terminals remain unknown.',
                       'No host/guest absolute-time subtraction or authenticated payload identity.'])
    encoded_report(result)
    return result


def analyze(directory):
    root=Path(directory).resolve(strict=True)
    manifest=json.loads((root/'manifest.json').read_text())
    if (type(manifest.get('qemu_exit'))is not int or manifest['qemu_exit']!=0
            or manifest.get('status')not in('FAIL','PASSTHROUGH_SUPPORT_PASS')
            or not isinstance(manifest.get('native_vm'),dict)):
        raise CaptureError('original terminal real QEMU run required')
    if any(manifest.get(k)is not False for k in('synthetic_empty_bulk','synthetic_hotplug','synthetic_warm',
                                               'artificial_guest_transport_fault','early_bootstrap_fault_requested')):
        raise CaptureError('synthetic USB sources excluded')
    materials=[]
    for name in ('usb-lifecycle.events','usb-lifecycle.log'):
        p=root/name;bound=4096 if name.endswith('.events')else BYTE_LIMIT
        with p.open('rb')as f:data=f.read(bound+1)
        if len(data)>bound:raise CaptureError('original lifecycle file byte budget')
        matches=[r for r in manifest['host_lifecycle_files']if Path(r['path']).name==name]
        digest=hashlib.sha256(data).hexdigest()
        if len(matches)!=1 or matches[0]['sha256']!=digest:raise CaptureError('frozen original lifecycle material required')
        materials.append(dict(path=name,sha256=digest,bytes=len(data)))
        if name.endswith('.events'):
            events=data.decode().splitlines()
            if len(events)!=len(set(events))or not REQUIRED<=set(events):raise CaptureError('complete cancellation observation event contract required')
        else:text=data.decode()
    ports=manifest['physical_resource_allocation']['selected_ports']
    if type(ports)is not list or not 1<=len(ports)<=4 or any(type(p)is not str for p in ports)or len(set(ports))!=len(ports):
        raise CaptureError('explicit original USB leaf allocation required')
    targets={(manifest['inventory_before'][p]['bus'],manifest['inventory_before'][p]['address'])for p in ports}
    proof=parse(text,targets)
    result=dict(status='QEMU_REQUEST_METADATA_OBSERVED_NOT_BUSINESS_QUALIFIED',original_result=manifest['status'],
                original_gate_qualified=False,materials=materials,logical=proof,
                scope='Read-only existing collector/parser; no USB/VM operation, credit refund, physical drain or application delivery claim.')
    encoded_report(result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path)
    import sys
    sys.stdout.write(encoded_report(analyze(parser.parse_args().run)))
