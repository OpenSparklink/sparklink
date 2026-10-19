"""Caller-owned local SSAP registration over the sole Rust application client.

Not manager staging, a wire Engine or remote service-publication receipt.
Explicit unregister and local close/context exit have different semantics.
"""
import ctypes
from dataclasses import dataclass
import errno
import os
import threading
import time
import select
from .client import ControllerId, _ControllerId, _deadline, _result
from .ssap import SsapOperations, SsapAccess


class _Property(ctypes.Structure):
    _fields_ = [('operations', ctypes.c_uint32), ('access', ctypes.c_uint32),
                ('value_length', ctypes.c_uint16), ('uuid_length', ctypes.c_uint8),
                ('reserved', ctypes.c_uint8 * 5), ('uuid', ctypes.c_uint8 * 16),
                ('value', ctypes.c_uint8 * 2042), ('tail', ctypes.c_uint8 * 2)]


class _Receipt(ctypes.Structure):
    _fields_ = [('controller', _ControllerId), ('start', ctypes.c_uint16),
                ('end', ctypes.c_uint16), ('property_count', ctypes.c_uint16),
                ('reserved', ctypes.c_uint8 * 2), ('handles', ctypes.c_uint16 * 64)]


@dataclass(frozen=True)
class LocalProperty:
    uuid: bytes
    operations: SsapOperations
    access: SsapAccess
    value: bytes = b''

    def __post_init__(self):
        if not isinstance(self.uuid, bytes) or len(self.uuid) not in (2, 16) or not any(self.uuid):
            raise ValueError('nonzero 2/16-byte property UUID required')
        if not isinstance(self.operations, SsapOperations) or not isinstance(self.access, SsapAccess):
            raise TypeError('validated SsapOperations and SsapAccess required')
        if not isinstance(self.value, bytes) or len(self.value) > 2042:
            raise ValueError('bounded 0..2042-byte initial local value required')

    def _encode(self):
        p = _Property()
        p.operations, p.access = self.operations.bits, self.access.bits
        p.uuid_length, p.value_length = len(self.uuid), len(self.value)
        p.uuid[:len(self.uuid)] = self.uuid
        p.value[:len(self.value)] = self.value
        return p


@dataclass(frozen=True)
class LocalServiceReceipt:
    controller: ControllerId
    start: int
    end: int
    handles: tuple[int, ...]


