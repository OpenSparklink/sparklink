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


def request_source_fixture():
    return ('''    USBPacket                        *p;
static USBHostRequest *usb_host_req_alloc(
    QTAILQ_INSERT_TAIL(&s->requests, r, next);
    QTAILQ_REMOVE(&r->host->requests, r, next);
    if (s->test_enum_reset_once && !usb_host_enum_reset_mode_valid(s)) {
''' + '\n'.join('    rc = libusb_submit_transfer(r->xfer);' for _ in range(2)) + '\n' +
        '\n'.join('            libusb_cancel_transfer(r->xfer);' for _ in range(2)) + '\n' +
        '\n'.join(f'''static void LIBUSB_CALL usb_host_req_complete_{name}(struct libusb_transfer *xfer)
{{
    if (r->p == NULL) {{
    goto out;
}}
''' for name in ('ctrl', 'data'))).encode()


def request_rows(*phases, ident=1, start=1, **changes):
    result=[]
    for index, phase in enumerate(phases, start):
        row=dict(ordinal=index,id=ident,bus=1,device=18,ep=1,phase=phase,
                 mono_ns=index*1000,live=int(phase not in ('cancel','callback','free')),
                 result=0,requested=0 if phase=='alloc' else 36,actual=-1,status=-1)
        if phase=='callback': row.update(actual=0,status=3)
        row.update(changes);result.append(row)
    return result


def request_log(rows):
    return ''.join('qemu: '+life.REQUEST_MARKER+' '.join(f'{k}={v}' for k,v in r.items())+'\n' for r in rows)


class QemuRequestObserver(unittest.TestCase):
    def test_transform_is_pinned_and_observes_both_cancel_and_callback_sites(self):
        source=request_source_fixture()
        with self.assertRaises(ValueError): observer.transform_requests(source)
        with patch.object(observer,'REQUEST_BASE_SHA256',hashlib.sha256(source).hexdigest()):
            actual=observer.transform_requests(source).decode()
        self.assertEqual(actual.count('int cancel_rc = libusb_cancel_transfer(r->xfer);'),2)
        self.assertEqual(actual.count('usb_host_observe_request(r, "submit", rc);'),2)
        self.assertIn('observe_request_events >= 4096',actual)
        self.assertNotIn('timer_new',actual)
        self.assertNotIn('usb_packet_copy',actual)
        for name in ('ctrl','data'):
            body=actual[actual.index(f'usb_host_req_complete_{name}(struct libusb_transfer *xfer)\n{{'):]
            self.assertLess(body.index('usb_host_observe_request(r, "callback", 0);'),body.index('if (r->p == NULL)'))
        self.assertLess(actual.index('usb_host_observe_request(r, "free", 0);'),
                        actual.index('QTAILQ_REMOVE(&r->host->requests'))
        for old in (b'    USBPacket                        *p;',b'    rc = libusb_submit_transfer(r->xfer);',
                    b'            libusb_cancel_transfer(r->xfer);'):
            changed=source.replace(old,b'changed',1)
            with patch.object(observer,'REQUEST_BASE_SHA256',hashlib.sha256(changed).hexdigest()),self.assertRaises(ValueError):
                observer.transform_requests(changed)

    def test_cancel_is_not_completion_and_late_callback_is_retained(self):
        rows=request_rows('alloc','submit','cancel')
        result=life.parse_requests(request_log(rows),{(1,18)})
        self.assertEqual(result['pending_callbacks'],[1])
        self.assertEqual(result['pending'],[1])
        rows+=request_rows('callback','free',start=4)
        result=life.parse_requests(request_log(rows),{(1,18)})
        self.assertEqual(result['pending_callbacks'],[])
        self.assertEqual(result['detached_callbacks'],[1])
        self.assertEqual(result['pending'],[])
        for field in ('physical_drain_qualified','recovery_qualified','business_delivery_qualified'):
            self.assertFalse(result[field])

    def test_submit_error_is_visible_and_not_consumption_or_refund(self):
        rows=request_rows('alloc','submit');rows[1]['result']=-4
        result=life.parse_requests(request_log(rows),{(1,18)})
        self.assertEqual(result['submit_errors'],[1]);self.assertEqual(result['pending'],[1])
        self.assertEqual(result['pending_callbacks'],[])
        with self.assertRaises(CaptureError):
            life.parse_requests(request_log(rows+request_rows('callback',start=3)),{(1,18)})

    def test_source_identity_budget_injection_and_truncated_metadata_rejected(self):
        good=request_log(request_rows('alloc','submit','cancel','callback','free'))
        for text in (good[:-1],good.replace('bus=1','bus=2'),
                     good.replace('ordinal=3','ordinal=4'),good.replace('phase=cancel','phase=complete'),
                     good.replace('id=1','id=18446744073709551615'),
                     good.replace(' actual=-1',' actual=0',1),good.replace(' result=0',' result=0 result=0',1),
                     good+'WS73_TEST_RUNTIME_HOLD: forbidden\n',good+'WS73_USB_REQUEST_BUDGET_V1 events=4096\n',
                     good.replace('requested=36','requested=37',1),good.replace('phase=free','phase=callback'),
                     good.replace('mono_ns=4000','mono_ns=1'),good.replace('live=0','live=1',1)):
            with self.subTest(text=text),self.assertRaises(CaptureError): life.parse_requests(text,{(1,18)})
        for phases in (('submit',),('alloc','submit','free'),('alloc','callback'),('alloc','submit','callback'),('alloc','submit','cancel','cancel'),('alloc','submit','submit')):
            with self.subTest(phases=phases),self.assertRaises(CaptureError):
                life.parse_requests(request_log(request_rows(*phases)),{(1,18)})

    def test_two_devices_and_reused_address_keep_process_unique_request_id(self):
        rows=request_rows('alloc','submit','cancel','callback','free')
        rows+=request_rows('alloc','submit','callback','free',ident=2,start=6,device=19,live=1)
        rows+=request_rows('alloc','free',ident=3,start=10,requested=0)
        result=life.parse_requests(request_log(rows),{(1,18),(1,19)})
        self.assertEqual(len(result['events']),11)
        self.assertEqual(result['pending'],[])
        rows[-2]['id']=1
        with self.assertRaises(CaptureError):life.parse_requests(request_log(rows),{(1,18),(1,19)})

    def test_actual_logging_helper_under_declared_struct_clock_and_sink_fixtures(self):
        # Compile the exact generated helper, NOT an alternate state machine.
        # Only plain structs, clock and error_report are fixtures; no libusb,
        # QEMU/BQL, kernel callback, cancellation or USB delivery is exercised.
        import subprocess
        import tempfile
        prefix=r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdarg.h>
