"""Typed READ/WRITE Provider requests over the sole Rust application frontend.

This module transports values and ownership only; it implements no D-Bus
endpoint, SSAP codec or Engine. Authorization remains a separate decision.
"""
import ctypes
from dataclasses import dataclass
import errno
import os
import select
import threading
import time

from .client import ControllerId, _ControllerId, _deadline, _result


class _Info(ctypes.Structure):
    _fields_ = [('controller', _ControllerId), ('token', ctypes.c_uint64),
                ('request_id', ctypes.c_uint64), ('connection_lifetime', ctypes.c_uint64),
                ('security_epoch', ctypes.c_uint64), ('deadline_ns', ctypes.c_uint64),
                ('security_level', ctypes.c_uint32), ('connection_handle', ctypes.c_uint16),
                ('property', ctypes.c_uint16), ('maximum_bytes', ctypes.c_uint16),
                ('local_tcid', ctypes.c_uint8), ('remote_tcid', ctypes.c_uint8),
                ('pi', ctypes.c_uint8), ('reserved', ctypes.c_uint8 * 11)]


@dataclass(frozen=True)
class ReadProviderInfo:
    controller: ControllerId
    token: int
    request_id: int
    connection_lifetime: int
    connection_handle: int
    security_epoch: int
    security_level: int
    deadline_ns: int
    property: int
    maximum_bytes: int
    local_tcid: int
    remote_tcid: int
    pi: int


