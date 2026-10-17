"""Finite report/USB-record fixtures and rejection controls, not RF acceptance."""
import copy
import unittest
from ws73_connection_objects import corroborate_peer_observations


def fixture():
    owners=[dict(path=f'/org/sparklink/slk{i}_g{i+1}',generation=i+1,bus=1,device=i+2,address=f'01:02:03:04:05:0{i+1}') for i in range(2)]
    r=dict(application_identity=dict(uids=[1000]*4,cap_eff='0',cap_prm='0',cap_amb='0'),commands=[],connection_control=dict(phases=[]))
    capture=dict(native_events=[])
    for n in range(2):
        phase=dict(caller=owners[n],peer=owners[1-n],typed_objects=[],disconnect_command=len(r['commands']))
        r['commands'].append(dict(start_wall_ns=100+n*100))
        for owner,remote in [(owners[0],owners[1]),(owners[1],owners[0])]:
            path=f"{owner['path']}/peer_t00_{remote['address'].replace(':','').lower()}"
            header=bytearray(23);header[2:8]=bytes.fromhex(remote['address'].replace(':',''));header[21]=216;header[22]=2
            data=bytes([n,owner['device']]);params=(header+data).hex()
            v=dict(path=path+'/link_0000000000000001',generation=owner['generation'],address_type=0,address=remote['address'])
            entry=dict(owner=owner,object=v,observation_command=len(r['commands']))
            r['commands'].append(dict(args=['slctl','--adapter',owner['path'],'peer-observation',path],exit=0,start_wall_ns=10+n*100,end_wall_ns=20+n*100,start_boottime_ns=10,end_boottime_ns=20,
              stdout=f"PeerObservation: path={path} generation={owner['generation']} address_type=0 valid=true rssi=-40 sequence=1 kernel_boottime_ns=5 lost=0 header={header.hex()} data={data.hex()}\n"))
            entry['peer_list_command']=len(r['commands'])
            r['commands'].append(dict(args=['slctl','--adapter',owner['path'],'peers'],exit=0,stdout=f"Peer: path={path} address={remote['address']} address_type=0 observation_valid=true rssi=-40 connection=connected\n"))
            phase['typed_objects'].append(entry)
            capture['native_events'].append(dict(event=0x180b,bus=owner['bus'],device=owner['device'],params=params,wall_ns=5+n*100))
        r['connection_control']['phases'].append(phase)
    return r,capture


class PeerObservations(unittest.TestCase):
    def test_actual_checker_accepts_only_the_finite_complete_contract(self):
        run,cap=fixture()
        self.assertEqual(len(corroborate_peer_observations(run,cap)),4)

    def test_identity_missing_cases_capture_payload_clock_and_privilege_fail_closed(self):
        run,cap=fixture()
        for kind in ['case','capture','owner','generation','payload','clock','list','exit','root','missing-command']:
            r=copy.deepcopy(run);c=copy.deepcopy(cap);entry=r['connection_control']['phases'][0]['typed_objects'][0]
            row=r['commands'][entry['observation_command']]
            if kind=='case':r['connection_control']['phases'][0]['typed_objects'].pop()
            elif kind=='capture':c['native_events'].pop(0)
            elif kind=='owner':r['connection_control']['phases'][0]['typed_objects'][1]=entry
            elif kind=='generation':entry['object']['generation']+=1
            elif kind=='payload':row['stdout']=row['stdout'].replace('data=0002','data=ffff')
            elif kind=='clock':row['end_boottime_ns']=0
            elif kind=='list':r['commands'][entry['peer_list_command']]['stdout']=''
            elif kind=='exit':row['exit']=1
            elif kind=='root':r['application_identity']['uids']=[0]*4
            else:del entry['observation_command']
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):
                corroborate_peer_observations(r,c)
