#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive a separate bounded, metadata-only QEMU/libusb observer fixture.

This is not a driver, a Host, a packet source or a recovery mechanism. The
explicitly selected test binary admits only the existing guarded WS73 USB
configuration. Never replace the original source/binary/prepared image.
"""
import argparse
import hashlib
from pathlib import Path

BASE_SHA256 = 'cc022d1a5f7f1077d766c4671d2c7919a3fe6565ce22085e679df0de09393ff7'

FIELDS = '''    QEMUTimer                       *observe_timer;
    uint64_t                         observe_samples;
    uint64_t                         observe_allocated;
    uint64_t                         observe_freed;
    uint64_t                         observe_data_callbacks;
    uint64_t                         observe_ctrl_callbacks;
    uint64_t                         observe_dead_callbacks;
    uint64_t                         observe_rx1_callbacks;
    uint64_t                         observe_rx1_bytes;
    uint64_t                         observe_tx1_callbacks;
    uint64_t                         observe_int3_callbacks;
    int64_t                          observe_last_callback_ns;
    int64_t                          observe_last_rx1_ns;
'''

PUMP = '''/* Test-only observation, serialized with the original main-loop/BQL path.
 * Counters describe entry/return, not kernel USB readiness or RF progress. */
static uint64_t observe_pump_calls, observe_pump_returns, observe_pump_errors;
static int64_t observe_pump_last_begin_ns, observe_pump_last_end_ns;
static int64_t observe_pump_max_ns;

static int usb_host_observed_events(struct timeval *tv)
{
    int ret;
    int64_t begin = g_get_monotonic_time() * 1000;

    observe_pump_calls++;
    observe_pump_last_begin_ns = begin;
    ret = libusb_handle_events_timeout(ctx, tv);
    observe_pump_last_end_ns = g_get_monotonic_time() * 1000;
    observe_pump_max_ns = MAX(observe_pump_max_ns,
                             observe_pump_last_end_ns - begin);
    observe_pump_returns++;
    observe_pump_errors += ret != 0;
    return ret;
}

'''

OBSERVER = '''/* Finite metadata-only heartbeat. No packet bytes, device I/O, credit,
 * completion, timer/deadline extension, reset or new protocol work. A timer
 * adds a scheduling input: this fixture cannot qualify performance. */
static void usb_host_observe_sample(USBHostDevice *s, const char *phase)
{
    USBHostRequest *r;
    unsigned int pending = 0, rx1 = 0, tx1 = 0, int3 = 0, dead = 0;
    bool overflow = false;

    QTAILQ_FOREACH(r, &s->requests, next) {
        if (++pending > 128) {
            overflow = true;
            break;
        }
        dead += r->p == NULL;
        rx1 += r->xfer->endpoint == 0x81;
        tx1 += r->xfer->endpoint == 0x01;
        int3 += r->xfer->endpoint == 0x83;
    }
    s->observe_samples++;
    error_report("WS73_USB_OBSERVE_V1 bus=%d device=%d sample=%" PRIu64
                 " phase=%s mono_ns=%" PRId64 " wall_ns=%" PRId64
                 " allocated=%" PRIu64 " freed=%" PRIu64
                 " pending=%u pending_rx1=%u pending_tx1=%u pending_int3=%u"
                 " pending_dead=%u overflow=%d data_cb=%" PRIu64
                 " ctrl_cb=%" PRIu64 " dead_cb=%" PRIu64
                 " rx1_cb=%" PRIu64 " rx1_bytes=%" PRIu64
                 " tx1_cb=%" PRIu64 " int3_cb=%" PRIu64
                 " last_cb_ns=%" PRId64 " last_rx1_ns=%" PRId64
                 " pump_calls=%" PRIu64 " pump_returns=%" PRIu64
                 " pump_errors=%" PRIu64 " pump_begin_ns=%" PRId64
                 " pump_end_ns=%" PRId64 " pump_max_ns=%" PRId64,
                 s->bus_num, s->addr, s->observe_samples, phase,
                 (int64_t)g_get_monotonic_time() * 1000,
                 (int64_t)g_get_real_time() * 1000,
                 s->observe_allocated, s->observe_freed, pending, rx1, tx1,
                 int3, dead, overflow, s->observe_data_callbacks,
                 s->observe_ctrl_callbacks, s->observe_dead_callbacks,
                 s->observe_rx1_callbacks, s->observe_rx1_bytes,
                 s->observe_tx1_callbacks, s->observe_int3_callbacks,
                 s->observe_last_callback_ns, s->observe_last_rx1_ns,
                 observe_pump_calls, observe_pump_returns, observe_pump_errors,
                 observe_pump_last_begin_ns, observe_pump_last_end_ns,
                 observe_pump_max_ns);
}

static void usb_host_observe_timer(void *opaque)
{
    USBHostDevice *s = opaque;

    usb_host_observe_sample(s, s->observe_samples < 4095 ? "tick" : "budget");
    if (s->observe_samples < 4096) {
        timer_mod(s->observe_timer,
                  qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + 100);
    }
}

static void usb_host_observe_start(USBHostDevice *s)
{
    s->observe_timer = timer_new_ms(QEMU_CLOCK_REALTIME,
                                    usb_host_observe_timer, s);
    timer_mod(s->observe_timer,
              qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + 100);
}

static void usb_host_observe_stop(USBHostDevice *s)
{
    if (s->observe_timer) {
        timer_del(s->observe_timer);
        timer_free(s->observe_timer);
        s->observe_timer = NULL;
        usb_host_observe_sample(s, "closing");
    }
}

'''


def transform(original):
    if hashlib.sha256(original).hexdigest() != BASE_SHA256:
        raise ValueError('exact complete guarded QEMU baseline required')
    text = original.decode()
    # Instrument only original calls. The wrapper itself is inserted later.
    if text.count('libusb_handle_events_timeout(ctx, &tv);') != 3:
        raise ValueError('exact existing event-pump call sites required')
    text = text.replace('libusb_handle_events_timeout(ctx, &tv);',
                        'usb_host_observed_events(&tv);')
    replacements = [
        ('    /* request queues */', FIELDS + '\n    /* request queues */'),
        ('static uint32_t loglevel;\n', 'static uint32_t loglevel;\n\n' + PUMP),
        ('    QTAILQ_INSERT_TAIL(&s->requests, r, next);',
         '    s->observe_allocated++;\n    QTAILQ_INSERT_TAIL(&s->requests, r, next);'),
        ('    QTAILQ_REMOVE(&r->host->requests, r, next);',
         '    r->host->observe_freed++;\n    QTAILQ_REMOVE(&r->host->requests, r, next);'),
        ('static USBHostRequest *usb_host_req_find(', OBSERVER + 'static USBHostRequest *usb_host_req_find('),
        ('    trace_usb_host_open_success(bus_num, addr);',
         '    usb_host_observe_start(s);\n    trace_usb_host_open_success(bus_num, addr);'),
        ('    trace_usb_host_close(s->bus_num, s->addr);',
         '    usb_host_observe_stop(s);\n    trace_usb_host_close(s->bus_num, s->addr);'),
        ('    usb_host_abort_xfers(s);\n    usb_host_iso_free_all(s);',
         '    usb_host_abort_xfers(s);\n    usb_host_observe_sample(s, "drained");\n    usb_host_iso_free_all(s);'),
        ('    if (s->dh) {\n        usb_host_abort_xfers(s);',
         '    usb_host_observe_stop(s);\n    if (s->dh) {\n        usb_host_abort_xfers(s);\n        usb_host_observe_sample(s, "drained");'),
        ('    if (s->test_enum_reset_once && !usb_host_enum_reset_mode_valid(s)) {',
         '    if (!usb_host_enum_reset_mode_valid(s)) {\n        error_setg(errp, "observer fixture requires explicit WS73 leaf and reset/detach opt-outs");\n        return;\n    }\n    if (s->test_enum_reset_once && !usb_host_enum_reset_mode_valid(s)) {'),
    ]
    # Native entry is before the null-packet branch, so late canceled callbacks
    # are counted too. Internal held-transfer re-entry is excluded by the live
    # experiment's independent no-fault QMP contract, not by a fabricated flag.
    for name, extra in [
        ('ctrl', '    s->observe_ctrl_callbacks++;\n'),
        ('data', '''    s->observe_data_callbacks++;
    if (xfer->endpoint == 0x81) {
        s->observe_rx1_callbacks++;
        s->observe_rx1_bytes += xfer->status == LIBUSB_TRANSFER_COMPLETED ? xfer->actual_length : 0;
        s->observe_last_rx1_ns = g_get_monotonic_time() * 1000;
    }
    s->observe_tx1_callbacks += xfer->endpoint == 0x01;
    s->observe_int3_callbacks += xfer->endpoint == 0x83;
''')]:
        start = f'static void LIBUSB_CALL usb_host_req_complete_{name}(struct libusb_transfer *xfer)\n{{'
        a = text.index(start)
        point = text.index('    if (r->p == NULL) {', a)
        text = (text[:point] + extra +
                '    s->observe_dead_callbacks += r->p == NULL;\n'
                '    s->observe_last_callback_ns = g_get_monotonic_time() * 1000;\n\n' + text[point:])
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError('exact observer source location required: ' + before[:70])
        text = text.replace(before, after, 1)
    return text.encode()


# Separate timerless profile for the original immutable hold-capable binary.
# Selection does not enable the hold/error fixtures. Their independent QMP
# no-injection contract must still be checked for every actual experiment.
REQUEST_BASE_SHA256 = '4443a20194d4b2584cd234306c43deedb5a3f77d396c44f79370054e495955ed'
REQUEST_FIELDS = '''    uint64_t                         observe_id;
    int                              observe_bus, observe_device, observe_ep;
'''
REQUEST_HELPER = '''/* Test-only, existing BQL/main-loop call sites. Global identities never reset
 * on reenumeration/object recreation. Pointer reuse is not identity. No packet
 * bytes, second event pump, timer, completion, cancellation or retry is added.
 * Logging perturbs scheduling and cannot qualify performance. */
static uint64_t observe_request_id, observe_request_events;

static void usb_host_observe_request(USBHostRequest *r, const char *phase,
                                     int result)
{
    bool callback = !strcmp(phase, "callback");

    if (observe_request_events >= 4096) {
        if (observe_request_events == 4096) {
            observe_request_events++;
            error_report("WS73_USB_REQUEST_BUDGET_V1 events=4096");
        }
        return;
    }
    observe_request_events++;
    error_report("WS73_USB_REQUEST_V1 ordinal=%" PRIu64
                 " id=%" PRIu64 " bus=%d device=%d ep=%d phase=%s"
                 " mono_ns=%" PRId64 " live=%d result=%d"
                 " requested=%d actual=%d status=%d",
                 observe_request_events, r->observe_id, r->observe_bus,
                 r->observe_device, r->observe_ep, phase,
                 (int64_t)g_get_monotonic_time() * 1000, r->p != NULL,
                 result, r->xfer->length,
                 callback ? r->xfer->actual_length : -1,
                 callback ? (int)r->xfer->status : -1);
}

'''


def transform_requests(original):
    """Metadata at existing request transitions; preserve all original I/O."""
    if hashlib.sha256(original).hexdigest() != REQUEST_BASE_SHA256:
        raise ValueError('exact complete request-observer baseline required')
    text = original.decode()
    replacements = [
        ('    USBPacket                        *p;\n',
         '    USBPacket                        *p;\n' + REQUEST_FIELDS, 1),
        ('static USBHostRequest *usb_host_req_alloc(',
         REQUEST_HELPER + 'static USBHostRequest *usb_host_req_alloc(', 1),
        ('    QTAILQ_INSERT_TAIL(&s->requests, r, next);',
         '''    /* Saturation is observable and rejected, never wrap to an old id. */
    if (observe_request_id != UINT64_MAX) {
        observe_request_id++;
    }
    r->observe_id = observe_request_id;
    r->observe_bus = s->bus_num;
    r->observe_device = s->addr;
    r->observe_ep = p->ep->nr | (p->ep->nr && in ? USB_DIR_IN : 0);
    usb_host_observe_request(r, "alloc", 0);
    QTAILQ_INSERT_TAIL(&s->requests, r, next);''', 1),
        ('    QTAILQ_REMOVE(&r->host->requests, r, next);',
         '    usb_host_observe_request(r, "free", 0);\n'
         '    QTAILQ_REMOVE(&r->host->requests, r, next);', 1),
        ('    rc = libusb_submit_transfer(r->xfer);',
         '    rc = libusb_submit_transfer(r->xfer);\n'
         '    usb_host_observe_request(r, "submit", rc);', 2),
        ('            libusb_cancel_transfer(r->xfer);',
         '''            int cancel_rc = libusb_cancel_transfer(r->xfer);
            usb_host_observe_request(r, "cancel", cancel_rc);''', 2),
        ('    if (s->test_enum_reset_once && !usb_host_enum_reset_mode_valid(s)) {',
         '''    if (!usb_host_enum_reset_mode_valid(s) || s->hostdevice ||
        s->test_enum_reset_once) {
        error_setg(errp, "request observer requires explicit WS73 leaf and all reset/detach opt-outs");
        return;
    }
    if (s->test_enum_reset_once && !usb_host_enum_reset_mode_valid(s)) {''', 1),
    ]
    for name in ('ctrl', 'data'):
        start = f'static void LIBUSB_CALL usb_host_req_complete_{name}(struct libusb_transfer *xfer)\n{{'
        if text.count(start) != 1:
            raise ValueError('exact request callback required')
        a = text.index(start)
        point = text.index('    if (r->p == NULL) {', a)
        text = text[:point] + '    usb_host_observe_request(r, "callback", 0);\n\n' + text[point:]
    for before, after, count in replacements:
        if text.count(before) != count:
            raise ValueError('exact request observer location required: ' + before[:70])
        text = text.replace(before, after)
    return text.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('heartbeat', 'requests'), default='heartbeat')
    args = parser.parse_args()
    convert = transform_requests if args.mode == 'requests' else transform
    data = convert(args.source.read_bytes())
    with args.output.open('xb') as stream:
        stream.write(data)
    print('TEST_ONLY_BOUNDED_USB_OBSERVER_SOURCE', hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
