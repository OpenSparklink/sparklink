# SPDX-License-Identifier: GPL-2.0-only
"""Offline rejection fixtures only, never physical object/RF acceptance."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_connection_objects import objects,info,peer_info,receipt,corroborate
from ws73_capture import CaptureError
from test_ws73_connection_control import fixture as base_fixture
from ws73_connection_control import corroborate as wire_proof


def value(owner,remote,lifetime):
    path=f"{owner['path']}/peer_t00_{remote['address'].replace(':','').lower()}/link_{lifetime:016x}"
    return dict(generation=owner['generation'],lifetime=lifetime,handle=0,role=0,address_type=0,address=remote['address'],path=path)


def enumeration(v):
    return f"NativeConnectionObjects: generation={v['generation']} event_seq=3 revision={v['lifetime']} known=true\nNativeConnectionObject: generation={v['generation']} lifetime={v['lifetime']} handle=0 role=0 type=0 address={v['address']} path={v['path']}\n"


def fixture():
    run,capture=base_fixture();proof=wire_proof(run,capture)
    run['connection_control']['connection_objects']='generation-type-lifetime-v1';prior=[]
    for n,phase in enumerate(run['connection_control']['phases']):
        phase['typed_objects']=[];phase['stale_object_rejections']=[]
        for owner in [phase['caller'],phase['peer']]:owner['path']=f"/org/sparklink/slk0_g{owner['generation']}"
        for owner,remote in [(phase['caller'],phase['peer']),(phase['peer'],phase['caller'])]:
            v=value(owner,remote,1+n*2);entry=dict(owner=owner,remote=remote,object=v)
            text=[enumeration(v),f"NativeConnectionInfo: generation={v['generation']} lifetime={v['lifetime']} handle=0 role=0 type=0 address={v['address']} known=true connected=true path={v['path']}\n",
                f"NativePeerInfo: generation={v['generation']} type=0 address={v['address']} known=true connected=true path={v['path'].rsplit('/link_',1)[0]}\nNativePeerConnection: path={v['path']}\n"]
            for k,args in enumerate([['connection-objects'],['connection-info',v['path']],['peer-info',v['path'].rsplit('/link_',1)[0]]]):
                index=len(run['commands']);run['commands'].append(dict(args=['slctl','--adapter',owner['path'],*args],stdout=text[k],exit=0,start_wall_ns=n*100+16+k,end_wall_ns=n*100+17+k))
                if k==0:entry['enumeration_commands']=[index]
                else:entry[['','info_command','peer_command'][k]]=index
            phase['typed_objects'].append(entry)
        v=phase['typed_objects'][0]['object'];row=run['commands'][phase['disconnect_command']]
        row['args']=['slctl','disconnect-object',v['path']]
        row['stdout']=f"NativeDisconnectObject: request=2 generation={v['generation']} lifetime={v['lifetime']} handle=0 role=0 type=0 address={v['address']} path={v['path']}\n"+row['stdout']
        for scope,entries in [('while-reused-handle-live',prior),('after-down',phase['typed_objects'])]:
            for entry in entries:
                start=n*100+(16 if scope.startswith('while') else 30);indices=[]
                for action in ['connection-info','disconnect-object']:
                    indices.append(len(run['commands']));run['commands'].append(dict(args=['slctl','--adapter',entry['owner']['path'],action,entry['object']['path']],stdout='',stderr='org.freedesktop.DBus.Error.UnknownObject',exit=1,start_wall_ns=start,end_wall_ns=start+1))
                phase['stale_object_rejections'].append(dict(owner=entry['owner'],object=entry['object'],scope=scope,info_commands=indices[:1],disconnect_command=indices[1]))
        prior=phase['typed_objects']
    return run,capture,proof


class TypedObjectEvidence(unittest.TestCase):
    def test_real_cli_selected_preamble_is_bound_to_the_same_adapter(self):
        run,_,_=fixture();entry=run['connection_control']['phases'][0]['typed_objects'][0];v=entry['object'];owner=entry['owner']
        for field,check in [('info_command',info),('peer_command',peer_info)]:
            text=run['commands'][entry[field]]['stdout'];check(f"Selected {owner['path']}\n"+text,v)
            for bad in [f"Selected /org/sparklink/slk9_g9\n"+text,f"Selected {owner['path']}\n"*2+text]:
                with self.assertRaises(CaptureError):check(bad,v)

    def test_complete_original_matrix_and_both_owners_required(self):
        run,capture,proof=fixture();self.assertEqual(len(corroborate(run,capture,proof)),2)
        for field in ['typed_objects','stale_object_rejections']:
            bad=copy.deepcopy(run);bad['connection_control']['phases'][1][field].pop()
            with self.subTest(field=field),self.assertRaises(CaptureError):corroborate(bad,capture,proof)
        bad=copy.deepcopy(run);bad['connection_control']['phases'][0]['typed_objects'][1]=bad['connection_control']['phases'][0]['typed_objects'][0]
        with self.assertRaises(CaptureError):corroborate(bad,capture,proof)

    def test_false_unknown_changed_type_lifetime_and_generation_fail(self):
        owner=dict(generation=7,path='/org/sparklink/slk0_g7');remote=dict(address='00:01:09:32:54:F9');v=value(owner,remote,1);text=enumeration(v)
        self.assertEqual(objects(text,owner)[1],[v])
        for old,new in [('known=true','known=false'),('generation=7','generation=8'),('lifetime=1','lifetime=2'),('type=0','type=1')]:
            with self.subTest(new=new),self.assertRaises(CaptureError):objects(text.replace(old,new),owner)
        with self.assertRaises(CaptureError):objects(text+text.splitlines()[1]+'\n',owner)

    def test_false_refusal_or_wire_command_cannot_pass(self):
        run,capture,proof=fixture();entry=run['connection_control']['phases'][1]['stale_object_rejections'][0]
        bad=copy.deepcopy(run);bad['commands'][entry['disconnect_command']]['exit']=0
        with self.assertRaises(CaptureError):corroborate(bad,capture,proof)
        bad=copy.deepcopy(capture);bad['commands'].append(dict(wall_ns=116))
        with self.assertRaises(CaptureError):corroborate(run,bad,proof)
        bad=copy.deepcopy(run);bad['connection_control']['phases'][1]['stale_object_rejections'][1]=bad['connection_control']['phases'][1]['stale_object_rejections'][0]
        with self.assertRaises(CaptureError):corroborate(bad,capture,proof)

if __name__=='__main__':unittest.main()
