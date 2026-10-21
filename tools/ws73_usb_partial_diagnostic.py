# SPDX-License-Identifier: GPL-2.0-only
"""Explicit single-device QMP diagnostic; never business/recovery qualification."""
import hashlib
import json
from pathlib import Path
import re
import time

from ws73_capture import CaptureError,read_live_prefix
from ws73_usb_lifecycle import BYTE_LIMIT,parse,parse_live_native_poll

QEMU_SHA256='5b89e4f5dac5338d1ed7b1c029aa906e68d1276aab15343eee31b9966c400c01'
FIELD='usb_partial_rx_diagnostic'
OPTION='usb_partial_rx_target'
RX_END='WS73_USB_RX_END_V1 '
PEER_OF_UNFINISHED='peer-of-unfinished'


def target_value(value):
    """Only a fixed slot or the unique PB peer inside the explicit pair."""
    if value in ('0','1'):return int(value)
    if value==PEER_OF_UNFINISHED:return value
    raise ValueError('target must be0,1 orpeer-of-unfinished within the explicit pair')


def valid_target(value):
    return type(value)is int and value in(0,1)or type(value)is str and value==PEER_OF_UNFINISHED


def requested(args):
    target=getattr(args,OPTION,None)
    if target is None:return None
    from ws73_benchmark_ssap import requested as service,profile
    allowed={'qmp_hotplug','connection_verify','channel_benchmark_dynamic','channel_benchmark_ssap_owned',
             'channel_benchmark_credit_observe','session_service_observe'}
    if (not valid_target(target)or args.command!='run'
            or len(getattr(args,'ports',[]))!=2
            or any(type(v)is bool and v and k not in allowed for k,v in vars(args).items())
            or getattr(args,'connection_advertising','fixed-t')!='negotiable-t'
            or getattr(args,'qmp_hotplug',False)is not True
            or getattr(args,'connection_verify',False)is not True
            or service(args)!=profile(observe=True)
            or any(getattr(args,k,False)for k in ('fault_recovery','early_bootstrap_fault',
                'daemon_cancel_remove','channel_daemon_crash','initializer_lifecycle','hotplug','warm','empty_bulk'))):
        raise CaptureError('partial RX diagnostic requires separate original sequential Owned benchmark VM')
    return target


def validate_inputs(package):
    if 'native_vm'not in package or hashlib.sha256(Path(package['qemu']['path']).read_bytes()).hexdigest()!=QEMU_SHA256:
        raise CaptureError('exact new RX-terminal observer native QEMU required')
    for name in ('ws73_target.py','ws73_usb_partial_diagnostic.py','ws73_usb_lifecycle.py'):
        expected=hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        rows=[v for v in package['inputs']if Path(v['path']).name==name]
        if len(rows)!=1 or rows[0]['sha256']!=expected:raise CaptureError('fresh partial RX diagnostic source required')


def read_prefix(path,limit):
    with Path(path).open('rb')as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise CaptureError('partial RX diagnostic byte budget')
    # A live append fragment is not a record. The retained decision includes
    # only this exact closed prefix and never qualifies a whole capture.
    closed=raw if raw.endswith(b'\n')else raw[:raw.rfind(b'\n')+1]
    return closed


def eligibility(proof,host,now):
    rows={ (r['bus'],r['device']):r['samples'][-1]for r in proof['native']['devices']}
    polls={(r['bus'],r['device']):r['samples'][-1]for r in proof['poll_devices']}
    if set(rows)!=set(host)or set(polls)!=set(host):raise CaptureError('exact two original USB identities required')
    for key,row in rows.items():
        if (row['phase']!='tick'or row['pending_rx1']!=1 or row['pending_dead']
                or not row['last_rx1_ns']or not 2_000_000_000<=row['mono_ns']-row['last_rx1_ns']<4_000_000_000
                or not 0<=now-row['mono_ns']<=750_000_000 or polls[key]['result']):return None
    return dict(native=list(rows.values()),poll=list(polls.values()))


def unfinished_application_prefix(capture,request,target):
    """Select raw unfinished PB and a real slktest prefix, not a delivered PDU."""
    from ws73_benchmark import frame
    if {v['owner']['port']for v in request['owners']}!={'1-1','1-2'}:
        raise CaptureError('exact original guest port/slot mapping required')
    source=next(v for v in request['owners']if v['owner']['port']!=f'1-{target+1}')
    owner=source['owner'];handle=source['object']['handle']
    packets=[p for p in capture['acb_packets']if p['direction']=='out'
        and(p['bus'],p['device'],p['handle'])==(owner['bus'],owner['device'],handle)
        and p['wall_ns']>=request['start_wall_ns']]
    if not packets or packets[-1]['boundary']not in(1,2):return None
    first=next((i for i in range(len(packets)-1,-1,-1)if packets[i]['boundary']==1),None)
    if first is None or any(p['boundary']not in(1,2)for p in packets[first:]):return None
    body=bytes.fromhex(packets[first]['data'])
    if len(body)!=254 or body[2:5]!=b'\xfb\x07\xf1'or body[5:13]!=b'SLKSOCK1':return None
    # The existing application decoder validates only the known prefix here.
    # Passing its prefix length does NOT establish all 2042 business bytes.
    known=body[5:]
    if known[28]not in(0,1):return None
    _,nonce,sequence=frame(known.hex(),len(known),known[28])
    return dict(source=owner,handle=handle,first_record=packets[first]['record'],last_record=packets[-1]['record'],
                prefix_sha256=hashlib.sha256(body).hexdigest(),nonce_sha256=hashlib.sha256(nonce).hexdigest(),
                sequence=sequence,known_prefix_bytes=len(known),whole_PDU_qualified=False)


