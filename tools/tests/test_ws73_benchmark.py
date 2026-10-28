# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic report contract negatives; actual Rust report replay is separate."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_benchmark as gate
from ws73_capture import CaptureError


def fixture(mode='rate', count=3, size=61):
    """Explicit JSON fixture, not socket/Host behavior or measured performance."""
    peer='duplex' if mode=='duplex' else 'peer'
    reports=[]
    for side,m in enumerate([mode,peer]):
        outgoing=[];incoming=[]
        for lane,rows,n in [('outgoing',outgoing,0 if m=='peer' else count),('incoming',incoming,count if m in ('peer','duplex') else 0)]:
            for i in range(n):
                direction=side if lane=='outgoing' else 1-side
                nonce=bytes([direction+1])*15+bytes([i+1]);seq=100*direction+i
                raw=b'SLKSOCK1'+nonce+seq.to_bytes(4,'little')+bytes([lane=='incoming'])
                raw+=bytes(nonce[j%16]^((seq+j)&255) for j in range(size-29))
                planned=i*1_000_000
                common=dict(index=i,send_attempts=1,would_block=0,errno=None,timed_out=False,frame_hex=raw.hex())
                if lane=='outgoing':
                    rows.append(dict(common,planned_ns=planned,dispatch_ns=planned+10,first_syscall_ns=planned+20,syscall_ns=planned+20,admitted_ns=planned+30,deadline_ns=planned+gate.REQUEST_NS,read_ns=planned+40,validated_ns=planned+50,local_budget_rejected=False,late=False,reply_count=1))
                else:
                    rows.append(dict(common,read_ns=planned+10,validated_ns=planned+20,deadline_ns=planned+10+gate.REQUEST_NS,reply_syscall_ns=planned+30,reply_admitted_ns=planned+40))
        nout=len(outgoing);nin=len(incoming);active=count*1_000_000
        endpoint=dict(user_cpu_ns=100,system_cpu_ns=100,process_lifetime_maxrss_kib=1000,open_fds=4,resident_pages=10,page_bytes=4096)
        summary=dict(scheduled=nout,dispatched=nout,unattempted=0,admitted=nout,validated_replies=nout,timed_out=0,late=0,local_budget_rejected=0,kernel_rejected=0,missing_admitted_replies=0,expired_before_admission=0,admitted_reply_timeouts=0,successful_timely_replies=nout,peer_reply_deadline_exceeded=0,peer_validated_requests=nin,peer_reply_admissions=nin,peer_validated_application_bytes=nin*size)
        counters=dict(rx_packets=nout+nin,duplicate_requests=0,duplicate_replies=0,reordered_replies=0,corrupt_packets=0,unknown_replies=0,unsolicited_requests=0,receiver_record_overflow=0,reply_queue_overflow=0,inflight_peak=1 if nout else 0,reply_queue_peak=1 if nin else 0,poll_calls=3,iterations=3)
        reports.append(dict(schema_version=2,status='LOAD_OBSERVED_NOT_QUALIFIED',correctness=True,performance_qualified=False,clock='process-local-Rust-Instant-relative-nanoseconds',wait_backend='ppoll-relative-nanoseconds',window_domain='application-awaiting-validated-reply-not-protocol-credit',rtt_definition='successful send syscall entry to validated reply;success-only excludes timed-out/late;no cross-clock arithmetic',percentile_method='nearest-rank;p99.9 requires10000 successes',request_deadline_ns=gate.REQUEST_NS,late_observation_grace_ns=gate.GRACE_NS,maximum_run_ns=gate.RUN_NS,config=dict(mode=m,count=count,bytes=size,window=count,interval_us=1000 if m=='rate' else 0),finalization=dict(completed=True,budget_ns=30_000_000_000,elapsed_ns=50,error=None),observation=dict(active_elapsed_ns=active,elapsed_ns=active+gate.GRACE_NS,error=None),unmeasured=['explicit fixture only'],channel_identity=dict(controller=side,generation=7+side,lifetime=11+side,handle=0,local_tcid=31,remote_tcid=31,pi=241,mtu=2042,mps=2047,mode=0,directions=3),outgoing=outgoing,incoming=incoming,summary=summary,counters=counters,success_only_rtt=dict(successful_samples=nout,min_ns=30,p50_ns=30,p90_ns=30,p95_ns=30,p99_ns=30,p999_ns=None,max_ns=30) if nout else None,rates=dict(denominator='own-process active_elapsed_ns before late-observation grace;includes timeouts and failures',requested_messages_per_second=1000 if m=='rate' else None,admitted_messages_per_second=nout*1e9/active,local_verified_datagram_goodput_Bps=nin*size*1e9/active,local_verified_pattern_payload_goodput_Bps=nin*(size-29)*1e9/active,benchmark_header_bytes_per_datagram=29,USB_bytes=None,USB_bytes_per_second=None),process_resources=dict(scope='process-wide snapshots bracketing drive;includes endpoint probe overhead;maxrss is process lifetime,not interval peak',before=endpoint.copy(),after=endpoint.copy(),user_cpu_delta_ns=0,system_cpu_delta_ns=0,kernel_workers=None,kernel_timers=None,URBs=None,protocol_credit_peak=None)))
    return reports


