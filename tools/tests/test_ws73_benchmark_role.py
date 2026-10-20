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
    def test_root_tool_admission_and_actual_request_profile_include_dynamic_dependency(self):
        import ast
        import ws73_application_role as role
        # Inspect the exact Root admission call, then evaluate the actual file
        # hasher/profile with explicit files. No Native/USB/Ready stub.
        tree=ast.parse(Path(role.__file__).read_text());function=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='_supervise')
        assignments=[n for n in ast.walk(function)if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='expected_tools'for t in n.targets)]
        self.assertTrue(any(isinstance(n.value,ast.Call)and isinstance(n.value.func,ast.Name)and n.value.func.id=='request_tools'and len(n.value.args)==1 and isinstance(n.value.args[0],ast.Name)and n.value.args[0].id=='row'for n in assignments))
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);target=root/'usr/libexec/opensparklink/native-lab/0123456789ab/slktest';target.parent.mkdir(parents=True);target.write_bytes(b'explicit file fixture')
            (root/'bin').mkdir();(root/'bin/slktest').symlink_to('/usr/libexec/opensparklink/native-lab/0123456789ab/slktest')
            from ws73_role_snapshot import HELPER,SUPERVISOR
            paths=['/bin/bus-policy-probe',HELPER,SUPERVISOR,*['/usr/share/sparklink/tools/'+n for n in ['ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_benchmark_resources.py','ws73_dynamic_channels.py','ws73_channel_fairness.py']]]
            for name in paths:
                p=root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'explicit file fixture')
            basic=gate.request_tools({},root)
            dynamic=gate.request_tools({gate.CHANNEL_FIELD:dict(version=1,kind='dynamic_basic',ports=[24576,24577],aid=29441,active_endpoint=0)},root)
            key='/usr/share/sparklink/tools/ws73_dynamic_channels.py'
            self.assertEqual(set(dynamic)-set(basic),{key})
            self.assertEqual({k:v for k,v in dynamic.items()if k!=key},basic)
            parallel=gate.request_tools({gate.CHANNEL_FIELD:gate.parallel_channel()},root)
            self.assertEqual(set(parallel)-set(dynamic),{'/usr/share/sparklink/tools/ws73_channel_fairness.py'})
            (root/key.lstrip('/')).write_bytes(b'changed source fixture')
            self.assertNotEqual(gate.request_tools({gate.CHANNEL_FIELD:dict(version=1,kind='dynamic_basic',ports=[24576,24577],aid=29441,active_endpoint=0)},root),dynamic)

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

    def test_parallel_profile_closes_root_hashes_boot_and_each_actual_application_request(self):
        for active in(0,1):
            args=SimpleNamespace(channel_benchmark='window',channel_benchmark_parallel=True,channel_benchmark_active_endpoint=active)
            channel=gate.requested_channel(args);r=request();r[gate.CHANNEL_FIELD]=channel
            gate.validate_role_request(r,0)
            self.assertEqual(gate.channel_from_boot(['console=ttyS0',*gate.channel_boot(channel)],r['config']),channel)
            self.assertEqual(gate.application_count(r),4)
            self.assertEqual(gate.release_order(r),[2,3,0,1])
            self.assertEqual([gate.application_config(r,i)['bytes']for i in range(4)],[61,61,2042,2042])
            self.assertEqual([gate.application_request(r,i)['passive']for i in range(4)], [i%2!=active for i in range(4)])
            for index in(-1,4,True):
                with self.assertRaises(CaptureError):gate.application_request(r,index)
            for extra in(['ws73.benchmark_parallel=1'],['ws73.benchmark_dynamic=1'],['ws73.benchmark_active=1']):
                with self.assertRaises(CaptureError):gate.channel_from_boot(gate.channel_boot(channel)+extra,r['config'])
            for change in('version','name','port','role','budget','extra'):
                bad=copy.deepcopy(channel)
                if change=='version':bad['version']=True
                elif change=='name':bad['channels'][1]['name']='short'
                elif change=='port':bad['channels'][1]['route']['ports']=[24576,24577]
                elif change=='role':bad['channels'][1]['route']['active_endpoint']=1-active
                elif change=='budget':bad['channels'][1]['config']['bytes']=61
                else:bad['channels'][0]['route']['extra']=True
                with self.subTest(change=change),self.assertRaises(CaptureError):gate.channel_configuration(bad)
        for change in(dict(channel_benchmark_dynamic=True),dict(channel_benchmark='duplex'),dict(channel_benchmark_count=16),dict(channel_benchmark_parallel=1)):
            args=SimpleNamespace(**(dict(channel_benchmark='window',channel_benchmark_parallel=True)|change))
            with self.subTest(change=change),self.assertRaises(CaptureError):gate.requested_channel(args)
        from ws73_north_star import file_record
        here=Path(gate.__file__).parent
        names=('ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh','ws73_dynamic_channels.py')
        package=dict(socket_benchmark_role_contract_version=1,benchmark_trace_contract_version=1,benchmark_process_resource_contract_version=1,inputs=[file_record(here/n)for n in names])
        with self.assertRaisesRegex(ValueError,'ws73_channel_fairness.py'):gate.validate_role_sources(package,dynamic=True,parallel=True)
        package['inputs'].append(file_record(here/'ws73_channel_fairness.py'));gate.validate_role_sources(package,dynamic=True,parallel=True)

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
    def fixture(self,root,channel=None,*,cross_namespace=False):
        # Synthetic schema2/wire/role metadata,not actual credentials or mount.
        from test_ws73_socket_benchmark import fixture as legacy_fixture,parallel_fixture
        from test_ws73_application_client import fixture as application_fixture
        from ws73_application_client import application_environment
        import hashlib,shutil
        run,capture=parallel_fixture(root,channel['channels'][0]['route']['active_endpoint'],cross_namespace=cross_namespace,close_short=gate.closes_short(channel))if gate.is_parallel(channel)else legacy_fixture(root,channel=channel);old_roles,_=application_fixture();daemon=dict(pid=11,start_ticks=31);supervisor=dict(pid=500 if gate.is_parallel(channel)else 12,start_ticks=41)
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
                config=gate.application_config(row,i)
                app['args']=gate.arguments('/bin/slktest',gate.application_owner(row,i),app['mode'],runtime,config['window'],count=config['count'],size=config['bytes'],interval_us=config['interval_us'],channel=gate.application_request(row,i));app['stdout']=app['stdout'].replace(before,runtime);app['credentials']=copy.deepcopy(role['credentials']);app['environment']=application_environment();app['output_files']=[str(gate.ROLE_ROOT/f'phase-{phase}'/f'benchmark-{phase}-{i}.{v}')for v in('stdout','stderr')]
                if gate.is_parallel(channel):
                    from test_ws73_benchmark_resources import snapshot as resource_snapshot
                    row[gate.RESOURCE_FIELD]=1
                    base=phase*(20000 if gate.closes_short(channel)else 2000)
                    app['process_resources']=dict(before=resource_snapshot(app['pid'],base+150),after=resource_snapshot(app['pid'],base+(8050 if gate.closes_short(channel)and i>=2 else 1050),15,6))
                (source/'reports'/f'benchmark-{phase}-{i}.json').write_text(json.dumps(app['report']));(source/f'benchmark-{phase}-{i}.stdout').write_text(app['stdout']);(source/f'benchmark-{phase}-{i}.stderr').write_text('')
            (source/'run.json').write_text(json.dumps(row))
            exported=root/'benchmark-role'/f'phase-{phase}';exported.parent.mkdir(exist_ok=True);snapshot.publish(source,exported,phase=phase,success=True,kind='benchmark')
            proof=json.loads((exported/'snapshot.json').read_text());proof['source_root']=str(gate.ROLE_RUNTIME/f'phase-{phase}');(exported/'snapshot.json').write_text(json.dumps(proof))
        (root/'benchmark-role/finished.json').write_text(json.dumps(dict(status=gate.ROLE_STATUS,daemon=daemon,supervisor=supervisor,snapshot_contract_version=1,socket_benchmark_role_contract_version=1)))
        return run,capture

    def test_parallel_target_uses_same_closed_supervisor_per_channel_cmtc_and_shared_progress_oracle(self):
        for active in(0,1):
            with tempfile.TemporaryDirectory()as temporary:
                root=Path(temporary);channel=gate.parallel_channel(active);run,capture=self.fixture(root,channel)
                proof=gate.corroborate(run,capture,root);role=gate.verify_role_artifacts(run,root)
                self.assertEqual((proof['round_trips'],role['application_processes'],role['report_files']),(72,8,8))
                self.assertTrue(gate.valid_parallel_summary(proof,channel,gate.configuration('window'),role))
                self.assertEqual([len(c['legs'])for c in proof['proofs'][0]['channels']],[40,32])
                self.assertEqual([c['name']for c in proof['proofs'][0]['channels']],['short','long'])
                self.assertTrue(all(len(c['dynamic_negotiation'])==2 for c in proof['proofs'][0]['channels']))
                self.assertEqual(len(proof['proofs'][0]['concurrent_progress']),2)
                self.assertIs(proof['full_fairness_acceptance'],False)
                for change in ('missing-target','single-role','missing-second-channel','missing-long-leg','wrong-request','wrong-progress','flattened-legs','wrong-group'):
                    p=copy.deepcopy(proof);r=copy.deepcopy(role);c=p['proofs'][0]['channels'][1]
                    if change=='missing-target':p.pop(gate.CHANNEL_FIELD)
                    elif change=='single-role':r['version']=1;r['application_processes']=r['report_files']=4
                    elif change=='missing-second-channel':p['proofs'][0]['channels'].pop()
                    elif change=='missing-long-leg':c['legs'].pop()
                    elif change=='wrong-request':c['application']['channel_requests'][0]['destination_port']-=2
                    elif change=='wrong-progress':p['proofs'][0]['concurrent_progress'][0]['short_pdus_between']=0
                    elif change=='flattened-legs':p['proofs'][0]['legs'].pop()
                    else:c['config']['bytes']=61
                    with self.subTest(change=change):self.assertFalse(gate.valid_parallel_summary(p,channel,gate.configuration('window'),r))

    def test_failed_control_diagnostic_reuses_closed_payloads_without_inventing_daemon_after(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);run,capture=self.fixture(root,gate.parallel_channel());run.pop('daemon_after')
            before=copy.deepcopy(run)
            with self.assertRaises(KeyError):gate.corroborate(run,capture,root)
            proof=gate.diagnose_closed_payloads(run,capture,root)
            self.assertEqual(run,before)
            self.assertEqual(proof['round_trips'],72)
            self.assertEqual(proof['status'],'DIAGNOSTIC_CLOSED_PAYLOAD_COMPONENT_ONLY')
            self.assertIs(proof['overall_run_acceptance'],False)
            self.assertEqual(proof['closed_role_facts']['application_processes'],8)
            self.assertFalse(gate.valid_role_supervision(proof['closed_role_facts']))
            self.assertNotIn('daemon_after',run)
            broken=copy.deepcopy(capture);broken['acb_packets'].pop()
            with self.assertRaises(CaptureError):gate.diagnose_closed_payloads(run,broken,root)
            (root/'benchmark-role/finished.json').unlink()
            with self.assertRaises(FileNotFoundError):gate.diagnose_closed_payloads(run,capture,root)

    def test_parallel_tcids_use_separate_local_remote_namespaces_per_direction(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);run,capture=self.fixture(root,gate.parallel_channel(),cross_namespace=True)
            proof=gate.corroborate(run,capture,root)
            self.assertEqual(proof['round_trips'],72)
            a,b=run['socket_benchmark'][0]['applications'][0::2]
            self.assertEqual(a['report']['channel_identity']['remote_tcid'],b['report']['channel_identity']['local_tcid'])
            self.assertNotEqual(a['report']['channel_identity']['local_tcid'],b['report']['channel_identity']['local_tcid'])

    def test_parallel_finalizer_requires_exact_role_cardinality_profile_resources_trace_and_both_channels(self):
        from test_ws73_benchmark_timeline import modern_trace
        from ws73_benchmark_timeline import check_xhci
        from ws73_target import run_exit_code
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);channel=gate.parallel_channel(1);run,capture=self.fixture(root,channel)
            proof=gate.corroborate(run,capture,root);role=gate.verify_role_artifacts(run,root)
            trace=root/'trace';trace.mkdir();modern_trace(trace,'off');xhci=check_xhci(trace,'off')
            names=['ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_benchmark_resources.py','ws73_application_role.py','ws73_role_snapshot.py','ws73_dynamic_channels.py','ws73_channel_fairness.py']
            record=dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,socket_benchmark_requested='window',socket_benchmark_window_requested=4,socket_benchmark_acceptance=True,socket_benchmark_corroboration=proof,performance_qualified=False,socket_benchmark_role_contract_version=1,socket_benchmark_apps_acceptance=True,socket_benchmark_role_supervision=role,benchmark_trace_contract_version=1,benchmark_process_resource_contract_version=1,socket_benchmark_xhci_requested='off',socket_benchmark_xhci_observation=xhci,benchmark_verifiers=[dict(path=n)for n in names],qemu_args=['ws73.socket_benchmark_apps=1 '+' '.join(gate.channel_boot(channel))],benchmark_channel_request=channel)
            self.assertEqual(run_exit_code(record),0)
            for change in('old-role','missing-role-target','missing-fairness-source','missing-trace','missing-resource','missing-target','old-boot','mixed-boot','missing-long','missing-resource-child','wrong-total','diagnostic-component'):
                r=copy.deepcopy(record)
                if change=='old-role':r['socket_benchmark_role_supervision']['version']=1
                elif change=='missing-role-target':r['socket_benchmark_role_supervision'].pop(gate.CHANNEL_FIELD)
                elif change=='missing-fairness-source':r['benchmark_verifiers'].pop()
                elif change=='missing-trace':r.pop('benchmark_trace_contract_version')
                elif change=='missing-resource':r.pop(gate.RESOURCE_FIELD)
                elif change=='missing-target':r.pop(gate.CHANNEL_FIELD)
                elif change=='old-boot':r['qemu_args']=['ws73.socket_benchmark_apps=1 ws73.benchmark_dynamic=1 ws73.benchmark_active=1']
                elif change=='mixed-boot':r['qemu_args'][0]+=' ws73.benchmark_dynamic=1'
                elif change=='missing-long':r['socket_benchmark_corroboration']['proofs'][0]['channels'].pop()
                elif change=='missing-resource-child':r['socket_benchmark_corroboration']['proofs'][0]['resource_observations'].pop()
                elif change=='diagnostic-component':r['socket_benchmark_corroboration']=gate.diagnose_closed_payloads(run,capture,root)
                else:r['socket_benchmark_corroboration']['round_trips']=40
                with self.subTest(change=change):self.assertEqual(run_exit_code(r),1)

    def test_parallel_actual_checker_rejects_wrong_group_tcids_barriers_signals_and_fragment_streams(self):
        for change in ('duplicate-pid','same-tcid','missing-fourth-arm','early-start','missing-fourth-quiescent','early-finish','missing-long-CMTC','cross-channel-data','missing-long-rx','interleaved-PB','no-overlap'):
            with tempfile.TemporaryDirectory()as temporary:
                root=Path(temporary);run,capture=self.fixture(root,gate.parallel_channel());row=run['socket_benchmark'][0]
                if change=='duplicate-pid':row['applications'][2]['pid']=row['applications'][0]['pid']
                elif change=='same-tcid':row['applications'][2]['report']['channel_identity']['local_tcid']=row['applications'][0]['report']['channel_identity']['local_tcid']
                elif change=='missing-fourth-arm':row['events']=[e for e in row['events']if not(e['application']==3 and e['kind']=='armed')]
                elif change=='early-start':next(e for e in row['events']if e['kind']=='start')['before_wall_ns']=105
                elif change=='missing-fourth-quiescent':row['events']=[e for e in row['events']if not(e['application']==3 and e['kind']=='quiescent')]
                elif change=='early-finish':next(e for e in row['events']if e['kind']=='finish')['before_wall_ns']=1005
                elif change=='missing-long-CMTC':
                    p=next(p for p in capture['acb_packets']if p['wall_ns']<100 and bytes.fromhex(p['data'])[4]==16 and bytes.fromhex(p['data'])[8]==0x83);capture['acb_packets'].remove(p)
                elif change=='cross-channel-data':
                    p=next(p for p in capture['acb_packets']if p['boundary']==1);p['data']='82'+p['data'][2:]
                elif change=='missing-long-rx':
                    p=next(p for p in capture['acb_packets']if p['boundary']==3 and p['direction']=='in');capture['acb_packets'].remove(p)
                elif change=='interleaved-PB':
                    first=next(p for p in capture['acb_packets']if p['boundary']==1)
                    p=dict(first,record=first['record']+.1,boundary=0,data='81000000');capture['acb_packets'].append(p)
                else:
                    for p in capture['acb_packets']:
                        if p['boundary']!=0 and p['wall_ns']<2000:p['wall_ns']+=600
                if change in ('duplicate-pid','same-tcid','missing-fourth-arm','early-start','missing-fourth-quiescent','early-finish'):
                    with self.subTest(transition=change),self.assertRaises(CaptureError):gate.check_supervision(row)
                with self.subTest(change=change),self.assertRaises((CaptureError,KeyError,FileNotFoundError)):
                    gate.corroborate(run,capture,root)

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
