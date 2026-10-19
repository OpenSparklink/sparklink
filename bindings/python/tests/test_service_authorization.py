"""Python ownership/ABI fixtures; not the Rust guard, daemon or RF proof."""
import ctypes
import errno
import os
import select
import threading
import time
import unittest
from unittest.mock import patch

from sparklink import AuthorizationRequest, ControllerId, LocalProperty, SsapAccess, SsapOperations
from sparklink.service_authorization import _Info
from test_local_services import Boundary, caller


class InboxBoundary(Boundary):
    def __init__(self):
        super().__init__()
        self.event = os.eventfd(0, os.EFD_CLOEXEC | os.EFD_NONBLOCK)
        self.pending = False
        self.stopped = False
        self.replies = []
        self.released = []
        self.next_calls = 0
        self.corrupt = lambda v: None

    def slk_client_register_local_service(self, *args):
        self.authorization = args[6]
        return super().slk_client_register_local_service(*args)

    def slk_local_service_authorization_fd(self, view, output):
        output._obj.value = os.dup(self.event)
        return 0

    def slk_local_service_next_authorization(self, view, output):
        self.next_calls += 1
        if self.stopped:
            return -errno.ESHUTDOWN
        if not self.pending:
            return -errno.EAGAIN
        self.pending = False
        output._obj.value = 555
        return 0

    def slk_authorization_request_info(self, view, output):
        v = output._obj
        v.controller.index, v.controller.generation = 2, 7
        v.token, v.request_id, v.connection_lifetime = 1, 19, 23
        v.security_epoch, v.deadline_ns = 31, time.monotonic_ns() + 1_000_000_000
        v.connection_handle, v.property = 3, 17
        v.local_tcid, v.remote_tcid = 10, 10
        v.write, v.value_length = 1, 3
        v.value[:3] = b'abc'
        self.corrupt(v)
        return 0

    def slk_authorization_request_reply(self, view, allow):
        if self.stopped:
            return -errno.ESHUTDOWN
        if self.replies:
            return -errno.ESTALE
        self.replies.append((view.value, allow))
        return 0

    def slk_authorization_request_free(self, view):
        self.released.append(view.value)

    def slk_local_service_free(self, view):
        super().slk_local_service_free(view)
        self.stopped = True
        os.eventfd_write(self.event, 1)

    def close_fixture(self):
        os.close(self.event)