def _configure(lib):
    functions = {
        'slk_client_register_local_service': [ctypes.c_void_p, ctypes.POINTER(_ControllerId),
            ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(_Property), ctypes.c_size_t,
            ctypes.c_uint32, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
        'slk_local_service_receipt': [ctypes.c_void_p, ctypes.POINTER(_Receipt)],
        'slk_local_service_read': [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.c_uint64],
        'slk_local_service_unregister': [ctypes.c_void_p, ctypes.c_uint64],
        'slk_local_service_free': [ctypes.c_void_p],
        'slk_local_service_authorization_fd': [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)],
        'slk_local_service_next_authorization': [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
    }
    for name, args in functions.items():
        f = getattr(lib, name)
        f.argtypes = args
        f.restype = None if name.endswith('_free') else ctypes.c_int


class LocalService:
    """Create through Client.register_local_service, retaining the same caller.

    Supports READ/WRITE_WITH_RSP initial values. authorization='requests' enables
    explicit bounded application decisions;default 'none' refuses approval bits. Other
    mechanism requirements remain enforced by the existing daemon/Engine.
    Receipt is local metadata only. unregister acknowledges original-owner local
    removal; timeout does not prove rollback/removal or remote peer completion.
    close/context exit free only the local reference. Other derived objects can
    keep that caller and service alive. No automatic retries, implicit global
    removal or controller disconnect. Do not use an inherited object after fork.
    """
    def __init__(self):
        raise TypeError('create through Client.register_local_service')

    def __del__(self):
        # Local reference only;never unregister,follow an owner or touch a fork copy.
        if getattr(self, '_handle', None) and getattr(self, '_pid', None) == os.getpid():
            self.close()

    @classmethod
    def _register(cls, client, controller, uuid, properties, deadline_ns, authorization):
        if not isinstance(controller, ControllerId):
            raise TypeError('immutable ControllerId required')
        if not isinstance(uuid, bytes) or len(uuid) not in (2, 16) or not any(uuid):
            raise ValueError('nonzero 2/16-byte service UUID required')
        if not isinstance(properties, (tuple, list)) or not 1 <= len(properties) <= 64:
            raise ValueError('1..64 LocalProperty definitions required')
        if any(not isinstance(p, LocalProperty) for p in properties):
            raise TypeError('LocalProperty definitions required')
        if authorization not in ('none', 'requests'):
            raise ValueError('authorization must be none or requests')
        deadline_ns = _deadline(deadline_ns)
        values = (_Property * len(properties))(*(p._encode() for p in properties))
        identity = _ControllerId(controller.generation, controller.index)
        output = ctypes.c_void_p()
        client._live()
        with client._lock:
            client._live()
            _configure(client._lib)
            _result(client._lib.slk_client_register_local_service(client._handle,
                ctypes.byref(identity), uuid, len(uuid), values, len(values),
                1 if authorization == 'requests' else 0, deadline_ns,
                ctypes.byref(output)))
            if not output.value:
                raise OSError(errno.EPROTO, 'missing local-service view')
            self = object.__new__(cls)
            self._lib, self._handle = client._lib, output
            self._pid, self._lock = os.getpid(), threading.RLock()
            try:
                raw = _Receipt()
                _result(self._lib.slk_local_service_receipt(self._handle, ctypes.byref(raw)))
                handles = tuple(raw.handles[:raw.property_count])
                if (raw.controller.index != controller.index
                        or raw.controller.generation != controller.generation
                        or any(raw.controller.reserved) or any(raw.reserved)
                        or not 0 < raw.start < raw.end or raw.property_count != len(properties)
                        or any(raw.handles[raw.property_count:])
                        or any(not raw.start < h <= raw.end for h in handles)
                        or any(a >= b for a, b in zip(handles, handles[1:]))):
                    raise OSError(errno.EPROTO, 'invalid local-service receipt ABI')
                self._receipt = LocalServiceReceipt(controller, raw.start, raw.end, handles)
            except BaseException:
                self.close()
                raise
            return self

    @property
    def receipt(self):
        return self._receipt

    def _live(self):
        if os.getpid() != self._pid:
            raise RuntimeError('local-service objects cannot be used after fork')
        if not self._handle.value:
            raise RuntimeError('local-service view closed')

    def authorization_fd(self):
        """New caller-owned CLOEXEC poll-only fd;never read/write its counter.

        It conveys readiness,not decision authority or a caller reference.
        Always attempt next before waiting. Close this duplicate with os.close.
        """
        self._live()
        with self._lock:
            self._live()
            fd = ctypes.c_int(-1)
            _result(self._lib.slk_local_service_authorization_fd(self._handle, ctypes.byref(fd)))
            return fd.value

    def next_authorization(self, *, deadline_ns=None):
        """One opaque request;None is nonblocking(EAGAIN),otherwise original <=30s.

        No service lock spans poll. Service close/unregister/daemon loss wakes
        it. Release each request after replying;one delivered view holds capacity
        through actual callback drain. This is not a remote-completion wait.
        """
        from .service_authorization import AuthorizationRequest
        if deadline_ns is not None:
            deadline_ns = _deadline(deadline_ns)
            left = deadline_ns - time.monotonic_ns()
            if left <= 0:
                raise OSError(errno.ETIMEDOUT, 'original authorization wait expired')
            if left > 30_000_000_000:
                raise ValueError('authorization wait exceeds30 seconds')
        fd = None
        try:
            while True:
                if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
                    raise OSError(errno.ETIMEDOUT, 'original authorization wait expired')
                self._live()
                with self._lock:
                    self._live()
                    output = ctypes.c_void_p()
                    code = self._lib.slk_local_service_next_authorization(self._handle, ctypes.byref(output))
                    if code != -errno.EAGAIN or deadline_ns is None:
                        _result(code)
                        request = AuthorizationRequest._from_view(self._lib, output, self.receipt)
                        if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
                            request.close()
                            raise OSError(errno.ETIMEDOUT, 'original authorization wait expired')
                        return request
                if fd is None:
                    fd = self.authorization_fd()
                left = deadline_ns - time.monotonic_ns()
                if left <= 0:
                    raise OSError(errno.ETIMEDOUT, 'original authorization wait expired')
                poller = select.poll()
                poller.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
                events = poller.poll((left + 999_999) // 1_000_000)
                if any(flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL) for _, flags in events):
                    raise OSError(errno.EIO, 'authorization notification fd failed')
        finally:
            if fd is not None:
                os.close(fd)

    def read_local(self, handle, *, deadline_ns, capacity=2042):
        """Current local value; a fresh read after ENOBUFS can observe new data."""
        if type(handle) is not int or not 1 <= handle <= 65535:
            raise ValueError('nonzero property handle required')
        if type(capacity) is not int or not 0 <= capacity <= 2042:
            raise ValueError('bounded capacity0..2042 required')
        deadline_ns = _deadline(deadline_ns)
        self._live()
        with self._lock:
            self._live()
            buffer = (ctypes.c_uint8 * capacity)()
            count = ctypes.c_size_t()
            _result(self._lib.slk_local_service_read(self._handle, handle,
                buffer if capacity else None, capacity, ctypes.byref(count), deadline_ns))
            if count.value > capacity:
                raise OSError(errno.EPROTO, 'local-service read length exceeds ABI buffer')
            return bytes(buffer[:count.value])

    def unregister(self, *, deadline_ns):
        deadline_ns = _deadline(deadline_ns)
        self._live()
        with self._lock:
            self._live()
            _result(self._lib.slk_local_service_unregister(self._handle, deadline_ns))

    def close(self):
        if os.getpid() != self._pid:
            raise RuntimeError('local-service objects cannot be closed after fork')
        with self._lock:
            if self._handle.value:
                self._lib.slk_local_service_free(self._handle)
                self._handle = ctypes.c_void_p()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *_):
        self.close()
