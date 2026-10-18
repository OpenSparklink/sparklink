# SPDX-License-Identifier: GPL-2.0-only
"""Explicit output/capture fixtures; no VM, USB, firmware or discovery RF run.

The real command_reply, Native result, marker and discovery checkers consume
format fixtures. These are test-oracle checks, not SDK/kernel concurrency tests.
"""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from ws73_application_discovery import (corroborate, reader_args, receipt, requested,
    supervise, validate_request, valid_summary, verify_supervisor_artifacts)
from ws73_capture import CaptureError, marker_data
from ws73_target import run_exit_code


def fixture():
    owners=[dict(index=i,generation=i+11,path=f'/org/sparklink/slk{i}_g{i+11}',
                 bus=1,device=i+3,address=f'00:01:02:03:04:0{i}') for i in (0,1)]
    tool=dict(path='/bin/slctl',sha256='a'*64)
    run=dict(initial=owners,slctl=tool,daemon_before=dict(pid=42,start_ticks=7),commands=[],application_discovery=[])
    capture=dict(commands=[],complete=[],reports=[],failures=[])
    def wire(owner,opcode,params,t):
        record=len(capture['commands'])*2+1
        capture['commands'].append(dict(bus=1,device=owner['device'],opcode=opcode,params=params.hex(),wall_ns=t,
                                       record=record,completion=dict(wall_ns=t+1)))
        capture['complete'].append(dict(bus=1,device=owner['device'],opcode=opcode,status=0,value='',wall_ns=t+2,record=record+1))
    for phase,(scanner,advertiser) in enumerate([owners,list(reversed(owners))]):
        offset=phase*1000
        markers=[f'{phase+1:02x}'*8+'22'*8,f'{phase+1:02x}'*8+'33'*8]
        source=dict(phase=phase,scanner=scanner,advertiser=advertiser,markers=markers,tool=tool,status='REQUESTED')
        row=copy.deepcopy(source);row['status']='EXPLICIT_RELEASE_OUTPUTS_CHECKED'
        row['verifier']=dict(path='/usr/share/sparklink/tools/ws73_application_discovery.py',sha256='b'*64)
        row['ready']=dict(phase=phase,scanner=scanner['path'],active_wall_ns=offset+50,sessions=['1','2'])
        row['first_released']=dict(phase=phase,first_end_wall_ns=offset+100,survivor_alive=True,observed_wall_ns=offset+110)
        row['readers']=[]
        for n in (0,1):
            lines=[f"DiscoverySession: id={n+1} path={scanner['path']} state=active source=broker"]
            for j in range(1 if n==0 else 8):
                marker=markers[0] if j<4 or n==0 else markers[1]
                lines.append(f"DiscoveryReport: session={n+1} generation={scanner['generation']} sequence={j+1} address_type=0 address={advertiser['address'].replace(':','')} rssi=-40 data={marker_data(marker).hex()}")
            lines.append(f"DiscoveryReleased: session={n+1} last_physical_stop_confirmed={'false' if n==0 else 'true'}")
            row['readers'].append(dict(args=reader_args(source,n),exit=0,stderr='',stdout='\n'.join(lines)+'\n',native_fds=[],
                credentials=dict(uids=[1004]*4,gids=[1004]*4,groups=[],capabilities={k:'0' for k in ['CapEff','CapPrm','CapAmb','CapInh']}),
                start_wall_ns=offset+10+n,end_wall_ns=offset+(100 if n==0 else 190)))
        item=dict(request=source,supervision=row,status='APPLICATION_DISCOVERY_EVIDENCE_PENDING',barrier=row['ready'],first_released=row['first_released'],advertisements=[])
        for i,marker in enumerate(markers):
            t=offset+(60 if i==0 else 130);request=phase*10+i+1
            out=f"NativeOperationResult: generation={advertiser['generation']} request={request} operation=1 state=3 errno=0 status=0x00 opcode=0x0c05 step=2/3 power=0 power_valid=1 adv=2 scan=1 profile=1\n"
            out+=f'NativeAdvertisementAccepted: request={request} marker={marker} data={marker_data(marker).hex()}\n'
            item['advertisements'].append(len(run['commands']))
            run['commands'].append(dict(args=['/bin/slctl','--adapter',advertiser['path'],'advertise','on',marker],exit=0,stdout=out,start_wall_ns=t,end_wall_ns=t+20))
            wire(advertiser,0x0c03,bytes([0,3,len(marker_data(marker))])+marker_data(marker),t+2)
        wire(scanner,0x1001,b'\0\0\1\0\x40\x06\x20\x03',offset+20)
        wire(scanner,0x1002,b'\1\0',offset+30)
        wire(scanner,0x1002,b'\0\0',offset+175)
        # Fanout can legitimately expose the same physical report to both
        # clients; the survivor's second marker has a separate raw RX record.
        for j in range(8):
            marker=markers[0 if j<4 else 1];t=offset+(90+j*2 if j<4 else 160+(j-4)*2)
            capture['reports'].append(dict(bus=1,device=scanner['device'],wall_ns=t,address=advertiser['address'],data=marker_data(marker).hex(),rssi=-40,record=500+phase*10+j,hcc_offset=0))
        run['application_discovery'].append(item)
    capture['commands'].sort(key=lambda c:c['wall_ns'])
    return run,capture


