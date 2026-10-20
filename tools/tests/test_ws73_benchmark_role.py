# SPDX-License-Identifier: GPL-2.0-only
"""Actual metadata/file/profile functions;no Native/USB/privileged-success stub."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ws73_socket_benchmark as gate
import ws73_role_snapshot as snapshot
from ws73_benchmark import read_report
from ws73_capture import CaptureError
from ws73_application_role import read_json


def request():
    owners=[]
    for i in(0,1):
        generation=i+7;path=f'/org/sparklink/slk{i}_g{generation}'
        owners.append(dict(owner=dict(index=i,generation=generation,path=path),object=dict(generation=generation,lifetime=11,handle=0,path=path+'/peer_t00_000000000001/link_000000000000000b')))
    return dict(phase=0,owners=owners,config=gate.configuration('window'),application_tool=dict(path='/bin/slktest',sha256='a'*64),start_wall_ns=1,status='RUNNING',applications=[],events=[],performance_qualified=False,clock=gate.CLOCK,socket_benchmark_role_contract_version=1,tools={})


class BenchmarkRole(unittest.TestCase):
    def test_typed_dynamic_request_uses_real_request_validation_and_cli_without_native_stubs(self):
        for active in(0,1):
            args=SimpleNamespace(channel_benchmark='window',channel_benchmark_dynamic=True,channel_benchmark_active_endpoint=active)
            target=gate.requested_channel(args);r=request();r[gate.CHANNEL_FIELD]=target
            gate.validate_role_request(r,0)
            for i in(0,1):
                app=gate.application_request(r,i)
                argv=gate.arguments('/bin/slktest',r['owners'][i],'window','/new/report',channel=app)
                self.assertEqual(argv[-1],'active'if i==active else'passive')
                self.assertEqual(app['source_port'],target['ports'][i])
                self.assertEqual(app['destination_port'],target['ports'][1-i])
                self.assertEqual(app['mtu']+5,app['mps'])
            for change in [dict(version=True),dict(kind='reliable'),dict(ports=[0,1]),dict(ports=[True,2]),dict(aid=0),dict(active_endpoint=True),dict(active_endpoint=2),dict(unknown=1)]:
                bad=copy.deepcopy(r);bad[gate.CHANNEL_FIELD].update(change)
                with self.subTest(change=change),self.assertRaises(CaptureError):gate.validate_role_request(bad,0)
        for args in [SimpleNamespace(channel_benchmark_dynamic=True),SimpleNamespace(channel_benchmark='window',channel_benchmark_active_endpoint=1),SimpleNamespace(channel_benchmark='window',channel_benchmark_dynamic=1)]:
            with self.assertRaises(CaptureError):gate.requested_channel(args)

    def test_fixed_request_rejects_extra_programs_identity_and_legacy_role(self):
        gate.validate_role_request(request(),0)
        for kind in ('legacy','boolean-version','extra','work','controller','lifetime','clock','budget'):
            r=request()
            if kind=='legacy':r.pop('socket_benchmark_role_contract_version')
            elif kind=='boolean-version':r['socket_benchmark_role_contract_version']=True
            elif kind=='extra':r['program']='/bin/sh'
            elif kind=='work':r['applications']=[{}]
            elif kind=='controller':r['owners'][1]['owner']['path']='/org/sparklink/slk9_g8'
            elif kind=='lifetime':r['owners'][1]['object']['lifetime']=12
            elif kind=='clock':r['clock']='peerclock-minus-local'
            else:r['config']['window']=10000
            with self.subTest(kind=kind),self.assertRaises(CaptureError):gate.validate_role_request(r,0)
        with self.assertRaises(CaptureError):gate.validate_role_request(request(),True)
        with self.assertRaises(CaptureError):gate.validate_role_request(request(),0,live=True)
        live=request();live[gate.RESOURCE_FIELD]=1;gate.validate_role_request(live,0,live=True)

    def test_fresh_prepared_source_closure_rejects_marker_only_or_old_guest(self):
        from ws73_north_star import file_record
        here=Path(gate.__file__).parent
        names=('ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh')
        package=dict(socket_benchmark_role_contract_version=1,benchmark_trace_contract_version=1,benchmark_process_resource_contract_version=1,inputs=[file_record(here/n)for n in names])
        gate.validate_role_sources(package)
        with self.assertRaisesRegex(ValueError,'ws73_dynamic_channels.py'):gate.validate_role_sources(package,dynamic=True)
        dynamic=copy.deepcopy(package);dynamic['inputs'].append(file_record(here/'ws73_dynamic_channels.py'))
        gate.validate_role_sources(dynamic,dynamic=True)
        dynamic['inputs'][-1]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'ws73_dynamic_channels.py'):gate.validate_role_sources(dynamic,dynamic=True)
        for kind in ('marker','bool','trace-marker','trace-bool','resource-marker','resource-bool','missing','oldhash','duplicate'):
            bad=copy.deepcopy(package)
            if kind=='marker':bad.pop('socket_benchmark_role_contract_version')
            elif kind=='bool':bad['socket_benchmark_role_contract_version']=True
            elif kind=='trace-marker':bad.pop('benchmark_trace_contract_version')
            elif kind=='trace-bool':bad['benchmark_trace_contract_version']=True
            elif kind=='resource-marker':bad.pop(gate.RESOURCE_FIELD)
            elif kind=='resource-bool':bad[gate.RESOURCE_FIELD]=True
            elif kind=='missing':bad['inputs'].pop()
            elif kind=='duplicate':bad['inputs'].append(bad['inputs'][0])
            else:bad['inputs'][0]['sha256']='0'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):gate.validate_role_sources(bad)

    def test_live_workload_refuses_outside_explicit_vm_before_child_or_files(self):
        with patch('ws73_application_role.require_vm',side_effect=CaptureError('outside disposable VM')):
            with patch.object(gate.subprocess,'Popen',side_effect=AssertionError('must not launch')):
                with self.assertRaises(CaptureError):gate.execute_supervised(SimpleNamespace(),{})

    def test_actual_prepare_declaration_closes_role_sources_before_any_vm(self):
        # Inspect the real prepare input declaration, not a hand-built success
        # package: a guest copy alone must not hide an omitted source record.
        import ast
        from ws73_north_star import file_record
        here=Path(gate.__file__).resolve().parent;target=here/'ws73_target.py'
        tree=ast.parse(target.read_text())
        prepare=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='prepare_locked')
        declarations=[n.value for n in ast.walk(prepare)if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='inputs'for t in n.targets)]
        self.assertEqual(len(declarations),1)
        paths=[target]
        for entry in declarations[0].elts:
            if (isinstance(entry,ast.BinOp)and isinstance(entry.op,ast.Div)
                and isinstance(entry.left,ast.Name)and entry.left.id=='HERE'
                and isinstance(entry.right,ast.Constant)and isinstance(entry.right.value,str)):
                paths.append(here/entry.right.value)
        package=dict(socket_benchmark_role_contract_version=1,benchmark_trace_contract_version=1,benchmark_process_resource_contract_version=1,inputs=[file_record(p)for p in paths])
        gate.validate_role_sources(package)
        package['inputs']=[v for v in package['inputs']if Path(v['path']).name!='ws73_role_snapshot.py']
        with self.assertRaisesRegex(ValueError,'ws73_role_snapshot.py'):gate.validate_role_sources(package)

    def test_benchmark_snapshot_profile_is_separate_and_fail_closed(self):
        self.assertEqual(gate.ROLE_ROOT,Path(snapshot.profile('benchmark')['artifact']))
        self.assertEqual(snapshot.profile('subscription')['limit'],16*1024*1024)
        self.assertEqual(snapshot.profile('benchmark')['limit'],512*1024*1024)
        with self.assertRaises(CaptureError):snapshot.profile('other')
        with tempfile.TemporaryDirectory()as temporary:
            source=Path(temporary)/'source';source.mkdir();(source/'run.json').write_text('{}')
            target=Path(temporary)/'target';proof=snapshot.publish(source,target,phase=0,success=True,kind='benchmark')
            self.assertEqual(snapshot.verify(target,phase=0,runtime_root=source,kind='benchmark'),proof)
            with self.assertRaises(CaptureError):snapshot.verify(target,phase=0,runtime_root=source)
            (target/'run.json').write_text('{"tampered":true}')
            with self.assertRaises(CaptureError):snapshot.verify(target,phase=0,runtime_root=source,kind='benchmark')

    def test_absolute_native_alias_is_resolved_inside_sealed_guest_root(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'bin').mkdir();target=root/'usr/libexec/opensparklink/native-lab/0123456789ab/slktest';target.parent.mkdir(parents=True);target.write_bytes(b'fixture')
            alias=root/'bin/slktest';alias.symlink_to('/usr/libexec/opensparklink/native-lab/0123456789ab/slktest')
            self.assertEqual(gate.role_tool_path(root,'/bin/slktest'),target)
            alias.unlink();alias.symlink_to('/bin/sh')
            with self.assertRaises(CaptureError):gate.role_tool_path(root,'/bin/slktest')

    def test_actual_report_reader_rejects_symlink_hardlink_owner_and_duplicates(self):
        with tempfile.TemporaryDirectory()as temporary:
            p=Path(temporary)/'report.json';p.write_text('{"a":1}');p.chmod(0o600)
            self.assertEqual(read_report(p)[0],{'a':1})
            if os.getuid()==os.getgid():self.assertEqual(read_report(p,expected_uid=os.getuid())[1]['uid'],os.getuid())
            else:
                with self.assertRaises(CaptureError):read_report(p,expected_uid=os.getuid())
            with self.assertRaises(CaptureError):read_report(p,expected_uid=os.getuid()+1)
            link=p.with_name('link');link.symlink_to(p)
            with self.assertRaises(OSError):read_report(link)
            hard=p.with_name('hard');os.link(p,hard)
            with self.assertRaises(CaptureError):read_report(p)
            hard.unlink();p.write_text('{"a":1,"a":2}')
            with self.assertRaises(CaptureError):read_report(p)

    def test_live_child_creation_mask_overrides_permissive_init_mask(self):
        # Use the actual launch keyword with a local file-only child. Identity,
        # Native, socket, USB and VM lifecycle are deliberately not exercised.
        import ast,subprocess,sys
        tree=ast.parse(Path(gate.__file__).read_text())
        execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='execute_supervised')
        launches=[n for n in ast.walk(execute)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='subprocess'and n.func.attr=='Popen']
        self.assertEqual(len(launches),1)
        mask=ast.literal_eval(next(k.value for k in launches[0].keywords if k.arg=='umask'))
        self.assertEqual(mask,0o077)
        code="import os,subprocess,sys;os.umask(0);kw={}if sys.argv[2]=='inherit'else dict(umask=int(sys.argv[2]));subprocess.run([sys.executable,'-c',\"import sys;open(sys.argv[1],'x').write('{}')\",sys.argv[1]],check=True,**kw)"
        with tempfile.TemporaryDirectory()as temporary:
            for name,setting,expected in [('old','inherit',0o666),('fixed',str(mask),0o600)]:
                path=Path(temporary)/name
                subprocess.run([sys.executable,'-c',code,str(path),setting],check=True)
                self.assertEqual(path.stat().st_mode&0o777,expected)

    def test_terminal_shape_requires_actual_apps_reports_and_closed_phases(self):
        proof=dict(status='ACTUAL_ROOT_BENCHMARK_APPS_ONLY_PHASES_CHECKED',version=1,uid=1004,gid=1004,extra_groups=[],role_probes=2,application_processes=4,report_files=4,phases=2,performance_qualified=False,daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2,start_ticks=2),snapshot_files=18,snapshot_bytes=1024)
        self.assertTrue(gate.valid_role_supervision(proof))
        for update in [dict(uid=1000),dict(version=True),dict(report_files=3),dict(snapshot_files=0),dict(extra_groups=[1000]),dict(performance_qualified=True),dict(snapshot_bytes=2**31)]:
            with self.subTest(update=update):self.assertFalse(gate.valid_role_supervision(proof|update))



class ClosedBenchmarkRoleFixture(unittest.TestCase):
    def fixture(self,root,channel=None):
        # Synthetic schema2/wire/role metadata,not actual credentials or mount.
        from test_ws73_socket_benchmark import fixture as legacy_fixture
        from test_ws73_application_client import fixture as application_fixture
        from ws73_application_client import application_environment
        import hashlib,shutil
        run,capture=legacy_fixture(root,channel=channel);old_roles,_=application_fixture();daemon=dict(pid=11,start_ticks=31);supervisor=dict(pid=12,start_ticks=41)
        run.update(daemon_before=daemon,daemon_after=daemon)
        for row in run['socket_benchmark']:
            phase=row['phase'];source=root/f'local-{phase}';source.mkdir();(source/'reports').mkdir();row['start_wall_ns']=max(1,row['start_wall_ns'])
            for owner in row['owners']:
                o=owner['owner'];c=owner['object'];c['path']=o['path']+'/peer_t00_000000000001/link_'+f"{c['lifetime']:016x}"
            role=copy.deepcopy(old_roles['application_clients'][phase]['role_probe']);role['args'][1]=row['owners'][0]['object']['path'];role.update(start_wall_ns=1,end_wall_ns=2,output_files=[str(gate.ROLE_ROOT/f'phase-{phase}'/'probe.stdout'),str(gate.ROLE_ROOT/f'phase-{phase}'/'probe.stderr')])
            row.update(performance_qualified=False,socket_benchmark_role_contract_version=1,channel_role='sparklink-apps-only',application_role_contract_version=2,role_supervisor=supervisor,role_probe=role,tools={'/usr/share/sparklink/tools/ws73_role_snapshot.py':dict(sha256=snapshot.helper_hash(),bytes=1)},clock=gate.CLOCK)
            (source/'probe.stdout').write_text(role['stdout']);(source/'probe.stderr').write_text('')
            for i,app in enumerate(row['applications']):
                before=app['report_path'];runtime=str(gate.ROLE_RUNTIME/f'phase-{phase}'/'reports'/f'benchmark-{phase}-{i}.json');app['report_path']=runtime;app['report_file'].update(path=runtime,uid=1004,gid=1004,mode=0o644,nlink=1)
                app['args']=gate.arguments('/bin/slktest',row['owners'][i],app['mode'],runtime,channel=gate.application_request(row,i));app['stdout']=app['stdout'].replace(before,runtime);app['credentials']=copy.deepcopy(role['credentials']);app['environment']=application_environment();app['output_files']=[str(gate.ROLE_ROOT/f'phase-{phase}'/f'benchmark-{phase}-{i}.{v}')for v in('stdout','stderr')]
                (source/'reports'/f'benchmark-{phase}-{i}.json').write_text(json.dumps(app['report']));(source/f'benchmark-{phase}-{i}.stdout').write_text(app['stdout']);(source/f'benchmark-{phase}-{i}.stderr').write_text('')
            (source/'run.json').write_text(json.dumps(row))
            exported=root/'benchmark-role'/f'phase-{phase}';exported.parent.mkdir(exist_ok=True);snapshot.publish(source,exported,phase=phase,success=True,kind='benchmark')
            proof=json.loads((exported/'snapshot.json').read_text());proof['source_root']=str(gate.ROLE_RUNTIME/f'phase-{phase}');(exported/'snapshot.json').write_text(json.dumps(proof))
        (root/'benchmark-role/finished.json').write_text(json.dumps(dict(status=gate.ROLE_STATUS,daemon=daemon,supervisor=supervisor,snapshot_contract_version=1,socket_benchmark_role_contract_version=1)))
        return run,capture

    def test_dynamic_target_binds_closed_role_reports_actual_cmtc_tcids_and_business(self):
        for active in(0,1):
            with tempfile.TemporaryDirectory()as temporary:
                root=Path(temporary);channel=dict(version=1,kind='dynamic_basic',ports=[24576,24577],aid=29441,active_endpoint=active)
                run,capture=self.fixture(root,channel)
                proof=gate.corroborate(run,capture,root)
                self.assertEqual(proof[gate.CHANNEL_FIELD],channel)
                self.assertEqual(proof['round_trips'],40)
                self.assertTrue(all(set(p['dynamic_negotiation'])=={'request','response'}for p in proof['proofs']))
                self.assertIs(proof['performance_qualified'],False)

    def test_dynamic_closed_evidence_refuses_downgrade_missing_signal_wrong_route_and_early_ready(self):
        cases=['missing-target','wrong-role','same-endpoint-ports','missing-stage','active-too-early','changed-report-request','missing-CMTC','changed-CMTC-AID','duplicate-CMTC','early-Ready','wrong-data-TCID','missing-peer-data']
        for kind in cases:
            with tempfile.TemporaryDirectory()as temporary:
                root=Path(temporary);channel=dict(version=1,kind='dynamic_basic',ports=[24576,24577],aid=29441,active_endpoint=0)
                run,capture=self.fixture(root,channel);row=run['socket_benchmark'][0]
                if kind=='missing-target':row.pop(gate.CHANNEL_FIELD)
                elif kind=='wrong-role':row[gate.CHANNEL_FIELD]['active_endpoint']=1
                elif kind=='same-endpoint-ports':row[gate.CHANNEL_FIELD]['ports'][1]=24576
                elif kind=='missing-stage':row['events']=[e for e in row['events']if not(e['kind']=='staged'and e['application']==1)]
                elif kind=='active-too-early':row['applications'][0]['start_wall_ns']=5
                elif kind=='changed-report-request':row['applications'][0]['report']['channel_request']['aid']+=1
                else:
                    candidates=[p for p in capture['acb_packets']if bytes.fromhex(p['data'])[:2]==b'\x02\0']
                    if kind=='missing-CMTC':capture['acb_packets'].remove(candidates[0])
                    elif kind=='changed-CMTC-AID':candidates[0]['data']=candidates[0]['data'][:-2]+'ff'
                    elif kind=='duplicate-CMTC':capture['acb_packets'].append(dict(candidates[0],record=99999))
                    elif kind=='early-Ready':candidates[3]['wall_ns']=115
                    elif kind=='wrong-data-TCID':
                        data=next(p for p in capture['acb_packets']if bytes.fromhex(p['data'])[:2]!=b'\x02\0');data['data']='1f'+data['data'][2:]
                    elif kind=='missing-peer-data':
                        data=next(p for p in capture['acb_packets']if p['direction']=='in'and bytes.fromhex(p['data'])[:2]!=b'\x02\0');capture['acb_packets'].remove(data)
                # Keep the original exported bytes untouched: changing metadata
                # cannot create a new qualified closed snapshot.
                with self.subTest(kind=kind),self.assertRaises((CaptureError,KeyError,FileNotFoundError)):
                    gate.corroborate(run,capture,root)

    def test_actual_checker_accepts_closed_fixture_and_rejects_role_file_scope_corruptions(self):
        for kind in(None,'credentials','report-owner','missing-snapshot','truncated-stream','old-root-request','wrong-source-root','wrong-daemon','missing-finish'):
            with tempfile.TemporaryDirectory()as temporary:
                root=Path(temporary);run,capture=self.fixture(root);row=run['socket_benchmark'][0];app=row['applications'][0]
                if kind=='credentials':app['credentials']['groups']=[1000]
                elif kind=='report-owner':app['report_file']['uid']=1000
                elif kind=='missing-snapshot':(root/'benchmark-role/phase-0/snapshot.json').unlink()
                elif kind=='truncated-stream':(root/'benchmark-role/phase-0/benchmark-0-0.stdout').write_text('')
                elif kind=='old-root-request':row.pop('socket_benchmark_role_contract_version')
                elif kind=='wrong-source-root':
                    p=root/'benchmark-role/phase-0/snapshot.json';v=json.loads(p.read_text());v['source_root']='/run/ws73-subscription-role/phase-0';p.write_text(json.dumps(v))
                elif kind=='wrong-daemon':run['daemon_after']['start_ticks']+=1
                elif kind=='missing-finish':(root/'benchmark-role/finished.json').unlink()
                if kind is None:
                    proof=gate.verify_role_artifacts(run,root);self.assertTrue(gate.valid_role_supervision(proof));self.assertEqual(gate.corroborate(run,capture,root)['round_trips'],40)
                else:
                    with self.subTest(kind=kind),self.assertRaises((CaptureError,KeyError,FileNotFoundError)):gate.corroborate(run,capture,root)

if __name__=='__main__':unittest.main()
