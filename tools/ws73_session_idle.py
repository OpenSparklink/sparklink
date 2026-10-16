# SPDX-License-Identifier: GPL-2.0-only
"""VM-only observation of the actual C Session worker; no synthetic wakeup.

A dedicated function-trace instance brackets a quiescent interval between real
business and the existing controlled-prefix test. This measures call absence,
not CPU utilization, concurrency proof or RF/latency qualification.
"""
import hashlib
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from ws73_channel_grant import send, receive
from sparklink.structs import SleChannelTxStatus
from ws73_management_setup import decode


class SessionIdleTrace:
    def __init__(self, record, save):
        if os.geteuid()!=0 or not Path('/scratch-root-uuid').is_file() or Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU':
            raise ValueError('isolated scratch VM only;never mount tracefs on host')
        self.record=record;self.save=save;self.root=Path('/sys/kernel/tracing');self.finished=False
        if not (self.root/'available_tracers').exists():
            subprocess.run(['/bin/mount','-t','tracefs','tracefs',str(self.root)],check=True)
        names=[v.split()[0] for v in (self.root/'available_filter_functions').read_text().splitlines() if v.split() and v.split()[0]=='sl_work']
        if names!=['sl_work']:raise ValueError('exact one instrumentable production sl_work required')
        self.path=self.root/'instances/slk_session_idle';self.path.mkdir()
        self.folder=Path('/evidence/session-idle');self.folder.mkdir()
        self.row=dict(status='TRACING_NOT_QUALIFIED',cookie=secrets.token_hex(16),function='sl_work',clock='global',pool_before=[],interval_monotonic_ns=[])
        record['session_idle']=self.row
        try:
            self.write('tracing_on','0');self.write('current_tracer','function');self.write('set_ftrace_filter','sl_work')
            self.write('trace_clock','global');self.write('trace','')
            if (self.path/'current_tracer').read_text().strip()!='function' or (self.path/'set_ftrace_filter').read_text().strip()!='sl_work' or '[global]' not in (self.path/'trace_clock').read_text():raise ValueError('exact trace instance readbacks required')
            self.row['readbacks']={name:(self.path/name).read_text().strip() for name in ['current_tracer','set_ftrace_filter','trace_clock']}
            self.write('tracing_on','1');save()
        except BaseException:
            self.close();raise

    def write(self, name, value):
        (self.path/name).write_text(value+'\n')

    def idle(self, grant):
        # Actual ordinary worker fd ioctls. No timer refresh, completion injection
        # or data path shortcut. Start only when both real ledgers/queues drained.
        deadline=time.monotonic()+2
        while True:
            for parent in grant.parents:send(parent,dict(kind='tx_status'))
            rows=[receive(parent) for parent in grant.parents]
            if any(v['stage']!='tx_status' for v in rows):raise ValueError('ordinary fd snapshot receipts required')
            samples=[decode(SleChannelTxStatus,v['value']) for v in rows]
            drained=True
            for n,v in enumerate(samples):
                o=grant.row['owners'][n]
                if (v.version,v.size,v.controller,v.generation,v.lifetime,v.handle,v.packet_maximum,v.capacity,v.reserved)!=(1,64,n,o['generation'],o['lifetime'],o['handle'],254,5,0):raise ValueError('current physical pool identity required')
                drained &= not any([v.outstanding,v.connection_debt,v.queued,v.busy,v.active_pdu_bytes,v.active_pdu_offset]) and v.flags==0
            if drained:break
            if time.monotonic()>deadline:raise TimeoutError('actual two-controller credit/queue drain before idle')
            time.sleep(.01)
        # Observation warmup, not an assertion that callbacks have drained.
        # The complete trace still rejects any work in the measured interval.
        self.row['settling_start_monotonic_ns']=time.monotonic_ns();time.sleep(.25)
        self.row['pool_before']=rows;self.save()
        self.write('trace_marker','SLK_IDLE_BEGIN:'+self.row['cookie']);self.row['interval_monotonic_ns'].append(time.monotonic_ns())
        time.sleep(2)
        self.row['interval_monotonic_ns'].append(time.monotonic_ns());self.write('trace_marker','SLK_IDLE_END:'+self.row['cookie']);self.save()

    def finish(self):
        self.write('tracing_on','0')
        text=(self.path/'trace').read_text();path=self.folder/'trace.txt';path.write_text(text)
        stats={p.parent.name:p.read_text() for p in sorted((self.path/'per_cpu').glob('cpu*/stats'))}
        self.row.update(status='OBSERVED_NOT_PERFORMANCE_QUALIFIED',trace_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),stats=stats)
        self.row['counts']=parse(text,self.row,require_idle=False)
        self.finished=True;self.save()

    def close(self):
        if (self.path/'tracing_on').exists():self.write('tracing_on','0')


