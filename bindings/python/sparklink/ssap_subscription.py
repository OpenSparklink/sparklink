"""Thin leased views of the shared Rust client,no codec or protocol Engine.

release observes remote cleanup;close frees local memory only. Destructive read
or renewal timeout can be uncertain. No automatic retry,reconnect or downgrade.
"""
import ctypes
from dataclasses import dataclass
import errno
import itertools
import os
import threading
from .client import ControllerId, _deadline, _integer, _result


class _Info(ctypes.Structure):
    _fields_ = [("generation", ctypes.c_uint64), ("lifetime", ctypes.c_uint64),
                ("security_epoch", ctypes.c_uint64), ("token", ctypes.c_uint64),
                ("expires_ns", ctypes.c_uint64), ("version", ctypes.c_uint32),
                ("controller", ctypes.c_uint16), ("handle", ctypes.c_uint16),
                ("capacity", ctypes.c_uint16), ("handle_count", ctypes.c_uint16),
                ("modes", ctypes.c_uint8), ("state", ctypes.c_uint8),
                ("reserved", ctypes.c_uint8 * 2), ("handles", ctypes.c_uint16 * 32)]


class _Packet(ctypes.Structure):
    _fields_ = [("sequence", ctypes.c_uint64), ("security_epoch", ctypes.c_uint64),
                ("security_level", ctypes.c_uint32), ("pdu_length", ctypes.c_uint16),
                ("indication", ctypes.c_uint8), ("reserved", ctypes.c_uint8 * 1),
                ("pdu", ctypes.c_uint8 * 2048)]


class _Batch(ctypes.Structure):
    _fields_ = [("info", _Info), ("last_sequence", ctypes.c_uint64),
                ("dropped_notifications", ctypes.c_uint64),
                ("refused_indications", ctypes.c_uint64),
                ("discarded_on_close", ctypes.c_uint64), ("flags", ctypes.c_uint32),
                ("count", ctypes.c_uint16), ("reason", ctypes.c_uint8),
                ("reserved", ctypes.c_uint8 * 1), ("packets", _Packet * 16)]


@dataclass(frozen=True)
class SsapSubscriptionInfo:
    """Last validated observation,not an active Grant or Ready declaration."""
    controller: ControllerId
    lifetime: int
    handle: int
    security_epoch: int
    token: int
    expires_ns: int
    handles: tuple
    modes: int
    state: int
    capacity: int


@dataclass(frozen=True)
class SsapSubscriptionPacket:
    sequence: int
    security_epoch: int
    security_level: int
    indication: bool
    pdu: bytes


@dataclass(frozen=True)
class SsapSubscriptionBatch:
    info: SsapSubscriptionInfo
    last_sequence: int
    dropped_notifications: int
    refused_indications: int
    discarded_on_close: int
    flags: int
    reason: int
    packets: tuple


def _invalid():
    raise OSError(errno.EPROTO, 'invalid SSAP subscription ABI result')


def _info(raw):
    if (raw.version != 1 or not raw.generation or not raw.lifetime or not raw.security_epoch
            or not raw.token or not raw.expires_ns or raw.capacity != 16
            or not 1 <= raw.handle_count <= 32 or raw.modes not in (1, 2, 3)
            or raw.state not in (0, 1, 2, 3) or any(raw.reserved)
            or any(raw.handles[raw.handle_count:])):
        _invalid()
    handles = tuple(raw.handles[:raw.handle_count])
    if 0 in handles or len(handles) != len(set(handles)):
        _invalid()
    return SsapSubscriptionInfo(ControllerId(raw.controller, raw.generation), raw.lifetime,
                                raw.handle, raw.security_epoch, raw.token, raw.expires_ns,
                                handles, raw.modes, raw.state, raw.capacity)


def _batch(raw):
    info = _info(raw.info)
    if raw.count > 16 or raw.flags & ~1 or raw.reason > 4 or any(raw.reserved):
        _invalid()
    packets = []
    for p in raw.packets[:raw.count]:
        if (not p.sequence or not p.security_epoch or p.security_level != 2
                or not 6 <= p.pdu_length <= 2048 or p.indication > 1
                or any(p.reserved) or any(p.pdu[p.pdu_length:])):
            _invalid()
        packets.append(SsapSubscriptionPacket(p.sequence, p.security_epoch, p.security_level,
                                              bool(p.indication), bytes(p.pdu[:p.pdu_length])))
    for p in raw.packets[raw.count:]:
        if any(ctypes.string_at(ctypes.addressof(p), ctypes.sizeof(p))):
            _invalid()
    return SsapSubscriptionBatch(info, raw.last_sequence, raw.dropped_notifications,
                                 raw.refused_indications, raw.discarded_on_close, raw.flags,
                                 raw.reason, tuple(packets))


