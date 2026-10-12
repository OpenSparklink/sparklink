# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic receipt mutation tests; never daemon/WS73 qualification."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'bindings/python'))
from sparklink.structs import SleControllerSnapshot, SleManagementQuery, SleLinkSnapshot
from test_ws73_channel_grant import fixture
from ws73_channel_daemon_crash import verify


def record():
    g,_=fixture();g['status']='DAEMON_CHANNEL_GATE_PASS';owners=[];transfers=[];observations=[];after=[]
    for n,w in enumerate(g['workers']):
        owner=dict(index=n,generation=n+7,address=f'00:01:02:03:04:0{n}',port=f'1-{n+1}',bus=1,device=n+2)
        obj=dict(path=f'/test/link{n}',handle=0,lifetime=1,role=n,address_type=0,address=owner['address'])
        owners.append(dict(owner=owner,object=obj));after.append(copy.deepcopy(owner))
        before=dict(pid=w['pid']);w['scm_rights']=dict(inode=n+100,before=before)
        client=dict(pid=n+500,daemon_pid=17,daemon_owner=':1.2',path=obj['path'],kernel_sender=dict(pid=n+500,uid=1000,gid=1002),inode=n+100)
        transfers.append(dict(client=client,client_exit=0,broker_closed=True,before=before))
        snapshot=SleControllerSnapshot(generation=n+7,version=1,dev_index=n,flags=1,profile=1)
        management=SleManagementQuery(generation=n+7,version=1)
        links=SleLinkSnapshot(generation=n+7,version=1,dev_index=n,flags=1,profile=1)
        observations.append(dict(snapshot=bytes(snapshot).hex(),management=bytes(management).hex(),links=bytes(links).hex(),wall_ns=120))
    g['owners']=owners;g['transfers']=transfers
    for key in ['other_after_death','other_after_successor']:g[key]=dict(g['after_withdrawal'],stage='denied')
    g['after_withdrawal']['stage']=g['after_successor']['stage']='denied'
    for b in g['business']:b['end_wall_ns']=40
    return dict(status='REAL_DAEMON_CHANNEL_DEATH_EVIDENCE_PENDING',automatic_recovery_acceptance=False,physical_acceptance=False,independent_owner_isolation=False,daemon_channel=g,bus_before=dict(pid=17,owner=':1.2'),bus_after=dict(pid=18,owner=':1.3'),death=dict(pid=17,status=137,before_wall_ns=100,reaped_wall_ns=110),successor=dict(pid=18,wall_ns=140),armed_wall_ns=99,cleanup_observations=[observations],after_ready=after)


class DeathReceipt(unittest.TestCase):
    def test_rejects_scope_authentication_cleanup_and_order_mutations(self):
        original=record();verify(original)
        ended=copy.deepcopy(original);ended['daemon_channel']['blocked_result']['errno']=116;verify(ended)
        for kind in ['no_death','same_owner','order','credentials','wrong_inode','wrong_path','not_reaped','ready_generation','not_free','before_reap','late_wake','peer_writable','duplicate_direction','duplicate_nonce','isolation_claim','recovery_claim']:
            r=copy.deepcopy(original);g=r['daemon_channel']
            if kind=='no_death':r['death']['status']=0
            elif kind=='same_owner':r['bus_after']['owner']=':1.2'
            elif kind=='order':r['death']['before_wall_ns']=80
            elif kind=='credentials':g['transfers'][0]['client']['kernel_sender']['uid']=0
            elif kind=='wrong_inode':g['workers'][0]['scm_rights']['inode']=900
            elif kind=='wrong_path':g['transfers'][0]['client']['path']='/other'
            elif kind=='not_reaped':g['transfers'][0]['client_exit']=1
            elif kind=='ready_generation':r['after_ready'][0]['generation']=99
            elif kind=='not_free':
                v=SleManagementQuery.from_buffer_copy(bytes.fromhex(r['cleanup_observations'][0][0]['management']));v.state=1;r['cleanup_observations'][0][0]['management']=bytes(v).hex()
            elif kind=='before_reap':r['cleanup_observations'][0][0]['wall_ns']=90
            elif kind=='late_wake':g['blocked_result']['errno']=11
            elif kind=='peer_writable':g['other_after_successor']['poll']|=4
            elif kind=='duplicate_direction':g['business'][1]['initiator']=0
            elif kind=='duplicate_nonce':g['business'][1]=copy.deepcopy(g['business'][0])
            elif kind=='isolation_claim':r['independent_owner_isolation']=True
            elif kind=='recovery_claim':r['automatic_recovery_acceptance']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify(r)
