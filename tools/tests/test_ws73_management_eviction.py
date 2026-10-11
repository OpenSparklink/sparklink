# SPDX-License-Identifier: GPL-2.0-only
"""Canonical evidence fixtures only; actual ioctl/USB/RF qualification is separate."""
import errno
import subprocess
import tempfile
import unittest
from pathlib import Path
from test_ws73_management_ready_peer import ready_fixture
from ws73_management_partial import standby,verify_records,corroborate
from ws73_management_eviction import expected,replacement,SURVIVORS,SUBMIT,RESULT
from sparklink.structs import SleControllerSnapshot


def fixture(case='release',domain='advertising'):
    r,peer,cap=ready_fixture(case,domain)
    def scale(value):
        if isinstance(value,dict):
            return {k:v*1000 if k.endswith('_wall_ns') or k=='wall_ns' else scale(v) for k,v in value.items()}
        if isinstance(value,list):return [scale(v) for v in value]
        return value
    r=scale(r);cap=scale(cap)
    r.update(format_version=9,status='MANAGED_ORDINARY_QUEUE_EVICTION_PASS',ordinary_queue_eviction=True,cancelled_request_id=1064)
    snapshot=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(r['initial_snapshots'][0]))
    def collection(queued=None,final=False):
        return dict(evicted=[dict(request_id=i,errno=errno.ENOENT,raw=None) for i in ([2] if domain=='scanning' else [])+[1,1000]],
            retained=[dict(request_id=i,errno=0,raw=expected(snapshot,i,domain,1 if i==queued else 5,final)) for i in SURVIVORS])
    r['cancelled']=expected(snapshot,1064,domain,5);r['final_result']=expected(snapshot,1064,domain,5,True)
    opcode=0xc02 if domain=='advertising' else 0x1001
    burst=dict(scheduler=0,online_cpus=2,start_wall_ns=260000,first_end_wall_ns=270000,end_wall_ns=281000,
        first_input=bytes(replacement(snapshot,1000,domain)).hex(),superseded_original=dict(request_id=1,errno=0,raw=expected(snapshot,1,domain,5,opcode=opcode)),
        before_release=collection(1064),workers=[])
    if domain=='scanning':burst['initializer_rejection']=dict(input=bytes(standby(snapshot,1000,domain)).hex(),errno=errno.EBUSY,result=dict(request_id=1000,errno=errno.ENOENT,raw=None))
    for n in [0,1]:
        worker=dict(worker=n,tid=10+n,fd=30+n,scheduler=0,online_cpus=2,closed_errno=errno.EBADF,start_wall_ns=271000,end_wall_ns=280000,calls=[])
        for j,i in enumerate(SURVIVORS[n*32:(n+1)*32]):
            start=272000+100*j+25*n
            worker['calls'].append(dict(request_id=i,input=bytes(replacement(snapshot,i,domain)).hex(),errno=0,start_wall_ns=start,end_wall_ns=start+75))
        burst['workers'].append(worker)
    r.update(ordinary_burst=burst,after_release_results=collection(),after_drain_results=collection(final=True))
    def command(op,t,params):return dict(bus=1,device=2,opcode=op,wall_ns=t,record=t,completion=dict(wall_ns=t+1),params=params)
    def reply(op,t,value='',sha='a'*64):return dict(bus=1,device=2,opcode=op,wall_ns=t,record=t,value=value,status=0,usb_length=178,usb_sha256=sha)
    adv=bytearray(49);adv[12:18]=bytes(snapshot.address)
    cap['commands'].append(command(opcode,150000,adv.hex() if domain=='advertising' else '0000010040062003'))
    cap['complete'].append(reply(opcode,401000,'06' if domain=='advertising' else ''))
    if domain=='advertising':
        cap['commands'].append(command(0xc05,402000,'00'*5));cap['complete'].append(reply(0xc05,403000))
    else:
        cap['commands'] += [command(0xc02,55000,adv.hex()),command(0xc05,75000,'00'*5)]
        cap['complete'] += [reply(0xc02,65000,'06'),reply(0xc05,85000)]
    for key in ['commands','complete']:cap[key].sort(key=lambda v:v['wall_ns'])
    host=dict(method='QMP_HOLD_ACTUAL_SUCCESSFUL_IN81',complete=True,physical_acceptance=False,automatic_fault_recovery_acceptance=False,observations=r['hold_acknowledgements'])
    log='WS73_TEST_RUNTIME_HOLD: dev 1:124 bytes=178 host_status=0 holds=1 sha256='+'a'*64+'\nWS73_TEST_RUNTIME_HOLD_RELEASE: dev 1:124 bytes=178 bounded=0 releases=1\n'
    return r,host,cap,log


