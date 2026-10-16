# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic evidence refusal controls, not kernel or hardware qualification."""
import copy,json,unittest
from ws73_security_agent import witness
from ws73_capture import CaptureError
from test_ws73_numeric_agent import fixture

def live_fixture(mode='numeric-approve'):
    row,phase,daemon,capture=fixture(mode)
    row['live_security_required']=True
    info=next(v for v in row['events'] if v['stage']=='probe_identity')['infos']
    for obj,identity in zip(phase['typed_objects'],info):
        path=obj['object']['path'];level=2 if mode=='numeric-approve' else 0
        facts=[15,4,16] if level else [0,0,0]
        row['events'] += [dict(stage='current_security_before',wall_ns=1,path=path,snapshot=identity[:3]+[1,1,0,0,0,0]),
                          dict(stage='current_security_after',wall_ns=98,path=path,snapshot=identity[:3]+[2,1,level]+facts)]
    seal(row)
    return row,phase,daemon,capture

def seal(row):row['command']['stdout']='\n'.join(json.dumps(v) for v in row['events'])

class LiveSecurity(unittest.TestCase):
    def test_positive_and_rejected_expired_mechanisms(self):
        for mode in ['numeric-approve','numeric-reject','numeric-late']:
            r,p,d,_=live_fixture(mode);witness(r,p,d)
    def test_missing_duplicate_foreign_or_inconsistent_snapshot_fails(self):
        base,p,d,_=live_fixture()
        for kind in ['missing','duplicate','identity','epochzero','epochold','epochsame','profile','level','flags','method','keysize','time','unknownstage']:
            r=copy.deepcopy(base);rows=r['events'];v=next(v for v in rows if v['stage']=='current_security_after')
            if kind=='missing':rows.remove(v)
            elif kind=='duplicate':rows.append(copy.deepcopy(v))
            elif kind=='identity':v['snapshot'][1]+=1
            elif kind=='epochzero':v['snapshot'][3]=0
            elif kind=='epochold':v['snapshot'][3]=-1
            elif kind=='epochsame':v['snapshot'][3]=1
            elif kind=='profile':v['snapshot'][4]=0
            elif kind=='level':v['snapshot'][5]=1
            elif kind=='flags':v['snapshot'][6]=13
            elif kind=='method':v['snapshot'][7]=3
            elif kind=='keysize':v['snapshot'][8]=7
            elif kind=='time':v['wall_ns']=0
            elif kind=='unknownstage':v['stage']='optional-unverified'
            seal(r)
            with self.subTest(kind=kind),self.assertRaises(CaptureError):witness(r,p,d)

if __name__=='__main__':unittest.main()