class AuthorizationBoundary(unittest.TestCase):
    def setUp(self):
        self.boundary = InboxBoundary()
        self.config = patch('sparklink.local_services._configure')
        self.request_config = patch('sparklink.service_authorization._configure')
        self.config.start()
        self.request_config.start()
        self.client = caller(self.boundary)
        self.view = self.client.register_local_service(ControllerId(2, 7), b'ab',
            [LocalProperty(b'cd', SsapOperations(5), SsapAccess(36), b'abc')],
            deadline_ns=1, authorization='requests')

    def tearDown(self):
        self.view.close()
        self.client.close()
        self.request_config.stop()
        self.config.stop()
        self.boundary.close_fixture()

    def take(self):
        self.boundary.pending = True
        return self.view.next_authorization()

    def test_explicit_mode_layout_and_local_decision_ownership(self):
        self.assertEqual(self.boundary.authorization, 1)
        self.assertEqual((ctypes.sizeof(_Info), _Info.value.offset), (2120, 72))
        with self.assertRaises(TypeError):
            AuthorizationRequest()
        with self.assertRaises(OSError) as error:
            self.view.next_authorization()
        self.assertEqual(error.exception.errno, errno.EAGAIN)
        fd = self.view.authorization_fd()
        try:
            self.assertFalse(os.get_inheritable(fd))
        finally:
            os.close(fd)
        request = self.take()
        self.client.close()
        self.assertEqual(request.info.value, b'abc')
        self.assertEqual((request.info.controller, request.info.property), (ControllerId(2, 7), 17))
        for wrong in [0, 1, 'yes', None]:
            with self.assertRaises(TypeError):
                request.reply(wrong)
        request.reply(True)
        with self.assertRaises(OSError) as error:
            request.reply(False)
        self.assertEqual(error.exception.errno, errno.ESTALE)
        self.assertEqual(self.boundary.replies, [(555, 1)])
        self.view.close()
        self.assertEqual(request.info.value, b'abc')
        with self.assertRaises(OSError) as error:
            request.reply(True)
        self.assertEqual(error.exception.errno, errno.ESHUTDOWN)
        request.close()
        request.close()
        self.assertEqual(self.boundary.released, [555])

    def test_corrupt_context_releases_without_decision(self):
        corruptions = [
            lambda v: setattr(v.controller, 'index', 3),
            lambda v: setattr(v.controller, 'generation', 8),
            lambda v: v.controller.reserved.__setitem__(0, 1),
            lambda v: v.reserved.__setitem__(0, 1),
            lambda v: v.tail.__setitem__(0, 1),
            lambda v: setattr(v, 'token', 0),
            lambda v: setattr(v, 'request_id', 0),
            lambda v: setattr(v, 'connection_lifetime', 0),
            lambda v: setattr(v, 'security_epoch', 0),
            lambda v: setattr(v, 'deadline_ns', 0),
            lambda v: setattr(v, 'security_level', 3),
            lambda v: setattr(v, 'property', 18),
            lambda v: setattr(v, 'write', 2),
            lambda v: setattr(v, 'write', 0),  # A read cannot carry proposed bytes.
            lambda v: setattr(v, 'value_length', 2043),
            lambda v: v.value.__setitem__(3, 1),
            lambda v: setattr(v, 'local_tcid', 31),
            lambda v: setattr(v, 'remote_tcid', 31),
            lambda v: setattr(v, 'pi', 241),
        ]
        for corrupt in corruptions:
            self.boundary.corrupt = corrupt
            with self.subTest(corrupt=corrupt), self.assertRaises(OSError) as error:
                self.take()
            self.assertEqual(error.exception.errno, errno.EPROTO)
        self.assertEqual(len(self.boundary.released), len(corruptions))
        self.assertFalse(self.boundary.replies)

    def test_wait_keeps_original_deadline_and_releases_notification_fd(self):
        original = time.monotonic_ns() + 40_000_000
        before = len(os.listdir('/proc/self/fd'))
        with self.assertRaises(OSError) as error:
            self.view.next_authorization(deadline_ns=original)
        self.assertEqual(error.exception.errno, errno.ETIMEDOUT)
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)
        calls = self.boundary.next_calls
        with self.assertRaises(OSError):
            self.view.next_authorization(deadline_ns=time.monotonic_ns() - 1)
        with self.assertRaises(ValueError):
            self.view.next_authorization(deadline_ns=time.monotonic_ns() + 31_000_000_000)
        self.assertEqual(self.boundary.next_calls, calls)

    def test_close_wakes_wait_without_holding_service_lock(self):
        entered = threading.Event()
        original_poll = select.poll
        class ObservedPoll:
            def __init__(self): self.inner = original_poll()
            def register(self, *args): self.inner.register(*args)
            def poll(self, timeout):
                entered.set()
                return self.inner.poll(timeout)
        results = []
        def wait():
            try:
                self.view.next_authorization(deadline_ns=time.monotonic_ns() + 1_000_000_000)
            except BaseException as error:
                results.append(error)
        with patch('sparklink.local_services.select.poll', ObservedPoll):
            thread = threading.Thread(target=wait)
            thread.start()
            self.assertTrue(entered.wait(1))
            self.view.close()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], RuntimeError)  # Closed Python object, before C.

    def test_fork_refusal_precedes_inherited_mutex_and_mode_is_explicit(self):
        request = self.take()
        class Poison:
            def __enter__(self): raise AssertionError('inherited lock touched')
        for obj, calls in [(request, [lambda: request.reply(True), request.close]),
                           (self.view, [self.view.next_authorization, self.view.authorization_fd])]:
            original_pid, original_lock = obj._pid, obj._lock
            obj._pid, obj._lock = -1, Poison()
            try:
                for call in calls:
                    with self.assertRaises(RuntimeError): call()
            finally:
                obj._pid, obj._lock = original_pid, original_lock
        request.close()
        for mode in ['', None, True, 'auto']:
            with self.assertRaises(ValueError):
                self.client.register_local_service(ControllerId(2, 7), b'ab',
                    [LocalProperty(b'cd', SsapOperations(5), SsapAccess(0))],
                    deadline_ns=1, authorization=mode)
