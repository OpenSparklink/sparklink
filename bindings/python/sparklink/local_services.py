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
from .ssap import SsapOperations, SsapAccess, MethodAccess


class _Property(ctypes.Structure):
    _fields_ = [('operations', ctypes.c_uint32), ('access', ctypes.c_uint32),
                ('value_length', ctypes.c_uint16), ('uuid_length', ctypes.c_uint8),
                ('reserved', ctypes.c_uint8 * 5), ('uuid', ctypes.c_uint8 * 16),
                ('value', ctypes.c_uint8 * 2042), ('tail', ctypes.c_uint8 * 2)]


class _Receipt(ctypes.Structure):
    _fields_ = [('controller', _ControllerId), ('start', ctypes.c_uint16),
                ('end', ctypes.c_uint16), ('property_count', ctypes.c_uint16),
                ('method_count', ctypes.c_uint16), ('handles', ctypes.c_uint16 * 64)]


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


class _Method(ctypes.Structure):
    _fields_ = [('access', ctypes.c_uint32), ('uuid_length', ctypes.c_uint8),
                ('reserved', ctypes.c_uint8 * 3), ('uuid', ctypes.c_uint8 * 16)]


@dataclass(frozen=True)
class LocalMethod:
    uuid: bytes
    access: MethodAccess

    def __post_init__(self):
        if not isinstance(self.uuid, bytes) or len(self.uuid) not in (2, 16) or not any(self.uuid):
            raise ValueError('nonzero 2/16-byte method UUID required')
        if not isinstance(self.access, MethodAccess):
            raise TypeError('validated MethodAccess required')

    def _encode(self):
        method = _Method()
        method.access, method.uuid_length = self.access.bits, len(self.uuid)
        method.uuid[:len(self.uuid)] = self.uuid
        return method


@dataclass(frozen=True)
class LocalServiceReceipt:
    controller: ControllerId
    start: int
    end: int
    handles: tuple[int, ...]
    method_handles: tuple[int, ...] = ()

    @property
    def property_handles(self):
        return self.handles[:len(self.handles) - len(self.method_handles)]