class EvictionTests(unittest.TestCase):
    def test_six_fd_domain_cases_require_all_actual_result_bytes_and_wire(self):
        for domain in ['advertising','scanning']:
            for case in ['release','close','dup']:
                r,h,c,l=fixture(case,domain)
                with self.subTest(domain=domain,case=case):
                    verify_records(r);p=corroborate(r,h,c,l,dict(bus=1,address=124))
                    self.assertEqual(p['retained_terminal_results'],64)
                    self.assertEqual(len(p['wire']['ready_peer_activity']['proofs']),14)
                    self.assertTrue(p['ordinary_scheduler_queue_eviction_case_acceptance'])
                    self.assertFalse(p['whole_managed_acceptance'])

    def test_missing_eviction_selected_replacement_fake_success_or_scheduler_is_rejected(self):
        for change in ['old-format','model','fifo','cpu','worker-fifo','same-worker','alias-open','partial','non-overlap','failed-call','wrong-input','retained-original','missing-result','selected-replacement','success','multiple-queued','before-reply','late','dup-revoked','fake-ready','fake-off','no-peer']:
            r,h,c,l=fixture('dup');b=r['ordinary_burst']
            if change=='old-format':r['format_version']=7
            if change=='model':r['synthetic_support']=True
            if change=='fifo':b['scheduler']=1
            if change=='cpu':b['online_cpus']=1
            if change=='worker-fifo':b['workers'][0]['scheduler']=1
            if change=='same-worker':b['workers'][1]['tid']=b['workers'][0]['tid']
            if change=='alias-open':b['workers'][0]['closed_errno']=0
            if change=='partial':b['workers'][0]['calls'].pop()
            if change=='non-overlap':
                for call in b['workers'][1]['calls']:
                    call['start_wall_ns']+=5000;call['end_wall_ns']+=5000
            if change=='failed-call':b['workers'][0]['calls'][0]['errno']=errno.EBUSY
            if change=='wrong-input':b['workers'][0]['calls'][0]['input']=r['input']
            if change=='retained-original':b['before_release']['evicted'][0]['errno']=0
            if change=='missing-result':r['after_drain_results']['retained'].pop()
            if change=='selected-replacement':r['after_release_results']['retained'][0]['raw']=r['pending']
            if change=='success':r['after_drain_results']['retained'][0]['raw']=r['ready_peer']['during'][0]['result']
            if change=='multiple-queued':b['before_release']['retained'][0]['raw']=b['before_release']['retained'][-1]['raw']
            if change=='before-reply':r['management_observations'][0]['raw']=r['final_management']
            if change=='late':r['release_after_wall_ns']=r['submit_before_wall_ns']+400000000
            if change=='dup-revoked':r['after_first_management']=r['revoking']
            if change=='fake-ready':r['final_snapshot']=r['peer_after']
            if change=='fake-off':r['final_result']=r['pending']
            if change=='no-peer':r['active_ready_peer']=False
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(r)

    def test_extra_commands_wrong_hash_or_peer_failure_cannot_pass(self):
        for change in ['extra-config','unselected-start','unnecessary-stop','wrong-hash','peer-failed','extra-reply']:
            r,h,c,l=fixture(domain='scanning')
            if change in ['extra-config','unselected-start','unnecessary-stop']:
                c['commands'].append(dict(bus=1,device=2,opcode=0x1001 if change=='extra-config' else 0x1002,params='0100',wall_ns=402000))
            if change=='wrong-hash':l=l.replace('a'*64,'b'*64)
            if change=='peer-failed':next(v for v in c['complete'] if v['device']==3)['status']=11
            if change=='extra-reply':c['complete'].append(dict(c['complete'][-1],device=2,wall_ns=403000))
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(r,h,c,l,dict(bus=1,address=124))

    def test_scan_initializer_refusal_preserves_no_admission(self):
        for change in ['success','admitted','wrong-id','missing']:
            r,h,c,l=fixture(domain='scanning');v=r['ordinary_burst']['initializer_rejection']
            if change=='success':v['errno']=0
            if change=='admitted':v['result']['errno']=0
            if change=='wrong-id':v['result']['request_id']=1
            if change=='missing':del r['ordinary_burst']['initializer_rejection']
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):verify_records(r)

    def test_raw_worker_ioctl_numbers_match_canonical_kernel_uapi(self):
        from ws73_target import LINUX
        kernel=LINUX
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'abi.c';binary=Path(tmp)/'abi'
            c.write_text('#include "sparklink_ioctl.h"\n_Static_assert(SL_IOCTL_DISCOVERY_SUBMIT == '+str(SUBMIT)+', "submit");\n_Static_assert(SL_IOCTL_DISCOVERY_RESULT == '+str(RESULT)+', "result");\nint main(void) { return 0; }\n')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(kernel/'include/uapi/linux'),str(c),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
