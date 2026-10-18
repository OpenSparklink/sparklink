"""Application discovery over the sole Rust lease and daemon coordinator."""
import ctypes
from dataclasses import dataclass
import errno
import os
import threading
from .client import ControllerId, _ControllerId, _deadline, _result


class _Batch(ctypes.Structure):
    _fields_ = [("generation", ctypes.c_uint64), ("session", ctypes.c_uint64),
                ("dropped", ctypes.c_uint64), ("kernel_lost", ctypes.c_uint64),
                ("version", ctypes.c_uint16), ("reserved", ctypes.c_uint8 * 6)]


class _Report(ctypes.Structure):
    _fields_ = [("sequence", ctypes.c_uint64), ("kernel_boottime_ns", ctypes.c_uint64),
                ("rssi", ctypes.c_int16), ("data_length", ctypes.c_uint16),
                ("address_type", ctypes.c_uint8), ("rssi_known", ctypes.c_uint8),
                ("address", ctypes.c_uint8 * 6), ("header", ctypes.c_uint8 * 23),
                ("data", ctypes.c_uint8 * 255), ("reserved", ctypes.c_uint8 * 6)]


@dataclass(frozen=True)
class DiscoveryReport:
    sequence: int
    kernel_boottime_ns: int
    address_type: int
    address: bytes
    rssi: int | None
    header: bytes
    data: bytes


@dataclass(frozen=True)
class DiscoveryBatch:
    controller: ControllerId
    session: int
    dropped: int
    kernel_lost: int
    reports: tuple[DiscoveryReport, ...]


def _configure(lib):
    functions = {
        "slk_client_discover": [ctypes.c_void_p, ctypes.POINTER(_ControllerId), ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.c_int16, ctypes.c_uint32, ctypes.c_uint64,
                                 ctypes.POINTER(ctypes.c_void_p)],
        "slk_discovery_identity": [ctypes.c_void_p, ctypes.POINTER(_ControllerId), ctypes.POINTER(ctypes.c_uint64)],
        "slk_discovery_read": [ctypes.c_void_p, ctypes.POINTER(_Batch), ctypes.POINTER(_Report),
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.c_uint32, ctypes.c_uint64],
        "slk_discovery_release": [ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint32)],
        "slk_discovery_free": [ctypes.c_void_p],
    }
    for name, args in functions.items():
        function = getattr(lib, name)
        function.argtypes = args
        function.restype = None if name.endswith("_free") else ctypes.c_int


def _decode(metadata, rows, count, controller, session):
    if (metadata.version != 1 or metadata.generation != controller.generation
            or metadata.session != session or not session or any(metadata.reserved)
            or not 0 <= count <= 32):
        raise OSError(errno.EPROTO, "invalid discovery batch ABI")
    result = []
    sequence = 0
    for row in rows[:count]:
        if (row.sequence <= sequence or row.address_type > 1 or row.rssi_known not in (0, 1)
                or not -128 <= row.rssi <= 127 or bool(row.rssi_known) != (row.rssi != 127)
                or row.data_length > 255 or any(row.reserved) or any(row.data[row.data_length:])
                or row.header[1] != row.address_type or bytes(row.header[2:8]) != bytes(row.address)):
            raise OSError(errno.EPROTO, "invalid discovery report ABI")
        result.append(DiscoveryReport(row.sequence, row.kernel_boottime_ns, row.address_type,
                                      bytes(row.address), row.rssi if row.rssi_known else None,
                                      bytes(row.header), bytes(row.data[:row.data_length])))
        sequence = row.sequence
    return DiscoveryBatch(controller, session, metadata.dropped, metadata.kernel_lost, tuple(result))