def _configure(lib):
    signatures = {
        'slk_connection_ssap_subscribe': [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16),
            ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_void_p)],
        'slk_ssap_subscription_info': [ctypes.c_void_p, ctypes.POINTER(_Info)],
        'slk_ssap_subscription_read': [ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(_Batch), ctypes.c_uint64],
        'slk_ssap_subscription_renew': [ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(_Info), ctypes.c_uint64],
        'slk_ssap_subscription_release': [ctypes.c_void_p, ctypes.POINTER(_Batch), ctypes.c_uint64],
        'slk_ssap_subscription_free': [ctypes.c_void_p],
    }
    if (ctypes.sizeof(_Info), _Info.handles.offset, ctypes.sizeof(_Packet), _Packet.pdu.offset,
            ctypes.sizeof(_Batch), _Batch.packets.offset) != (120, 56, 2072, 24, 33312, 160):
        _invalid()
    for name, args in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype = None if name.endswith('_free') else ctypes.c_int


class SsapSubscription:
    """Finite lease retaining the originating caller after parent close.

    Destructive reads have no peek/retry or lossless-delivery promise. Protocol
    confirmation is not application processing. release and local close are
    separate;context exit alone is not confirmed remote cleanup. No fork use.
    This is not a socket fd with dup/SCM_RIGHTS semantics.
    """
    def __init__(self):
        raise TypeError('use Connection.ssap().subscribe')

    @classmethod
    def _acquire(cls, connection, handles, modes, duration_ms, deadline_ns):
        handles = tuple(itertools.islice(handles, 33))
        if not 1 <= len(handles) <= 32:
            raise ValueError('1..32 unique handles required')
        for h in handles:
            _integer(h, 16, 'handle', nonzero=True)
        if len(set(handles)) != len(handles):
            raise ValueError('1..32 unique handles required')
        if type(modes) is not int or modes not in (1, 2, 3):
            raise ValueError('modes must be 1,2,3')
        _integer(duration_ms, 32, 'duration_ms')
        if not 250 <= duration_ms <= 60000:
            raise ValueError('duration_ms must be 250..60000')
        deadline_ns = _deadline(deadline_ns)
        connection._live()
        view = object.__new__(cls)
        view._lib, view._handle = connection._lib, ctypes.c_void_p()
        view._pid, view._lock = os.getpid(), threading.RLock()
        _configure(view._lib)
        values = (ctypes.c_uint16 * len(handles))(*handles)
        with connection._lock:
            connection._live()
            _result(view._lib.slk_connection_ssap_subscribe(connection._handle, values,
                len(handles), modes, duration_ms, deadline_ns, ctypes.byref(view._handle)))
        if not view._handle:
            _invalid()
        return view

    def _live(self):
        if self._pid != os.getpid():
            raise RuntimeError('cannot use an inherited SSAP subscription after fork')
        if not self._handle:
            raise ValueError('SSAP subscription is closed')

    def info(self):
        self._live()
        output = _Info()
        with self._lock:
            self._live()
            _result(self._lib.slk_ssap_subscription_info(self._handle, ctypes.byref(output)))
        return _info(output)

    def read(self, *, deadline_ns, wait=True):
        if type(wait) is not bool:
            raise TypeError('wait must be boolean')
        deadline_ns = _deadline(deadline_ns)
        self._live()
        output = _Batch()
        with self._lock:
            self._live()
            _result(self._lib.slk_ssap_subscription_read(self._handle, int(wait),
                                                       ctypes.byref(output), deadline_ns))
        return _batch(output)

    def renew(self, duration_ms, *, deadline_ns):
        _integer(duration_ms, 32, 'duration_ms')
        if not 250 <= duration_ms <= 60000:
            raise ValueError('duration_ms must be 250..60000')
        deadline_ns = _deadline(deadline_ns)
        self._live()
        output = _Info()
        with self._lock:
            self._live()
            _result(self._lib.slk_ssap_subscription_renew(self._handle, duration_ms,
                                                        ctypes.byref(output), deadline_ns))
        return _info(output)

    def release(self, *, deadline_ns):
        """Observe original remote configuration cleanup;failure is uncertain."""
        deadline_ns = _deadline(deadline_ns)
        self._live()
        output = _Batch()
        with self._lock:
            self._live()
            _result(self._lib.slk_ssap_subscription_release(self._handle, ctypes.byref(output), deadline_ns))
        return _batch(output)

    def close(self):
        if self._pid != os.getpid():
            raise RuntimeError('cannot close an inherited SSAP subscription after fork')
        with self._lock:
            if self._handle:
                self._lib.slk_ssap_subscription_free(self._handle)
                self._handle = ctypes.c_void_p()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        if getattr(self, '_pid', None) == os.getpid() and hasattr(self, '_lock'):
            self.close()