def _configure(lib):
    functions = {
        'slk_client_register_local_service': [ctypes.c_void_p, ctypes.POINTER(_ControllerId),
            ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(_Property), ctypes.c_size_t,
            ctypes.c_uint32, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
        'slk_client_register_local_entries': [ctypes.c_void_p, ctypes.POINTER(_ControllerId),
            ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(_Property), ctypes.c_size_t,
            ctypes.POINTER(_Method), ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
        'slk_local_service_receipt': [ctypes.c_void_p, ctypes.POINTER(_Receipt)],
        'slk_local_service_read': [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.c_uint64],
        'slk_local_service_unregister': [ctypes.c_void_p, ctypes.c_uint64],
        'slk_local_service_replace': [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_uint64],
        'slk_local_service_set_description': [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_uint64],
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

    Supports READ/WRITE_WITH_RSP initial values;NOTIFY/INDICATE require CLIENT_CFG_WR
    and authorization='requests'. CPCD also needs an actual authenticated Session.
    authorization='requests' enables
    explicit bounded application decisions;default 'none' refuses approval bits. Other
    mechanism requirements remain enforced by the existing daemon/Engine.
    Receipt is local metadata only. unregister acknowledges original-owner local
    removal; timeout does not prove rollback/removal or remote peer completion.
    close/context exit free the local reference and stop its Provider inboxes.
    Other caller-owning views can keep that caller alive; Provider inboxes,
    requests and notification fds do not. No automatic retries, implicit global
    removal or controller disconnect. Do not use an inherited object after fork.
    """
    def __init__(self):
        raise TypeError('create through Client.register_local_service')

    def __del__(self):
        # Local reference only;never unregister,follow an owner or touch a fork copy.
        if getattr(self, '_handle', None) and getattr(self, '_pid', None) == os.getpid():
            self.close()

    @classmethod
    def _register(cls, client, controller, uuid, properties, deadline_ns, authorization, *, methods=(), entries=False):
        if not isinstance(controller, ControllerId):
            raise TypeError('immutable ControllerId required')
        if not isinstance(uuid, bytes) or len(uuid) not in (2, 16) or not any(uuid):
            raise ValueError('nonzero 2/16-byte service UUID required')
        if (not isinstance(properties, (tuple, list)) or not isinstance(methods, (tuple, list))
                or not 1 <= len(properties) + len(methods) <= 64):
            raise ValueError('1..64 combined property/method definitions required')
        if any(not isinstance(m, LocalMethod) for m in methods):
            raise TypeError('LocalMethod definitions required')
        if any(not isinstance(p, LocalProperty) for p in properties):
            raise TypeError('LocalProperty definitions required')
        if authorization not in ('none', 'requests'):
            raise ValueError('authorization must be none or requests')
        deadline_ns = _deadline(deadline_ns)
        values = (_Property * len(properties))(*(p._encode() for p in properties))
        method_values = (_Method * len(methods))(*(m._encode() for m in methods))
        identity = _ControllerId(controller.generation, controller.index)
        output = ctypes.c_void_p()
        client._live()
        with client._lock:
            client._live()
            _configure(client._lib)
            arguments = [client._handle, ctypes.byref(identity), uuid, len(uuid), values, len(values)]
            function = client._lib.slk_client_register_local_service
            if entries:
                function = client._lib.slk_client_register_local_entries
                arguments += [method_values, len(method_values)]
            arguments += [1 if authorization == 'requests' else 0, deadline_ns, ctypes.byref(output)]
            _result(function(*arguments))
            if not output.value:
                raise OSError(errno.EPROTO, 'missing local-service view')
            self = object.__new__(cls)
            self._lib, self._handle = client._lib, output
            self._pid, self._lock = os.getpid(), threading.RLock()
            try:
                raw = _Receipt()
                _result(self._lib.slk_local_service_receipt(self._handle, ctypes.byref(raw)))
                total = raw.property_count + raw.method_count
                handles = tuple(raw.handles[:total])
                if (raw.controller.index != controller.index
                        or raw.controller.generation != controller.generation
                        or any(raw.controller.reserved) or raw.method_count != len(methods)
                        or not 0 < raw.start < raw.end or raw.property_count != len(properties)
                        or total > 64 or any(raw.handles[total:])
                        or any(not raw.start < h <= raw.end for h in handles)
                        or any(a >= b for a, b in zip(handles, handles[1:]))):
                    raise OSError(errno.EPROTO, 'invalid local-service receipt ABI')
                self._receipt = LocalServiceReceipt(controller, raw.start, raw.end, handles, handles[len(properties):])
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

    def replace_local(self, handle, value, *, deadline_ns):
        """Local commit only;timeout can leave uncertain effects. Never retries.

        Peer permissions stay unchanged;this sends no notification or wire PDU.
        A separate real peer read can observe the committed current value.
        """
        if type(handle) is not int or not 1 <= handle <= 65535:
            raise ValueError('nonzero property handle required')
        if not isinstance(value, bytes) or len(value) > 2042:
            raise ValueError('bounded 0..2042-byte local value required')
        deadline_ns = _deadline(deadline_ns)
        self._live()
        with self._lock:
            self._live()
            _result(self._lib.slk_local_service_replace(self._handle, handle, value,
                len(value), deadline_ns))

    def bind_read_provider(self, handle, *, deadline_ns):
        """Bind an exact READ property once and return its bounded value inbox.

        The original stored value is discarded. This cannot be undone or
        rebound within the registration; an uncertain bind must not be retried.
        Keep this service alive: the inbox and requests retain no owner/service.
        Authorization remains separate and uses the original callback deadline.
        """
        from .service_provider import ReadProvider, _configure as configure_provider
        return self._bind_provider(handle, deadline_ns, ReadProvider, configure_provider,
                                   'slk_local_service_bind_read_provider')

    def bind_write_provider(self, handle, *, deadline_ns):
        """Bind an original write-only type0 property once. No stored fallback,
        rebind or automatic retry after uncertain commit. Apply the application
        effect before replying; callback expiry cannot reverse that effect.
        """
        from .service_provider import WriteProvider, _configure_write
        return self._bind_provider(handle, deadline_ns, WriteProvider, _configure_write,
                                   'slk_local_service_bind_write_provider')

    def bind_method_provider(self, handle, *, deadline_ns):
        """Bind an original method once; result is independent of its arguments.

        Same original owner, deadline, queue and stop/drain as READ/WRITE.
        Local reply is not peer delivery and does not roll back method effects.
        """
        from .service_provider import MethodProvider, _configure_method
        return self._bind_provider(handle, deadline_ns, MethodProvider, _configure_method,
                                   'slk_local_service_bind_method_provider')

    def _bind_provider(self, handle, deadline_ns, provider, configure, method):
        if type(handle) is not int or not 1 <= handle <= 65535:
            raise ValueError('nonzero property handle required')
        deadline_ns = _deadline(deadline_ns)
        self._live()
        with self._lock:
            self._live()
            configure(self._lib)
            output = ctypes.c_void_p()
            _result(getattr(self._lib, method)(
                self._handle, handle, deadline_ns, ctypes.byref(output)))
            return provider._from_view(self._lib, output, self.receipt.controller, handle)

    def set_description(self, handle, description, *, deadline_ns):
        """Set a public read-only description,1..244 UTF-8 bytes,as this owner.

        Success is local commit only;timeout can leave uncertain effects. No
        peer publication claim,retry,property mutation or permission change.
        """
        if type(handle) is not int or not 1 <= handle <= 65535:
            raise ValueError('nonzero property handle required')
        if not isinstance(description, str):
            raise TypeError('UTF-8 description text required')
        value = description.encode('utf-8')
        if not 1 <= len(value) <= 244 or b'\0' in value:
            raise ValueError('description must contain1..244 UTF-8 bytes without NUL')
        deadline_ns = _deadline(deadline_ns)
        self._live()
        with self._lock:
            self._live()
            _result(self._lib.slk_local_service_set_description(self._handle, handle,
                value, len(value), deadline_ns))

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