def _configure(lib):
    methods = {
        'slk_local_service_bind_read_provider': [ctypes.c_void_p, ctypes.c_uint16,
            ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
        'slk_read_provider_fd': [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)],
        'slk_read_provider_next': [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
        'slk_read_provider_free': [ctypes.c_void_p],
        'slk_read_provider_request_info': [ctypes.c_void_p, ctypes.POINTER(_Info)],
        'slk_read_provider_request_reply': [ctypes.c_void_p, ctypes.c_uint16,
            ctypes.c_void_p, ctypes.c_size_t],
        'slk_read_provider_request_free': [ctypes.c_void_p],
    }
    for name, args in methods.items():
        function = getattr(lib, name)
        function.argtypes = args
        function.restype = None if name.endswith('_free') else ctypes.c_int


class _ProviderInbox:
    """Create with LocalService.bind_read_provider for an exact READ property.

    This inbox retains neither Client nor service. Keep the original service
    alive; service close/unregister or owner loss stops its callbacks. Closing
    the inbox stops local admission, without unbinding, restoring stored bytes
    or unregistering the service. A poll fd is readiness only, never authority.
    """
    def __init__(self):
        raise TypeError('create through the matching LocalService provider binding')

    @classmethod
    def _from_view(cls, lib, handle, controller, property):
        if not handle.value:
            raise OSError(errno.EPROTO, 'missing provider inbox')
        self = object.__new__(cls)
        self._lib, self._handle = lib, handle
        self._controller, self._property = controller, property
        self._pid, self._lock = os.getpid(), threading.RLock()
        return self

    def _live(self):
        if self._pid != os.getpid():
            raise RuntimeError('provider objects cannot be used after fork')
        if not self._handle.value:
            raise RuntimeError('provider inbox closed')

    def notification_fd(self):
        """Return a caller-owned CLOEXEC poll fd; close it with os.close.

        Never read/write its counter. Always try next_request before polling;
        the duplicate retains no service, owner or request authority.
        """
        self._live()
        with self._lock:
            self._live()
            output = ctypes.c_int(-1)
            _result(getattr(self._lib, self._prefix + '_fd')(self._handle, ctypes.byref(output)))
            if output.value < 0:
                raise OSError(errno.EPROTO, 'missing provider notification fd')
            return output.value

    def next_request(self, *, deadline_ns=None):
        """Take one request; None is nonblocking and may raise EAGAIN.

        An optional absolute monotonic deadline bounds only this local wait,
        at most 30 seconds. It cannot renew the callback's original deadline.
        Poll holds no object lock. Release each delivered request after reply;
        its capacity remains held until both release and callback drain.
        """
        if deadline_ns is not None:
            deadline_ns = _deadline(deadline_ns)
            left = deadline_ns - time.monotonic_ns()
            if left <= 0:
                raise OSError(errno.ETIMEDOUT, 'original provider wait expired')
            if left > 30_000_000_000:
                raise ValueError('provider wait exceeds 30 seconds')
        fd = None
        try:
            while True:
                if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
                    raise OSError(errno.ETIMEDOUT, 'original provider wait expired')
                self._live()
                with self._lock:
                    self._live()
                    output = ctypes.c_void_p()
                    code = getattr(self._lib, self._prefix + '_next')(self._handle, ctypes.byref(output))
                    if code != -errno.EAGAIN or deadline_ns is None:
                        _result(code)
                        request = self._request_type._from_view(
                            self._lib, output, self._controller, self._property)
                        if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
                            request.close()
                            raise OSError(errno.ETIMEDOUT, 'original provider wait expired')
                        return request
                if fd is None:
                    fd = self.notification_fd()
                left = deadline_ns - time.monotonic_ns()
                if left <= 0:
                    raise OSError(errno.ETIMEDOUT, 'original provider wait expired')
                poller = select.poll()
                poller.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
                events = poller.poll((left + 999_999) // 1_000_000)
                if any(flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL)
                       for _, flags in events):
                    raise OSError(errno.EIO, 'provider notification fd failed')
        finally:
            if fd is not None:
                os.close(fd)

    def close(self):
        if self._pid != os.getpid():
            raise RuntimeError('provider objects cannot be used after fork')
        with self._lock:
            if self._handle.value:
                getattr(self._lib, self._prefix + '_free')(self._handle)
                self._handle = ctypes.c_void_p()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if getattr(self, '_handle', None) and getattr(self, '_pid', None) == os.getpid():
            self.close()


class _ProviderRequest:
    """One original callback view; its immutable info is not reply authority.

    No Client, service or inbox reference is retained. reply accepts one local
    value/error only; the Rust frontend still checks original scope/deadline and
    fresh admission. Local acceptance is not daemon commit or peer delivery.
    Closing an unanswered view abandons it, without claiming a wire outcome.
    """
    def __init__(self):
        raise TypeError('create through the matching Provider.next_request')

    @classmethod
    def _from_view(cls, lib, handle, controller, property):
        if not handle.value:
            raise OSError(errno.EPROTO, 'missing provider request')
        self = object.__new__(cls)
        self._lib, self._handle = lib, handle
        self._pid, self._lock = os.getpid(), threading.RLock()
        try:
            raw = cls._raw_type()
            _result(getattr(lib, cls._prefix + '_request_info')(handle, ctypes.byref(raw)))
            identity = ControllerId(raw.controller.index, raw.controller.generation)
            if (identity != controller or any(raw.controller.reserved) or any(raw.reserved)
                    or not raw.token or not raw.request_id or not raw.connection_lifetime
                    or not raw.security_epoch or not raw.deadline_ns or raw.security_level > 2
                    or raw.property != property or raw.connection_handle > 0x0fff
                    or (raw.local_tcid, raw.remote_tcid, raw.pi) != (10, 10, 0)):
                raise OSError(errno.EPROTO, 'invalid provider context ABI')
            self._info = cls._decode_info(identity, raw)
            self._snapshot()
            return self
        except BaseException:
            self.close()
            raise

    @property
    def info(self):
        return self._info

    def _live(self):
        if self._pid != os.getpid():
            raise RuntimeError('provider requests cannot be used after fork')
        if not self._handle.value:
            raise RuntimeError('provider request closed')

    def reply(self, value, *, status=0):
        """Submit one local result under the original READ or WRITE contract.

        READ supplies up to its byte budget; verified WRITE supplies the actual
        accepted bytes, other WRITE success and all application errors are empty.
        Invalid inputs do not consume the request. Oversize raises EMSGSIZE;
        expiry, stop and duplicate errors come from the same original Rust view.
        There is no retry, truncation, stored fallback or new deadline argument.
        """
        if not isinstance(value, bytes):
            raise TypeError('immutable bytes required')
        if type(status) is not int:
            raise TypeError('explicit integer application status required')
        if status != 0 and not 0xAF <= status <= 0xFF:
            raise ValueError('status must be 0 or AF..FF')
        if status and value:
            raise ValueError('application error must have an empty value')
        if len(value) > self._reply_capacity():
            raise OSError(errno.EMSGSIZE, 'value exceeds original callback budget')
        self._live()
        with self._lock:
            self._live()
            _result(getattr(self._lib, self._prefix + '_request_reply')(
                self._handle, status, value if value else None, len(value)))

    def close(self):
        if self._pid != os.getpid():
            raise RuntimeError('provider requests cannot be used after fork')
        with self._lock:
            if self._handle.value:
                getattr(self._lib, self._prefix + '_request_free')(self._handle)
                self._handle = ctypes.c_void_p()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if getattr(self, '_handle', None) and getattr(self, '_pid', None) == os.getpid():
            self.close()


class ReadProviderRequest(_ProviderRequest):
    """Original read request; status0 supplies bounded bytes, AF..FF an error."""
    _prefix = 'slk_read_provider'
    _raw_type = _Info

    @staticmethod
    def _decode_info(identity, raw):
        if raw.maximum_bytes > 2042:
            raise OSError(errno.EPROTO, 'invalid read value budget')
        return ReadProviderInfo(identity, raw.token, raw.request_id,
            raw.connection_lifetime, raw.connection_handle, raw.security_epoch,
            raw.security_level, raw.deadline_ns, raw.property, raw.maximum_bytes,
            raw.local_tcid, raw.remote_tcid, raw.pi)

    def _snapshot(self):
        # READ has no proposed bytes; it remains a value provider.
        pass

    def _reply_capacity(self):
        return self._info.maximum_bytes


class ReadProvider(_ProviderInbox):
    """Original READ inbox over the single Rust Provider dispatcher."""
    _prefix = 'slk_read_provider'
    _request_type = ReadProviderRequest


class _WriteInfo(ctypes.Structure):
    _fields_ = [('controller', _ControllerId), ('token', ctypes.c_uint64),
                ('request_id', ctypes.c_uint64), ('connection_lifetime', ctypes.c_uint64),
                ('security_epoch', ctypes.c_uint64), ('deadline_ns', ctypes.c_uint64),
                ('security_level', ctypes.c_uint32), ('connection_handle', ctypes.c_uint16),
                ('property', ctypes.c_uint16), ('offset', ctypes.c_uint16),
                ('value_length', ctypes.c_uint16), ('local_tcid', ctypes.c_uint8),
                ('remote_tcid', ctypes.c_uint8), ('pi', ctypes.c_uint8),
                ('operation', ctypes.c_uint8), ('data_type', ctypes.c_uint8),
                ('verify', ctypes.c_uint8), ('reserved', ctypes.c_uint8 * 6)]


@dataclass(frozen=True)
class WriteProviderInfo:
    controller: ControllerId
    token: int
    request_id: int
    connection_lifetime: int
    connection_handle: int
    security_epoch: int
    security_level: int
    deadline_ns: int
    property: int
    offset: int
    value_length: int
    local_tcid: int
    remote_tcid: int
    pi: int
    operation: int
    data_type: int
    verify: bool


def _configure_write(lib):
    methods = {
        'slk_local_service_bind_write_provider': [ctypes.c_void_p, ctypes.c_uint16,
            ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
        'slk_write_provider_fd': [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)],
        'slk_write_provider_next': [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
        'slk_write_provider_free': [ctypes.c_void_p],
        'slk_write_provider_request_info': [ctypes.c_void_p, ctypes.POINTER(_WriteInfo)],
        'slk_write_provider_request_value': [ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)],
        'slk_write_provider_request_reply': [ctypes.c_void_p, ctypes.c_uint16,
            ctypes.c_void_p, ctypes.c_size_t],
        'slk_write_provider_request_free': [ctypes.c_void_p],
    }
    for name, args in methods.items():
        function = getattr(lib, name)
        function.argtypes = args
        function.restype = None if name.endswith('_free') else ctypes.c_int


class WriteProviderRequest(_ProviderRequest):
    """Proposed write and one-shot local result. Apply the actual application
    effect before replying success; timeout/revocation cannot roll it back.
    reply(value,status=0) needs the actually accepted bytes when verify is true,
    otherwise empty. This is local acceptance, never peer delivery.
    """
    _prefix = 'slk_write_provider'
    _raw_type = _WriteInfo

    @staticmethod
    def _decode_info(identity, raw):
        if (raw.offset or raw.data_type or raw.value_length > 2042
                or raw.operation not in (12, 13) or raw.verify not in (0, 1)
                or raw.operation == 12 and raw.verify):
            raise OSError(errno.EPROTO, 'invalid write-provider value context')
        return WriteProviderInfo(identity, raw.token, raw.request_id,
            raw.connection_lifetime, raw.connection_handle, raw.security_epoch,
            raw.security_level, raw.deadline_ns, raw.property, raw.offset,
            raw.value_length, raw.local_tcid, raw.remote_tcid, raw.pi,
            raw.operation, raw.data_type, bool(raw.verify))

    def _snapshot(self):
        buffer = ctypes.create_string_buffer(max(1, self._info.value_length))
        length = ctypes.c_size_t()
        _result(self._lib.slk_write_provider_request_value(
            self._handle, buffer, self._info.value_length, ctypes.byref(length)))
        if length.value != self._info.value_length:
            raise OSError(errno.EPROTO, 'write-provider snapshot length changed')
        self._value = buffer.raw[:length.value]

    @property
    def value(self):
        """Immutable proposed bytes, not proof of current reply authority."""
        return self._value

    def _reply_capacity(self):
        return self._info.value_length if self._info.verify else 0


class WriteProvider(_ProviderInbox):
    """Original write-only inbox. Same Dispatcher16 budget and stop/drain as READ;
    use LocalService.bind_write_provider and keep the original service alive.
    """
    _prefix = 'slk_write_provider'
    _request_type = WriteProviderRequest
