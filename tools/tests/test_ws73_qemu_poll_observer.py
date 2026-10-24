# SPDX-License-Identifier: GPL-2.0-only
"""Visible source/metadata fixtures, not real readiness or callback proof."""
from pathlib import Path
import hashlib
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_qemu_poll_observer as observer
import ws73_usb_lifecycle as life
from ws73_capture import CaptureError
from test_ws73_qemu_event_observer import sample,log


def poll(row,**changes):
    fields=dict(bus=row['bus'],device=row['device'],sample=row['sample'],before_ns=row['mono_ns']+1000,
                after_ns=row['mono_ns']+10000,wall_ns=row['wall_ns']+10000,count=2,result=0,errno=0,error=0,
                fds=f"7:4:0:{row['bus']}:{row['device']};8:1:0:0:0")
    fields.update(changes)
    return 'qemu: '+life.POLL_MARKER+' '.join(f'{k}={v}'for k,v in fields.items())+'\n'


def fixture():
    return ''.join(log(row)+poll(row)for row in(sample(1),sample(2,'closing'),sample(3,'drained')))


class QemuPollObserver(unittest.TestCase):
    def test_transform_exact_digest_and_source_anchors(self):
        source=b'static void usb_host_observe_sample(USBHostDevice *s, const char *phase)\n{\n                 observe_pump_max_ns);\n}\n'
        with self.assertRaises(ValueError):observer.transform(source)
        with patch.object(observer,'BASE_SHA256',hashlib.sha256(source).hexdigest()):actual=observer.transform(source).decode()
        self.assertEqual(actual.count('poll(fds, count, 0);'),1)
        self.assertEqual(actual.count('usb_host_observe_poll(s);'),1)
        self.assertIn('node.st_ino != original.st_ino',actual)
        self.assertIn('struct pollfd fds[8]',actual)
        self.assertNotIn('libusb_handle_events_timeout',actual)
        for op in('read(', 'ioctl(', 'libusb_submit_transfer(', 'libusb_cancel_transfer('):self.assertNotIn(op,actual)
        for broken in(source+source,source.replace(b'observe_pump_max_ns);',b'changed;')):
            with patch.object(observer,'BASE_SHA256',hashlib.sha256(broken).hexdigest()),self.assertRaises(ValueError):observer.transform(broken)

    def test_nonready_and_ready_are_raw_snapshots_not_delivery_or_continuity(self):
        text=fixture().replace('fds=7:4:0:1:18','fds=7:4:4:1:18',1).replace('result=0','result=1',1)
        r=life.parse_native_poll(text,{(1,18)})
        self.assertEqual(r['poll_devices'][0]['samples'][0]['fds'][0]['revents'],4)
        self.assertEqual(r['poll_devices'][0]['samples'][1]['result'],0)
        for key in('continuous_completion_availability_proved','physical_drain_qualified','credit_truth_qualified','performance_qualified'):self.assertFalse(r[key])

    def test_lookup_error_missing_or_truncated_is_not_zero_readiness(self):
        good=fixture()
        for text in(good.replace('error=0','error=1',1),good.replace('errno=0','errno=12',1),
                    good.replace('result=0','result=-1',1),good.replace('count=2','count=9',1),
                    good.replace('fds=7:4:0:1:18;8:1:0:0:0','fds=-',1),
                    ''.join(l+'\n'for l in good.splitlines()if life.POLL_MARKER not in l),good[:-1]):
            with self.subTest(text=text[:60]),self.assertRaises(CaptureError):life.parse_native_poll(text,{(1,18)})

    def test_fd_identity_count_and_error_bits_are_not_guessed(self):
        for changed in('7:4:0:1:19;8:1:0:0:0','7:4:0:1:18;7:1:0:0:0',
                       '7:4:0:1:18;8:4:0:1:18','7:4:0:1:18','7:2:0:1:18;8:1:0:0:0',
                       '7:4:64:1:18;8:1:0:0:0','7:4:0:0:0;8:1:0:0:0'):
            text=fixture().replace('7:4:0:1:18;8:1:0:0:0',changed,1)
            with self.subTest(changed=changed),self.assertRaises(CaptureError):life.parse_native_poll(text,{(1,18)})
        # Error/hangup readiness is retained as such, never turned into data.
        text=fixture().replace('fds=7:4:0:1:18','fds=7:4:8:1:18',1).replace('result=0','result=1',1)
        self.assertEqual(life.parse_native_poll(text,{(1,18)})['poll_devices'][0]['samples'][0]['fds'][0]['revents'],8)

    def test_sequence_pair_clock_and_integer_errors_fail_closed(self):
        good=fixture();lines=good.splitlines()
        mutations=[good.replace('sample=1 before_ns','sample=2 before_ns',1),
                   good.replace('before_ns=100001000','before_ns=1',1),
                   good.replace('after_ns=100010000','after_ns=200000001',1),
                   good.replace('wall_ns=1100010000','wall_ns=1',1),
                   good.replace('count=2','count=2 count=2',1),
                   good.replace('result=0','result=18446744073709551616',1),
                   '\n'.join(lines[:1]+[lines[1],lines[1]]+lines[2:])+'\n',
                   '\n'.join([lines[0],lines[2],lines[1]]+lines[3:])+'\n']
        for text in mutations:
            with self.subTest(text=text[:70]),self.assertRaises(CaptureError):life.parse_native_poll(text,{(1,18)})

    def test_two_devices_and_budget_require_complete_native_poll_pairs(self):
        text=fixture()+fixture().replace('device=18','device=19').replace(':1:18',':1:19')
        result=life.parse_native_poll(text,{(1,18),(1,19)})
        self.assertEqual(len(result['poll_devices']),2)
        with self.assertRaises(CaptureError):life.parse_native_poll(fixture(),{(1,18),(1,19)})
        for key,value in(('BYTE_LIMIT',1),('LINE_LIMIT',1),('REPORT_LIMIT',1)):
            with self.subTest(key=key),patch.object(life,key,value),self.assertRaises(CaptureError):life.parse_native_poll(fixture(),{(1,18)})
