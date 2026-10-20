# SPDX-License-Identifier: GPL-2.0-only
"""Actual resource parsers/receipt arithmetic with explicit proc fixtures.

No successful Native/USB/VM dependencies. VM collection has its own real gate.
"""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_benchmark_resources as resources
from ws73_capture import CaptureError


def snapshot(pid=123,begin=300,user=10,system=4):
    # Linux stat fields3..24; these literal positions are independent oracle.
    fields=['S','500','500','500','0','-1','0','0','0','0','0',str(user),str(system),
            '0','0','20','0','1','0','777','8192','2']
    raw=f'{pid} (slk (test)) '+ ' '.join(fields)+'\n'
    status=f'Name:\tslktest\nTgid:\t{pid}\nPid:\t{pid}\nPPid:\t500\n'
    status+='Uid:\t1004 1004 1004 1004\nGid:\t1004 1004 1004 1004\nGroups:\n'
    status+=''.join(f'{k}:\t0000000000000000\n'for k in ('CapEff','CapPrm','CapAmb','CapInh'))
    status+='VmPeak:\t128 kB\nVmSize:\t64 kB\nVmHWM:\t32 kB\nVmRSS:\t16 kB\nRssAnon:\t8 kB\nRssFile:\t8 kB\nRssShmem:\t0 kB\n'
    return dict(version=1,pid=pid,ppid=500,clock_ticks=100,page_bytes=4096,
                begin_mono_ns=begin,end_mono_ns=begin+10,stat=raw,identity_stat=raw,
                status=status,fds=[0,1,2,4],image=dict(device=1,inode=900))


def row():
    events=[]
    for kind,stamp in [('armed',100),('start',600),('quiescent',1000),('finish',1600)]:
        for index in (0,1):events.append(dict(kind=kind,application=index,monotonic_ns=stamp+index,before_monotonic_ns=stamp+index-1))
    return dict(benchmark_process_resource_contract_version=1,role_supervisor=dict(pid=500),events=events,
                applications=[dict(pid=p,process_resources=dict(before=snapshot(p),after=snapshot(p,1200,15,6)))for p in (123,124)])


class ProcessResources(unittest.TestCase):
    def test_literal_proc_fields_and_units(self):
        point=resources.parse(snapshot())
        self.assertEqual((point['pid'],point['ppid'],point['start_ticks']), (123,500,777))
        self.assertEqual((point['user_ticks'],point['system_ticks']),(10,4))
        self.assertEqual(point['memory_bytes']['VmRSS'],16384)
        self.assertEqual(point['memory_bytes']['VmHWM'],32768)
        self.assertEqual(point['fd_count'],4)
        self.assertEqual(point['clock_ticks'],100)

    def test_parser_rejects_partial_identity_units_authority_and_budgets(self):
        for kind in ['bool','missing','pid','ppid','status-uid','status-cap','status-group','unit','duplicate',
                     'negative','zombie','identity-reuse','duplicate-fd','boolean-fd','too-many-fds','oversize','time','hwm']:
            point=snapshot()
            if kind=='bool':point['version']=True
            elif kind=='missing':point.pop('status')
            elif kind=='pid':point['pid']=124
            elif kind=='ppid':point['ppid']=501
            elif kind=='status-uid':point['status']=point['status'].replace('1004','0')
            elif kind=='status-cap':point['status']=point['status'].replace('CapEff:\t0000000000000000','CapEff:\t0000000000000001')
            elif kind=='status-group':point['status']=point['status'].replace('Groups:\n','Groups:\t1002\n')
            elif kind=='unit':point['status']=point['status'].replace(' kB',' MB')
            elif kind=='duplicate':point['status']+='VmRSS:\t16 kB\n'
            elif kind=='negative':point['status']=point['status'].replace('16 kB','-1 kB')
            elif kind=='zombie':point['stat']=point['stat'].replace(') S ',') Z ')
            elif kind=='identity-reuse':point['identity_stat']=point['identity_stat'].replace('777','778')
            elif kind=='duplicate-fd':point['fds']=[0,0]
            elif kind=='boolean-fd':point['fds']=[False,1]
            elif kind=='too-many-fds':point['fds']=list(range(4097))
            elif kind=='oversize':point['stat']='x'*8193
            elif kind=='time':point['end_mono_ns']=point['begin_mono_ns']+5_000_000_001
            else:point['status']=point['status'].replace('32 kB','8 kB')
            with self.subTest(kind=kind),self.assertRaises(CaptureError):resources.parse(point)

    def test_pair_arithmetic_barriers_and_metadata_summary(self):
        original=row();samples=resources.observations(original)
        self.assertEqual([(s['user_ticks_delta'],s['system_ticks_delta'])for s in samples],[(5,2),(5,2)])
        proof=dict(benchmark_process_resource_contract_version=1,proofs=[dict(phase=p,resource_observations=copy.deepcopy(samples))for p in (0,1)])
        self.assertTrue(resources.valid_summary(proof))
        proof['proofs'][0]['resource_observations'][0]['user_ticks_delta']+=1
        self.assertFalse(resources.valid_summary(proof))
        for kind in ['missing','old','mixed','reuse','different-app','different-parent','clock','before-start','after-finish','counter-regression']:
            changed=row();pair=changed['applications'][0]['process_resources']
            if kind=='missing':pair.pop('after')
            elif kind=='old':changed.pop('benchmark_process_resource_contract_version')
            elif kind=='mixed':changed['applications'][1].pop('process_resources')
            elif kind=='reuse':pair['after']['stat']=pair['after']['identity_stat']=pair['after']['stat'].replace('777','778')
            elif kind=='different-app':changed['applications'][0]['pid']=999
            elif kind=='different-parent':changed['role_supervisor']['pid']=501
            elif kind=='clock':pair['after']['clock_ticks']=1000
            elif kind=='before-start':pair['before']['end_mono_ns']=601
            elif kind=='after-finish':pair['after']['end_mono_ns']=1600
            else:pair['after']=snapshot(123,1200,1,1)
            with self.subTest(kind=kind),self.assertRaises(CaptureError):resources.observations(changed)
        self.assertIsNone(resources.observations(dict(applications=[{},{}])))

    def test_live_collection_stops_before_proc_access_outside_vm(self):
        with patch('ws73_application_role.require_vm',side_effect=CaptureError('outside VM')):
            with self.assertRaises(CaptureError):resources.collect(123,'/must-not-open')


if __name__=='__main__':unittest.main()
