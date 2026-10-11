# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic syscall/wire/QMP fixtures; never real cancellation acceptance."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
from test_ws73_diagnostic_capture import inputs
from test_ws73_diagnostic_cancel import cancellation_fixture
from test_ws73_diagnostic_probe import admission_fixture
from ws73_capture import corroborate_diagnostic, CaptureError
from ws73_diagnostic_hold import corroborate_host_hold, PROPERTIES


def capture_fixture(deadline=False,autonomous=False):
    run,capture,diag=inputs()
    factory=cancellation_fixture
    if deadline:
        from test_ws73_diagnostic_deadline import deadline_fixture
        factory=deadline_fixture
    if autonomous:
        from test_ws73_diagnostic_autonomous import autonomous_fixture
        factory=autonomous_fixture
    diag.update(format_version=7 if autonomous else 6 if deadline else 5,deadline_requested=deadline or autonomous,autonomous_requested=autonomous,admission_copyout_requested=True,admission_eviction_requested=True,
                legacy_poll_copy_requested=True,cancellation_requested=True,
                records=factory(admission_fixture(diag['records'])))
    # Preserve original bootstrap/metadata; CLI windows move after new phases.
    capture['commands']=capture['commands'][:8];capture['complete']=capture['complete'][:8]
    def add(start,data,opcode=0x0406,reply=None):
        capture['commands'].append({'bus':1,'device':2,'opcode':opcode,'params':'','wall_ns':start,
                                    'completion':{'wall_ns':start+1}})
        capture['complete'].append({'bus':1,'device':2,'opcode':opcode,'status':0,'value':data,
                                    'wall_ns':start+2 if reply is None else reply,
                                    'usb_sha256':'a'*64,'usb_length':128})
    for row in diag['records']:
        if 'legacy_poll' in row or row.get('eviction')=='fill':add(row['start_wall_ns']+1,row['data'])
    held,final=[r for r in diag['records'] if 'cancel' in r]
    data=next(r['data'] for r in diag['records'] if r.get('case')=='metadata')
    add(held['start_wall_ns']+1,data,reply=final['start_wall_ns']+20)
    add(final['start_wall_ns']+30,data)
    eviction=[r for r in diag['records'] if 'eviction' in r]
    for i,row in enumerate(diag['cli_queries']):
        start=eviction[-1]['end_wall_ns']+1000*(i+1)
        row.update(start_wall_ns=start,end_wall_ns=start+20)
        value=next(r['data'] for r in diag['records'] if r.get('opcode')==[0x0406,0x0403,0x0404,0x0402][i])
        add(start+1,value,opcode=[0x0406,0x0403,0x0404,0x0402][i])
    for key in ('commands','complete'):capture[key].sort(key=lambda r:r['wall_ns'])
    for i,row in enumerate(sorted(capture['commands']+capture['complete'],key=lambda r:r['wall_ns'])):row['record']=i
    run['initial'][0]['observed_wall_ns']=diag['cli_queries'][-1]['end_wall_ns']+1000
    markers=[r for r in diag['records'] if 'hold_phase' in r]
    observations=[]
    for i,(stage,marker) in enumerate(zip(['armed','held','released'],markers)):
        values=[i==0,i==1,int(i>0),int(i==2),0,0,False,0]
        observations.append({'stage':stage,'request':marker,'host_wall_ns':100+i,
                             'state':dict(zip(PROPERTIES,values))})
    diag['host_hold_acknowledgements']=observations
    host={'method':'QMP_HOLD_ACTUAL_SUCCESSFUL_IN81','complete':True,'observations':observations,
          'physical_acceptance':False,'automatic_fault_recovery_acceptance':False}
    log='WS73_TEST_RUNTIME_HOLD: dev 1:101 bytes=128 host_status=0 holds=1 sha256='+ 'a'*64+'\n'
    log+='WS73_TEST_RUNTIME_HOLD_RELEASE: dev 1:101 bytes=128 bounded=0 releases=1\n'
    return run,capture,diag,host,log


class CancellationCaptureTests(unittest.TestCase):
    def test_fixture_requires_both_wire_pairs_and_separate_host_corrobation(self):
        run,capture,diag,host,log=capture_fixture();_,proofs=corroborate_diagnostic(run,capture,diag)
        cancel=[p for p in proofs if p['caller'].startswith('C ') and 'cancel' in p['caller']]
        self.assertEqual(len(cancel),3)
        proof=corroborate_host_hold(host,diag,proofs,log,{'bus':1,'address':101})
        self.assertEqual(proof['host_transfer_bytes'],128);self.assertFalse(proof['physical_acceptance'])

    def test_early_new_out_early_reply_queued_out_extra_reply_and_missing_old_reply_fail(self):
        for mutation in ['early_out','early_reply','queued_out','extra_reply','missing_reply']:
            run,capture,diag,_,_=capture_fixture();held,final=[r for r in diag['records'] if 'cancel' in r]
            late=[c for c in capture['commands'] if final['start_wall_ns']<=c['wall_ns']<=final['end_wall_ns']]
            replies=[c for c in capture['complete'] if final['start_wall_ns']<=c['wall_ns']<=final['end_wall_ns']]
            if mutation=='early_out':late[0]['wall_ns']=held['end_wall_ns']-1
            if mutation=='early_reply':replies[0]['wall_ns']=held['end_wall_ns']-1
            if mutation=='queued_out':capture['commands'].append({**late[0],'opcode':0x0403})
            if mutation=='extra_reply':capture['complete'].append(copy.deepcopy(replies[0]))
            if mutation=='missing_reply':capture['complete'].remove(replies[0])
            with self.subTest(mutation=mutation):
                with self.assertRaises(CaptureError):corroborate_diagnostic(run,capture,diag)

    def test_missing_mode_downgrade_and_boolean_version_do_not_hide_cancellation(self):
        for key,value in [('cancellation_requested',False),('format_version',4),('format_version',True)]:
            run,capture,diag,_,_=capture_fixture();diag[key]=value
            with self.assertRaises(CaptureError):corroborate_diagnostic(run,capture,diag)

    def test_host_wrong_bytes_hash_counter_or_bounded_release_cannot_pass(self):
        for mutation in ['hash','length','bounded','duplicate','wrong_owner','readback','missing_ack']:
            run,capture,diag,host,log=capture_fixture();_,proofs=corroborate_diagnostic(run,capture,diag)
            if mutation=='hash':log=log.replace('a'*64,'b'*64)
            if mutation=='length':log=log.replace('bytes=128','bytes=129')
            if mutation=='bounded':log=log.replace('bounded=0','bounded=1')
            if mutation=='duplicate':log+=log
            if mutation=='wrong_owner':log=log.replace('dev 1:101','dev 1:102')
            if mutation=='readback':host['observations'][2]['state']['test-runtime-in-bounded-releases']=1
            if mutation=='missing_ack':diag['host_hold_acknowledgements']=[]
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):corroborate_host_hold(host,diag,proofs,log,{'bus':1,'address':101})
