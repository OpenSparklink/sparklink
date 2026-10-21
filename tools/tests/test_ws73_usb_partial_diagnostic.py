# SPDX-License-Identifier: GPL-2.0-only
"""Visible metadata/selector fixtures only; no USB/kernel/drain proof."""
from pathlib import Path
import copy,hashlib,sys,tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_usb_partial_diagnostic as diag
import ws73_qemu_rx_terminal_observer as observer
import ws73_usb_lifecycle as life
from ws73_capture import CaptureError
from test_ws73_qemu_event_observer import sample,log
from test_ws73_qemu_poll_observer import poll


def terminal(actual=0,status=3,**changes):
    row=dict(bus=1,device=18,ordinal=1,request=12,packet='0xabc',allocation_ns=100,
        callback_ns=3_100_000_000,wall_ns=10_000_000_000,requested=20480,actual=actual,
        status=status,live=0,bounded=1,sha256=hashlib.sha256(b'').hexdigest()if not actual else'a'*64)
    row.update(changes)
    return 'qemu: '+diag.RX_END+' '.join(f'{k}={v}'for k,v in row.items())+'\n'


def record():
    return dict(attempted=True,action_acknowledged=True,host=dict(bus=1,address=18),
        pending_request=dict(packet='0xabc',size=20480),candidate=dict(native=[dict(bus=1,device=18,mono_ns=3_000_000_000)]),
        before_monotonic_ns=3_050_000_000,after_monotonic_ns=3_150_000_000)


def app_prefix():
    nonce=bytes(range(16));seq=9
    raw=b'SLKSOCK1'+nonce+seq.to_bytes(4,'little')+b'\0'
    raw+=bytes(nonce[j%16]^((seq+j)&255)for j in range(249-29))
    return bytes.fromhex('8000fb07f1')+raw