struct libusb_transfer { int length, actual_length, status; };
typedef struct { uint64_t observe_id; int observe_bus,observe_device,observe_ep;
 void *p; struct libusb_transfer *xfer; } USBHostRequest;
static int64_t g_get_monotonic_time(void) { static int64_t n=1; return n++; }
static void error_report(const char *fmt, ...) {
 va_list a; va_start(a,fmt);vprintf(fmt,a);putchar('\n');va_end(a);
}
'''
        suffix=r'''
int main(void) {
 struct libusb_transfer x={0};USBHostRequest r={1,1,18,1,(void *)1,&x};
 usb_host_observe_request(&r,"alloc",0);
 x.length=36;usb_host_observe_request(&r,"submit",0);
 r.p=NULL;usb_host_observe_request(&r,"cancel",0);
 x.status=3;usb_host_observe_request(&r,"callback",0);
 usb_host_observe_request(&r,"free",0);
 observe_request_events=4095;
 usb_host_observe_request(&r,"free",0);
 usb_host_observe_request(&r,"free",0);
 usb_host_observe_request(&r,"free",0);
 return observe_request_id != 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'helper.c';binary=Path(tmp)/'helper'
            source.write_text(prefix+observer.REQUEST_HELPER+suffix)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True,capture_output=True)
            result=subprocess.run([str(binary)],check=True,capture_output=True,text=True).stdout
        lines=result.splitlines()
        proof=life.parse_requests('\n'.join(lines[:5])+'\n',{(1,18)})
        self.assertEqual(proof['detached_callbacks'],[1])
        self.assertEqual(len(lines),7)
        self.assertEqual(lines[-1],'WS73_USB_REQUEST_BUDGET_V1 events=4096')
        with self.assertRaises(CaptureError):life.parse_requests(result,{(1,18)})