class Schema2Reports(unittest.TestCase):
    def dynamic_pair(self, mode='window'):
        pair = fixture(mode)
        for i,report in enumerate(pair):
            report['channel_request'] = dict(version=1,kind='dynamic_basic',source_port=24576+i,
                destination_port=24577-i,aid=29441,mtu=249,mps=254,slqi=1,passive=bool(i))
            report['channel_identity'].update(local_tcid=0x81+i,remote_tcid=0x82-i,mtu=249,mps=254)
        return pair

    def test_dynamic_requests_are_separate_from_actual_cross_end_tcids(self):
        for mode in ['rate','window','duplex']:
            pair = self.dynamic_pair(mode)
            for reports in [pair,pair[::-1]]:
                out = gate.load_application_reports(*reports)
                self.assertEqual(out['channel_requests'],[r['channel_request'] for r in reports])
                self.assertIn('wire CMTC routing',out['remaining'][-1])
                self.assertIs(out['performance_qualified'],False)

    def test_dynamic_metadata_cannot_downgrade_or_grant_actual_negotiation(self):
        changes = {
            'missing-left-tag':lambda a,b:a.pop('channel_request'),
            'missing-both-tags':lambda a,b:(a.pop('channel_request'),b.pop('channel_request')),
            'unknown-kind':lambda a,b:a['channel_request'].update(kind='reliable'),
            'boolean-version':lambda a,b:a['channel_request'].update(version=True),
            'zero-port':lambda a,b:a['channel_request'].update(source_port=0),
            'port-is-tcid':lambda a,b:a['channel_request'].update(destination_port=0x82),
            'aid-mismatch':lambda a,b:b['channel_request'].update(aid=29442),
            'same-negotiation-role':lambda a,b:b['channel_request'].update(passive=False),
            'numeric-role':lambda a,b:b['channel_request'].update(passive=1),
            'changed-budget':lambda a,b:a['channel_request'].update(mps=255),
            'changed-slqi':lambda a,b:a['channel_request'].update(slqi=0),
            'extra-field':lambda a,b:a['channel_request'].update(ready=True),
            'fixed-under-dynamic':lambda a,b:a['channel_identity'].update(local_tcid=31),
            'outside-tcid':lambda a,b:b['channel_identity'].update(remote_tcid=0xe0),
            'cross-tcid-mismatch':lambda a,b:b['channel_identity'].update(remote_tcid=0x84),
            'budget-escalation':lambda a,b:a['channel_identity'].update(mtu=250,mps=255),
        }
        for name,change in changes.items():
            a,b = self.dynamic_pair(); change(a,b)
            with self.subTest(name=name),self.assertRaises(CaptureError):
                gate.load_application_reports(a,b)
        a,b = fixture()
        a['channel_request'] = None; b['channel_request'] = None
        with self.assertRaises(CaptureError): gate.load_application_reports(a,b)

    def test_complementary_roles_and_direction_swap(self):
        for mode in ['rate','window','duplex']:
            for pair in [fixture(mode),fixture(mode)[::-1]]:
                out=gate.load_application_reports(*pair)
                self.assertEqual(out['status'],'LOAD_APPLICATION_REPORTS_CONSISTENT_NOT_QUALIFIED')
                self.assertIs(out['performance_qualified'],False)

    def test_independent_failure_classes_never_become_complete_pair(self):
        changes={
            'missing-peer':lambda a,b:b.clear(),
            'schema-bool':lambda a,b:a.update(schema_version=True),
            'incomplete':lambda a,b:a.update(status='INCOMPLETE'),
            'qualified':lambda a,b:a.update(performance_qualified=True),
            'correctness-bool':lambda a,b:a.update(correctness=1),
            'same-mode':lambda a,b:b['config'].update(mode='rate',interval_us=1000),
            'window':lambda a,b:b['config'].update(window=1),
            'count-bool':lambda a,b:a['config'].update(count=True),
            'unbounded':lambda a,b:a['config'].update(count=10001),
            'clock':lambda a,b:a.update(clock='host-wallclock'),
            'rtt-origin':lambda a,b:a.update(rtt_definition='batch start'),
            'window-domain':lambda a,b:a.update(window_domain='controller-credit'),
            'empty-unmeasured':lambda a,b:a.update(unmeasured=[]),
            'deadline-extension':lambda a,b:a.update(request_deadline_ns=20_000_000_000),
            'grace-missing':lambda a,b:a['observation'].update(elapsed_ns=100),
            'missing-finalization':lambda a,b:a.pop('finalization'),
            'finish-not-authorized':lambda a,b:a['finalization'].update(completed=False),
            'finish-timeout':lambda a,b:a['finalization'].update(elapsed_ns=30_000_000_000),
            'finish-unbounded':lambda a,b:a['finalization'].update(budget_ns=0),
            'finish-error':lambda a,b:a['finalization'].update(error='EOF'),
            'observation-error':lambda a,b:a['observation'].update(error='missing peer'),
            'identity-old':lambda a,b:a['channel_identity'].update(lifetime=0),
            'same-controller-new-generation':lambda a,b:b['channel_identity'].update(controller=0),
            'MTU':lambda a,b:a['channel_identity'].update(mtu=28),
            'MPS':lambda a,b:a['channel_identity'].update(mps=2042),
            'tcid':lambda a,b:a['channel_identity'].update(remote_tcid=10),
            'missing-message':lambda a,b:b['incoming'].pop(),
            'missing-errno':lambda a,b:a['outgoing'][0].pop('errno'),
            'failed':lambda a,b:a['outgoing'][0].update(errno=11),
            'timeout-lost':lambda a,b:a['outgoing'][0].update(timed_out=True),
            'late':lambda a,b:a['outgoing'][0].update(late=True),
            'rejected':lambda a,b:a['outgoing'][0].update(local_budget_rejected=True),
            'attempts':lambda a,b:a['outgoing'][0].update(would_block=1),
            'bad-index':lambda a,b:a['outgoing'][0].update(index=True),
            'deadline-row':lambda a,b:a['outgoing'][0].update(deadline_ns=gate.REQUEST_NS+1),
            'plan':lambda a,b:a['outgoing'][1].update(planned_ns=0),
            'batch-origin':lambda a,b:a['outgoing'][1].update(syscall_ns=0),
            'cross-clock':lambda a,b:b['incoming'][0].update(read_ns=10**18),
            'reply-deadline':lambda a,b:b['incoming'][0].update(deadline_ns=20_000_000_000),
            'payload':lambda a,b:b['incoming'][0].update(frame_hex='00'*61),
            'duplicate':lambda a,b:b['incoming'][1].update(frame_hex=b['incoming'][0]['frame_hex']),
            'reply-count':lambda a,b:a['outgoing'][0].update(reply_count=2),
            'summary':lambda a,b:a['summary'].update(timed_out=1),
            'summary-missing':lambda a,b:a['summary'].pop('unattempted'),
            'rx-counter':lambda a,b:a['counters'].update(rx_packets=0),
            'counter-bool':lambda a,b:a['counters'].update(rx_packets=True),
            'overflow':lambda a,b:b['counters'].update(reply_queue_overflow=1),
            'inflight':lambda a,b:a['counters'].update(inflight_peak=99),
            'distribution':lambda a,b:a['success_only_rtt'].update(p99_ns=1),
            'float-distribution':lambda a,b:a['success_only_rtt'].update(p99_ns=30.0),
            'small-p999':lambda a,b:a['success_only_rtt'].update(p999_ns=30),
            'rate-unit':lambda a,b:a['rates'].update(admitted_messages_per_second=1_000_000),
            'nan-rate':lambda a,b:a['rates'].update(admitted_messages_per_second=float('nan')),
            'invent-USB':lambda a,b:a['rates'].update(USB_bytes=0),
            'cpu-delta':lambda a,b:a['process_resources'].update(user_cpu_delta_ns=10),
            'resource-incomplete':lambda a,b:a['process_resources'].update(incomplete=True),
            'invent-kernel-resource':lambda a,b:a['process_resources'].update(URBs=1),
            'fixture-hidden':lambda a,b:a.update(test_fixture='AF_UNIX'),
        }
        for name,change in changes.items():
            a,b=fixture();change(a,b)
            with self.subTest(name=name),self.assertRaises(CaptureError):gate.load_application_reports(a,b)

    def test_two_individually_valid_pairs_cannot_mix_payloads(self):
        a,b=fixture('duplex');x,y=fixture('duplex')
        # Keep each row self-consistent; change only one direction's whole pair.
        from ws73_benchmark import frame
        raw=bytearray.fromhex(y['incoming'][0]['frame_hex']);raw[8]^=1
        seq=int.from_bytes(raw[24:28],'little')
        for j in range(32):raw[29+j]=raw[8+j%16]^((seq+j)&255)
        y['incoming'][0]['frame_hex']=raw.hex()
        with self.assertRaises(CaptureError):gate.load_application_reports(a,y)
        self.assertEqual(len(frame(b['incoming'][0]['frame_hex'],61,1)[0]),61)

    def test_json_reader_rejects_duplicate_fields_nonfinite_and_report_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'input'
            for raw in ['{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}','{']:
                p.write_text(raw)
                with self.subTest(raw=raw),self.assertRaises((CaptureError,ValueError)):gate.read_report(p)
            from unittest.mock import patch
            p.write_text('12345')
            with patch.object(gate,'MAX_REPORT_BYTES',4),self.assertRaises(CaptureError):gate.read_report(p)

    def test_actual_checker_cli_never_leaves_success_on_failure_or_overwrites_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);paths=[root/'a.json',root/'b.json'];out=root/'result.json'
            for p,r in zip(paths,fixture()):p.write_text(json.dumps(r))
            args=[sys.executable,str(Path(gate.__file__)),'--left',str(paths[0]),'--right',str(paths[1]),'--output',str(out)]
            result=subprocess.run(args,capture_output=True);self.assertEqual(result.returncode,0,result.stderr)
            saved=out.read_bytes();self.assertIs(json.loads(saved)['performance_qualified'],False)
            self.assertNotEqual(subprocess.run(args,capture_output=True).returncode,0)
            self.assertEqual(out.read_bytes(),saved)
            out.unlink();paths[1].unlink()
            self.assertNotEqual(subprocess.run(args,capture_output=True).returncode,0)
            self.assertEqual(json.loads(out.read_text())['status'],'FAIL')