def parse(text,row,*,require_idle=True):
    if len(text)>4*1024*1024 or row['function']!='sl_work' or row['clock']!='global' or not re.fullmatch('[0-9a-f]{32}',row['cookie']):raise ValueError('bounded exact Session trace required')
    if 'LOST' in text.upper():raise ValueError('trace loss is not idle evidence')
    if re.findall(r'^# tracer: (.*)$',text,re.M)!=['function']:raise ValueError('actual function tracer header required')
    header=re.findall(r'#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)',text)
    if len(header)!=1 or header[0][0]!=header[0][1] or int(header[0][0])<4:raise ValueError('complete nonempty trace buffer required')
    if set(row['stats'])!={'cpu0','cpu1'}:raise ValueError('both configured VM CPU trace statistics required')
    for raw in row['stats'].values():
        fields=dict(re.findall(r'^([^:\n]+):\s*(\d+)\s*$',raw,re.M))
        if any(fields.get(k)!='0' for k in ['overrun','commit overrun','dropped events']):raise ValueError('missing or lost per-CPU trace events')
    times=row['interval_monotonic_ns']
    if len(times)!=2 or not 1_900_000_000<=times[1]-times[0]<=3_000_000_000:raise ValueError('actual bounded two-second guest monotonic idle interval required')
    phase=0;counts=[0,0,0];events=0
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):continue
        m=re.search(r'\d+\.\d+:\s*(.*)$',line)
        if not m:raise ValueError('unparsed function trace row')
        event=m[1];events+=1
        if event=='tracing_mark_write: SLK_IDLE_BEGIN:'+row['cookie']:
            if phase!=0:raise ValueError('duplicate/out-of-order idle marker')
            phase=1
        elif event=='tracing_mark_write: SLK_IDLE_END:'+row['cookie']:
            if phase!=1:raise ValueError('missing/out-of-order idle marker')
            phase=2
        elif re.match(r'^sl_work(?:\s|$)',event):counts[phase]+=1
        else:raise ValueError('unexpected tracer/filter/identity')
    if phase!=2 or not counts[0] or not counts[2] or events!=int(header[0][0]):raise ValueError('real pre/post work and full trace/marker closure required')
    if require_idle and counts[1]:raise ValueError('Session work executed during drained idle interval: '+str(counts[1]))
    return dict(before=counts[0],idle=counts[1],after=counts[2],events=events)


def corroborate(record,share):
    row=record['session_idle'];path=Path(share)/'session-idle/trace.txt'
    if row['status']!='OBSERVED_NOT_PERFORMANCE_QUALIFIED' or hashlib.sha256(path.read_bytes()).hexdigest()!=row['trace_sha256']:raise ValueError('original captured Session trace required')
    read=row['readbacks']
    if read['current_tracer']!='function' or read['set_ftrace_filter']!='sl_work' or '[global]' not in read['trace_clock']:raise ValueError('captured original tracer readbacks required')
    counts=parse(path.read_text(),row)
    if counts!=row['counts']:raise ValueError('recorded Session counts differ from raw trace')
    owners=record['channel_grant']['owners']
    if len(row['pool_before'])!=2:raise ValueError('both ordinary fd pool receipts required')
    for n,r in enumerate(row['pool_before']):
        v=decode(SleChannelTxStatus,r['value']);o=owners[n]
        worker=record['channel_grant']['workers'][n]
        if (r['pid'],r['fd'])!=(worker['pid'],worker['fd']):raise ValueError('same ordinary worker fd identity required')
        if (r['stage'],v.version,v.size,v.controller,v.generation,v.lifetime,v.handle,v.packet_maximum,v.capacity,v.queue_limit,v.flags)!=('tx_status',1,64,n,o['generation'],o['lifetime'],o['handle'],254,5,8,0) or any([v.outstanding,v.connection_debt,v.queued,v.busy,v.active_pdu_bytes,v.active_pdu_offset,v.reserved]):raise ValueError('actual drained current owner receipts required')
    return dict(status='REAL_SESSION_IDLE_AND_EVENT_RESTART_CORROBORATED',counts=counts,idle_monotonic_ns=row['interval_monotonic_ns'][1]-row['interval_monotonic_ns'][0],trace_sha256=row['trace_sha256'],scope='Aggregate production sl_work calls on two-controller VM;real business before/controlled prefix after;not Runtime idleCPU,concurrency proof,RF or performance qualification')
