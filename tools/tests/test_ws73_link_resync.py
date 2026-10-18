# SPDX-License-Identifier: GPL-2.0-only
"""Offline negative fixtures, never real ring/RF acceptance."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_link_resync import corroborate,status
from ws73_capture import CaptureError,marker_data
from sparklink.structs import SleLinkSnapshot,SleControllerSnapshot,SleManagementQuery


def fixture():
    run=dict(daemon_before=dict(pid=123),commands=[],link_resync=[]);capture=dict(reports=[],commands=[])
    owners=[dict(index=i,generation=7+i,bus=1,device=i+1,address=':'.join([f'{i+1:02X}']*6)) for i in [0,1]]
    def observation(owner,seq,revision):
        table=SleLinkSnapshot(version=1,profile=1,generation=owner['generation'],dev_index=owner['index'],flags=1,event_seq=seq,revision=revision)
        controller=SleControllerSnapshot(version=1,profile=1,generation=owner['generation'],dev_index=owner['index'],flags=1);controller.address[:]=bytes.fromhex(owner['address'].replace(':',''))
        management=SleManagementQuery(version=1,generation=owner['generation'],state=1,mode=1)
        return dict(raw_links=bytes(table).hex(),raw_controller=bytes(controller).hex(),raw_management=bytes(management).hex(),links=dict(event_seq=seq,revision=revision,generation=owner['generation']))
    for phase,(caller,peer) in enumerate([owners,owners[::-1]]):
        base=phase*300;marker=f'{phase+1:032x}'
        supervisor=dict(phase=phase,pid=123,request=dict(phase=phase,caller=caller,peer=peer),status='REAL_RING_OVERFLOW_RESUMED',
            stop_wall_ns=base+99,stopped_wall_ns=base+100,continue_wall_ns=base+200,end_wall_ns=base+201,stopped_status='State:\tT (stopped)\n',
            before=observation(caller,10,phase*2),peer_before=observation(peer,10,phase*2),peer_stopped=observation(peer,10,phase*2),observations=[observation(caller,10,phase*2),observation(caller,50,phase*2)])
        row=dict(phase=phase,caller=caller,peer=peer,marker=marker,status='REAL_RING_RESYNC_EVIDENCE_PENDING',supervisor=supervisor,before_command=len(run['commands']),after_commands=[len(run['commands'])+1])
        run['link_resync'].append(row)
        for seq,lost in [(10,0),(50,8)]:run['commands'].append(dict(args=['slctl','show'],exit=0,stdout=f'  Native links: event_seq={seq} revision={phase*2} known=true lost={lost}\n'))
        for n in range(40):capture['reports'].append(dict(bus=caller['bus'],device=caller['device'],wall_ns=base+110+n,address=peer['address'],data=marker_data(marker).hex(),record=phase*40+n,hcc_offset=92))
    return run,capture


class RingResyncEvidence(unittest.TestCase):
    def test_both_roles_distinct_reports_and_quiet_wire_required(self):
        run,capture=fixture();self.assertEqual([p['lost_delta'] for p in corroborate(run,capture)],[8,8])
        for field,value in [('reports',capture['reports'][:-1]),('commands',[dict(wall_ns=150)])]:
            bad=copy.deepcopy(capture);bad[field]=value
            with self.subTest(field=field),self.assertRaises(CaptureError):corroborate(run,bad)
        bad=copy.deepcopy(capture);bad['reports'][1]=bad['reports'][0]
        with self.assertRaises(CaptureError):corroborate(run,bad)

    def test_unknown_missing_loss_wrong_barrier_and_replacement_fail(self):
        run,capture=fixture()
        for old,new in [('known=true','known=false'),('lost=8','lost=0'),('event_seq=50','event_seq=49'),('revision=0','revision=1')]:
            bad=copy.deepcopy(run);bad['commands'][1]['stdout']=bad['commands'][1]['stdout'].replace(old,new)
            with self.subTest(new=new),self.assertRaises(CaptureError):corroborate(bad,capture)
        bad=copy.deepcopy(run);bad['link_resync'][0]['supervisor']['pid']=456
        with self.assertRaises(CaptureError):corroborate(bad,capture)

    def test_original_bytes_and_actual_stopped_state_required(self):
        run,capture=fixture()
        bad=copy.deepcopy(run);bad['link_resync'][0]['supervisor']['stopped_status']='State:\tS (sleeping)\n'
        with self.assertRaises(CaptureError):corroborate(bad,capture)
        for field in ['raw_controller','raw_links','raw_management']:
            bad=copy.deepcopy(run);row=bad['link_resync'][0]['supervisor']['observations'][0];row[field]='00'*(len(row[field])//2)
            with self.subTest(field=field),self.assertRaises(CaptureError):corroborate(bad,capture)

    def test_status_requires_one_original_observation(self):
        text='  Native links: event_seq=10 revision=2 known=true lost=8\n'
        self.assertEqual(status(text),dict(event_seq=10,revision=2,known=True,lost=8))
        for value in ['',text+text,text.replace('true','1')]:
            with self.assertRaises(CaptureError):status(value)

if __name__=='__main__':unittest.main()
