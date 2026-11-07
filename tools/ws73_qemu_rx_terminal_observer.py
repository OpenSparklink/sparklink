#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive a separate bounded native RX-error metadata observer fixture.

No cancellation, reset, delivery or protocol behavior is added here. Existing
callbacks expose length/status/digest before the canceled-packet branch. No
payload bytes or keys are logged. A controlled detach is a separate test action.
"""
import argparse
import hashlib
from pathlib import Path

BASE_SHA256='d9e5a75451f07f45c2d82377c22c3967367ef739edf3f9015ef4dceeba78a799'

HELPER='''static void usb_host_observe_rx_end(USBHostRequest *r,
                                    struct libusb_transfer *xfer)
{
    USBHostDevice *s = r->host;
    bool bounded;
    g_autofree char *checksum = NULL;

    if (!r->in || xfer->endpoint != 0x81 ||
        xfer->type != LIBUSB_TRANSFER_TYPE_BULK ||
        xfer->status == LIBUSB_TRANSFER_COMPLETED) {
        return;
    }
    s->observe_rx_ends++;
    if (s->observe_rx_ends > 128) {
        if (s->observe_rx_ends == 129) {
            error_report("WS73_USB_RX_END_BUDGET_V1 bus=%d device=%d count=129",
                         s->bus_num, s->addr);
        }
        return;
    }
    bounded = xfer->length > 0 && xfer->length <= 20 * 1024 &&
              xfer->actual_length >= 0 && xfer->actual_length <= xfer->length &&
              (xfer->actual_length == 0 || r->buffer != NULL);
    if (bounded) {
        checksum = g_compute_checksum_for_data(G_CHECKSUM_SHA256,
            xfer->actual_length ? r->buffer : (const unsigned char *)"",
            xfer->actual_length);
    }
    error_report("WS73_USB_RX_END_V1 bus=%d device=%d ordinal=%" PRIu64
                 " request=%" PRIu64 " packet=%p allocation_ns=%" PRId64
                 " callback_ns=%" PRId64 " wall_ns=%" PRId64
                 " requested=%d actual=%d status=%d live=%d bounded=%d sha256=%s",
                 s->bus_num, s->addr, s->observe_rx_ends, r->observe_request,
                 r->observe_packet, r->observe_allocation_ns,
                 (int64_t)g_get_monotonic_time() * 1000,
                 (int64_t)g_get_real_time() * 1000, xfer->length,
                 xfer->actual_length, (int)xfer->status, r->p != NULL,
                 bounded, checksum ? checksum : "-");
}

'''


def transform(original):
    if hashlib.sha256(original).hexdigest()!=BASE_SHA256:
        raise ValueError('exact guarded complete poll-observer source required')
    text=original.decode()
    replacements=[
        ('    uint64_t                         observe_samples;',
         '    uint64_t                         observe_rx_ends;\n    uint64_t                         observe_samples;'),
        ('    USBPacket                        *p;\n    bool                             in;',
         '    USBPacket                        *p;\n    void                             *observe_packet;\n    uint64_t                         observe_request;\n    int64_t                          observe_allocation_ns;\n    bool                             in;'),
        ('    s->observe_allocated++;\n    QTAILQ_INSERT_TAIL',
         '    s->observe_allocated++;\n    r->observe_packet = p;\n    r->observe_request = s->observe_allocated;\n    r->observe_allocation_ns = g_get_monotonic_time() * 1000;\n    QTAILQ_INSERT_TAIL'),
        ('static void LIBUSB_CALL usb_host_req_complete_data(struct libusb_transfer *xfer);',
         HELPER+'static void LIBUSB_CALL usb_host_req_complete_data(struct libusb_transfer *xfer);'),
        ('    s->observe_data_callbacks++;',
         '    usb_host_observe_rx_end(r, xfer);\n    s->observe_data_callbacks++;'),
    ]
    for before,after in replacements:
        if text.count(before)!=1:raise ValueError('exact RX terminal observer location required')
        text=text.replace(before,after,1)
    return text.encode()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();data=transform(args.source.read_bytes())
    with args.output.open('xb')as stream:stream.write(data)
    print('TEST_ONLY_RX_TERMINAL_METADATA_SOURCE',hashlib.sha256(data).hexdigest())


if __name__=='__main__':main()
