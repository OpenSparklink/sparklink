# SPDX-License-Identifier: GPL-2.0-only
"""Host trace parser fixtures only: no controller, scheduling or RF qualification."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_host_usb import request_ledger, read_requests, completion_candidates, original_mapping, observe_failed, terminal_observations


def event(micros, name, tail):
    return f'7@1790000000.{micros:06d}:usb_host_req_{name} dev 1:18, packet 0x42{tail}'


def pair():
    return [event(1, 'data', ', in 0, ep 1, size 128'),
            event(3, 'complete', ', status 0, length 128')]


class HostUSB(unittest.TestCase):
    def test_no_work_error_requires_explicit_mode_and_never_invents_fault_or_interval(self):
        row=dict(owners=[{},{}],events=[dict(kind='start',before_wall_ns=1000)])
        reports=[dict(channel_identity=dict(controller=i,generation=7+i,lifetime=3,handle=0))for i in (0,1)]
        mapping=[dict(guest=(1,2+i))for i in (0,1)]
        capture=dict(commands=[],native_events=[dict(bus=1,device=2+i,event=5,record=10+i,wall_ns=3000+i,params='00000007')for i in (0,1)])
        parsed=dict(rows=[],offset_ns=[100,200],quantum_ns=1)
        with self.assertRaisesRegex(CaptureError,'no software fault'):
            terminal_observations(row,reports,capture,mapping,parsed)
        first,downs,commands=terminal_observations(row,reports,capture,mapping,parsed,observe_without_work_error=True)
        self.assertIsNone(first);self.assertEqual(commands,[])
        self.assertTrue(all(d['after_first_software_fault_lower_ns']is None and d['after_first_software_fault_upper_ns']is None for d in downs))
        for case in ('missing-down','wrong-handle','duplicate-down','bad-mode','old-lifetime-error'):
            import copy
            c,p=copy.deepcopy(capture),copy.deepcopy(parsed);enabled=True
            if case=='missing-down':c['native_events'].pop()
            elif case=='wrong-handle':c['native_events'][0]['params']='00010007'
            elif case=='duplicate-down':c['native_events'].append(copy.deepcopy(c['native_events'][0]))
            elif case=='bad-mode':enabled=1
            else:
                p['rows']=[dict(event='work',stage=1,error=-110,ctl=0,gen=7,life=1,mono_ns=500)]
                # An earlier physical lifetime cannot supply the missing fault.
                self.assertIsNone(terminal_observations(row,reports,c,mapping,p,observe_without_work_error=True)[0])
                with self.assertRaises(CaptureError):terminal_observations(row,reports,c,mapping,p)
                continue
            with self.subTest(case=case),self.assertRaises(CaptureError):
                terminal_observations(row,reports,c,mapping,p,observe_without_work_error=enabled)

    def test_opt_in_mode_cannot_hide_existing_matching_work_error(self):
        row=dict(owners=[{},{}],events=[dict(kind='start',before_wall_ns=1000)])
        reports=[dict(channel_identity=dict(controller=i,generation=7+i,lifetime=3,handle=0))for i in (0,1)]
        mapping=[dict(guest=(1,2+i))for i in (0,1)]
        capture=dict(commands=[],native_events=[dict(bus=1,device=2+i,event=5,record=10+i,wall_ns=3000+i,params='00000007')for i in (0,1)])
        error=dict(event='work',stage=1,error=-110,ctl=0,gen=7,life=3,service=2,mono_ns=500)
        parsed=dict(rows=[error],offset_ns=[100,200],quantum_ns=1)
        original=terminal_observations(row,reports,capture,mapping,parsed)
        explicit=terminal_observations(row,reports,capture,mapping,parsed,observe_without_work_error=True)
        self.assertEqual(original,explicit);self.assertEqual(original[0],error)
        self.assertEqual(original[1][0]['after_first_software_fault_lower_ns'],2299)
        self.assertEqual(original[1][0]['after_first_software_fault_upper_ns'],2401)

    def test_host_analysis_is_explicit_and_hash_failure_precedes_association(self):
        from ws73_session_service import analyze_failed_benchmark
        with self.assertRaisesRegex(ValueError,'explicit failed application'):
            analyze_failed_benchmark('/never-opened-host-fixture',0,host_usb=True)
        for options in (dict(observe_without_work_error=True),dict(observe_without_work_error=1,host_usb=True,application_progress=True)):
            with self.assertRaisesRegex(ValueError,'explicit failed host USB'):
                analyze_failed_benchmark('/never-opened-host-fixture',0,**options)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for n,text in [('usb-lifecycle.log','\n'.join(pair())),('usb-lifecycle.events','usb_host_req_data'),('qmp.jsonl','{}')]:
                (root/n).write_text(text)
            manifest=dict(host_lifecycle_files=[dict(path='usb-lifecycle.log',sha256='0'*64)])
            with self.assertRaisesRegex(CaptureError,'material hash'):
                observe_failed(root,manifest,{},[],{}, {},{}, {})

    def test_exact_integer_interval_above_float_precision(self):
        proof = request_ledger(pair(), [(1, 18)])
        self.assertEqual(proof['closed'][0]['interval_ns'], 2000)
        self.assertEqual(proof['closed'][0]['submit_wall_ns'], 1790000000000001000)

    def test_cancellation_emulation_and_reused_pointer_are_different(self):
        lines = [event(1, 'data', ', in 1, ep 3, size 8'), event(2, 'canceled', ''),
                 event(3, 'control', ', req 0x5, value 1, index 0'),
                 event(4, 'emulated', ', status 0'),
                 event(5, 'data', ', in 0, ep 1, size 128'),
                 event(6, 'complete', ', status -1, length 0')]
        rows = request_ledger(lines, [(1, 18)])['closed']
        self.assertEqual([r['terminal'] for r in rows], ['canceled', 'emulated', 'complete'])
        self.assertEqual(rows[-1]['status'], -1)

    def test_missing_duplicate_wrong_owner_time_and_length_rejected(self):
        for case in ['no-submit', 'no-complete', 'duplicate-submit', 'duplicate-complete',
                     'wrong-owner', 'too-long', 'backwards', 'unknown', 'malformed', 'emulated-data']:
            lines = pair()
            if case == 'no-submit': lines.pop(0)
            elif case == 'no-complete': lines.pop()
            elif case == 'duplicate-submit': lines.insert(0, lines[0])
            elif case == 'duplicate-complete': lines.append(lines[-1])
            elif case == 'wrong-owner': lines[-1] = lines[-1].replace('1:18', '1:19')
            elif case == 'too-long': lines[-1] = lines[-1].replace('length 128', 'length 129')
            elif case == 'backwards': lines[-1] = lines[-1].replace('.000003', '.000000')
            elif case == 'unknown': lines[0] = lines[0].replace('req_data', 'req_unknown')
            elif case == 'malformed': lines[-1] = lines[-1][:-3]
            else: lines[-1] = event(3, 'emulated', ', status 0')
            with self.subTest(case=case), self.assertRaises(CaptureError):
                request_ledger(lines, [(1, 18)])

    def test_short_and_zero_completion_stay_observed_not_delivery(self):
        for size in [0, 64]:
            rows = request_ledger([pair()[0], event(3, 'complete', f', status 0, length {size}')],
                                  [(1, 18)])['closed']
            self.assertEqual(rows[0]['length'], size)
            self.assertNotIn('delivered', rows[0])

    def test_control_and_endpoint_bounds_and_release_identity(self):
        for lines in [[event(1, 'data', ', in 0, ep 0, size 128')],
                      [event(1, 'data', ', in 0, ep 1, size 1048577')],
                      [event(1, 'control', ', req 0x5, value 65536, index 0')],
                      pair() + ['7@1790000000.000004:usb_host_release_interface dev 1:19, if 0']]:
            with self.assertRaises(CaptureError): request_ledger(lines, [(1, 18)])

    def test_explicit_owner_and_nonempty_closed_trace(self):
        for devices in [[], [(1, 18), (1, 18)], [(True, 18)], [[1, 18]]]:
            with self.assertRaises(CaptureError): request_ledger(pair(), devices)
        with self.assertRaises(CaptureError): request_ledger([], [(1, 18)])

    def test_input_and_state_budgets(self):
        with patch('ws73_host_usb.MAX_LINES', 1), self.assertRaises(CaptureError):
            request_ledger(pair(), [(1, 18)])
        with patch('ws73_host_usb.MAX_REQUESTS', 0), self.assertRaises(CaptureError):
            request_ledger(pair(), [(1, 18)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.log'
            path.write_text('\n'.join(pair()) + '\n')
            self.assertEqual(len(read_requests(path, [(1, 18)])['closed']), 1)
            with patch('ws73_host_usb.MAX_BYTES', 1), self.assertRaises(CaptureError):
                read_requests(path, [(1, 18)])
            path.write_bytes(b'\xff\xff')
            with self.assertRaises(CaptureError): read_requests(path, [(1, 18)])

    def test_candidate_requires_unique_full_ordered_sequence_not_nearest_time(self):
        source = []
        for i, size in enumerate([7, 4, 5, 6]):
            source.extend([event(i*10+1,'data',', in 1, ep 1, size 128'),
                           event(i*10+3,'complete',f', status 0, length {size}')])
        parsed = request_ledger(source,[(1,18)])
        bulk = [dict(bus=1,device=2,endpoint=129,kind='C',status=0,length=n,record=i+100)
                for i,n in enumerate([4,5,6])]
        out = completion_candidates(parsed,bulk,(1,18),(1,2),1)
        self.assertEqual([r['length'] for r in out.values()],[4,5,6])
        for case in ['absent','ambiguous','wrong-order','parallel','wrong-owner','empty']:
            import copy
            old, points = copy.deepcopy(parsed),copy.deepcopy(bulk)
            if case=='absent':points[1]['length']=8
            elif case=='ambiguous':old['closed']+=copy.deepcopy(old['closed'][1:])
            elif case=='wrong-order':points[1]['record']=99
            elif case=='parallel':old['closed'][1]['submit_wall_ns']=old['closed'][0]['terminal_wall_ns']-1
            elif case=='wrong-owner':points[1]['device']=3
            else:points=[]
            # Arrange a second, nonoverlapping candidate rather than failing an incidental time guard.
            if case=='ambiguous':
                for i,r in enumerate(old['closed']):r.update(submit_wall_ns=i*10,terminal_wall_ns=i*10+1)
            with self.subTest(case=case),self.assertRaises(CaptureError):
                completion_candidates(old,points,(1,18),(1,2),1)

    def test_mapping_uses_original_explicit_ports_and_refuses_boundaries(self):
        import copy
        ports=['1-1.1.1','1-1.1.2']
        manifest=dict(qmp_guest_hotplug=True,physical_resource_allocation=dict(selected_ports=ports),
                      inventory_before={p:dict(path=p,bus=1,address=18+i)for i,p in enumerate(ports)})
        owners=[dict(owner=dict(port=f'1-{i+1}',bus=1,device=2+i,index=i,generation=8+i))for i in range(2)]
        messages=[dict(execute='device_add',arguments=dict(driver='usb-host',port=str(i+1),hostbus=1,
            hostport=p[2:],**{'guest-reset':False,'guest-resets-all':False,'kernel-driver-detach':False,'host-reset':False}))for i,p in enumerate(ports)]
        self.assertEqual(original_mapping(manifest,messages,owners)[0]['host'],(1,18))
        exchanged = original_mapping(manifest,messages,list(reversed(owners)))
        self.assertEqual([r['host'] for r in exchanged], [(1,19),(1,18)])
        self.assertEqual([r['guest'] for r in exchanged], [(1,3),(1,2)])
        self.assertEqual([r['controller'] for r in exchanged], [1,0])
        self.assertEqual([r['generation'] for r in exchanged], [9,8])
        self.assertEqual(original_mapping(manifest,list(reversed(messages)),owners)[0]['host'],(1,18))
        for case in ['foreign-port','old-default','duplicate-guest-port','duplicate-owner','duplicate-host','reset','detach','test','extra-owner','mutation','inventory']:
            m,ms,os=copy.deepcopy(manifest),copy.deepcopy(messages),copy.deepcopy(owners)
            if case=='foreign-port':ms[0]['arguments']['hostport']='1.1.3'
            elif case=='old-default':ms[0]['arguments']['hostport']='2.1.2'
            elif case=='duplicate-guest-port':ms[1]['arguments']['port']='1'
            elif case=='duplicate-owner':os[1]=copy.deepcopy(os[0])
            elif case=='duplicate-host':ms[1]['arguments']['hostport']=ports[0][2:]
            elif case=='reset':ms[0]['arguments']['host-reset']=True
            elif case=='detach':ms[0]['arguments']['kernel-driver-detach']=True
            elif case=='test':ms[0]['arguments']['test-runtime-in-held']=False
            elif case=='extra-owner':os.append(copy.deepcopy(os[0]))
            elif case=='mutation':ms.append(dict(execute='system_reset'))
            else:m['inventory_before'][ports[0]]['bus']=2
            with self.subTest(case=case),self.assertRaises(CaptureError):original_mapping(m,ms,os)


if __name__ == '__main__':
    unittest.main()
