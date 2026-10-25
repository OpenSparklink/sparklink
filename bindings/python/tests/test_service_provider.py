"""Python ABI/ownership fixtures only; not Rust admission, daemon or RF proof."""
import ctypes
import errno
import gc
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import threading
import time
import unittest
import weakref
from unittest.mock import patch

from sparklink import (ControllerId, LocalProperty, ReadProvider, ReadProviderInfo,
                       ReadProviderRequest, SsapAccess, SsapOperations)
from sparklink.service_provider import _Info, _configure
from test_local_services import Boundary, caller


class ProviderBoundary(Boundary):
    def __init__(self):
        super().__init__()
        self.event = os.eventfd(0, os.EFD_CLOEXEC | os.EFD_NONBLOCK)
        self.pending, self.stopped, self.bound = False, False, False
        self.bind_calls, self.replies, self.released, self.inboxes = [], [], [], []
        self.next_calls, self.reply_error, self.bind_error = 0, 0, 0
        self.corrupt = lambda value: None
        self.after_next = lambda: None
        self.original_deadline = time.monotonic_ns() + 5_000_000_000
        self.maximum = 2042
        self.request_handle, self.inbox_handle = 555, 444

    def slk_local_service_bind_read_provider(self, service, handle, deadline, output):
        self.bind_calls.append((service.value, handle, deadline))
        if self.bind_error:
            return self.bind_error
        if self.bound:
            return -errno.EALREADY
        self.bound = True
        output._obj.value = self.inbox_handle
        return 0

    def slk_read_provider_fd(self, provider, output):
        output._obj.value = os.dup(self.event)
        return 0

    def slk_read_provider_next(self, provider, output):
        self.next_calls += 1
        if self.stopped:
            return -errno.ESHUTDOWN
        if not self.pending:
            return -errno.EAGAIN
        self.pending = False
        output._obj.value = self.request_handle
        self.after_next()
        return 0

    def slk_read_provider_request_info(self, request, output):
        raw = output._obj
        raw.controller.index, raw.controller.generation = 2, 7
        raw.token, raw.request_id, raw.connection_lifetime = 1, 19, 23
        raw.security_epoch, raw.deadline_ns = 31, self.original_deadline
        raw.connection_handle, raw.property, raw.maximum_bytes = 3, 17, self.maximum
        raw.local_tcid, raw.remote_tcid = 10, 10
        self.corrupt(raw)
        return 0

    def slk_read_provider_request_reply(self, request, status, value, length):
        if self.stopped:
            return -errno.ESHUTDOWN
        if self.reply_error:
            return self.reply_error
        if self.replies:
            return -errno.ESTALE
        self.replies.append((request.value, status, bytes(value[:length]) if value else b''))
        return 0

    def slk_read_provider_request_free(self, request):
        self.released.append(request.value)

    def stop(self):
        self.stopped = True
        os.eventfd_write(self.event, 1)

    def slk_read_provider_free(self, provider):
        self.inboxes.append(provider.value)
        self.stop()

    def slk_local_service_free(self, service):
        super().slk_local_service_free(service)
        self.stop()

    def slk_local_service_unregister(self, service, deadline):
        super().slk_local_service_unregister(service, deadline)
        self.stop()
        return self.error


class ProviderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.boundary = ProviderBoundary()
        self.config = patch('sparklink.local_services._configure')
        self.provider_config = patch('sparklink.service_provider._configure')
        self.config.start()
        self.provider_config.start()
        self.client = caller(self.boundary)
        self.service = self.client.register_local_service(ControllerId(2, 7), b'ab',
            [LocalProperty(b'cd', SsapOperations.READ, SsapAccess(0), b'old')], deadline_ns=1)
        self.provider = None
        self.requests = []

    def tearDown(self):
        for request in self.requests:
            request.close()
        if self.provider:
            self.provider.close()
        if self.service:
            self.service.close()
        if self.client:
            self.client.close()
        self.provider_config.stop()
        self.config.stop()
        os.close(self.boundary.event)

    def bind(self):
        self.provider = self.service.bind_read_provider(17, deadline_ns=2)
        return self.provider

    def take(self):
        if self.provider is None:
            self.bind()
        self.boundary.pending = True
        request = self.provider.next_request()
        self.requests.append(request)
        return request

    def test_bind_forwarding_layout_and_opaque_construction(self):
        for cls in (ReadProvider, ReadProviderRequest):
            with self.assertRaises(TypeError):
                cls()
        self.bind()
        self.assertEqual(self.boundary.bind_calls, [(123, 17, 2)])
        self.assertEqual(ctypes.sizeof(_Info), 80)
        offsets = {'controller': 0, 'token': 16, 'request_id': 24,
            'connection_lifetime': 32, 'security_epoch': 40, 'deadline_ns': 48,
            'security_level': 56, 'connection_handle': 60, 'property': 62,
            'maximum_bytes': 64, 'local_tcid': 66, 'remote_tcid': 67, 'pi': 68,
            'reserved': 69}
        self.assertEqual({name: getattr(_Info, name).offset for name in offsets}, offsets)
        with self.assertRaises(OSError) as error:
            self.service.bind_read_provider(17, deadline_ns=3)
        self.assertEqual(error.exception.errno, errno.EALREADY)
        self.assertEqual(len(self.boundary.bind_calls), 2)
        request = self.take()
        self.assertIsInstance(request.info, ReadProviderInfo)
        self.assertEqual((request.info.controller, request.info.property,
                          request.info.deadline_ns),
                         (ControllerId(2, 7), 17, self.boundary.original_deadline))
        with self.assertRaises(AttributeError):
            request.info.maximum_bytes = 2

    def test_ctypes_layout_matches_current_generated_c_header(self):
        header = Path(__file__).resolve().parents[3] / 'crates/libsparklink/include/sparklink.h'
        source = ['#include <stddef.h>', '#include "sparklink.h"',
            f'_Static_assert(sizeof(SlkReadProviderRequestInfo) == {ctypes.sizeof(_Info)}, "size");',
            f'_Static_assert(_Alignof(SlkReadProviderRequestInfo) == {ctypes.alignment(_Info)}, "alignment");']
        for name, kind in _Info._fields_:
            source += [f'_Static_assert(offsetof(SlkReadProviderRequestInfo, {name}) == '
                       f'{getattr(_Info, name).offset}, "{name} offset");',
                       f'_Static_assert(sizeof(((SlkReadProviderRequestInfo *)0)->{name}) == '
                       f'{ctypes.sizeof(kind)}, "{name} size");']
        source += [
            'int (*bind_fn)(SlkLocalService *, uint16_t, uint64_t, SlkReadProvider **) = slk_local_service_bind_read_provider;',
            'int (*fd_fn)(const SlkReadProvider *, int *) = slk_read_provider_fd;',
            'int (*next_fn)(const SlkReadProvider *, SlkReadProviderRequest **) = slk_read_provider_next;',
            'void (*free_fn)(SlkReadProvider *) = slk_read_provider_free;',
            'int (*info_fn)(const SlkReadProviderRequest *, SlkReadProviderRequestInfo *) = slk_read_provider_request_info;',
            'int (*reply_fn)(const SlkReadProviderRequest *, uint16_t, const uint8_t *, size_t) = slk_read_provider_request_reply;',
            'void (*request_free_fn)(SlkReadProviderRequest *) = slk_read_provider_request_free;',
        ]
        with tempfile.TemporaryDirectory(prefix='sparklink-provider-abi-') as directory:
            unit = Path(directory) / 'provider.c'
            unit.write_text('\n'.join(source) + '\n')
            result = subprocess.run(shlex.split(os.environ.get('CC', 'cc')) +
                ['-std=c11', '-Werror', '-fsyntax-only', '-I', str(header.parent), str(unit)],
                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_ffi_symbol_is_configured_before_binding(self):
        class Function:
            pass
        class Library:
            pass
        library = Library()
        names = ['slk_local_service_bind_read_provider', 'slk_read_provider_fd',
            'slk_read_provider_next', 'slk_read_provider_free',
            'slk_read_provider_request_info', 'slk_read_provider_request_reply',
            'slk_read_provider_request_free']
        for name in names:
            setattr(library, name, Function())
        _configure(library)
        self.assertEqual(library.slk_local_service_bind_read_provider.argtypes,
            [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)])
        self.assertEqual(library.slk_read_provider_request_info.argtypes,
            [ctypes.c_void_p, ctypes.POINTER(_Info)])
        self.assertEqual(library.slk_read_provider_request_reply.argtypes,
            [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p, ctypes.c_size_t])
        for name in names:
            self.assertIs(getattr(library, name).restype,
                None if name.endswith('_free') else ctypes.c_int)
        self.provider_config.stop()
        try:
            with self.assertRaises(AttributeError):
                self.bind()  # Boundary functions cannot accept ctypes signatures.
            self.assertFalse(self.boundary.bind_calls)
        finally:
            self.provider_config.start()

    def test_invalid_bind_and_uncertain_error_are_not_retried(self):
        for handle in (0, 65536, True, '17'):
            with self.assertRaises(ValueError):
                self.service.bind_read_provider(handle, deadline_ns=2)
        for deadline in (0, -1, True, 1 << 64):
            with self.assertRaises(ValueError):
                self.service.bind_read_provider(17, deadline_ns=deadline)
        self.assertFalse(self.boundary.bind_calls)
        self.boundary.bind_error = -errno.ETIMEDOUT
        with self.assertRaises(OSError) as error:
            self.bind()
        self.assertEqual(error.exception.errno, errno.ETIMEDOUT)
        self.assertEqual(self.boundary.bind_calls, [(123, 17, 2)])

    def test_invalid_reply_preserves_original_request_then_full_value(self):
        request = self.take()
        for value, status, error in [(bytearray(b'x'), 0, TypeError), ('x', 0, TypeError),
                (b'', True, TypeError), (b'', 'ff', TypeError), (b'', 1, ValueError),
                (b'', 0xAE, ValueError), (b'', 256, ValueError),
                (b'x', 0xFF, ValueError), (b'x' * 2043, 0, OSError)]:
            with self.subTest(value_type=type(value), status=status), self.assertRaises(error) as e:
                request.reply(value, status=status)
            if error is OSError:
                self.assertEqual(e.exception.errno, errno.EMSGSIZE)
        self.assertFalse(self.boundary.replies)
        request.reply(b'x' * 2042)
        self.assertEqual(self.boundary.replies, [(555, 0, b'x' * 2042)])
        with self.assertRaises(OSError) as error:
            request.reply(b'')
        self.assertEqual(error.exception.errno, errno.ESTALE)

    def test_empty_and_explicit_application_error_zero_budget(self):
        self.boundary.maximum = 0
        request = self.take()
        for status in (0, 0xAF, 0xFF):
            self.boundary.replies.clear()  # Independent wrapper forwarding samples.
            request.reply(b'', status=status)
            self.assertEqual(self.boundary.replies, [(555, status, b'')])
        with self.assertRaises(OSError) as error:
            request.reply(b'x')
        self.assertEqual(error.exception.errno, errno.EMSGSIZE)

    def test_original_terminal_errors_and_snapshot_after_close(self):
        request = self.take()
        for code in (errno.ETIMEDOUT, errno.ESTALE, errno.ESHUTDOWN):
            self.boundary.reply_error = -code
            with self.assertRaises(OSError) as error:
                request.reply(b'')
            self.assertEqual(error.exception.errno, code)
        original = request.info
        self.service.close()
        with self.assertRaises(OSError) as error:
            request.reply(b'')
        self.assertEqual(error.exception.errno, errno.ESHUTDOWN)
        request.close()
        request.close()
        self.assertIs(request.info, original)
        self.assertEqual(self.boundary.released, [555])
        with self.assertRaises(RuntimeError):
            request.reply(b'')

    def test_inbox_close_stops_requests_without_withdrawing_service(self):
        request = self.take()
        self.provider.close()
        self.provider.close()
        self.assertEqual(self.boundary.inboxes, [444])
        self.assertFalse(self.boundary.freed)
        self.assertFalse(self.boundary.unregistered)
        self.assertEqual(request.info.property, 17)
        with self.assertRaises(OSError) as error:
            request.reply(b'')
        self.assertEqual(error.exception.errno, errno.ESHUTDOWN)
        with self.assertRaises(RuntimeError):
            self.provider.next_request()
        self.service.unregister(deadline_ns=3)
        self.assertEqual(self.boundary.unregistered, [(123, 3)])

    def test_context_corruption_releases_without_value(self):
        corruptions = [lambda v: setattr(v.controller, 'index', 3),
            lambda v: setattr(v.controller, 'generation', 8),
            lambda v: v.controller.reserved.__setitem__(0, 1),
            lambda v: v.reserved.__setitem__(10, 1),
            lambda v: setattr(v, 'security_level', 3),
            lambda v: setattr(v, 'property', 18),
            lambda v: setattr(v, 'maximum_bytes', 2043),
            lambda v: setattr(v, 'local_tcid', 31),
            lambda v: setattr(v, 'remote_tcid', 31),
            lambda v: setattr(v, 'pi', 241)]
        corruptions += [lambda v, field=field: setattr(v, field, 0)
            for field in ('token', 'request_id', 'connection_lifetime', 'security_epoch', 'deadline_ns')]
        self.bind()
        for corrupt in corruptions:
            self.boundary.corrupt = corrupt
            with self.subTest(corrupt=corrupt), self.assertRaises(OSError) as error:
                self.take()
            self.assertEqual(error.exception.errno, errno.EPROTO)
        self.assertEqual(len(self.boundary.released), len(corruptions))
        self.assertFalse(self.boundary.replies)

    def test_null_success_outputs_fail_closed(self):
        self.boundary.inbox_handle = 0
        with self.assertRaises(OSError) as error:
            self.bind()
        self.assertEqual(error.exception.errno, errno.EPROTO)
        self.boundary.bound = False
        self.boundary.inbox_handle = 444
        self.bind()
        self.boundary.request_handle = 0
        with self.assertRaises(OSError) as error:
            self.take()
        self.assertEqual(error.exception.errno, errno.EPROTO)
        self.assertFalse(self.boundary.replies)

    def test_inbox_request_fd_do_not_retain_original_service_or_client(self):
        request = self.take()
        fd = self.provider.notification_fd()
        try:
            self.assertFalse(os.get_inheritable(fd))
            service_ref, client_ref = weakref.ref(self.service), weakref.ref(self.client)
            self.client = None
            self.service = None
            gc.collect()
            self.assertIsNone(service_ref())
            self.assertIsNone(client_ref())
            self.assertEqual(self.boundary.freed, [123])
            self.assertEqual(self.boundary.closed, [42])
            self.assertEqual(request.info.property, 17)
            with self.assertRaises(OSError) as error:
                request.reply(b'')
            self.assertEqual(error.exception.errno, errno.ESHUTDOWN)
        finally:
            os.close(fd)

    def test_wait_retains_deadline_and_releases_fd(self):
        self.bind()
        with self.assertRaises(OSError) as error:
            self.provider.next_request()
        self.assertEqual(error.exception.errno, errno.EAGAIN)
        before = len(os.listdir('/proc/self/fd'))
        with self.assertRaises(OSError) as error:
            self.provider.next_request(deadline_ns=time.monotonic_ns() + 20_000_000)
        self.assertEqual(error.exception.errno, errno.ETIMEDOUT)
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)
        calls = self.boundary.next_calls
        with self.assertRaises(OSError):
            self.provider.next_request(deadline_ns=time.monotonic_ns() - 1)
        with self.assertRaises(ValueError):
            self.provider.next_request(deadline_ns=time.monotonic_ns() + 31_000_000_000)
        self.assertEqual(self.boundary.next_calls, calls)

    def test_delivered_after_local_wait_deadline_releases_without_reply(self):
        self.bind()
        clock = [100]
        self.boundary.pending = True
        self.boundary.after_next = lambda: clock.__setitem__(0, 201)
        with patch('sparklink.service_provider.time.monotonic_ns', lambda: clock[0]):
            with self.assertRaises(OSError) as error:
                self.provider.next_request(deadline_ns=200)
        self.assertEqual(error.exception.errno, errno.ETIMEDOUT)
        self.assertEqual(self.boundary.released, [555])
        self.assertFalse(self.boundary.replies)

    def test_service_close_wakes_wait_without_provider_or_service_lock(self):
        self.bind()
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
                self.provider.next_request(deadline_ns=time.monotonic_ns() + 1_000_000_000)
            except BaseException as error:
                results.append(error)
        with patch('sparklink.service_provider.select.poll', ObservedPoll):
            thread = threading.Thread(target=wait)
            thread.start()
            self.assertTrue(entered.wait(1))
            self.service.close()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], OSError)
        self.assertEqual(results[0].errno, errno.ESHUTDOWN)

    def test_fork_refusal_precedes_inherited_mutex(self):
        request = self.take()
        class Poison:
            def __enter__(self): raise AssertionError('inherited lock touched')
        for obj, calls in [(request, [lambda: request.reply(b''), request.close]),
                (self.provider, [self.provider.next_request, self.provider.notification_fd, self.provider.close]),
                (self.service, [lambda: self.service.bind_read_provider(17, deadline_ns=3)])]:
            old_pid, old_lock = obj._pid, obj._lock
            obj._pid, obj._lock = -1, Poison()
            try:
                for call in calls:
                    with self.assertRaises(RuntimeError):
                        call()
            finally:
                obj._pid, obj._lock = old_pid, old_lock


if __name__ == '__main__':
    unittest.main()