class PartialDiagnostic(unittest.TestCase):
    def test_default_closed_contract_unchanged_live_prefix_is_explicit(self):
        text=''
        for i in(1,2):text+=log(sample(i))+poll(sample(i))
        with self.assertRaises(CaptureError):life.parse_native_poll(text,{(1,18)})
        live=life.parse_live_native_poll(text,{(1,18)})
        self.assertEqual(live['status'],'LIVE_LIBUSB_POLL_PREFIX_NOT_QUALIFIED')
        self.assertFalse(live['physical_drain_qualified'])
        with self.assertRaises(CaptureError):life.parse_live_native_poll(text.rsplit('qemu:',1)[0],{(1,18)})

    def test_native_terminal_zero_partial_and_failures_are_not_delivery(self):
        for count in(0,512,20480):
            with self.subTest(count=count):
                r=record();diag.finalize(r,terminal(count),{(1,18)})
                self.assertTrue(r['complete']);self.assertEqual(r['reported_partial_bytes'],count)
                self.assertFalse(r['original_gate_qualified']);self.assertFalse(r['natural_recovery_acceptance'])
        r=dict(attempted=False);diag.finalize(r,'',{(1,18)})
        self.assertFalse(r['complete']);self.assertEqual(r['status'],'DIAGNOSTIC_NOT_EXECUTED')

    def test_terminal_identity_status_clock_duplicate_budget_and_hash_fail(self):
        for text in(terminal(status=0),terminal(status=7),terminal(live=1),terminal(device=19),
                    terminal(requested=0),terminal(actual=20481),terminal(sha256='0'*64),
                    terminal(callback_ns=99),terminal(bounded=0),terminal()+terminal(),
                    terminal()[:-1],terminal()+'WS73_USB_RX_END_BUDGET_V1 count=129\n'):
            with self.subTest(text=text[:80]),self.assertRaises(CaptureError):diag.finalize(record(),text,{(1,18)})
        for changes in(dict(status=2),dict(packet='0xdef'),dict(allocation_ns=3_060_000_000),dict(callback_ns=6_000_000_000)):
            with self.subTest(changes=changes),self.assertRaises(CaptureError):diag.finalize(record(),terminal(**changes),{(1,18)})
        with self.assertRaises(CaptureError):diag.rx_ends(terminal(),{(True,18)})

    def test_unfinished_real_application_prefix_maps_guest_slot_not_role_order(self):
        request=dict(start_wall_ns=1,owners=[dict(owner=dict(port='1-2',bus=1,device=3),object=dict(handle=0)),
                                         dict(owner=dict(port='1-1',bus=1,device=2),object=dict(handle=0))])
        p=dict(direction='out',bus=1,device=3,handle=0,wall_ns=2,record=10,boundary=1,data=app_prefix().hex())
        result=diag.unfinished_application_prefix(dict(acb_packets=[p]),request,0)
        self.assertEqual(result['source']['port'],'1-2');self.assertEqual(result['known_prefix_bytes'],249)
        self.assertFalse(result['whole_PDU_qualified'])
        self.assertIsNone(diag.unfinished_application_prefix(dict(acb_packets=[p]),request,1))
        for changed in(p|dict(boundary=0),p|dict(data=('00'+p['data'][2:])),p|dict(wall_ns=0),p|dict(direction='in')):
            # Changing TCID alone is an opaque selector input, not an authority
            # check. Other tests cover wire/frame fields and finalized PB.
            if changed['data']!=p['data']:continue
            self.assertIsNone(diag.unfinished_application_prefix(dict(acb_packets=[changed]),request,0))
        complete=p|dict(boundary=3,record=11)
        self.assertIsNone(diag.unfinished_application_prefix(dict(acb_packets=[p,complete]),request,0))
        bad=p|dict(data=p['data'][:10]+'00'+p['data'][12:])
        self.assertIsNone(diag.unfinished_application_prefix(dict(acb_packets=[bad]),request,0))

    def test_unique_peer_selection_is_confined_to_original_pair(self):
        request=dict(start_wall_ns=1,owners=[dict(owner=dict(port='1-2',bus=1,device=3),object=dict(handle=0)),
                                         dict(owner=dict(port='1-1',bus=1,device=2),object=dict(handle=0))])
        p=dict(direction='out',bus=1,device=3,handle=0,wall_ns=2,record=10,boundary=1,data=app_prefix().hex())
        reverse=p|dict(device=2,record=11)
        for packet,slot in((p,0),(reverse,1)):
            selection=diag.select_target(dict(acb_packets=[packet]),request,diag.PEER_OF_UNFINISHED)
            self.assertEqual(selection[0],slot)
            self.assertFalse(selection[1]['whole_PDU_qualified'])
        for packets in([], [p,reverse], [p|dict(boundary=3)], [p|dict(device=9)]):
            self.assertIsNone(diag.select_target(dict(acb_packets=packets),request,diag.PEER_OF_UNFINISHED))
        for value in(None,True,False,2,'auto','0'):
            with self.subTest(value=value),self.assertRaises(CaptureError):
                diag.select_target(dict(acb_packets=[p]),request,value)
        self.assertIsNone(diag.select_target(dict(acb_packets=[p]),request,1))

    def test_cli_target_is_typed_and_has_no_discovery_fallback(self):
        for raw,value in(('0',0),('1',1),(diag.PEER_OF_UNFINISHED,diag.PEER_OF_UNFINISHED)):
            self.assertEqual(diag.target_value(raw),value)
        for bad in('auto','2','-1','all','0,1','',True,None):
            with self.subTest(bad=bad),self.assertRaises(ValueError):diag.target_value(bad)

    def test_fresh_two_second_two_device_quiet_is_required_not_a_grant(self):
        proof=dict(native=dict(devices=[]),poll_devices=[])
        for bus,dev in((1,18),(1,19)):
            row=sample(1,device=dev,mono_ns=3_000_000_000,last_rx1_ns=500_000_000)
            proof['native']['devices'].append(dict(bus=bus,device=dev,samples=[row]))
            proof['poll_devices'].append(dict(bus=bus,device=dev,samples=[dict(result=0)]))
        self.assertIsNotNone(diag.eligibility(proof,{(1,18),(1,19)},3_000_100_000))
        for key,value in(('pending_rx1',0),('pending_dead',1),('last_rx1_ns',2_000_000_000),('phase','closing')):
            p=copy.deepcopy(proof);p['native']['devices'][1]['samples'][0][key]=value
            self.assertIsNone(diag.eligibility(p,{(1,18),(1,19)},3_000_100_000))
        self.assertIsNone(diag.eligibility(proof,{(1,18),(1,19)},4_000_000_000))

    def test_diagnostic_always_refuses_original_whole_gate(self):
        from ws73_target import run_exit_code
        for value in(True,False,None,1,'yes',{}):
            self.assertEqual(run_exit_code(dict(usb_partial_rx_diagnostic_requested=value)),1)

    def test_explicit_original_profile_and_no_additional_experiments(self):
        args=dict(usb_partial_rx_target=0,command='run',ports=['1-1.1.1','1-1.1.2'],
            qmp_hotplug=True,connection_verify=True,connection_advertising='negotiable-t',
            channel_benchmark='window',channel_benchmark_count=128,channel_benchmark_bytes=2042,
            channel_benchmark_window=8,channel_benchmark_dynamic=True,channel_benchmark_active_endpoint=0,
            channel_benchmark_ssap_owned=True,channel_benchmark_credit_observe=True,
            session_service_observe=True)
        self.assertEqual(diag.requested(SimpleNamespace(**args)),0)
        self.assertEqual(diag.requested(SimpleNamespace(**(args|dict(usb_partial_rx_target=diag.PEER_OF_UNFINISHED)))),diag.PEER_OF_UNFINISHED)
        self.assertIsNone(diag.requested(SimpleNamespace()))
        for change in(dict(usb_partial_rx_target=True),dict(usb_partial_rx_target=2),dict(ports=['1-1.1.1']),
                      dict(command='prepare'),dict(qmp_hotplug=False),dict(connection_verify=False),
                      dict(connection_advertising='fixed-t'),dict(channel_benchmark_count=127),
                      dict(channel_benchmark_ssap_duplex=True),dict(fault_recovery=True),dict(empty_bulk=True),
                      dict(unrecognized_experiment=True)):
            with self.subTest(change=change),self.assertRaises(CaptureError):
                diag.requested(SimpleNamespace(**(args|change)))

    def test_prepared_identity_requires_actual_fixture_and_all_host_tools(self):
        with tempfile.TemporaryDirectory()as folder:
            qemu=Path(folder)/'fixture';qemu.write_bytes(b'explicit unit fixture, not executable QEMU')
            inputs=[dict(path=str(Path(diag.__file__).with_name(name)),
                         sha256=hashlib.sha256(Path(diag.__file__).with_name(name).read_bytes()).hexdigest())
                    for name in ('ws73_target.py','ws73_usb_partial_diagnostic.py','ws73_usb_lifecycle.py')]
            package=dict(native_vm={},qemu=dict(path=str(qemu)),inputs=inputs)
            with self.assertRaises(CaptureError):diag.validate_inputs(package)
            with patch.object(diag,'QEMU_SHA256',hashlib.sha256(qemu.read_bytes()).hexdigest()):
                diag.validate_inputs(package)
                for bad in(package|dict(inputs=inputs[:-1]),package|dict(inputs=inputs+inputs[-1:]),
                           package|dict(inputs=[r|dict(sha256='0'*64)for r in inputs])):
                    with self.subTest(bad=bad),self.assertRaises(CaptureError):diag.validate_inputs(bad)

    def test_rx_terminal_transform_only_adds_metadata_before_dead_branch(self):
        source=b'''    uint64_t                         observe_samples;
    USBPacket                        *p;
    bool                             in;
    s->observe_allocated++;
    QTAILQ_INSERT_TAIL
static void LIBUSB_CALL usb_host_req_complete_data(struct libusb_transfer *xfer);
    s->observe_data_callbacks++;
'''
        with self.assertRaises(ValueError):observer.transform(source)
        with patch.object(observer,'BASE_SHA256',hashlib.sha256(source).hexdigest()):out=observer.transform(source).decode()
        for op in('libusb_cancel_transfer(', 'libusb_submit_transfer(', 'usb_packet_copy(', 'usb_packet_complete('):self.assertNotIn(op,out)
        self.assertIn('s->observe_rx_ends > 128',out);self.assertIn('xfer->actual_length <= xfer->length',out)