class DiscoveryGate(unittest.TestCase):
    def test_fixed_request_boundary_and_marker_prefix(self):
        run,_=fixture();row=run['application_discovery'][0]['request'];validate_request(row,0)
        self.assertEqual(bytes.fromhex(reader_args(row,1)[4]),marker_data(row['markers'][0])[:-16])
        for kind in ['extra','phase','same','prefix','path','tool','generation','index']:
            bad=copy.deepcopy(row)
            if kind=='extra':bad['args']=['/bin/sh']
            elif kind=='phase':bad['phase']=False
            elif kind=='same':bad['markers'][1]=bad['markers'][0]
            elif kind=='prefix':bad['markers'][1]='44'*16
            elif kind=='path':bad['scanner']['path']='/bin/sh'
            elif kind=='tool':bad['tool']['path']='/bin/sh'
            elif kind=='generation':bad['scanner']['generation']=0
            elif kind=='index':bad['advertiser']=copy.deepcopy(bad['scanner'])
            with self.subTest(kind=kind),self.assertRaises(CaptureError):validate_request(bad,0)

    def test_actual_format_receipts_and_capture_positive(self):
        run,capture=fixture();proof=corroborate(run,capture)
        self.assertTrue(valid_summary(proof));self.assertEqual(len(proof['phases'][0]['reports']),9)

    def test_output_needs_real_role_identity_new_payload_and_last_stop(self):
        run,_=fixture();row=run['application_discovery'][0]['supervision']
        for kind in ['uid','group','caps','native','exit','stderr','firststop','laststop','marker','sequence','generation','rssi','truncate','args']:
            bad=copy.deepcopy(row);a=bad['readers'][0];b=bad['readers'][1]
            if kind=='uid':a['credentials']['uids']=[0]*4
            elif kind=='group':a['credentials']['groups']=[1000]
            elif kind=='caps':a['credentials']['capabilities']['CapInh']='1'
            elif kind=='native':a['native_fds']=['/dev/sparklink']
            elif kind=='exit':a['exit']=1
            elif kind=='stderr':a['stderr']='error'
            elif kind=='firststop':a['stdout']=a['stdout'].replace('confirmed=false','confirmed=true')
            elif kind=='laststop':b['stdout']=b['stdout'].replace('confirmed=true','confirmed=false')
            elif kind=='marker':b['stdout']=b['stdout'].replace(marker_data(bad['markers'][1]).hex(),marker_data(bad['markers'][0]).hex())
            elif kind=='sequence':b['stdout']=b['stdout'].replace('sequence=2 ','sequence=1 ')
            elif kind=='generation':a['stdout']=a['stdout'].replace('generation=11 ','generation=12 ')
            elif kind=='rssi':a['stdout']=a['stdout'].replace('rssi=-40','rssi=unknown')
            elif kind=='truncate':a['stdout']=a['stdout'].splitlines()[0]
            elif kind=='args':a['args'][-1]='-20'
            with self.subTest(kind=kind),self.assertRaises(CaptureError):
                receipt(bad,0);receipt(bad,1)

    def test_missing_wire_duplicate_start_early_stop_and_timeline_rejected(self):
        for kind in ['rx','one_rx','sender','reply','duplicate','earlystop','radioframe','corrupt','roles','timeout','barrier','session','marker_reuse','target_failure']:
            run,capture=fixture();row=run['application_discovery'][0];proof=row['supervision']
            if kind=='rx':capture['reports']=[]
            elif kind=='one_rx':capture['reports']=[capture['reports'][0],capture['reports'][4]]
            elif kind=='sender':capture['commands']=[c for c in capture['commands'] if c['opcode']!=0x0c03]
            elif kind=='reply':capture['complete']=[]
            elif kind=='duplicate':capture['commands'].append(copy.deepcopy(capture['commands'][1]))
            elif kind=='earlystop':
                for c in capture['commands']:
                    if c['opcode']==0x1002 and c['params']=='0000':c['wall_ns']=105;c['completion']['wall_ns']=106
            elif kind=='radioframe':
                next(c for c in capture['commands'] if c['opcode']==0x1001)['params']='0000000000000000'
            elif kind=='corrupt':capture['reports'][0]['data']='00'
            elif kind=='roles':run['initial']=list(reversed(run['initial']))
            elif kind=='timeout':proof['readers'][0]['end_wall_ns']+=10_000_000_000
            elif kind=='barrier':proof['first_released']['observed_wall_ns']=200
            elif kind=='session':proof['ready']['sessions']=['9','10']
            elif kind=='marker_reuse':run['application_discovery'][1]['request']['markers']=copy.deepcopy(row['request']['markers'])
            elif kind=='target_failure':capture['failures'].append(dict(bus=1,device=3,wall_ns=90))
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):corroborate(run,capture)

    def test_original_supervisor_files_not_copied_summary_alone(self):
        run,_=fixture();expected=run['application_discovery'][0]['supervision']['verifier']
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp);requests=root/'application/passthrough-control';requests.mkdir(parents=True)
            for phase,item in enumerate(run['application_discovery']):
                folder=root/'discovery-role'/f'phase-{phase}';folder.mkdir(parents=True)
                request=requests/f'discovery-role-{phase}.request.json';request.write_text(json.dumps(item['request']))
                row=item['supervision'];row['request_sha256']=hashlib.sha256(request.read_bytes()).hexdigest()
                (folder/'run.json').write_text(json.dumps(row))
                (folder/'ready.json').write_text(json.dumps(item['barrier']))
                (folder/'first-released.json').write_text(json.dumps(item['first_released']))
                for n,app in enumerate(row['readers']):
                    for suffix in ['stdout','stderr']:(folder/f'{n}.{suffix}').write_text(app[suffix])
            (root/'discovery-role/finished.json').write_text(json.dumps(dict(status='TWO_EXPLICIT_RELEASE_PHASES_COMPLETED',daemon=run['daemon_before'])))
            verify_supervisor_artifacts(run,root,expected)
            target=root/'discovery-role/phase-0/0.stdout';text=target.read_text();target.write_text(text+'fake\n')
            with self.assertRaises(CaptureError):verify_supervisor_artifacts(run,root,expected)
            target.write_text(text);requests.joinpath('discovery-role-0.request.json').unlink()
            with self.assertRaises(FileNotFoundError):verify_supervisor_artifacts(run,root,expected)

    def test_fail_closed_exit_and_finite_mode_boundary(self):
        opts=SimpleNamespace(application_discovery_verify=True,qmp_hotplug=True,connection_verify=True,ports=['1-1.1.1','1-1.1.2'])
        self.assertTrue(requested(opts))
        for changes in [dict(ports=['1-1.1.1']),dict(connection_verify=False),dict(fault_recovery=True),dict(application_client_verify=True),dict(channel_benchmark='rate')]:
            with self.subTest(changes=changes),self.assertRaises(CaptureError):requested(SimpleNamespace(**(vars(opts)|changes)))
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,application_discovery_requested=True,qemu_args=['qemu','-append','ws73.application_discovery=1'])
        self.assertEqual(run_exit_code(record),1)
        run,capture=fixture();proof=corroborate(run,capture)
        record.update(application_discovery_acceptance=True,application_discovery_corroboration=proof,
                      application_discovery_supervision=dict(status='ORIGINAL_DISCOVERY_ROLE_FILES_CHECKED',uid=1004,phases=2))
        self.assertEqual(run_exit_code(record),0)
        for changes in [dict(supervisor_exit=1),dict(application_discovery_acceptance=False),dict(application_discovery_requested=False),dict(application_discovery_corroboration={}),dict(qemu_args=[]),dict(qemu_args=['ws73.application_discovery=1 ws73.application_discovery=1'])]:
            self.assertEqual(run_exit_code(record|changes),1)

    def test_refuses_non_vm_launcher(self):
        with patch('ws73_application_role.os.geteuid',return_value=1000),self.assertRaises(CaptureError):supervise(42)


if __name__=='__main__':unittest.main()