def select_target(capture,request,selector):
    """No device discovery: evaluate only the two already bound guest slots."""
    if not valid_target(selector):raise CaptureError('explicit pair diagnostic target required')
    slots=range(2)if selector==PEER_OF_UNFINISHED else(selector,)
    candidates=[]
    for slot in slots:
        witness=unfinished_application_prefix(capture,request,slot)
        if witness is not None:candidates.append((slot,witness))
    return candidates[0]if len(candidates)==1 else None


class Coordinator:
    def __init__(self,share,output,record,target,ports):
        self.share=Path(share);self.output=Path(output);self.record=record;self.target=target;self.ports=ports
        self.next_probe=0;self.observations=[]
        record.update(version=1,method='ONE_QMP_DEVICE_DEL_DURING_UNFINISHED_PB_RX_QUIET',target=target,
                      attempted=False,complete=False,live_observations=self.observations,
                      physical_acceptance=False,natural_recovery_acceptance=False)

    def poll(self,monitor,owner):
        if self.record['attempted']or self.record.get('terminal'):return
        now=time.monotonic_ns()
        if now<self.next_probe:return
        self.next_probe=now+500_000_000
        path=self.share/'application/passthrough-control/benchmark-role-1.request.json'
        if not path.exists():return
        if(self.share/'benchmark-role/phase-1/run.json').exists():
            self.record['terminal']='ROLE_TERMINAL_WITHOUT_DIAGNOSTIC';return
        with path.open('rb')as f:raw=f.read(1_048_577)
        if len(raw)>1_048_576:raise CaptureError('bounded original role request required')
        request=json.loads(raw)
        from ws73_socket_benchmark import validate_role_request
        from ws73_benchmark_ssap import FIELD as service_field,profile
        validate_role_request(request,1,live=True)
        if request.get(service_field)!=profile(observe=True):raise CaptureError('original sequential SSAP observer request required')
        hosts=[owner(i)for i in range(2)];targets={(v['bus'],v['address'])for v in hosts}
        text=read_prefix(self.output/'qemu-stderr.log',BYTE_LIMIT)
        if not text or text.rfind(b'WS73_USB_OBSERVE_V1 ')>text.rfind(b'WS73_USB_POLL_V1 '):return
        proof=parse_live_native_poll(text.decode(),targets)
        selected=eligibility(proof,targets,time.monotonic_ns())
        if selected is None:return
        capture=read_live_prefix(self.output,self.share/'ws73.pcap',
            {(o['owner']['bus'],o['owner']['device'])for o in request['owners']},self.observations)
        if capture is None:return
        selection=select_target(capture,request,self.target)
        if selection is None:return
        target,witness=selection
        lifecycle=read_prefix(self.output/'usb-lifecycle.log',BYTE_LIMIT)
        logical=parse(lifecycle.decode(),targets)
        h=hosts[target];key=h['bus'],h['address']
        pending=[r for r in logical['requests']if r['kind']=='DATA'and r['direction']==1 and r['endpoint']==1
                 and(r['bus'],r['device'])==key and r['terminal']is None]
        if len(pending)!=1 or pending[0]['size']!=20480:raise CaptureError('one exact pending original bulk RX request required')
        # Recheck the same native state after the pcap observation; this still
        # is a controlled admin action, not a race-free generation grant.
        fresh=read_prefix(self.output/'qemu-stderr.log',BYTE_LIMIT)
        if not fresh or fresh.rfind(b'WS73_USB_OBSERVE_V1 ')>fresh.rfind(b'WS73_USB_POLL_V1 '):return
        proof2=parse_live_native_poll(fresh.decode(),targets)
        selected2=eligibility(proof2,targets,time.monotonic_ns())
        if selected2 is None or any(a['last_rx1_ns']!=b['last_rx1_ns']for a,b in zip(selected['native'],selected2['native'],strict=True)):return
        for i in range(2):
            path=f'/machine/peripheral/ws73_{i}'
            if monitor.execute('qom-get',dict(path=path,property='attached'))is not True:raise CaptureError('original attached USB object required')
            for prop in ('host-reset','guest-reset','guest-resets-all','kernel-driver-detach','test-enumeration-reset-once'):
                if monitor.execute('qom-get',dict(path=path,property=prop))is not False:raise CaptureError('reset/detach experiments excluded')
        if owner(target)!=h:raise CaptureError('USB ownership changed before partial diagnostic')
        for name,data in (('partial-rx-native-prefix.log',fresh),('partial-rx-lifecycle-prefix.log',lifecycle)):
            path=self.output/name
            with path.open('xb')as stream:stream.write(data)
            path.chmod(0o600)
        self.record.update(attempted=True,target=target,target_selector=self.target,host=h,original_request=request,request_sha256=hashlib.sha256(raw).hexdigest(),
            candidate=selected2,pending_request=pending[0],wire_prefix=witness,live_observations=self.observations,
            native_prefix_sha256=hashlib.sha256(fresh).hexdigest(),lifecycle_prefix_sha256=hashlib.sha256(lifecycle).hexdigest(),
            before_monotonic_ns=time.monotonic_ns(),before_wall_ns=time.time_ns())
        # Existing normal QEMU teardown owns cancellation/drain. No transfer
        # length/status is fabricated and this object is never re-added here.
        monitor.execute('device_del',{'id':f'ws73_{target}'})
        self.record.update(after_monotonic_ns=time.monotonic_ns(),after_wall_ns=time.time_ns(),action_acknowledged=True)


