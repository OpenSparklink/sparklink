# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic receipt/raw-parser tests;not kernel concurrency or WS73 proof."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_link_measurement import KINDS, observation, corroborate_entry, corroborate, exit_gate, TOKEN


def fixture(index=0):
    controller=index%2
    owner = dict(path=f'/org/sparklink/slk{controller}_g{11+controller}', bus=1, device=2+controller, generation=11+controller)
    identity = dict(generation=owner['generation'], lifetime=42+index, handle=0x1234, role=(index//2+controller)%2,
                    address_type=0, address='00:01:09:32:54:F9', path=owner['path']+'/link')
    entry = dict(owner=owner, object=identity, link_measurements=dict(version=1,
        status='REAL_REPLY_PENDING_RAW_AUDIT', queries=[]))
    capture = dict(commands=[], complete=[])
    for offset, (kind, word, opcode, size) in enumerate(KINDS):
        clock = index*1000+100+offset*100
        value = {k:v for k,v in identity.items() if k != 'path'}
        value.update(request_id=index*2+offset+1, deadline_monotonic_ns=5000,
                     kind=kind, state=2, error=0, status=0, flags=7,
                     data=[0x34,0x12]+[0xfe]*(size-2))
        row = dict(args=['/bin/slctl','--adapter',owner['path'],'link-measurement',identity['path'],word,'5000'],
                   start_wall_ns=clock, end_wall_ns=clock+50, exit=0, stderr='',
                   stdout='NativeLinkMeasurement: '+json.dumps(value)+'\n')
        entry['link_measurements']['queries'].append(dict(kind=kind, command=row, observation=value))
        wire = dict(bus=1, device=owner['device'], opcode=opcode)
        capture['commands'].append(dict(wire, record=index*10+offset*2+1, wall_ns=clock+10,
            params='3412', completion=dict(wall_ns=clock+11)))
        capture['complete'].append(dict(wire, record=index*10+offset*2+2, wall_ns=clock+12,
            status=0, value=bytes(value['data']).hex()))
    return entry, capture


class LinkMeasurementTests(unittest.TestCase):
    def test_actual_receipt_and_raw_oracles_agree_on_full_reply(self):
        entry, capture = fixture()
        proof = corroborate_entry(entry, capture)
        self.assertEqual([q['real_DLI']['command']['opcode'] for q in proof['queries']], [0x180c,0x1805])
        self.assertNotIn('application_delivery', proof)

    def test_all_identity_and_status_fields_are_required(self):
        entry, _ = fixture()
        query = entry['link_measurements']['queries'][0]
        for field, replacement in [('generation',12),('lifetime',43),('handle',2),('role',1),
            ('address_type',1),('address','00:00:00:00:00:00'),('request_id',0),
            ('deadline_monotonic_ns',0),('kind',2),('state',1),('error',-1),('status',1),('flags',5),('flags',True)]:
            row = copy.deepcopy(query['command']); value = dict(query['observation']); value[field] = replacement
            row['stdout'] = 'NativeLinkMeasurement: '+json.dumps(value)+'\n'
            with self.subTest(field=field,replacement=replacement),self.assertRaises(ValueError):
                observation(row,entry,1)

    def test_data_shape_handle_and_rssi_sentinel_are_not_normalized(self):
        entry, _ = fixture(); query=entry['link_measurements']['queries'][0]
        for data in [[],[0x34,0x12],[0x34,0x12,1,0],[0x35,0x12,1],[0x34,0x12,127],[0x34,0x12,True],[0x34,0x12,256]]:
            row = copy.deepcopy(query['command']); value = dict(query['observation'],data=data)
            row['stdout']='NativeLinkMeasurement: '+json.dumps(value)+'\n'
            with self.subTest(data=data),self.assertRaises(ValueError):observation(row,entry,1)

    def test_duplicate_json_extra_output_wrong_caller_and_failures_rejected(self):
        entry, _ = fixture(); source=entry['link_measurements']['queries'][0]['command']
        for case in ['duplicate','extra','wrong-command','stderr','exit','oversize']:
            row=copy.deepcopy(source)
            if case=='duplicate':row['stdout']=row['stdout'].replace('{','{"kind":2,',1)
            elif case=='extra':row['stdout']+='extra\n'
            elif case=='wrong-command':row['args'][3]='query'
            elif case=='stderr':row['stderr']='failed'
            elif case=='exit':row['exit']=1
            else:row['stdout']='NativeLinkMeasurement: '+(' '*4096)+'\n'
            with self.subTest(case=case),self.assertRaises(ValueError):observation(row,entry,1)

    def test_missing_complete_wrong_wire_and_fabricated_cache_fail(self):
        for case in ['missing-complete','wrong-opcode','wrong-params','wrong-reply','cache-changed']:
            entry,capture=fixture()
            if case=='missing-complete':capture['complete'].pop(0)
            elif case=='wrong-opcode':capture['commands'][0]['opcode']=0x0406
            elif case=='wrong-params':capture['commands'][0]['params']='3512'
            elif case=='wrong-reply':capture['complete'][0]['value']='34127f'
            else:entry['link_measurements']['queries'][0]['observation']['request_id']=999
            with self.subTest(case=case),self.assertRaises(ValueError):corroborate_entry(entry,capture)

    def test_explicit_request_and_complete_command_accounting(self):
        entry,capture=fixture()
        self.assertIsNone(corroborate({},capture,False))
        run=dict(connection_control=dict(phases=[dict(typed_objects=[entry])]),link_measurement_commands=[])
        for requested in [False,True]:
            with self.subTest(requested=requested),self.assertRaises(ValueError):corroborate(run,capture,requested)
        with self.assertRaises(ValueError):corroborate({},capture,1)

    def test_two_roles_two_owners_and_original_global_command_order(self):
        entries=[];capture=dict(commands=[],complete=[])
        for index in range(4):
            entry,raw=fixture(index);entries.append(entry)
            for key in capture:capture[key].extend(raw[key])
        run=dict(application_identity=dict(uids=[1000]*4,cap_eff='0',cap_prm='0',cap_amb='0'),
            connection_control=dict(phases=[dict(typed_objects=entries[:2]),dict(typed_objects=entries[2:])]),
            link_measurement_commands=[q['command']for e in entries for q in e['link_measurements']['queries']],
            link_measurement_attempts=[dict(owner=e['owner'],object=e['object'],record=e['link_measurements'])for e in entries])
        self.assertEqual(len(corroborate(run,capture,True)),4)
        for case in ['missing-command','command-order','root','capability','same-controller','reused-author']:
            broken=copy.deepcopy(run)
            if case=='missing-command':broken['link_measurement_commands'].pop()
            elif case=='command-order':broken['link_measurement_commands'].reverse()
            elif case=='root':broken['application_identity']['uids']=[0]*4
            elif case=='capability':broken['application_identity']['cap_eff']='1'
            elif case=='same-controller':broken['connection_control']['phases'][1]['typed_objects'][0]['owner']['generation']=99
            else:
                query=broken['connection_control']['phases'][1]['typed_objects'][0]['link_measurements']['queries'][0]
                value=query['observation'];value['request_id']=1
                query['command']['stdout']='NativeLinkMeasurement: '+json.dumps(value)+'\n'
            with self.subTest(case=case),self.assertRaises(ValueError):corroborate(broken,capture,True)


    def test_final_gate_requires_explicit_boot_scope_and_complete_proof(self):
        self.assertTrue(exit_gate({}))
        record=dict(link_measurements_requested=True,link_measurement_acceptance=True,
            link_measurement_verifier=dict(sha256='a'*64),qemu_args=['qemu','-append','console=ttyS0 '+TOKEN],
            link_measurement_corroboration=[dict(status='FINITE_REAL_LINK_OBSERVATIONS',queries=[dict(kind=1),dict(kind=2)])for _ in range(4)])
        self.assertTrue(exit_gate(record)) # Metadata only;raw oracles tested separately.
        for case in ['unrequested','no-boot','duplicate-boot','missing-proof','missing-kind','no-acceptance','no-pin']:
            bad=copy.deepcopy(record)
            if case=='unrequested':bad['link_measurements_requested']=False
            elif case=='no-boot':bad['qemu_args']=[]
            elif case=='duplicate-boot':bad['qemu_args'][-1]+=' '+TOKEN
            elif case=='missing-proof':bad['link_measurement_corroboration'].pop()
            elif case=='missing-kind':bad['link_measurement_corroboration'][0]['queries'].pop()
            elif case=='no-acceptance':bad['link_measurement_acceptance']=False
            else:bad['link_measurement_verifier']['sha256']='old'
            with self.subTest(case=case):self.assertFalse(exit_gate(bad))


if __name__ == '__main__':
    unittest.main()
