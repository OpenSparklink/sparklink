# SPDX-License-Identifier: GPL-2.0-only
"""Visible source/metadata fixtures only; not libusb, BQL or hardware proof."""
from pathlib import Path
import hashlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_qemu_event_observer as observer
import ws73_usb_lifecycle as life
from ws73_capture import CaptureError


def sample(index,phase='tick',**changes):
    row={k:0 for k in life.NATIVE_KEYS}
    row.update(bus=1,device=18,sample=index,phase=phase,mono_ns=index*100000000,
               wall_ns=1000000000+index*100000000,allocated=3,freed=1,pending=2,
               pending_rx1=1,pending_int3=1,data_cb=1,rx1_cb=1,rx1_bytes=178,
               last_cb_ns=10000,last_rx1_ns=10000,pump_calls=index,pump_returns=index,
               pump_begin_ns=index*100000000-20000,pump_end_ns=index*100000000-10000,
               pump_max_ns=10000)
    row.update(changes)
    return row


def log(*rows):
    return ''.join('qemu: '+life.NATIVE_MARKER+' '.join(f'{k}={v}'for k,v in r.items())+'\n'for r in rows)


def source_fixture():
    # Deliberately non-compilable source anchors. Only the declared digest is
    # substituted; the real complete pinned source has a separate build gate.
    return ('''    /* request queues */
static uint32_t loglevel;
    QTAILQ_INSERT_TAIL(&s->requests, r, next);
    QTAILQ_REMOVE(&r->host->requests, r, next);
static USBHostRequest *usb_host_req_find(
    trace_usb_host_open_success(bus_num, addr);
    trace_usb_host_close(s->bus_num, s->addr);
    usb_host_abort_xfers(s);
    usb_host_iso_free_all(s);
    if (s->dh) {
        usb_host_abort_xfers(s);
    if (s->test_enum_reset_once && !usb_host_enum_reset_mode_valid(s)) {
''' + '\n'.join('libusb_handle_events_timeout(ctx, &tv);'for _ in range(3)) + '\n' +
        '\n'.join(f'''static void LIBUSB_CALL usb_host_req_complete_{name}(struct libusb_transfer *xfer)
{{
    if (r->p == NULL) {{
    goto out;
}}
'''for name in('ctrl','data'))).encode()


class QemuEventObserver(unittest.TestCase):
    def test_source_digest_rejection_and_exclusive_observer_transform(self):
        source=source_fixture()
        with self.assertRaises(ValueError):observer.transform(source)
        with patch.object(observer,'BASE_SHA256',hashlib.sha256(source).hexdigest()):
            actual=observer.transform(source).decode()
        self.assertEqual(actual.count('ret = libusb_handle_events_timeout(ctx, tv);'),1)
        self.assertEqual(actual.count('usb_host_observed_events(&tv);'),3)
        self.assertEqual(actual.count('    s->observe_dead_callbacks += r->p == NULL;'),2)
        self.assertIn('s->observe_samples < 4096',actual)
        self.assertIn('pending > 128',actual)
        self.assertIn('observer fixture requires explicit WS73 leaf',actual)
        for name in('ctrl','data'):
            body=actual[actual.index(f'usb_host_req_complete_{name}(struct libusb_transfer *xfer)\n{{'):]
            self.assertLess(body.index('observe_dead_callbacks'),body.index('if (r->p == NULL)'))

    def test_changed_or_duplicate_source_anchor_rejected(self):
        for source in(source_fixture().replace(b'    /* request queues */',b'changed'),
                      source_fixture()+b'\n    trace_usb_host_close(s->bus_num, s->addr);',
                      source_fixture().replace(b'libusb_handle_events_timeout(ctx, &tv);',b'changed',1)):
            with patch.object(observer,'BASE_SHA256',hashlib.sha256(source).hexdigest()),self.assertRaises(ValueError):
                observer.transform(source)

    def test_native_callback_and_logical_cancel_are_separate_observations(self):
        rows=[sample(1),sample(2,'closing',data_cb=2,dead_cb=1,freed=2,pending=1,pending_int3=0),
              sample(3,'drained',data_cb=3,dead_cb=2,freed=3,pending=0,pending_rx1=0,pending_int3=0)]
        result=life.parse_native(log(*rows),{(1,18)})
        self.assertEqual(len(result['devices'][0]['samples']),3)
        self.assertFalse(result['physical_drain_qualified'])
        self.assertFalse(result['performance_qualified'])
        self.assertFalse(result['credit_truth_qualified'])

    def test_missing_duplicate_late_and_wrong_owner_fail_closed(self):
        a,b,c=sample(1),sample(2,'closing'),sample(3,'drained')
        for text in(log(a,b),log(a,c),log(a,b,c,c),log(a,b,c,sample(4)),
                    log(a,b,c).replace('bus=1','bus=2'),log(a,b,c)[:-1],
                    log(a,b,c).replace('pending=2','pending=2 pending=2',1),
                    log(a,b,c).replace('data_cb=1','data_cb=0',1),
                    log(a,b,c).replace(' wall_ns=1100000000','',1),
                    log(a,b,c)+'WS73_TEST_RUNTIME_HOLD: forbidden\n'):
            with self.subTest(text=text[:80]),self.assertRaises(CaptureError):life.parse_native(text,{(1,18)})

    def test_counter_clock_endpoint_and_budget_regressions_fail(self):
        for changes in(dict(allocated=0),dict(freed=4),dict(pending_dead=3),dict(pending_tx1=1),
                       dict(ctrl_cb=3),dict(dead_cb=3),dict(pump_returns=4),dict(pump_errors=4),
                       dict(mono_ns=999),dict(wall_ns=1),dict(rx1_bytes=1),dict(overflow=1),
                       dict(phase='budget'),dict(sample=4099),dict(last_cb_ns=2**64),dict(freed=-1)):
            with self.subTest(changes=changes),self.assertRaises(CaptureError):
                life.parse_native(log(sample(1),sample(2,'closing')|changes,sample(3,'drained')),{(1,18)})
        for key,value in(('BYTE_LIMIT',1),('LINE_LIMIT',1),('REPORT_LIMIT',1)):
            with self.subTest(key=key),patch.object(life,key,value),self.assertRaises(CaptureError):
                life.parse_native(log(sample(1),sample(2,'closing'),sample(3,'drained')),{(1,18)})

    def test_two_devices_require_complete_independent_samples(self):
        a=log(sample(1),sample(2,'closing'),sample(3,'drained'))
        with self.assertRaises(CaptureError):life.parse_native(a,{(1,18),(1,19)})
        result=life.parse_native(a+a.replace('device=18','device=19'),{(1,18),(1,19)})
        self.assertEqual(len(result['devices']),2)
