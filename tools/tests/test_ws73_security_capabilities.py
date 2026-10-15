# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic evidence rejection tests, not hardware/pairing qualification."""
import copy
import errno
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ws73_channel_link_down import fixture as down_fixture
from ws73_security_capabilities import verify,corroborate,request,OFFER,Result
from ws73_management_setup import setup,decode
from sparklink.structs import SleLinkSnapshot


def fixture():
    r,c=down_fixture();old=r.pop('data_link_down');r.update(status='SECURITY_CAPABILITIES_PASS',end_wall_ns=500);g=r['channel_grant'];g.pop('revoke_prefix');g.pop('armed');g.pop('blocking_witness')
    row=dict(status='REAL_LIMITED_CAPABILITIES_PASS',start_wall_ns=160,g_start_before_wall_ns=180,t_arm_before_monotonic_ns=170,observed_monotonic_ns=260,observed_wall_ns=250,cleanup_before_wall_ns=350,cleanup_after_wall_ns=370,scan_checked_wall_ns=410,before_links=old['links_before'],after_links=old['links_before'],before_ready=old['ready_before'],after_ready=old['ready_before'],management_before=old['management_before'],management_after=old['management_before'],management_cleaned=old['management_cleaned'],requests=[],results=[],negative=[],down=old['down'],cleanup_result=old['result'])
    r['security_capabilities']=row
    row['ordinary_denial']=dict(credentials=copy.deepcopy(g['workers'][0]['credentials']),submit_errno=errno.EPERM,result_errno=errno.EPERM)
    expected={'generation':errno.ENODEV,'lifetime':errno.ESTALE,'address':errno.ESTALE,'role':errno.ESTALE,'profile':errno.EOPNOTSUPP,'flags':errno.EINVAL,'reserved':errno.EINVAL,'nonowner_submit':errno.EPERM,'nonowner_result':errno.EPERM,'same_lifetime_restart':errno.EBUSY}
    for n in [0,1]:
        s=setup(r['initial_snapshots'][n],n);l=decode(SleLinkSnapshot,row['before_links'][n]).links[0];req=request(s,l);row['requests'].append(bytes(req).hex())
        out=Result(version=1,profile=1,generation=req.generation,lifetime=req.lifetime,request_id=1,handle=req.handle,role=req.role,state=4,flags=7);out.local_caps[:]=OFFER;out.peer_caps[:]=OFFER;row['results'].append(bytes(out).hex())
        if n==1:out.state=1;out.flags=0;out.peer_caps[:]=bytes(10);row['t_armed']=bytes(out).hex()
        row['negative'] += [dict(index=n,kind=k,errno=e) for k,e in expected.items()]
    before=copy.deepcopy(g['business']);after=copy.deepcopy(before)
    for b in after:b.update(label='after_capabilities',start_wall_ns=270,end_wall_ns=320)
    g['business']+=after
    c['acb_packets'].pop();extra=copy.deepcopy(c['acb_packets'])
    for a in extra:a['wall_ns']=280;a['record']+=40
    c['acb_packets']+=extra
    c['commands']=[];c['complete']=[];c['native_events']=[]
    for n in [0,1]:
        tx=0x134 if n==0 else 0x135;rx=0x135 if n==0 else 0x134;when=200 if n==0 else 220
        c['commands'].append(dict(**r['usb'][n],opcode=0x1812,params=(b'\0\0'+tx.to_bytes(2,'little')+b'\x0a'+OFFER).hex(),wall_ns=when,completion={'record':61},record=60+n))
        c['complete'].append(dict(**r['usb'][n],opcode=0x1812,status=0,value=(b'\0\0'+tx.to_bytes(2,'little')).hex(),wall_ns=when+5,record=62+n))
        c['native_events'].append(dict(**r['usb'][n],event=0x14,params=(b'\0\0'+rx.to_bytes(2,'little')+b'\x0a'+OFFER).hex(),wall_ns=230 if n==0 else 210,record=64+n))
        row['down'][n]['wall_ns']=360+n;c['native_events'].append(dict(**r['usb'][n],**row['down'][n],record=100+n))
    c['commands'].append(dict(**r['usb'][0],opcode=0x1403,params='000013',wall_ns=355,completion={'record':90},record=89))
    c['native_events'].append(dict(**r['usb'][0],event=1,params='03140100',wall_ns=358,record=91))
    for enabled,when in [(True,380),(False,400)]:
        c['commands'].append(dict(**r['usb'][1],opcode=0x1002,params=bytes([enabled,0]).hex(),wall_ns=when,completion={'record':110},record=109))
        c['complete'].append(dict(**r['usb'][1],opcode=0x1002,status=0,wall_ns=when+1))
    return r,c


class LimitedCapabilities(unittest.TestCase):
    def test_actual_caps_both_wire_directions_and_ordinary_business_required(self):
        r,c=fixture();verify(r);p=corroborate(r,c);self.assertEqual(p['business_round_trips'],4);self.assertEqual(len(p['controllers']),2)

    def test_approval_local_success_or_trusted_flags_cannot_replace_peer_rx(self):
        for kind in ['root_business','ordinary_approval','wrong_lifetime','armed_fake_rx','mitm','wrong_author','restart','missing_business','trusted']:
            r,c=fixture();row=r['security_capabilities']
            if kind=='root_business':r['channel_grant']['workers'][0]['credentials']['uids']=[0]*4
            elif kind=='ordinary_approval':row['ordinary_denial']['submit_errno']=0
            elif kind in ['wrong_lifetime','mitm','trusted']:
                v=decode(Result,row['results'][0])
                if kind=='wrong_lifetime':v.lifetime+=1
                elif kind=='mitm':v.local_caps[2]=5
                else:v.flags|=8
                row['results'][0]=bytes(v).hex()
            elif kind=='armed_fake_rx':v=decode(Result,row['t_armed']);v.flags=4;row['t_armed']=bytes(v).hex()
            elif kind=='wrong_author':row['negative'][7]['errno']=0
            elif kind=='restart':row['negative'][9]['errno']=0
            else:r['channel_grant']['business'].pop()
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify(r)

    def test_usb_complete_alone_or_wrong_reply_is_not_delivery(self):
        for kind in ['missing_rx','wrong_rx','missing_out','failed_complete','wrong_echo','causality','scan','install','business']:
            r,c=fixture()
            if kind=='missing_rx':c['native_events'].pop(0)
            elif kind=='wrong_rx':c['native_events'][0]['params']='000035010a'+bytes(10).hex()
            elif kind=='missing_out':c['commands'].pop(0)
            elif kind=='failed_complete':c['complete'][0]['status']=1
            elif kind=='wrong_echo':c['complete'][0]['value']='01003401'
            elif kind=='causality':c['native_events'][0]['wall_ns']=190
            elif kind=='scan':c['complete'][-1]['status']=1
            elif kind=='install':c['commands'].append(dict(**r['usb'][0],opcode=0x1c05,params='',wall_ns=240))
            else:c['acb_packets'].pop(0)
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c)
