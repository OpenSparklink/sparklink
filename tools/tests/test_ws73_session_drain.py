# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic metadata boundaries only;not Native/USB/fairness qualification."""
import copy
import unittest
from ws73_session_drain import decode,settled,corroborate,BUDGET_NS
from ws73_capture import CaptureError


def fixture():
    owners=[];before=[];after=[]
    def observed(entry,open,retired,start):
        o,obj=entry['owner'],entry['object'];failed=1 if o['index']==0 else 0
        v=dict(index=o['index'],generation=7,lifetime=11,handle=3,capacity=5,outstanding=0,debt=0,queued=0,active=0,open=open,pending=0,retired=retired,failed=failed,allocated=3+failed,flags=0)
        r=dict(args=['/bin/slctl','--adapter',o['path'],'transport-status',obj['path']],exit=0,stdout='SessionTxStatus: '+' '.join(k+'='+str(value) for k,value in v.items())+'\n',start_monotonic_ns=start,end_monotonic_ns=start+10,start_wall_ns=start+10000,end_wall_ns=start+10010)
        return dict(values=v,receipt=r)
    for i in range(2):
        owner=dict(owner=dict(index=i,generation=7,path=f'/adapter{i}',buffers=[254,5,0,0],bus=1,device=i+2),object=dict(lifetime=11,handle=3,path='/link'+str(i)))
        owners.append(owner);before.append(observed(owner,1,2,100+i*20));after.append(observed(owner,0,3,300+i*20))
    row=dict(version=1,status='NATIVE_TERMINAL_AND_ZERO_DEBT_OBSERVED_NOT_CALLBACK_DRAIN',start_monotonic_ns=200,deadline_monotonic_ns=200+BUDGET_NS,fd_reaped_wall_ns=10290,samples=[dict(sequence=0,observations=after,wall_ns=10400,monotonic_ns=400)],end_monotonic_ns=400,end_wall_ns=10400)
    channel=dict(owners=owners,close_start_monotonic_ns=200,close_start_wall_ns=10200,end_wall_ns=10400,before_close_status=before,session_drain=row)
    return channel,dict(commands=[],acb_packets=[])


class SessionDrain(unittest.TestCase):
    def test_state_facts_never_imply_callback_or_credit_truth(self):
        channel,capture=fixture();p=corroborate(channel,capture)
        self.assertFalse(p['callback_drain_proved']);self.assertFalse(p['nocp_accuracy_proved']);self.assertFalse(p['safe_reuse'])
        for i,row in enumerate(channel['before_close_status']):self.assertFalse(settled(row['values'],i))

    def test_identity_errors_pending_and_original_deadline_rejected(self):
        for kind in ['old-gen','failed-process','wrong-args','float-values','missing-owner','pending','debt','worker','failed-close','expired','extended','not-first','no-positive','float-clock','backwards-clock','future-wall','new-wire']:
            ch,cap=fixture();row=ch['session_drain'];sample=row['samples'][0];entry=sample['observations'][0]
            if kind=='old-gen':ch['owners'][0]['owner']['generation']=8
            elif kind=='failed-process':entry['receipt']['exit']=1
            elif kind=='wrong-args':entry['receipt']['args'][-1]='/other-lifetime'
            elif kind=='float-values':entry['values']['debt']=0.0
            elif kind=='missing-owner':sample['observations'].pop()
            elif kind in ['pending','debt','worker','failed-close']:
                if kind=='pending':a,b='pending=0','pending=1'
                elif kind=='debt':a,b='outstanding=0 debt=0','outstanding=1 debt=1'
                elif kind=='worker':a,b='flags=0','flags=1'
                else:a,b='retired=3 failed=1','retired=2 failed=2'
                entry['receipt']['stdout']=entry['receipt']['stdout'].replace(a,b)
                entry['values']=decode(entry['receipt'],ch['owners'][0]) if kind!='pending' else entry['values']
            elif kind=='expired':sample['monotonic_ns']=row['deadline_monotonic_ns']
            elif kind=='extended':row['deadline_monotonic_ns']+=1
            elif kind=='not-first':row['samples'].append(copy.deepcopy(sample));row['samples'][1].update(sequence=1,monotonic_ns=500)
            elif kind=='no-positive':ch['before_close_status'].pop()
            elif kind=='float-clock':entry['receipt']['start_monotonic_ns']=300.0
            elif kind=='backwards-clock':entry['receipt']['start_wall_ns']=entry['receipt']['end_wall_ns']+1
            elif kind=='future-wall':entry['receipt']['end_wall_ns']=sample['wall_ns']+1
            else:cap['commands'].append(dict(bus=1,device=2,wall_ns=10105))
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError,CaptureError)):corroborate(ch,cap)
