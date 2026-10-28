# SPDX-License-Identifier: GPL-2.0-only
"""Evidence fixtures, not a real daemon, controller or hardware qualification.

The ordinary owner oracle is reused unchanged. Independent fixed description
vectors and child receipts exercise missing/foreign/mutated evidence refusal.
"""
import ast
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError, reassemble_acb
from ws73_application_client import application_environment
from ws73_ssap_owned import corroborate
import ws73_ssap_description as gate
from test_ws73_ssap_owned import fixture as owned_fixture


def fixture(phase=0, *, tx_budget=254):
    row, old_matched, packets = owned_fixture()
    row.update(phase=phase, ssap_description_required=True, ssap_description_version=1)
    # Only this new fixture gains full endpoint identities. The historical owner
    # fixture and its original assertions are intentionally unchanged.
    for pos, entry in enumerate(row['owners']):
        entry['owner'].update(index=pos, generation=4, bus=1, device=10+pos)
        entry['object'].update(generation=4, lifetime=100+phase*2+pos, handle=3+pos)
    def adjust(value, offset=0):
        if isinstance(value, dict):
            for key, child in value.items():
                value[key] = child*1000+offset if key.endswith('_wall_ns') else adjust(child, offset)
        elif isinstance(value, list):
            for index, child in enumerate(value): value[index] = adjust(child, offset)
        elif isinstance(value, str):
            for pos in (0, 1): value = value.replace(f'/a{pos}/link', f'/a{pos}/peer_0/connection_{100+phase*2+pos}')
        return value
    adjust(row['owners'])
    capture = dict(acb_packets=[], native_events=[])
    for ordinal, item in enumerate(row['ssap_owned']):
        offset = phase*1000000+ordinal*100000
        adjust(item, offset)
        stamp = lambda n: offset+n*1000
        s, t, h = item['sender'], item['target'], item['handle']
        source = row['owners'][s]; size = gate.SIZES[item['policy']]
        seed = hashlib.sha256(f'{phase}/{s}/{item["policy"]}'.encode()).hexdigest()
        text = '说明-' + (seed * 4)[:size - 7]; value = text.encode()
        item['stdout'] += f'SsapOwnedDescription: handle={h} bytes={size}; local commit only\n'
        uuid = bytes.fromhex(item['uuid']); next_h = (h+1).to_bytes(2, 'little')
        queries = [b'\x06\x13\x01\0\xff\xff' + uuid, b'\x06\x13' + next_h + b'\xff\xff' + uuid]
        replies = [b'\x07\x0b\x81\x11\0' + uuid + b'\x05\0\0\0\x01\x01', b'\x01\0\x06' + next_h + b'\x0b']
        discovery = dict(exit=0, stderr='', start_wall_ns=stamp(4), end_wall_ns=stamp(5),
            stdout=f'SsapRemoteEntry: category=10 handle={h} end={h} uuid={uuid.hex()} operations=5 descriptors=01 members=0\n'
            + f'SsapRemoteDiscovery: path={source["object"]["path"]} kind=3 entries=1 requests={"|".join(q.hex() for q in queries)} responses={"|".join(q.hex() for q in replies)}\n')
        api = 'c' if item['policy'] == 'allow' else 'python'
        prefix = ['/bin/ws73-application-client-c'] if api == 'c' else ['/bin/python3', '/usr/share/sparklink/tools/ws73-application-client.py']
        operation = 'ssap-read-description'; path = source['object']['path']
        app = dict(api=api, exit=0, stderr='', environment=application_environment(),
            credentials=dict(uids=[1000]*4, capabilities={k: '0' for k in ('CapEff','CapPrm','CapAmb','CapInh')}),
            args=prefix+['ssap',str(s),'4',path,operation,str(h),value.hex()],
            ssap_operation=operation,ssap_path=path,ssap_handle=h,ssap_expected=value.hex(),
            stdout=json.dumps(dict(stage='ssap_start_barrier',api=api,client_closed=True))+'\n'
                +f'SsapPeerValue: operation={operation} path={path} handle={h} value={value.hex()}\n',
            start_wall_ns=stamp(6),end_wall_ns=stamp(7))
        removed=dict(exit=1,stderr='peer read error 4',start_wall_ns=stamp(80),end_wall_ns=stamp(81))
        item['description']=dict(text=text,value=value.hex(),bytes=size,start_wall_ns=stamp(2),
            committed_wall_ns=stamp(3),discovery=discovery,read=app,end_wall_ns=stamp(8),retired_read=removed)
        steps=[(discovery,q,r) for q,r in zip(queries,replies)]
        steps += [(app,b'\x08\x03\x11\0\x01',b'\x09\x03'+value),
                  (removed,b'\x08\x03\x11\0\x01',b'\x09\x0b\x04\0')]
        for window, req, rsp in steps:
            for a,b,pdu in ((s,t,req),(t,s,rsp)):
                # Independent literal SSAP vectors above; actual production ACB
                # reassembly below, not a matcher that fabricates successful RX.
                frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
                for endpoint, direction in ((a, 'out'), (b, 'in')):
                    owner=row['owners'][endpoint]
                    budget=tx_budget if direction=='out' else 127
                    chunks=[frame[n:n+budget] for n in range(0,len(frame),budget)]
                    for n,chunk in enumerate(chunks):
                        record=phase*10000+len(capture['acb_packets'])+1
                        capture['acb_packets'].append(dict(bus=owner['owner']['bus'],device=owner['owner']['device'],
                            handle=owner['object']['handle'],direction=direction,data=chunk.hex(),record=record,
                            wall_ns=window['start_wall_ns']+100+len(capture['acb_packets']),
                            boundary=0 if len(chunks)==1 else 1 if n==0 else 3 if n==len(chunks)-1 else 2))
    packets.extend(reassemble_acb(capture))
    def matched(owner,direction,frame,window):
        key=(row['owners'].index(owner),direction,frame,id(window))
        if key in packets: return old_matched(owner,direction,frame,window)
        found=[p for p in packets if isinstance(p,dict)
               and (p['bus'],p['device'],p['handle'],p['direction'],p['data']) ==
                   (owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
               and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(found)!=1: raise CaptureError('one exact retained description endpoint packet required')
        packets.remove(found[0]); return found[0]
    return row,matched,packets


def summary():
    proofs=[]
    for phase in (0,1):
        row,matched,_=fixture(phase)
        proofs.append(dict(phase=phase,owners=row['owners'],ssap_owned=corroborate(row,matched)[0]))
    return dict(proofs=proofs)


class DescriptionEvidence(unittest.TestCase):
    def test_actual_host_loads_then_validates_before_any_process_launch(self):
        # Exercise the real CLI parser and _run. Only the prepared-artifact and
        # read-only host observations are fixtures; no successful device path
        # is supplied. The actual input validators must produce durable FAIL.
        import ws73_target as host
        file_record = host.file_record
        names = ('ws73_ssap_description.py', 'ws73_ssap_owned.py',
                 'ws73_application_client.py', 'ws73_channel_socket.py',
                 'ws73_target_control.py', 'ws73_target_guest.py', 'ws73_target_init.sh')
        good = dict(inputs=[file_record(TOOLS / n) for n in names],
                    application_client_tools=dict(sources=[file_record(TOOLS / n) for n in
                        ('testing/application_client/client.c', 'testing/application_client/client.py')]),
                    ssap_exchange_contract_version=False)
        for kind, expected in (
                ('consumer', 'fresh exact application consumer source required'),
                ('helper', 'fresh exact description input required'),
                ('validated', 'explicit known SSAP exchange artifact contract required')):
            package = copy.deepcopy(good)
            if kind == 'consumer': package['application_client_tools']['sources'] = []
            if kind == 'helper': package['inputs'][0]['sha256'] = '0' * 64
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); prepared = root / 'prepared'; prepared.mkdir()
                (prepared / 'manifest.json').write_text(json.dumps(package))
                output = root / 'output'
                argv = ['ws73_target.py', 'run', '--prepared', str(prepared), '--output', str(output),
                        '--ports', '1-1.1.1', '1-1.1.2', '--qmp-hotplug',
                        '--firmware-evidence', 'runtime-observation', '--connection-verify',
                        '--connection-advertising', 'negotiable-t', '--channel-socket-verify',
                        '--ssap-owned-verify', '--ssap-description-verify']
                with patch.object(sys, 'argv', argv), patch.object(host, 'run', side_effect=lambda args: args):
                    args = host.main()
                stdout = io.StringIO()
                with redirect_stdout(stdout), patch.object(host, 'ordinary_identity'), \
                     patch.object(host, 'prepared', return_value=package) as loaded, \
                     patch.object(host, 'lab_module', return_value=SimpleNamespace(inventory=lambda: [])), \
                     patch.object(gate, 'validate_inputs', wraps=gate.validate_inputs) as checked, \
                     patch.object(host.subprocess, 'Popen', side_effect=AssertionError('must not launch')) as launch:
                    self.assertEqual(host._run(args), 1)
                loaded.assert_called_once_with(prepared.resolve())
                checked.assert_called_once_with(package)
                launch.assert_not_called()
                self.assertEqual(stdout.getvalue().strip(), f'FAIL {output / "manifest.json"}')
                record = json.loads((output / 'manifest.json').read_text())
                self.assertEqual(record['status'], 'FAIL')
                self.assertIn(expected, record['error'])
                self.assertIs(record['ssap_description_acceptance'], False)
                self.assertIs(record['physical_acceptance'], False)
                self.assertNotIn('qemu_args', record)

    def test_original_owned_assertions_and_every_description_leg_remain_required(self):
        proofs=[]
        for phase in (0,1):
            row,matched,packets=fixture(phase);proof,credit=corroborate(row,matched)
            self.assertFalse(packets);self.assertEqual(credit,{0:36,1:36})
            proofs.append(dict(phase=phase,owners=row['owners'],ssap_owned=proof))
        self.assertTrue(gate.valid_summary(dict(proofs=proofs)))
        self.assertFalse(gate.valid_summary(dict(proofs=proofs[:1])))

    def test_mutated_or_missing_description_is_not_qualified(self):
        for kind in ('payload','wrong-kind','missing-peer','missing-discovery','wrong-handle',
                     'wrong-advertisement','property-fallback','wrong-sdk','owner-order',
                     'missing-terminal','failed-child','extra-output','old-policy-failure','descriptor-approval'):
            row,matched,packets=fixture();item=row['ssap_owned'][0];d=item['description']
            if kind=='payload':d['text']='a'*32
            elif kind=='wrong-kind':d['read']['ssap_operation']='ssap-read'
            elif kind=='missing-peer':packets[:]=[p for p in packets if not(isinstance(p,dict) and p['device']==11 and p['direction']=='in' and d['read']['start_wall_ns']<=p['wall_ns']<=d['read']['end_wall_ns'])]
            elif kind=='missing-discovery':d['discovery']['stdout']=''
            elif kind=='wrong-handle':d['read']['ssap_handle']=18
            elif kind=='wrong-advertisement':d['discovery']['stdout']=d['discovery']['stdout'].replace('descriptors=01','descriptors=02')
            elif kind=='property-fallback':d['value']=item['secret']
            elif kind=='wrong-sdk':d['read']['args'][0]='/old/helper'
            elif kind=='owner-order':d['retired_read']['start_wall_ns']=item['owner_exit_wall_ns']-1
            elif kind=='missing-terminal':d['retired_read']['exit']=0
            elif kind=='failed-child':d['read']['exit']=1
            elif kind=='extra-output':d['read']['stdout']+='PASS\n'
            elif kind=='descriptor-approval':item['stdout']+='SsapAuthorizationDecision: request=9 property=17 data_type=1 write=false security=0 approved=true; local policy only\n'
            else:item['stdout']=item['stdout'].replace('request=2','request=1')
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):
                corroborate(row,matched)

    def test_summary_replays_original_receipts_identity_and_every_wire_byte(self):
        good=summary()
        self.assertTrue(gate.valid_summary(json.loads(json.dumps(good))))
        for change in ('missing-read','tx-byte','rx-is-tx','fragment-byte','fragment-identity',
                       'missing-fragment','duplicate-leg','discovery','application','old-lifetime','bool-sender','foreign-context','bool-phase'):
            bad=copy.deepcopy(good);d=bad['proofs'][0]['ssap_owned'][0]['description']
            if change=='missing-read':d.pop('read')
            elif change=='tx-byte':d['wire'][0]['tx']['data']='ff'
            elif change=='rx-is-tx':d['wire'][0]['rx']=copy.deepcopy(d['wire'][0]['tx'])
            elif change=='fragment-byte':d['wire'][0]['tx']['fragments'][0]['data']='ff'
            elif change=='fragment-identity':d['wire'][0]['rx']['fragments'][0]['device']=10
            elif change=='missing-fragment':d['wire'][0]['tx']['fragments']=[]
            elif change=='duplicate-leg':d['wire'][1]=copy.deepcopy(d['wire'][0])
            elif change=='discovery':d['case']['description']['discovery']['stdout']=''
            elif change=='application':d['case']['description']['read']['exit']=1
            elif change=='old-lifetime':d['context']['owners'][0]['object']['generation']=3
            elif change=='bool-sender':d['case']['sender']=False
            elif change=='foreign-context':d['context']['owners'][0]['object']['lifetime']+=10
            else:bad['proofs'][0]['phase']=False
            with self.subTest(change=change):self.assertFalse(gate.valid_summary(bad))

    def test_all_physical_fragments_must_be_inside_original_window(self):
        row,matched,packets=fixture(tx_budget=128)
        item=row['ssap_owned'][1];window=item['description']['read']
        packet=next(p for p in packets if isinstance(p,dict) and p['direction']=='out'
                    and len(p['fragments'])>1 and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns'])
        packet['fragments'][0]['wall_ns']=window['start_wall_ns']-1
        # The top-level last-fragment timestamp still matches the old matcher.
        self.assertGreaterEqual(packet['wall_ns'],window['start_wall_ns'])
        with self.assertRaises(CaptureError):corroborate(row,matched)
        good=summary();d=good['proofs'][0]['ssap_owned'][1]['description']
        d['wire'][5]['rx']['fragments'][0]['wall_ns']=d['case']['description']['read']['start_wall_ns']-1
        self.assertFalse(gate.valid_summary(good))

    def test_credit_counts_actual_tx_pb_fragments_not_logical_packets_or_rx(self):
        row,matched,packets=fixture(tx_budget=128)
        proof,credit=corroborate(row,matched)
        self.assertFalse(packets)
        # Each endpoint sends one two-PB 244-byte reply; RX is independently
        # fragmented but does not consume this controller's outbound credit.
        self.assertEqual(credit,{0:37,1:37})
        self.assertEqual([len(i['description']['wire'][5]['tx']['fragments']) for i in proof],[1,2,1,2])

    def test_required_rows_and_manifest_do_not_upgrade_missing_phases(self):
        rows=[fixture(p)[0]for p in (0,1)];gate.validate_rows(rows,True)
        for change in ('false','missing','version','descriptor'):
            bad=copy.deepcopy(rows)
            if change=='false':bad[0]['ssap_description_required']=False
            elif change=='missing':bad.pop()
            elif change=='version':bad[0]['ssap_description_version']=True
            else:bad[0]['ssap_owned'][0].pop('description')
            with self.assertRaises(CaptureError):gate.validate_rows(bad,True)
        complete=dict(qemu_args=['ws73.ssap_owned=1 '+gate.TOKEN],ssap_description_requested=True,
            ssap_description_version=1,ssap_description_acceptance=True,ssap_owned_acceptance=True,
            status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,ordinary_channel_socket_acceptance=True,
            channel_socket_corroboration=summary())
        self.assertTrue(gate.valid_manifest(complete))
        complete['channel_socket_corroboration']['proofs'][0]['ssap_owned'][0]['description'].pop('read')
        self.assertFalse(gate.valid_manifest(complete))
        self.assertFalse(gate.valid_manifest(dict(qemu_args=[gate.TOKEN],ssap_description_requested=True)))
        self.assertTrue(gate.valid_manifest({}))
        with self.assertRaises(CaptureError):gate.validate_rows(rows,False)

    def test_actual_selectors_cli_and_strict_boot_dependency(self):
        args=SimpleNamespace(ssap_description_verify=True,ssap_owned_verify=True,
            channel_socket_verify=True,passthrough=True)
        self.assertTrue(gate.requested(args))
        for key,value in (('ssap_owned_verify',False),('channel_socket_verify',False),
                          ('passthrough',False),('channel_socket_bytes',250),('parallel',True)):
            bad=copy.copy(args);setattr(bad,key,value)
            with self.assertRaises(ValueError):gate.requested(bad)
        line=next(l for l in (TOOLS/'ws73_target_init.sh').read_text().splitlines() if 'description_arg=$(' in l)
        self.assertIn('PYTHONPATH=/usr/share/sparklink/tools /bin/python3',line)
        code=re.search(r"-c '([^']+)'",line).group(1)
        for tokens,success in (([],True),(['ws73.ssap_owned=1',gate.TOKEN],True),
                               ([gate.TOKEN],False),(['ws73.ssap_owned=1',gate.TOKEN,gate.TOKEN],False),
                               (['ws73.ssap_owned=1','ws73.ssap_description=0'],False)):
            r=subprocess.run([sys.executable,'-c',code,*tokens],env=dict(os.environ,PYTHONPATH=str(TOOLS)),capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode==0,success,r.stderr)
        for argv in (['ws73_target.py','run','--help'],['ws73_target_control.py','--help']):
            r=subprocess.run([sys.executable,str(TOOLS/argv[0]),*argv[1:]],capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr);self.assertIn('--ssap-description-verify',r.stdout)

    def test_source_is_staged_and_actual_external_callers_use_new_sdk(self):
        tree=ast.parse((TOOLS/'ws73_target.py').read_text())
        prepare=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='prepare_locked')
        self.assertEqual(sum(isinstance(n,ast.BinOp)and isinstance(n.right,ast.Constant)and n.right.value=='ws73_ssap_description.py'for n in ast.walk(prepare)),1)
        self.assertEqual(sum(isinstance(n,ast.List)and any(isinstance(v,ast.Constant)and v.value=='ws73_ssap_description.py'for v in n.elts)for n in ast.walk(prepare)),1)
        self.assertIn('slk_connection_ssap_read_description(link,',(TOOLS/'testing/application_client/client.c').read_text())
        self.assertIn('remote.read_description(handle,deadline_ns=deadline)',(TOOLS/'testing/application_client/client.py').read_text())


if __name__=='__main__':unittest.main()
