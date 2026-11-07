#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive a separate bounded non-consuming libusb poll-readiness fixture.

Reuse the existing guarded native-callback observer and its finite timer.
No URB reap, USB request, protocol work, credit change or recovery operation.
"""
import argparse
import hashlib
from pathlib import Path

BASE_SHA256 = 'aa70ca6dda9a88827b0c5b26774e2919da7aa8ae35849a61461186db3aa41b60'

PEEK = '''/* Test-only Linux poll snapshot. Never reap/consume an URB or call the
 * event pump here. fd identity is a local /proc/stat observation, not device
 * authentication or a generation grant. Heartbeat scheduling is intrusive. */
static void usb_host_observe_poll(USBHostDevice *s)
{
    const struct libusb_pollfd **source;
    struct pollfd fds[8] = { 0 };
    char items[768] = { 0 };
    unsigned int count = 0;
    size_t used = 0;
    int result = -1, observed_errno = 0, error = 0;
    int64_t before = g_get_monotonic_time() * 1000;

    source = libusb_get_pollfds(ctx);
    if (!source) {
        error = 1;
    } else {
        while (source[count] && count < ARRAY_SIZE(fds)) {
            fds[count].fd = source[count]->fd;
            fds[count].events = source[count]->events;
            count++;
        }
        if (source[count]) {
            error = 2; /* No partial fd set may qualify. */
        }
    }
    if (!error) {
        result = poll(fds, count, 0);
        observed_errno = result < 0 ? errno : 0;
        for (unsigned int i = 0; i < count; i++) {
            char name[64], target[128], trailing;
            struct stat original, node;
            unsigned int bus = 0, device = 0;
            ssize_t length;
            int written;

            snprintf(name, sizeof(name), "/proc/self/fd/%d", fds[i].fd);
            length = readlink(name, target, sizeof(target) - 1);
            if (length <= 0 || (size_t)length >= sizeof(target) - 1 ||
                fstat(fds[i].fd, &original)) {
                error = 3;
                break;
            }
            target[length] = 0;
            if (sscanf(target, "/dev/bus/usb/%u/%u%c", &bus, &device,
                       &trailing) == 2) {
                if (!S_ISCHR(original.st_mode) || stat(target, &node) ||
                    node.st_dev != original.st_dev ||
                    node.st_ino != original.st_ino ||
                    node.st_rdev != original.st_rdev) {
                    error = 4;
                    break;
                }
            } else {
                bus = device = 0; /* Explicitly non-USB, not a chosen device. */
            }
            written = snprintf(items + used, sizeof(items) - used,
                               "%s%d:%d:%d:%u:%u", i ? ";" : "",
                               fds[i].fd, (int)fds[i].events,
                               (int)fds[i].revents, bus, device);
            if (written < 0 || (size_t)written >= sizeof(items) - used) {
                error = 5;
                break;
            }
            used += written;
        }
    }
    free(source);
    error_report("WS73_USB_POLL_V1 bus=%d device=%d sample=%" PRIu64
                 " before_ns=%" PRId64 " after_ns=%" PRId64
                 " wall_ns=%" PRId64 " count=%u result=%d errno=%d error=%d fds=%s",
                 s->bus_num, s->addr, s->observe_samples, before,
                 (int64_t)g_get_monotonic_time() * 1000,
                 (int64_t)g_get_real_time() * 1000, count, result,
                 observed_errno, error, used ? items : "-");
}

'''


def transform(original):
    if hashlib.sha256(original).hexdigest() != BASE_SHA256:
        raise ValueError('exact guarded complete native-observer source required')
    text = original.decode()
    before = 'static void usb_host_observe_sample(USBHostDevice *s, const char *phase)'
    end = '                 observe_pump_max_ns);\n}'
    if text.count(before) != 1 or text.count(end) != 1:
        raise ValueError('exact original bounded observer locations required')
    text = text.replace(before, PEEK + before, 1)
    text = text.replace(end, '                 observe_pump_max_ns);\n    usb_host_observe_poll(s);\n}', 1)
    return text.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = transform(args.source.read_bytes())
    with args.output.open('xb') as stream:
        stream.write(data)
    print('TEST_ONLY_BOUNDED_USB_POLL_SOURCE', hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