class DiscoverySession:
    """Create through Client.discover(...), sharing its caller and bounded executor.

    read is a destructive, finite-batch observation; it is not lossless delivery
    or a connection/security state. release(deadline_ns=...) withdraws this lease
    and returns whether the broker confirmed last-lease physical STOP. A timeout
    cannot prove cleanup or undo remote effects. close/context exit free local
    references only; without release, owner loss/finite lease expiry bound cleanup.
    Calls serialize, and a waiting read can delay other calls on the same Client.
    Original deadlines include queue waiting. No cross-fork use or automatic retry.
    """
    def __init__(self):
        raise TypeError("use Client.discover(...)")

    @classmethod
    def _open(cls, client, controller, prefix, minimum_rssi, duration_ms, deadline_ns):
        deadline_ns = _deadline(deadline_ns)
        if not isinstance(controller, ControllerId):
            raise TypeError("controller must be ControllerId")
        if not isinstance(prefix, (bytes, bytearray, memoryview)):
            raise TypeError("prefix must be bytes-like")
        prefix = bytes(prefix)
        if (len(prefix) > 64 or type(minimum_rssi) is not int or not -128 <= minimum_rssi <= 20
                or type(duration_ms) is not int or not 250 <= duration_ms <= 60000):
            raise ValueError("invalid discovery filter or lease duration")
        client._live()
        value = cls.__new__(cls)
        value._lock, value._pid = threading.RLock(), os.getpid()
        value._handle, value._lib = ctypes.c_void_p(), client._lib
        _configure(value._lib)
        identity = _ControllerId(controller.generation, controller.index)
        with client._lock:
            client._live()
            try:
                _result(value._lib.slk_client_discover(client._handle, ctypes.byref(identity), prefix,
                                                       len(prefix), minimum_rssi, duration_ms, deadline_ns,
                                                       ctypes.byref(value._handle)))
                session = ctypes.c_uint64()
                returned = _ControllerId()
                _result(value._lib.slk_discovery_identity(value._handle, ctypes.byref(returned), ctypes.byref(session)))
                if (returned.index, returned.generation) != (controller.index, controller.generation) or any(returned.reserved) or not session.value:
                    raise OSError(errno.EPROTO, "invalid acquired discovery identity")
                value.controller, value.session_id = controller, session.value
            except BaseException:
                value.close()
                raise
        return value

    def _live(self):
        if self._pid != os.getpid():
            raise RuntimeError("exec/spawn before creating a discovery lease after fork")
        if not self._handle:
            raise ValueError("DiscoverySession is closed")

    def read(self, *, deadline_ns, wait=True, peek=False):
        deadline_ns = _deadline(deadline_ns)
        if type(wait) is not bool or type(peek) is not bool:
            raise ValueError("wait and peek must be bool")
        self._live()
        with self._lock:
            self._live()
            metadata, rows, count = _Batch(), (_Report * 32)(), ctypes.c_size_t()
            _result(self._lib.slk_discovery_read(self._handle, ctypes.byref(metadata), rows, 32,
                                                ctypes.byref(count), int(wait) | (int(peek) << 1), deadline_ns))
            try:
                return _decode(metadata, rows, count.value, self.controller, self.session_id)
            except OSError:
                self.close()  # Invalid ABI is not silently retried or relabelled.
                raise

    def release(self, *, deadline_ns):
        deadline_ns = _deadline(deadline_ns)
        self._live()
        with self._lock:
            self._live()
            stopped = ctypes.c_uint32()
            _result(self._lib.slk_discovery_release(self._handle, deadline_ns, ctypes.byref(stopped)))
            if stopped.value not in (0, 1):
                self.close()
                raise OSError(errno.EPROTO, "invalid discovery release result")
            return bool(stopped.value)

    def close(self):
        if self._pid != os.getpid():
            raise RuntimeError("cannot free an inherited discovery view after fork")
        with self._lock:
            if self._handle:
                self._lib.slk_discovery_free(self._handle)
                self._handle = ctypes.c_void_p()

    def __enter__(self):
        with self._lock:
            self._live()
        return self

    def __exit__(self, *_):
        self.close()
