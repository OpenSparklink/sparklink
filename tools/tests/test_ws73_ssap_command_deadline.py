"""Finite evidence-verifier controls, not Native, scheduler or RF qualification.

Existing positive/policy fixtures supply their already-defined contracts. This
file independently authors the additional short command bytes, Owner prompt,
terminal observations and ordering. The shared matcher calls the real ACB
reassembler; no protocol encoder or always-success transport is substituted.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ws73_ssap_command as positive
import ws73_ssap_command_policy as policy
import ws73_ssap_command_deadline as gate
from ws73_capture import CaptureError
from test_ws73_ssap_command import credentials, matcher, output
from test_ws73_ssap_command_policy import fixture as policy_fixture, add_pair, manifest as policy_manifest
from test_ws73_channel_socket import fixture as application_fixture

PREFIX = 'ssap_command_deadline'


def ordinary_business(row, clock):
    """Independent existing application vectors plus complete raw ACB pairs.

    These are finite parser fixtures. There is no real SDK binary, kernel,
    scheduler, capture source or firmware behind the explicitly synthetic hash.
    """
    row.update(application_fixture())
    row.update(application_tool=dict(path='/bin/slktest', sha256='a'*64),
        channel_info_required=True, tx_status_required=True,
        message_security_required=True, tx_constraint_required=True, dtap_limits_version=1,
        cmtc_local_capability=dict(mtu=2042,mps=2047))
    for i, (app, entry) in enumerate(zip(row['applications'], row['owners'], strict=True)):
        o, c = entry['owner'], entry['object']; o['buffers'] = [254,5,0,0]
        app.update(stderr='', start_wall_ns=clock+5_007_000_000+i,
            end_wall_ns=clock+5_105_000_000+i,
            args=['/bin/slktest','--adapter',o['path'],'channel','peer' if i else 'ping',
                c['path'],'--check','--count','4','--bytes','61','--message-security'])
        app['stdout'] += (f"NativeChannelInfo: index={o['index']} generation={o['generation']} lifetime={c['lifetime']} handle={c['handle']} local=31 remote=31 pi=241 mtu=2042 mps=2047 mode=0 directions=3\n"
            'NativeChannelInfoCopy: partial=16 retry=1 unchanged=1\n'
            f"NativeTxStatus: stage=ready sequence=0 index={o['index']} generation={o['generation']} lifetime={c['lifetime']} handle={c['handle']} maximum=254 capacity=5 outstanding=0 debt=0 peak=1 queued=0 limit=8 busy=0 bytes=0 offset=0 flags=0 blocks=0\n")
        for sequence in range(4):
            app['stdout'] += f"NativeMessageSecurity: sequence={sequence} index={o['index']} generation={o['generation']} lifetime={c['lifetime']} handle={c['handle']} local=31 remote=31 pi=241 security=0 epoch=42 flags=3\n"
            if i:
                app['stdout'] += f'NativeConstrainedReply: sequence={sequence} epoch=42 minimum=0 deadline_ns={clock+5_050_000_000}\n'
                for ordinal,kind in enumerate(('epoch','lifetime','deadline')):
                    rejected=b'SLKINTRE'+bytes([sequence*3+ordinal+1])*53
                    app['stdout'] += f'NativeConstraintRejected: sequence={sequence} kind={kind} errno={110 if kind=="deadline" else 13} bytes={rejected.hex()}\n'
        app['stdout'] += 'NativeControlRejected: errno=95 bytes='+ (b'SLKCMREJ'+bytes([i+1])*53).hex()+'\n'
    capture = dict(acb_packets=[],native_events=[])
    legs = []
    # Read independently authored application fixture lines, not a production encoder.
    sent = re.findall(r'^NativeChannelSent: sequence=\d+ bytes=([0-9a-f]+)$',row['applications'][0]['stdout'],re.M)
    replies = re.findall(r'^NativeChannelReply: sequence=\d+ bytes=([0-9a-f]+)$',row['applications'][1]['stdout'],re.M)
    for sequence, (message, reply) in enumerate(zip(sent,replies,strict=True)):
        for sender, raw in enumerate((message,reply)):
            frame = b'\x1f\x00\x3e\x00\xf1'+bytes.fromhex(raw)
            stamp = clock+5_010_000_000+(sequence*2+sender)*1_000_000
            for index,direction,offset in ((sender,'out',0),(1-sender,'in',1)):
                entry = row['owners'][index]
                capture['acb_packets'].append(dict(bus=entry['owner']['bus'],device=entry['owner']['device'],
                    handle=entry['object']['handle'],direction=direction,boundary=0,data=frame.hex(),
                    record=len(capture['acb_packets'])+1,wall_ns=stamp+offset))
    from ws73_capture import reassemble_acb
    packets = reassemble_acb(capture)
    for i in range(0,len(packets),2):
        legs.append(dict(sequence=i//4,tx=packets[i],rx=packets[i+1]))
    return legs


def shift(value, amount, phase):
    """Rebase existing fixture clocks/physical lifetimes without a wire codec."""
    if isinstance(value, dict):
        return {key: (item + amount if key.endswith('_ns') and type(item) is int else
                      item + 100 if key == 'lifetime' and phase else shift(item, amount, phase))
                for key, item in value.items()}
    if isinstance(value, list):
        return [shift(item, amount, phase) for item in value]
    if isinstance(value, str):
        value = re.sub(r'("(?:deadline|call|returned)_ns"\s*:\s*)(\d+)',
                       lambda m: m[1] + str(int(m[2]) + amount), value)
        value = re.sub(r'(deadline_ns=)(\d+)', lambda m: m[1]+str(int(m[2])+amount), value)
        if phase:
            value = re.sub(r'(lifetime=)(21|22)(?=\s)', lambda m: m[1]+str(int(m[2])+100), value)
            for old in (21, 22):
                value = value.replace(f'/link_{old:016x}', f'/link_{old+100:016x}')
        return value
    return value


def refresh_outputs(value):
    if isinstance(value, dict):
        if 'output_collection' in value:
            output(value)
        for item in value.values():
            refresh_outputs(item)
    elif isinstance(value, list):
        for item in value:
            refresh_outputs(item)


def fixture(phase=0):
    row, capture = policy_fixture(phase)
    # Old fixtures deliberately share identities. Here an actual second
    # physical lifetime is a mandatory, separately tested witness.
    row, capture = shift(row, phase * 20_000_000_000, phase), shift(capture, phase * 20_000_000_000, phase)
    clock = phase * 21_000_000_000 + 500_000_000
    row['end_wall_ns'] = clock + 10_000_000_000
    for entry, info in zip(row['owners'], row['ssap_receipts'], strict=True):
        info.update(args=['/bin/slctl', '--adapter', entry['owner']['path'], 'ssap-info', entry['object']['path']], stderr='')
    sender, api = phase, ('c', 'python')[phase]
    source, target = row['owners'][sender], row['owners'][1-sender]
    handle = 101
    token = lambda key: hashlib.sha256(f'deadline/{phase}/{key}'.encode()).digest()
    secret, value = token('before').hex(), (phase.to_bytes(4, 'little')+token('command')[:28]).hex()
    owner = dict(sender=sender, target=1-sender, api=api, operations=3, policy='ask', handle=handle,
        start=handle-1, end=handle, secret=secret, service=token('service')[:16].hex(),
        uuid=token('uuid')[:16].hex(), pid=5000+phase, start_wall_ns=clock-10,
        end_wall_ns=clock+5_111_000_000, exit=0, stderr='', credentials=credentials(), value_snapshots=[])
    owner['args'] = ['/bin/slctl', '--adapter', target['owner']['path'], 'ssap-serve',
        owner['service'], owner['uuid'], '3', '36', secret, 'ask']
    owner['stdout'] = f'SsapOwnedService: start={handle-1} end={handle} property={handle}; local registration only\n'
    case = dict(sequence=phase, sender=sender, target=1-sender, api=api, handle=handle, value=value,
        start_wall_ns=clock, end_wall_ns=clock+5_109_000_000, status=gate.STATUS)

    def snapshot(stamp):
        snap = dict(handle=handle, value=secret, ordinal=len(owner['value_snapshots'])+1,
            start_wall_ns=stamp, end_wall_ns=stamp+1, start_monotonic_ns=stamp, end_monotonic_ns=stamp+1)
        owner['value_snapshots'].append(snap)
        owner['stdout'] += f'SsapOwnedValue: handle={handle} value={secret}\n'
        return snap

    case['local_before'] = snapshot(clock+10)
    barrier = dict(stage='ssap_command_start_barrier', api=api, deadline_ns=clock+1_000_000_000, client_closed=True)
    admitted = dict(api=api, handle=handle, value=value, minimum=0, admission_only=True,
        peer_delivery_confirmed=False, deadline_ns=barrier['deadline_ns'], call_ns=clock+1200, returned_ns=clock+90_000)
    prefix = ['/bin/ws73-application-client-c'] if api == 'c' else ['/bin/python3', '/usr/share/sparklink/tools/ws73-application-client.py']
    case['command'] = dict(api=api, args=prefix+['ssap-command', str(source['owner']['index']),
        str(source['owner']['generation']), source['object']['path'], str(handle), value, '0'],
        environment=dict(PYTHONPATH='/usr/share/sparklink/python:/usr/share/sparklink/tools', LIBSPARKLINK_PATH='/usr/lib/libsparklink.so.0'),
        credentials=credentials(), exit=0, stderr='', stdout=json.dumps(barrier)+'\nSSAP_COMMAND_ADMITTED: '+json.dumps(admitted)+'\n',
        start_wall_ns=clock+1000, end_wall_ns=clock+100_000, barrier_wall_ns=clock+1100, release_wall_ns=clock+1150,
        start_monotonic_ns=clock+1000, barrier_monotonic_ns=clock+1100, release_monotonic_ns=clock+1150)
    output(case['command'])
    p = dict(token=1, request=77, index=target['owner']['index'], generation=target['owner']['generation'],
        lifetime=target['object']['lifetime'], handle=target['object']['handle'], epoch=42, security=0,
        property=handle, data_type=0, write=True, bytes=32, deadline_ns=clock+5_000_000_000, yes=1, no=1)
    rendered = dict(p, write='true')
    owner['stdout'] += ('SsapAuthorizationPrompt: token={token} request={request} index={index} generation={generation} '
        'lifetime={lifetime} handle={handle} epoch={epoch} security={security} property={property} data_type={data_type} '
        'write={write} bytes={bytes} deadline_ns={deadline_ns}; answer \'yes {yes}\' or \'no {no}\'\n').format(**rendered)
    owner['stdout'] += f'SsapAuthorizationDecision: request=77 property={handle} data_type=0 write=true security=0 approved=false; local policy only\n'
    case['prompt'] = dict(fields=p, wall_ns=clock+200_000, monotonic_ns=clock+200_000)

    def info(entry, start, failed):
        return dict(args=['/bin/slctl','--adapter',entry['owner']['path'],'ssap-info',entry['object']['path']],
            exit=1 if failed else 0, stdout=f'Selected {entry["owner"]["path"]}\n' if failed else row['ssap_receipts'][sender]['stdout'],
            stderr='Error: broker: org.freedesktop.DBus.Error.Failed: original SSAP obligation deadline\n' if failed else '',
            start_wall_ns=start, end_wall_ns=start+1000, start_monotonic_ns=start, end_monotonic_ns=start+1000)
    case['terminal_attempts'] = [info(target, clock+5_001_000_000, True)]
    case['terminal_observation_deadline_ns'] = clock+7_000_000_000
    case['terminal'] = 'original SSAP obligation deadline'
    case['late_input'] = dict(text='yes 1', wall_ns=clock+5_003_000_000, monotonic_ns=clock+5_003_000_000)
    case['local_after_late'] = snapshot(clock+5_004_000_000)
    case['source_info'] = info(source, clock+5_005_000_000, False)
    case['business_window'] = dict(start_wall_ns=clock+5_006_000_000, end_wall_ns=clock+5_106_000_000,
        start_monotonic_ns=clock+5_006_000_000, end_monotonic_ns=clock+5_106_000_000)
    row['fixture_business_legs'] = ordinary_business(row,clock)
    case['terminal_after_business'] = info(target, clock+5_107_000_000, True)
    case['local_after_business'] = snapshot(clock+5_108_000_000)
    owner['removal'] = dict(exit=0, stderr='', stdout='SsapLocalServices: []\n',
        start_wall_ns=clock+5_110_000_000, end_wall_ns=clock+5_110_000_001)
    row.update(ssap_command_deadline_required=True, ssap_command_deadline_contract=1,
        ssap_command_deadline_case=case, ssap_command_deadline_publishers=[owner])
    # Independently authored single-value WriteCommand (not production encoder).
    add_pair(capture, source, target, b'\x0c\x03'+handle.to_bytes(2,'little')+b'\x00'+bytes.fromhex(value), clock+150_000)
    output(owner)
    refresh_outputs(row)
    return row, capture


def corroborated():
    summary = dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED', proofs=[])
    for phase in (0,1):
        row, capture = fixture(phase); matched, packets = matcher(capture)
        positives, _ = positive.corroborate(row, matched)
        policies, _ = policy.corroborate(row, matched, packets)
        deadlines, credit = gate.corroborate(row, matched, packets)
        gate.verify_business(row,row[PREFIX+'_case'],row['fixture_business_legs'])
        assert not packets and credit == {phase:1,1-phase:0}
        summary['proofs'].append(dict(phase=phase, owners=row['owners'], ssap_write_commands=positives,
            ssap_command_policy=policies, ssap_command_deadline=deadlines,legs=row['fixture_business_legs']))
    return summary


def manifest(summary):
    value = policy_manifest(summary); source = Path(gate.__file__).resolve()
    value['qemu_args'][-1] += ' ws73.ssap_command_deadline=1'
    value.update(ssap_command_deadline_requested=True, ssap_command_deadline_acceptance=True,
        ssap_command_deadline_contract_version=1,
        ssap_command_deadline_verifier=dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    return value


class CommandDeadlineGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = corroborated()

    def test_original_positive_policy_and_two_terminal_cases_remain_distinct(self):
        rows = [fixture(phase)[0] for phase in (0,1)]
        gate.validate_rows(rows, True)
        for row in rows:
            case, owner = row[PREFIX+'_case'], row[PREFIX+'_publishers'][0]
            self.assertEqual(gate.case_contract(row, case, owner), b'\x0c\x03e\x00\x00'+bytes.fromhex(case['value']))
        self.assertTrue(positive.valid_summary(self.summary))
        self.assertTrue(policy.valid_summary(self.summary))
        self.assertTrue(gate.valid_summary(self.summary))
        self.assertTrue(gate.valid_manifest(manifest(self.summary)))
        self.assertEqual(sum(len(p['ssap_write_commands']) for p in self.summary['proofs']),24)
        self.assertEqual(sum(len(p['ssap_command_policy']) for p in self.summary['proofs']),8)
        self.assertEqual(sum(len(p[PREFIX]) for p in self.summary['proofs']),2)

    def test_selectors_and_row_identity_fail_closed(self):
        self.assertFalse(gate.boot_requested([]))
        tokens=['ws73.ssap_write_command=1','ws73.ssap_command_policy=1','ws73.ssap_command_deadline=1']
        self.assertTrue(gate.boot_requested(tokens))
        for value in ('','0','2','true'):
            with self.subTest(value=value), self.assertRaises(CaptureError):
                gate.boot_requested(tokens[:2]+['ws73.ssap_command_deadline='+value])
        for bad in (tokens+tokens[-1:],tokens[1:],tokens[2:],['ws73.ssap_command_deadline'],tokens[0], [1]):
            with self.subTest(tokens=bad), self.assertRaises(CaptureError):gate.boot_requested(bad)
        for name in ('short','typed-phase','typed-required','missing-case','missing-owner','wrong-contract','unselected'):
            rows=[fixture(p)[0] for p in (0,1)];selected=True
            if name=='short':rows.pop()
            elif name=='typed-phase':rows[1]['phase']=True
            elif name=='typed-required':rows[0][PREFIX+'_required']=1
            elif name=='missing-case':del rows[0][PREFIX+'_case']
            elif name=='missing-owner':rows[0][PREFIX+'_publishers']=[]
            elif name=='wrong-contract':rows[0][PREFIX+'_contract']=True
            else:selected=False
            with self.subTest(name=name),self.assertRaises((CaptureError,KeyError)):gate.validate_rows(rows,selected)

    def test_terminal_and_original_timeline_refuse_changed_receipts(self):
        mutations = {
            'wrong-api': lambda c,o,r:c.update(api='python'),
            'early-yes': lambda c,o,r:c['late_input'].update(monotonic_ns=c['prompt']['fields']['deadline_ns']-1),
            'wrong-token': lambda c,o,r:c['late_input'].update(text='yes 77'),
            'long-author-deadline': lambda c,o,r:c['prompt']['fields'].update(deadline_ns=c['prompt']['monotonic_ns']+6_000_000_000),
            'value-changed': lambda c,o,r:c['local_after_late'].update(value=c['value']),
            'source-failed': lambda c,o,r:c['source_info'].update(exit=1),
            'source-new-info': lambda c,o,r:c['source_info'].update(stdout=c['source_info']['stdout'].replace('lifetime=21','lifetime=99')),
            'missing-attempt': lambda c,o,r:c.update(terminal_attempts=[]),
            'unbounded-observation': lambda c,o,r:c.update(terminal_observation_deadline_ns=c['prompt']['fields']['deadline_ns']+4_000_000_000),
            'generic-failure': lambda c,o,r:c['terminal_attempts'][0].update(stderr='org.freedesktop.DBus.Error.Failed: unrelated\n'),
            'rpc-timeout': lambda c,o,r:c['terminal_attempts'][0].update(stderr='org.freedesktop.DBus.Error.Timeout: original SSAP obligation deadline\n'),
            'terminal-success': lambda c,o,r:c['terminal_after_business'].update(exit=0),
            'different-terminal': lambda c,o,r:c['terminal_after_business'].update(stderr='org.freedesktop.DBus.Error.Failed: original SSAP authorization deadline\n'),
            'late-observation': lambda c,o,r:c['terminal_attempts'][0].update(end_monotonic_ns=c['terminal_observation_deadline_ns']+1),
            'owner-exit': lambda c,o,r:o.update(exit=1),
            'owner-root': lambda c,o,r:o['credentials'].update(uids=[0]*4),
            'missing-app': lambda c,o,r:r['applications'].pop(),
            'app-failed': lambda c,o,r:r['applications'][0].update(exit=1),
            'app-before-failed': lambda c,o,r:r['applications'][0].update(start_wall_ns=c['prompt']['wall_ns']),
            'long-business': lambda c,o,r:c['business_window'].update(end_monotonic_ns=c['business_window']['start_monotonic_ns']+32_000_000_000),
            'owner-remains': lambda c,o,r:o['removal'].update(stdout='SsapLocalServices: [[100,101]]\n'),
        }
        for name, mutate in mutations.items():
            row,_=fixture();case,owner=row[PREFIX+'_case'],row[PREFIX+'_publishers'][0];mutate(case,owner,row)
            with self.subTest(name=name),self.assertRaises(CaptureError):gate.case_contract(row,case,owner)

    def test_wire_requires_both_endpoints_exact_value_and_full_inventory(self):
        for name in ('missing-rx','changed-value','wrong-lifetime-handle','extra-response','extra-exchange','duplicate'):
            row,capture=fixture();case=row[PREFIX+'_case'];packet=capture['acb_packets'][-1]
            if name=='missing-rx':capture['acb_packets'].pop()
            elif name=='changed-value':packet['data']=packet['data'][:-2]+'ff'
            elif name=='wrong-lifetime-handle':packet['handle']+=1
            elif name=='duplicate':capture['acb_packets'].append(dict(packet,record=packet['record']+1))
            else:
                pdu=b'\x0e\x03\x01' if name=='extra-response' else b'\x02\x07\xfa\x07\x01\x02\x04\x00\x00\x00'
                add_pair(capture,row['owners'][1],row['owners'][0],pdu,case['prompt']['wall_ns']+1)
            matched,packets=matcher(capture)
            with self.subTest(name=name),self.assertRaises(CaptureError):gate.corroborate(row,matched,packets)
        for field,new in [('data','ff'),('wall_ns',1),('record',1),('boundary',1)]:
            proof=copy.deepcopy(self.summary['proofs'][0][PREFIX][0]);row,_=fixture()
            proof['window_packets']=copy.deepcopy(proof['window_packets'])
            proof['window_packets'][0]['fragments'][0][field]=new
            pdu=b'\x0c\x03e\x00\x00'+bytes.fromhex(proof['case']['value'])
            with self.subTest(fragment=field),self.assertRaises(CaptureError):
                gate.verify_wire(row,proof['case'],pdu,proof['wire'],proof['window_packets'])

    def test_summary_refuses_stale_lifetime_source_and_missing_business(self):
        for name in ('missing-phase','missing-case','version','phase','unbounded-absence','recovery','old-lifetime',
                     'missing-rx','terminal','source','apps','missing-positive','missing-policy','old-positive-time'):
            value=copy.deepcopy(self.summary);first=value['proofs'][0];proof=first[PREFIX][0]
            if name=='missing-phase':value['proofs'].pop()
            elif name=='missing-case':first[PREFIX]=[]
            elif name=='version':proof['contract']=True
            elif name=='phase':proof['phase']=True
            elif name=='unbounded-absence':proof['bounded_absence_only']=False
            elif name=='recovery':proof['automatic_recovery_qualification']=True
            elif name=='old-lifetime':value['proofs'][1]['owners'][0]['object']['lifetime']=21
            elif name=='missing-rx':del proof['wire']['rx']
            elif name=='terminal':proof['case']['terminal']='irrelevant'
            elif name=='source':proof['source_info_original']['stdout']='old source\n'
            elif name=='apps':proof['applications'].pop()
            elif name=='missing-positive':first['ssap_write_commands'].pop()
            elif name=='missing-policy':first['ssap_command_policy'].pop()
            else:proof['case']['end_wall_ns']=30_000_000_000
            with self.subTest(name=name):self.assertFalse(gate.valid_summary(value))

    def test_ordinary_business_needs_exact_peer_reply_and_post_terminal_wire(self):
        for name in ('missing-leg','missing-fragment','wrong-value','early-wire','old-handle','bad-pb',
                     'reordered','wrong-sequence','source-receipt','peer-reply','privileged-app',
                     'missing-tx-status','wrong-channel-capability','wrong-args','missing-message-security',
                     'old-message-lifetime','missing-constraint','constraint-errno','constraint-epoch',
                     'constraint-deadline','constraints-disabled'):
            row,_=fixture();case=row[PREFIX+'_case'];legs=row['fixture_business_legs']
            if name=='missing-leg':legs.pop()
            elif name=='missing-fragment':legs[0]['rx']['fragments']=[]
            elif name=='wrong-value':legs[0]['rx']['data']=legs[0]['rx']['data'][:-2]+'ff'
            elif name=='early-wire':
                for packet in (legs[0]['tx'],legs[0]['rx']):
                    packet['wall_ns']=case['prompt']['wall_ns']
                    for fragment in packet['fragments']:fragment['wall_ns']=case['prompt']['wall_ns']
            elif name=='old-handle':legs[0]['rx']['handle']+=1
            elif name=='bad-pb':legs[0]['rx']['fragments'][0]['boundary']=1
            elif name=='reordered':legs[0],legs[2]=legs[2],legs[0]
            elif name=='wrong-sequence':legs[0]['sequence']=True
            elif name=='source-receipt':row['applications'][0]['stdout']=row['applications'][0]['stdout'].replace('NativeChannelRoundTrip:', 'Missing:')
            elif name=='peer-reply':row['applications'][1]['stdout']=row['applications'][1]['stdout'].replace('NativeChannelReply:', 'Missing:')
            elif name=='privileged-app':row['applications'][1]['credentials']['uids']=[0]*4
            elif name=='missing-tx-status':row['applications'][0]['stdout']=row['applications'][0]['stdout'].replace('NativeTxStatus:', 'Missing:')
            elif name=='wrong-channel-capability':row['applications'][0]['stdout']=row['applications'][0]['stdout'].replace('mps=2047','mps=249')
            elif name=='wrong-args':row['applications'][1]['args'][-1]='--wrong'
            elif name=='missing-message-security':row['applications'][0]['stdout']=row['applications'][0]['stdout'].replace('NativeMessageSecurity:', 'Missing:')
            elif name=='old-message-lifetime':row['applications'][0]['stdout']=re.sub(r'(^NativeMessageSecurity:.*)lifetime=21',r'\g<1>lifetime=99',row['applications'][0]['stdout'],flags=re.M)
            elif name=='missing-constraint':row['applications'][1]['stdout']=row['applications'][1]['stdout'].replace('NativeConstraintRejected:', 'Missing:')
            elif name=='constraint-errno':row['applications'][1]['stdout']=row['applications'][1]['stdout'].replace('errno=110','errno=0')
            elif name=='constraint-epoch':row['applications'][1]['stdout']=row['applications'][1]['stdout'].replace('NativeConstrainedReply: sequence=0 epoch=42','NativeConstrainedReply: sequence=0 epoch=41')
            elif name=='constraint-deadline':row['applications'][1]['stdout']=re.sub(r'(^NativeConstrainedReply:.*deadline_ns=)\d+',r'\g<1>0',row['applications'][1]['stdout'],flags=re.M)
            else:row['tx_constraint_required']=False
            with self.subTest(name=name),self.assertRaises(CaptureError):gate.verify_business(row,case,legs)

        # A retained summary must preserve the same parent evidence, not just
        # both process exit codes or an unrelated successful prior run.
        for name in ('missing-leg','early-wire','missing-peer-reply','application-tool','missing-message-security','missing-constraints'):
            summary=copy.deepcopy(self.summary);parent=summary['proofs'][0];proof=parent[PREFIX][0]
            if name=='missing-leg':parent['legs'].pop()
            elif name=='early-wire':parent['legs'][0]['rx']['fragments'][0]['wall_ns']=proof['case']['start_wall_ns']
            elif name=='missing-peer-reply':proof['applications'][1]['stdout']=proof['applications'][1]['stdout'].replace('NativeChannelReply:', 'Missing:')
            elif name=='application-tool':proof['application_tool']['sha256']='not-an-artifact-identity'
            elif name=='missing-message-security':proof['applications'][0]['stdout']=proof['applications'][0]['stdout'].replace('NativeMessageSecurity:', 'Missing:')
            else:proof['applications'][1]['stdout']=proof['applications'][1]['stdout'].replace('NativeConstraintRejected:', 'Missing:')
            with self.subTest(summary=name):self.assertFalse(gate.valid_summary(summary))

    def test_manifest_requires_all_original_gates_and_new_selector(self):
        self.assertTrue(gate.valid_manifest({}))
        for name in ('request','acceptance','version','verifier','missing-boot','duplicate-boot','wrong-boot',
                     'no-policy','no-positive','qemu','status','ordinary','missing-proof','unselected'):
            value=manifest(copy.deepcopy(self.summary))
            if name=='request':value[PREFIX+'_requested']=1
            elif name=='acceptance':value[PREFIX+'_acceptance']=1
            elif name=='version':value[PREFIX+'_contract_version']=True
            elif name=='verifier':value[PREFIX+'_verifier']['sha256']='invalid'
            elif name=='missing-boot':value['qemu_args'][-1]=value['qemu_args'][-1].replace(' ws73.ssap_command_deadline=1','')
            elif name=='duplicate-boot':value['qemu_args'][-1]+=' ws73.ssap_command_deadline=1'
            elif name=='wrong-boot':value['qemu_args'][-1]=value['qemu_args'][-1].replace('deadline=1','deadline=2')
            elif name=='no-policy':value['ssap_command_policy_acceptance']=False
            elif name=='no-positive':value['ssap_write_command_acceptance']=False
            elif name=='qemu':value['qemu_exit']=1
            elif name=='status':value['status']='SUPPORT_PASS'
            elif name=='ordinary':value['ordinary_channel_socket_acceptance']=False
            elif name=='missing-proof':del value['channel_socket_corroboration']['proofs'][0][PREFIX]
            else:value[PREFIX+'_requested']=False;value['qemu_args']=[]
            with self.subTest(name=name):self.assertFalse(gate.valid_manifest(value))


if __name__ == '__main__':
    unittest.main()
