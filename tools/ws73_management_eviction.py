#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""VM-only actual held reply, concurrent ioctl submission and result eviction.

Raw ioctls deliberately bypass the Python adapter's userspace RLock: these
workers exercise kernel admission on dup references to the same owning File.
They never change scheduling policy, synthesize replies or extend deadlines.
"""
import ctypes
import errno
import fcntl
import os
import threading
import time

from sparklink.structs import SleDiscoverySubmit, SleDiscoveryResult, SleControllerSnapshot, SleManagementQuery
from ws73_management_setup import decode, setup

SUBMIT = 0x40000000 | ctypes.sizeof(SleDiscoverySubmit) << 16 | ord('S') << 8 | 0x88
RESULT = 0xc0000000 | ctypes.sizeof(SleDiscoveryResult) << 16 | ord('S') << 8 | 0x89
SURVIVORS = list(range(1001, 1065))


def replacement(snapshot, identifier, domain):
    from ws73_management_partial import standby
    if domain=='advertising':return standby(snapshot,identifier,domain)
    # A pending ScanInitializeOff cannot admit another enable recipe. Its
    # same-domain STOP is legal and is still never selected while IN is held.
    return SleDiscoverySubmit(version=1,generation=snapshot.generation,
        request_id=identifier,profile=1,operation=4)


def result_row(fd, generation, identifier):
    value = bytearray(bytes(SleDiscoveryResult(version=1, generation=generation, request_id=identifier)))
    try:
        fcntl.ioctl(fd, RESULT, value, True)
    except OSError as error:
        return dict(request_id=identifier, errno=error.errno, raw=None)
    return dict(request_id=identifier, errno=0, raw=value.hex())


def collect(fd, snapshot, domain):
    evicted = ([2] if domain == 'scanning' else []) + [1, 1000]
    return dict(evicted=[result_row(fd, snapshot.generation, i) for i in evicted],
                retained=[result_row(fd, snapshot.generation, i) for i in SURVIVORS])


def burst(target, observer, snapshot, record):
    from ws73_management_partial import standby
    fd = target.fileno()
    value = dict(scheduler=os.sched_getscheduler(0), online_cpus=len(os.sched_getaffinity(0)),
                 start_wall_ns=time.time_ns(), first_input=bytes(replacement(snapshot, 1000, record['domain'])).hex(), workers=[])
    record['ordinary_burst'] = value
    if record['domain']=='scanning':
        rejected=dict(input=bytes(standby(snapshot,1000,'scanning')).hex())
        value['initializer_rejection']=rejected
        try:target.submit_discovery(standby(snapshot,1000,'scanning'))
        except OSError as error:rejected['errno']=error.errno
        else:raise ValueError('pending initializer must not admit another enable')
        rejected['result']=result_row(observer.fileno(),snapshot.generation,1000)
        if rejected['errno']!=errno.EBUSY or rejected['result']!=dict(request_id=1000,errno=errno.ENOENT,raw=None):
            raise ValueError('refused initialization must not admit a result')
    target.submit_discovery(replacement(snapshot, 1000, record['domain']))
    value['superseded_original'] = result_row(observer.fileno(), snapshot.generation, 1)
    value['first_end_wall_ns'] = time.time_ns()
    barrier = threading.Barrier(2, timeout=2)
    workers = []
    def submitter(number, alias):
        row = dict(worker=number, fd=alias, tid=threading.get_native_id(),
                   scheduler=os.sched_getscheduler(0), online_cpus=len(os.sched_getaffinity(0)), calls=[])
        value['workers'].append(row)
        try:
            barrier.wait()
            row['start_wall_ns'] = time.time_ns()
            for identifier in SURVIVORS[number*32:(number+1)*32]:
                request = replacement(snapshot, identifier, record['domain'])
                call = dict(request_id=identifier, input=bytes(request).hex(), start_wall_ns=time.time_ns())
                row['calls'].append(call)
                try:
                    fcntl.ioctl(alias, SUBMIT, bytes(request))
                    call['errno'] = 0
                except OSError as error:
                    call['errno'] = error.errno
                call['end_wall_ns'] = time.time_ns()
                if call['errno']:
                    raise OSError(call['errno'], 'concurrent discovery admission')
            row['end_wall_ns'] = time.time_ns()
        except BaseException as error:
            row.update(error_type=type(error).__name__, error=str(error))
        finally:
            os.close(alias)
            try:
                fcntl.fcntl(alias, fcntl.F_GETFD)
            except OSError as error:
                row['closed_errno'] = error.errno
    # Both dup references exist before either worker can close one: identities
    # and lifetime are unambiguous even if a worker runs ahead of its sibling.
    aliases = [os.dup(fd), os.dup(fd)]
    for number, alias in enumerate(aliases):
        thread = threading.Thread(target=submitter, args=(number, alias))
        workers.append(thread)
        thread.start()
    for thread in workers:
        thread.join()
    value['workers'].sort(key=lambda row: row['worker'])
    value['end_wall_ns'] = time.time_ns()
    if any('error' in row for row in value['workers']):
        raise ValueError('concurrent worker failed; retain original burst')
    value['before_release'] = collect(observer.fileno(), snapshot, record['domain'])
    queued = [row for row in value['before_release']['retained']
              if row['errno'] == 0 and decode(SleDiscoveryResult, row['raw']).state == 1]
    if len(queued) != 1:
        raise ValueError('one actually retained never-selected replacement required')
    record['cancelled_request_id'] = queued[0]['request_id']


def expected(snapshot, identifier, domain, state, final=False, opcode=0):
    return bytes(SleDiscoveryResult(version=1, generation=snapshot.generation, dev_index=0,
        request_id=identifier, profile=1, operation=5 if domain=='advertising' else 6 if opcode else 4,
        state=state, error=-errno.ECANCELED if state==5 else 0,
        count=2 if domain=='advertising' else 3 if opcode else 1, opcode=opcode,
        radio_adv=1 if final or domain=='scanning' else 0)).hex()


def verify_collection(value, snapshot, domain, queued=None, final=False):
    evicted = ([2] if domain=='scanning' else []) + [1, 1000]
    if value['evicted'] != [dict(request_id=i, errno=errno.ENOENT, raw=None) for i in evicted]:
        raise ValueError('exact old terminal results must be absent, never recreated')
    wanted = [dict(request_id=i, errno=0, raw=expected(snapshot,i,domain,1 if i==queued else 5,final)) for i in SURVIVORS]
    if value['retained'] != wanted:
        raise ValueError('all64 retained results must be canonical, never-selected and terminal after release')


def verify_records(record):
    from ws73_management_partial import standby, verify_preparation
    from ws73_management_ready_peer import ready_bytes, verify as verify_peer
    if (type(record.get('format_version')) is not int or record['format_version']!=9
            or record.get('ordinary_queue_eviction') is not True
            or record.get('status')!='MANAGED_ORDINARY_QUEUE_EVICTION_PASS'
            or record.get('synthetic_support') is not False
            or record.get('selected_domain_cleanup') is not True
            or record.get('active_ready_peer') is not True
            or record.get('real_later_step',False) is not False
            or record.get('initialization_step',0)!=0
            or record.get('physical_acceptance') is not False
            or record.get('automatic_fault_recovery_acceptance') is not False
            or record.get('daemon_running_during_hold') is not False
            or record.get('case') not in ['release','close','dup']
            or record.get('domain') not in ['advertising','scanning']
            or record.get('scan_parameter_cleanup',False) is not (record['domain']=='scanning')):
        raise ValueError('explicit actual ordinary two-worker first-step eviction gate required')
    snapshots=[setup(raw,i) for i,raw in enumerate(record['initial_snapshots'])]
    if len(snapshots)!=2 or snapshots[0].generation==snapshots[1].generation:
        raise ValueError('two independent registration identities required')
    snapshot=snapshots[0];domain=record['domain'];opcode=0xc02 if domain=='advertising' else 0x1001
    verify_preparation(record,snapshot)
    if record['input']!=bytes(standby(snapshot,1,domain)).hex() or record['pending']!=expected(snapshot,1,domain,2,opcode=opcode):
        raise ValueError('one actual original selected command must precede replacements')
    value=record['ordinary_burst']
    if type(value['scheduler']) is not int or value['scheduler']!=os.SCHED_OTHER or type(value['online_cpus']) is not int or value['online_cpus']<2:
        raise ValueError('ordinary scheduling and at least two available CPUs required')
    start=value['start_wall_ns'];end=value['end_wall_ns']
    if (type(start) is not int or type(end) is not int or not record['markers'][1]['wall_ns']<start<value['first_end_wall_ns']<end<record['release_before_wall_ns']
            or end-start>=200_000_000):
        raise ValueError('bounded actual submissions must precede lease release')
    if value['first_input']!=bytes(replacement(snapshot,1000,domain)).hex() or value['superseded_original']!=dict(request_id=1,errno=0,raw=expected(snapshot,1,domain,5,opcode=opcode)):
        raise ValueError('actual original cancellation before eviction required')
    if domain=='scanning':
        rejected=value['initializer_rejection']
        if rejected!=dict(input=bytes(standby(snapshot,1000,domain)).hex(),errno=errno.EBUSY,result=dict(request_id=1000,errno=errno.ENOENT,raw=None)):
            raise ValueError('pending scan initializer must reject without admission')
    elif 'initializer_rejection' in value:raise ValueError('unexpected initializer rejection')
    workers=value['workers']
    if len(workers)!=2 or [r['worker'] for r in workers]!=[0,1] or len({r['tid'] for r in workers})!=2 or len({r['fd'] for r in workers})!=2:
        raise ValueError('two distinct completed submitters and dup references required')
    for number,row in enumerate(workers):
        if (type(row['tid']) is not int or row['tid']<=0 or type(row['fd']) is not int or row['fd']<0
                or row['fd'] in [record['original_fd'],record['duplicate_fd']]
                or type(row['scheduler']) is not int or row['scheduler']!=os.SCHED_OTHER
                or type(row['online_cpus']) is not int or row['online_cpus']<2
                or row['closed_errno']!=errno.EBADF or 'error' in row
                or not value['first_end_wall_ns']<row['start_wall_ns']<=row['end_wall_ns']<=end):
            raise ValueError('ordinary worker identity, lifetime and bounded interval required')
        if [call['request_id'] for call in row['calls']]!=SURVIVORS[number*32:(number+1)*32]:
            raise ValueError('complete disjoint64 replacement submissions required')
        previous=row['start_wall_ns']
        for call in row['calls']:
            if (call['input']!=bytes(replacement(snapshot,call['request_id'],domain)).hex()
                    or type(call['errno']) is not int or call['errno']!=0
                    or not previous<=call['start_wall_ns']<=call['end_wall_ns']<=row['end_wall_ns']):
                raise ValueError('actual successful ordered typed ioctl required')
            previous=call['end_wall_ns']
    if not any(a['start_wall_ns']<b['end_wall_ns'] and b['start_wall_ns']<a['end_wall_ns'] for a in workers[0]['calls'] for b in workers[1]['calls']):
        raise ValueError('actual ioctl invocation intervals must overlap between workers')
    identifier=record['cancelled_request_id']
    if type(identifier) is not int or identifier not in SURVIVORS:
        raise ValueError('derive surviving queued identity from actual results')
    verify_collection(value['before_release'],snapshot,domain,queued=identifier)
    verify_collection(record['after_release_results'],snapshot,domain)
    verify_collection(record['after_drain_results'],snapshot,domain,final=True)
    if record['cancelled']!=expected(snapshot,identifier,domain,5) or record['final_result']!=expected(snapshot,identifier,domain,5,final=True):
        raise ValueError('last actual queued request must remain cancelled across original reply')
    for key,state,mode in [('before_management',1,1),('revoking',2,0),('final_management',0,0)]:
        if record[key]!=bytes(SleManagementQuery(version=1,generation=snapshot.generation,state=state,mode=mode)).hex():
            raise ValueError('actual Held/Revoking/Free observations required')
    final=SleControllerSnapshot.from_buffer_copy(bytes(snapshot));final.flags=2
    if record['final_snapshot']!=bytes(final).hex() or record['peer_after']!=ready_bytes(snapshots[1]):
        raise ValueError('untouched scan remains Unknown/Setup; Ready peer metadata unchanged')
    if type(record['original_fd']) is not int or record['original_fd']<0 or type(record['lease']) is not int or not record['lease']:
        raise ValueError('actual original descriptor/lease required')
    if record['case']!='release' and record.get('original_fd_errno')!=errno.EBADF:
        raise ValueError('original fd must really close')
    if record['case']=='dup':
        if (type(record['duplicate_fd']) is not int or record['duplicate_fd']<0 or record['duplicate_fd']==record['original_fd']
                or record.get('duplicate_fd_errno')!=errno.EBADF or record['after_first_management']!=record['before_management']):
            raise ValueError('first dup close retains ownership; final reference closes')
    elif record['duplicate_fd']!=-1:
        raise ValueError('unexpected persistent alias')
    markers=record['markers'];acks=record['hold_acknowledgements']
    if [r['hold_phase'] for r in markers]!=['arm_ready','wait_held','release_ready'] or len(acks)!=3 or [r['stage'] for r in acks]!=['armed','held','released'] or [r['request'] for r in acks]!=markers:
        raise ValueError('actual original host arm/hold/release handshake required')
    clocks=[record[k] for k in ['submit_before_wall_ns','submit_after_wall_ns','release_before_wall_ns','release_after_wall_ns']]
    if any(type(v) is not int or v<=0 for v in clocks) or clocks!=sorted(clocks) or clocks[-1]-clocks[0]>=400_000_000 or not markers[0]['wall_ns']<clocks[0]<=clocks[1]<markers[1]['wall_ns']<clocks[2]<=clocks[3]<markers[2]['wall_ns']:
        raise ValueError('original500ms deadline must remain unchanged')
    previous=markers[2]['wall_ns'];observations=record['management_observations']
    if not observations or observations[-1]['raw']!=record['final_management']:
        raise ValueError('complete bounded ownership drain required')
    for number,row in enumerate(observations):
        if type(row['wall_ns']) is not int or row['wall_ns']<previous or row['raw']!=bytes(SleManagementQuery(version=1,generation=snapshot.generation,state=0 if number==len(observations)-1 else 2)).hex():
            raise ValueError('only Revoking until actual final Free allowed')
        previous=row['wall_ns']
    verify_peer(record,snapshots[1])
    return snapshots


def corroborate(record, host, capture, stderr, identity):
    snapshots=verify_records(record)
    from ws73_management_partial import corroborate_wire
    wire=corroborate_wire(record,snapshots,host,capture,stderr,identity)
    return dict(scope='two SCHED_OTHER submitters,65 replacements,64 actual retained results,original successful host frame and active Ready peer',
        wire=wire, original_actual_pending=record['pending'], original_actual_cancelled_before_eviction=record['ordinary_burst']['superseded_original'],
        old_result_absence=record['after_drain_results']['evicted'],retained_terminal_results=64,
        ordinary_scheduler_queue_eviction_case_acceptance=True,
        whole_managed_acceptance=False,automatic_fault_recovery_acceptance=False,natural_fault_root_cause_closed=False)
