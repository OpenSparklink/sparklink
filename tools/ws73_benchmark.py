#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent schema2 application-report checks, never RF/performance qualification.

Only a complete successful application pair is eligible for the consistent result.
Diagnostic failures retain their original reports and are refused here. No peer
clock subtraction, Native state transition, socket loop or protocol Engine.
"""
import argparse
import hashlib
import json
import math
import os
import stat
from pathlib import Path

from ws73_capture import CaptureError

REQUEST_NS = 10_000_000_000
GRACE_NS = 1_000_000_000
RUN_NS = 612_000_000_000
MAX_REPORT_BYTES = 256 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise CaptureError('schema2 benchmark: ' + message)


def integer(value, low=0, high=(1 << 64)-1):
    return type(value) is int and low <= value <= high


def exact_counts(value, expected, name):
    require(type(value) is dict and set(value) == set(expected), name + ' fields')
    require(all(integer(value[k]) and value[k] == v for k, v in expected.items()), name + ' counts')


def distribution(values):
    if not values:
        return None
    values = sorted(values)
    def rank(p, denominator=100):
        return values[(p * len(values) + denominator - 1) // denominator - 1]
    return dict(successful_samples=len(values), min_ns=values[0], p50_ns=rank(50),
                p90_ns=rank(90), p95_ns=rank(95), p99_ns=rank(99),
                p999_ns=rank(999, 1000) if len(values) >= 10000 else None,
                max_ns=values[-1])


def frame(value, size, reply):
    require(type(value) is str and len(value) == size * 2 and
            all(c in '0123456789abcdef' for c in value), 'bounded canonical frame hex')
    raw = bytes.fromhex(value)
    require(raw[:8] == b'SLKSOCK1' and raw[28] == reply, 'frame lane/header')
    nonce, seq = raw[8:24], int.from_bytes(raw[24:28], 'little')
    require(all(raw[29+j] == nonce[j % 16] ^ ((seq+j) & 255)
                for j in range(size-29)), 'payload validation')
    # Normalize the single request/reply bit for independent two-end comparison.
    return raw[:28] + bytes(1) + raw[29:], nonce, seq


def ordered(row, names, active):
    times = [row.get(n) for n in names]
    require(all(integer(v) for v in times) and times == sorted(times)
            and times[-1] <= active, 'same-process timestamp order/range')


def resource_check(value):
    require(type(value) is dict and value.get('incomplete') is not True,
            'complete process endpoint observations')
    require(value.get('scope') == 'process-wide snapshots bracketing drive;includes endpoint probe overhead;maxrss is process lifetime,not interval peak', 'resource scope')
    fields = {'user_cpu_ns', 'system_cpu_ns', 'process_lifetime_maxrss_kib',
              'open_fds', 'resident_pages', 'page_bytes'}
    for end in ('before', 'after'):
        v = value.get(end)
        require(type(v) is dict and set(v) == fields and
                all(integer(n) for n in v.values()), 'resource endpoint fields/types')
        require(v['open_fds'] > 0 and v['page_bytes'] > 0 and
                v['process_lifetime_maxrss_kib'] > 0, 'resource endpoint bounds')
    for name in ('user_cpu', 'system_cpu'):
        delta = value['after'][name+'_ns'] - value['before'][name+'_ns']
        require(integer(value.get(name+'_delta_ns')) and
                value[name+'_delta_ns'] == delta, 'resource delta')
    require(value['after']['process_lifetime_maxrss_kib'] >= value['before']['process_lifetime_maxrss_kib'], 'process lifetime RSS')
    for name in ('kernel_workers', 'kernel_timers', 'URBs', 'protocol_credit_peak'):
        require(name in value and value[name] is None, 'unmeasured kernel resource '+name)


def load_application_reports(left, right, *, fixture=False):
    """Recompute successful schema2 application closure; not artifact/capture closure.

    fixture=True permits only explicitly marked AF_UNIX report fixtures and the
    test's 1s finalization budget; default requires the actual CLI's 30s budget.
    Native credentials, owner topology and capture coverage belong to the VM gate.
    """
    require(type(fixture) is bool, 'explicit fixture flag')
    require(type(left) is dict and type(right) is dict, 'two original reports')
    reports = (left, right)
    configs = [r.get('config') for r in reports]
    for c in configs:
        require(type(c) is dict and set(c) == {'mode','count','bytes','window','interval_us'}, 'exact config')
        require(integer(c['count'],1,10000) and integer(c['bytes'],29,2042)
                and integer(c['window'],1,min(c['count'],256)), 'bounded count/bytes/window')
        if c['mode'] == 'rate':
            require(integer(c['interval_us'],10,1_000_000) and c['interval_us']*c['count'] <= 600_000_000, 'absolute plan bounds')
        else:
            require(c['mode'] in ('window','duplex','peer') and type(c['interval_us']) is int and c['interval_us'] == 0, 'mode/interval')
    a, b = configs
    require(all(a[k] == b[k] for k in ('count','bytes','window')), 'matching offered workload')
    modes = (a['mode'], b['mode'])
    require(modes in (('rate','peer'),('window','peer'),('peer','rate'),('peer','window'),('duplex','duplex')), 'complementary endpoint roles')
    endpoints=[]
    for report, c in zip(reports, configs):
        require(type(report.get('schema_version')) is int and report['schema_version'] == 2, 'schema version')
        require(report.get('performance_qualified') is False and report.get('correctness') is True
                and report.get('status') == 'LOAD_OBSERVED_NOT_QUALIFIED', 'complete successful diagnostic only')
        require((type(report.get('test_fixture')) is str and bool(report['test_fixture'])) if fixture else 'test_fixture' not in report, 'fixture requires explicit opt-in; never Native')
        require(report.get('clock') == 'process-local-Rust-Instant-relative-nanoseconds'
                and report.get('wait_backend') == 'ppoll-relative-nanoseconds', 'clock domain and units')
        require(report.get('window_domain') == 'application-awaiting-validated-reply-not-protocol-credit', 'separate application window')
        require(report.get('rtt_definition') == 'successful send syscall entry to validated reply;success-only excludes timed-out/late;no cross-clock arithmetic', 'RTT origin')
        require(report.get('percentile_method') == 'nearest-rank;p99.9 requires10000 successes', 'percentile definition')
        for k,v in [('request_deadline_ns',REQUEST_NS),('late_observation_grace_ns',GRACE_NS),('maximum_run_ns',RUN_NS)]:
            require(type(report.get(k)) is int and report[k] == v, 'original budget '+k)
        require(type(report.get('unmeasured')) is list and len(report['unmeasured']) > 0
                and all(type(v) is str and v for v in report['unmeasured']), 'explicit incomplete qualification')
        end=report.get('finalization')
        require(type(end) is dict and set(end) == {'completed','budget_ns','elapsed_ns','error'}
                and end['completed'] is True and end['error'] is None, 'paired-end barrier completed')
        require(type(end['budget_ns']) is int and end['budget_ns'] == (1_000_000_000 if fixture else 30_000_000_000)
                and integer(end['elapsed_ns']) and end['elapsed_ns'] < end['budget_ns'], 'bounded finalization')
        o=report.get('observation')
        require(type(o) is dict and set(o) == {'elapsed_ns','active_elapsed_ns','error'}
                and o['error'] is None and integer(o['elapsed_ns'],1,RUN_NS)
                and integer(o['active_elapsed_ns'],1,o['elapsed_ns'])
                and o['elapsed_ns']-o['active_elapsed_ns'] >= GRACE_NS, 'active/grace/run observation')
        active=o['active_elapsed_ns'];count=c['count'];size=c['bytes'];mode=c['mode']
        identity=report.get('channel_identity')
        require(type(identity) is dict and set(identity) == {'controller','generation','lifetime','handle','local_tcid','remote_tcid','pi','mtu','mps','mode','directions'}, 'exact identity')
        for k,lo,hi in [('controller',0,65535),('generation',1,(1<<64)-1),('lifetime',1,(1<<64)-1),('handle',0,4095),('mtu',size,2042),('mps',size+5,2047)]:
            require(integer(identity.get(k),lo,hi), 'identity/capability '+k)
        require(all(type(identity[k]) is int and identity[k] == v for k,v in [('local_tcid',31),('remote_tcid',31),('pi',241),('mode',0),('directions',3)])
                and identity['mtu']+5 <= identity['mps'], 'basic CUTC capability')
        rows=[];latencies=[]
        for lane,expected in [('outgoing',0 if mode=='peer' else count),('incoming',count if mode in ('peer','duplex') else 0)]:
            values=report.get(lane)
            require(type(values) is list and len(values) == expected, 'all '+lane+' records')
            frames=[];nonces=set();seqs=set();previous=0
            for index,row in enumerate(values):
                expected_fields={'index','planned_ns','dispatch_ns','first_syscall_ns','admitted_ns','syscall_ns','deadline_ns','read_ns','validated_ns','send_attempts','would_block','errno','local_budget_rejected','timed_out','late','reply_count','frame_hex'} if lane=='outgoing' else {'index','read_ns','validated_ns','deadline_ns','reply_syscall_ns','reply_admitted_ns','send_attempts','would_block','errno','timed_out','frame_hex'}
                require(type(row) is dict and set(row)==expected_fields and type(row.get('index')) is int and row['index'] == index, 'all original typed row fields/indices')
                require(row.get('errno') is None and row.get('timed_out') is False, 'no hidden failed row')
                require(integer(row.get('send_attempts'),1) and integer(row.get('would_block'))
                        and row['send_attempts'] == row['would_block']+1, 'exact attempts/EAGAIN')
                raw,nonce,seq=frame(row.get('frame_hex'),size,0 if lane=='outgoing' else 1)
                require(nonce not in nonces and seq not in seqs, 'unique per-direction nonce/sequence')
                nonces.add(nonce);seqs.add(seq);frames.append(raw)
                if lane == 'outgoing':
                    require(row.get('local_budget_rejected') is False and row.get('late') is False
                            and type(row.get('reply_count')) is int and row['reply_count'] == 1, 'no hidden rejected/late/duplicate reply')
                    ordered(row,['planned_ns','dispatch_ns','first_syscall_ns','syscall_ns','admitted_ns','read_ns','validated_ns'],active)
                    require(integer(row.get('deadline_ns')) and row['deadline_ns'] == row['planned_ns']+REQUEST_NS
                            and row['validated_ns'] < row['deadline_ns'], 'original source deadline')
                    require(previous <= row['planned_ns'], 'source plan order');previous=row['planned_ns']
                    if mode == 'rate':require(row['planned_ns'] == index*c['interval_us']*1000, 'absolute per-message plan')
                    latencies.append(row['validated_ns']-row['syscall_ns'])
                else:
                    ordered(row,['read_ns','validated_ns','reply_syscall_ns','reply_admitted_ns'],active)
                    require(previous <= row['read_ns'], 'receive order');previous=row['read_ns']
                    require(integer(row.get('deadline_ns')) and row['deadline_ns'] == row['read_ns']+REQUEST_NS
                            and row['reply_admitted_ns'] < row['deadline_ns'], 'read-based reply deadline')
            rows.append(frames)
        outgoing,incoming=rows;nout=len(outgoing);nin=len(incoming)
        expected=dict(scheduled=nout,dispatched=nout,unattempted=0,admitted=nout,validated_replies=nout,timed_out=0,late=0,local_budget_rejected=0,kernel_rejected=0,missing_admitted_replies=0,expired_before_admission=0,admitted_reply_timeouts=0,successful_timely_replies=nout,peer_reply_deadline_exceeded=0,peer_validated_requests=nin,peer_reply_admissions=nin,peer_validated_application_bytes=nin*size)
        exact_counts(report.get('summary'),expected,'summary')
        counters=report.get('counters');failures=['duplicate_requests','duplicate_replies','reordered_replies','corrupt_packets','unknown_replies','unsolicited_requests','receiver_record_overflow','reply_queue_overflow']
        require(type(counters) is dict and set(counters) == set(failures+['rx_packets','inflight_peak','reply_queue_peak','poll_calls','iterations'])
                and all(integer(v) for v in counters.values()), 'complete typed counters')
        require(all(counters[k] == 0 for k in failures) and counters['rx_packets'] == nout+nin, 'all actual receives and failures')
        require((1 <= counters['inflight_peak'] <= c['window'] if nout else counters['inflight_peak'] == 0)
                and (1 <= counters['reply_queue_peak'] <= c['window'] if nin else counters['reply_queue_peak'] == 0)
                and counters['iterations'] >= 1 and counters['poll_calls'] >= 1, 'finite application queue observations')
        dist=distribution(latencies);observed=report.get('success_only_rtt')
        if dist is None:require(observed is None,'peer has no source RTT')
        else:
            require(type(observed) is dict and set(observed) == set(dist)
                    and all((v is None and k=='p999_ns' and nout<10000) or integer(v) for k,v in observed.items())
                    and observed == dist, 'recomputed integer ns nearest-rank distribution')
        rates=report.get('rates')
        require(type(rates) is dict and set(rates) == {'denominator','requested_messages_per_second','admitted_messages_per_second','local_verified_datagram_goodput_Bps','local_verified_pattern_payload_goodput_Bps','benchmark_header_bytes_per_datagram','USB_bytes','USB_bytes_per_second'}, 'rate fields')
        require(rates['denominator'] == 'own-process active_elapsed_ns before late-observation grace;includes timeouts and failures'
                and type(rates['benchmark_header_bytes_per_datagram']) is int and rates['benchmark_header_bytes_per_datagram'] == 29
                and rates['USB_bytes'] is None and rates['USB_bytes_per_second'] is None, 'rate domain and unknown USB')
        expected_rates=dict(requested_messages_per_second=1_000_000/c['interval_us'] if mode=='rate' else None,admitted_messages_per_second=nout*1e9/active,local_verified_datagram_goodput_Bps=nin*size*1e9/active,local_verified_pattern_payload_goodput_Bps=nin*(size-29)*1e9/active)
        for k,v in expected_rates.items():
            actual=rates[k]
            require(actual is None if v is None else type(actual) in (int,float) and 0 <= actual <= 1e30 and math.isfinite(actual) and math.isclose(actual,v,rel_tol=1e-12,abs_tol=1e-9), 'recomputed rate/units '+k)
        resource_check(report.get('process_resources'))
        endpoints.append(dict(identity=identity,outgoing=outgoing,incoming=incoming,rtt=dist))
    require(endpoints[0]['identity']['controller'] != endpoints[1]['identity']['controller'], 'distinct simultaneous controllers')
    for index,e in enumerate(endpoints):
        other=endpoints[1-index]
        require(e['outgoing'] == other['incoming'], 'actual peer validated/replied every offered message in order')
    if modes == ('duplex','duplex'):
        require(not set(endpoints[0]['outgoing']) & set(endpoints[1]['outgoing']), 'independent duplex source payloads')
    return dict(status='LOAD_APPLICATION_REPORTS_CONSISTENT_NOT_QUALIFIED',performance_qualified=False,
                modes=list(modes),messages=[len(e['outgoing']) for e in endpoints],
                source_rtt=[e['rtt'] for e in endpoints],fixture=fixture,
                remaining=['actual credential/Grant/owner topology','compiled source/artifact/tool/config/firmware closure',
                           'independent two-end USB/HCC capture coverage/drop checks and supervisor evidence',
                           'stable baseline/resources/trace overhead and performance qualification'])


def verify_vm_build(vm, build):
    """Bind a completed empty-USB VM to the selected Cargo test artifact.

    This checks identities, not compiler correctness or reproducible builds.
    The qualification registry separately pins source maps and retained bytes.
    It prevents an honest generic VM PASS with an old test executable being
    upgraded to a new source qualification, as observed in the first attempt.
    """
    import re
    require(type(build) is dict and re.fullmatch('[0-9a-f]{40}', build.get('compiled_source','')) is not None,
            'exact compiled source identity')
    count=build.get('test_count');listing=build.get('test_listing')
    require(integer(count,1,10000) and type(listing) is str, 'actual Cargo library test listing')
    names=[line[:-6] for line in listing.splitlines() if line.endswith(': test')]
    require(len(names)==count and len(set(names))==count, 'complete unique test listing')
    artifact=build.get('compiler_artifact')
    require(type(artifact) is dict and artifact.get('reason')=='compiler-artifact'
            and artifact.get('target',{}).get('name')=='slktest'
            and artifact.get('target',{}).get('kind')==['lib']
            and artifact.get('profile',{}).get('test') is True, 'actual Cargo library test artifact')
    require(type(vm) is dict and vm.get('status')=='PASS_ISOLATED_NATIVE_ROOT_SMOKE'
            and vm.get('qemu_exit')==0 and vm.get('physical_acceptance') is False
            and vm.get('native_acceptance') is False, 'scoped completed emptyUSB VM')
    require(type(vm.get('application_tests')) is int and vm['application_tests']==count,
            'VM tests belong to selected current library')
    require(vm.get('application_test_listing_sha256')==hashlib.sha256(listing.encode()).hexdigest(),
            'VM uses exact selected test listing')
    require(artifact.get('executable')==build.get('artifacts',{}).get('tests',{}).get('path'),
            'selected Cargo executable path')
    for selected,name in [('slktest','slktest'),('tests','slktest-tests')]:
        expected=build.get('artifacts',{}).get(selected,{})
        require(re.fullmatch('[0-9a-f]{64}',expected.get('sha256','')) is not None
                and integer(expected.get('bytes'),1), 'exact build artifact '+selected)
        require(vm.get('inputs',{}).get(name,{}).get('sha256')==expected['sha256'],
                'VM artifact mismatch '+selected)
    return dict(status='VM_SELECTED_APPLICATION_ARTIFACTS_MATCH_NOT_QUALIFIED',
                compiled_source=build['compiled_source'],tests=count,performance_qualified=False,
                remaining=['retained bytes/source-map checks','compiler/build reproducibility',
                           'Native/realWS73/performance qualification'])


def read_report(path,*,expected_uid=None):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode)and info.st_nlink==1 and 0<info.st_size<=MAX_REPORT_BYTES,'regular bounded unique report')
        if expected_uid is not None:
            require(type(expected_uid)is int and info.st_uid==expected_uid and info.st_gid==expected_uid and not info.st_mode&0o022,'actual application-owned report')
        with os.fdopen(os.dup(fd),'rb')as stream:raw=stream.read(MAX_REPORT_BYTES+1)
        after=os.fstat(fd)
        require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'closed report changed while reading')
    finally:os.close(fd)
    require(len(raw) <= MAX_REPORT_BYTES,'report byte budget')
    def pairs(items):
        result={}
        for k,v in items:
            require(k not in result,'duplicate JSON field');result[k]=v
        return result
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(CaptureError('nonfinite JSON number')))
    record=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    if expected_uid is not None:record.update(uid=info.st_uid,gid=info.st_gid,mode=info.st_mode&0o777,nlink=info.st_nlink)
    return value,record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--left',type=Path,required=True)
    parser.add_argument('--right',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixture',action='store_true',help='explicit local AF_UNIX identity fixtures only')
    args=parser.parse_args()
    # Exclusive creation and initial incomplete state survive input/process failure.
    with args.output.open('x') as stream:
        json.dump(dict(status='INCOMPLETE',performance_qualified=False),stream);stream.write('\n');stream.flush()
    try:
        left,l=read_report(args.left);right,r=read_report(args.right)
        result=load_application_reports(left,right,fixture=args.fixture)
        result['reports']=[l,r]
    except (OSError,ValueError,KeyError,TypeError,CaptureError) as error:
        # Original inputs are never overwritten; failure cannot retain success.
        args.output.write_text(json.dumps(dict(status='FAIL',performance_qualified=False,error=str(error)))+'\n')
        raise SystemExit(1) from error
    args.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
