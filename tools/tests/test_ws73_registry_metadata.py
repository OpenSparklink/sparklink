"""Metadata verdict fixtures; actual C/CLI and kernel behavior need VM evidence."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import unittest
from ws73_registry_metadata import corroborate,STATUS
from ws73_north_star import file_record
from ws73_capture import CaptureError


def fixture():
    owners=[{'index':0,'generation':7},{'index':1,'generation':8}]
    r={'version':1,'status':STATUS,'start_wall_ns':10,'end_wall_ns':30,
       'owners':owners,'cases':[], 'probe':file_record(Path(__file__)),
       'cli':file_record(Path(__file__).with_name('test_retired_interfaces.py'))}
    run={'registry_metadata':r,'connection_control':{'owners':copy.deepcopy(owners),'status':'CONNECTION_CONTROL_EVIDENCE_PENDING','end_wall_ns':9},'registry_metadata_commands':[],'artifacts':{'registry_probe':copy.deepcopy(r['probe']),'registry_cli':copy.deepcopy(r['cli'])}}
    for o in owners:
        i,g=o['index'],o['generation'];offset=i*4
        c={'args':[r['probe']['path'],'metadata',str(i),str(g)],'exit':0,'start_wall_ns':11+offset,'end_wall_ns':12+offset,
           'stdout':f'CoreRegistryMetadata: index={i} generation={g} mask=3 count=2 flags=1\nWS73_NATIVE_C_BINDINGS: PASS mode=metadata uid=1000 index={i} generation={g}\n'}
        cli={'args':[r['cli']['path'],'--adapter',str(i),'--generation',str(g),'connections'],'exit':0,'start_wall_ns':13+offset,'end_wall_ns':14+offset,
             'stdout':f'NativeLinks: index={i} generation={g} revision=4 sequence=8 count=0\n'}
        r['cases'].append({'owner':o,'c':c,'cli':cli});run['registry_metadata_commands'] += [c,cli]
    return run


class RegistryMetadataVerdict(unittest.TestCase):
    def test_declared_fixture_only(self):
        self.assertEqual(corroborate(fixture())['allocated'],2)

    def test_missing_changed_duplicate_failed_and_old_identity_rejected(self):
        for kind in ['case','parent-owner','parent-not-done','order','count','bitmap','generation','uid','flags','failed','cli-generation','cli-links','cli-revision','interval','hash','old-valid-hash','duplicate','command']:
            run=fixture();r=run['registry_metadata'];c=r['cases'][0]['c'];cli=r['cases'][0]['cli']
            if kind=='case':r['cases'].pop()
            elif kind=='parent-owner':run['connection_control']['owners'][0]['generation']+=1
            elif kind=='parent-not-done':run['connection_control']['status']='RUNNING'
            elif kind=='order':r['cases'][1]['c']['start_wall_ns']=11
            elif kind=='count':c['stdout']=c['stdout'].replace('count=2','count=0')
            elif kind=='bitmap':c['stdout']=c['stdout'].replace('mask=3','mask=1')
            elif kind=='generation':c['stdout']=c['stdout'].replace('generation=7','generation=9')
            elif kind=='uid':c['stdout']=c['stdout'].replace('uid=1000','uid=0')
            elif kind=='flags':c['stdout']=c['stdout'].replace('flags=1','flags=0')
            elif kind=='failed':c['exit']=1
            elif kind=='cli-generation':cli['stdout']=cli['stdout'].replace('generation=7','generation=9')
            elif kind=='cli-links':cli['stdout']=cli['stdout'].replace('count=0','count=1')
            elif kind=='cli-revision':cli['stdout']=cli['stdout'].replace('revision=4','revision=0')
            elif kind=='interval':r['start_wall_ns']=8
            elif kind=='hash':r['probe']['sha256']='not-hash'
            elif kind=='old-valid-hash':r['probe']['sha256']='f'*64
            elif kind=='duplicate':r['cases'][1]=copy.deepcopy(r['cases'][0])
            else:run['registry_metadata_commands'].pop()
            with self.subTest(kind=kind),self.assertRaises((CaptureError,KeyError,ValueError)):corroborate(run)