class VmSelectedArtifacts(unittest.TestCase):
    def pair(self):
        import hashlib
        listing='benchmark::test: test\n\n1 test, 0 benchmarks\n'
        b=dict(compiled_source='a'*40,test_count=1,test_listing=listing,
               compiler_artifact=dict(reason='compiler-artifact',target=dict(name='slktest',kind=['lib']),profile=dict(test=True),executable='/build/current-tests'),
               artifacts=dict(slktest=dict(sha256='b'*64,bytes=100,path='/build/slktest'),tests=dict(sha256='c'*64,bytes=200,path='/build/current-tests')))
        v=dict(supervisor_exit=0,status='PASS_ISOLATED_NATIVE_ROOT_SMOKE',qemu_exit=0,physical_acceptance=False,native_acceptance=False,application_tests=1,application_test_listing_sha256=hashlib.sha256(listing.encode()).hexdigest(),inputs={'slktest':dict(sha256='b'*64),'slktest-tests':dict(sha256='c'*64)})
        return v,b
    def test_generic_vm_pass_cannot_upgrade_old_or_missing_selected_artifact(self):
        v,b=self.pair();self.assertEqual(gate.verify_vm_build(v,b)['tests'],1)
        for change in ['oldtests','wrongcount','wronglist','missingmain','wrongkind','notestprofile','wrongexecutable','noterminal','duplicate-list']:
            v,b=self.pair()
            if change=='oldtests':v['inputs']['slktest-tests']['sha256']='d'*64
            if change=='wrongcount':v['application_tests']=22
            if change=='wronglist':v['application_test_listing_sha256']='d'*64
            if change=='missingmain':v['inputs'].pop('slktest')
            if change=='wrongkind':b['compiler_artifact']['target']['kind']=['bin']
            if change=='notestprofile':b['compiler_artifact']['profile']['test']=False
            if change=='wrongexecutable':b['compiler_artifact']['executable']='/build/old-tests'
            if change=='noterminal':v['status']='RUNNING'
            if change=='duplicate-list':b['test_listing']+='benchmark::test: test\n'
            with self.subTest(change=change),self.assertRaises(CaptureError):gate.verify_vm_build(v,b)
