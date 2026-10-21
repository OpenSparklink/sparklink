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