def rx_ends(text,targets):
    if (not isinstance(text,str)or len(text.encode())>BYTE_LIMIT or not text.endswith('\n')
            or not targets or len(targets)>4
            or any(type(b)is not int or type(d)is not int or not 0<b<65536 or not 0<d<128 for b,d in targets)
            or 'WS73_USB_RX_END_BUDGET_V1 'in text or 'WS73_TEST_RUNTIME_'in text
            or len(text.splitlines())>250000):raise CaptureError('bounded complete native RX terminal log required')
    rows=[];counts={k:0 for k in targets};requests=set()
    pattern=re.compile(r'bus=(\d+) device=(\d+) ordinal=(\d+) request=(\d+) packet=(0x[0-9a-f]+) allocation_ns=(\d+) callback_ns=(\d+) wall_ns=(\d+) requested=(\d+) actual=(\d+) status=(\d+) live=([01]) bounded=1 sha256=([0-9a-f]{64})$')
    for line in text.splitlines():
        if RX_END not in line:continue
        if len(line)>2048 or line.count(RX_END)!=1:raise CaptureError('native RX terminal line budget')
        m=pattern.fullmatch(line.split(RX_END,1)[1])
        if m is None:raise CaptureError('typed bounded RX terminal metadata required')
        values=m.groups();b,d,n,r=map(int,values[:4]);packet=values[4];a,c,w,asked,actual,status,live=map(int,values[5:12]);digest=values[12];key=b,d
        if (key not in counts or n!=counts[key]+1 or n>128 or not 0<r<2**64 or(key,r)in requests
                or int(packet,16)==0 or not 0<a<=c<2**63 or not 0<w<2**63
                or not 0<=actual<=asked<=20480 or not asked or not 1<=status<=6
                or(actual==0 and digest!=hashlib.sha256(b'').hexdigest())):raise CaptureError('native RX terminal identity/count/length/clock bounds')
        counts[key]=n;requests.add((key,r));rows.append(dict(bus=b,device=d,ordinal=n,request=r,packet=packet,
            allocation_ns=a,callback_ns=c,wall_ns=w,requested=asked,actual=actual,status=status,live=bool(live),sha256=digest))
    return rows


def finalize(record,text,targets):
    """Original callback report after a controlled detach, never a delivery PASS."""
    if not record.get('attempted'):
        record.update(status='DIAGNOSTIC_NOT_EXECUTED',complete=False);return
    if record.get('action_acknowledged')is not True:raise CaptureError('original QMP action acknowledgement required')
    host=record['host'];key=host['bus'],host['address'];pending=record['pending_request']
    selected=next(v for v in record['candidate']['native']if(v['bus'],v['device'])==key)
    rows=rx_ends(text,targets)
    matches=[r for r in rows if(r['bus'],r['device'],r['packet'])==(*key,pending['packet'])
        and r['allocation_ns']<=selected['mono_ns']
        and record['before_monotonic_ns']<=r['callback_ns']<=record['after_monotonic_ns']+2_000_000_000]
    if len(matches)!=1:raise CaptureError('one original pending-incarnation native callback required')
    row=matches[0]
    if row['status']!=3 or row['live']or row['requested']!=pending['size']:
        raise CaptureError('actual libusb canceled callback after normal packet retirement required')
    record.update(status='CANCELED_RX_LENGTH_REPORTED_NOT_ROOT_CAUSE_OR_DELIVERY',complete=True,
        native_callback=row,reported_partial_bytes=row['actual'],nonzero_reported_partial=row['actual']>0,
        original_gate_qualified=False,natural_recovery_acceptance=False,
        scope='Native libusb canceled callback length/digest only. Zero does not prove no hardware partial progress;nonzero is not whole HCC/application delivery. No endpoint/firmware/RF RCA,credit refund or kernel/reference drain qualification.')
