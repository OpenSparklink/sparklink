"""Synchronous views over the same Rust Client directory stream, no Python D-Bus.

Directory publication is not Native Ready, Down, ownership or a drain barrier.
Snapshot membership and following changes can overlap. Gap requires an explicit
new observer; no automatic resnapshot/reconnect or controller operation occurs.
"""
import ctypes
from dataclasses import dataclass
import errno
import os
import threading

from .client import ControllerId, _ControllerId, _deadline, _result


@dataclass(frozen=True)
class ControllerEvent:
    kind: str
    sequence: int
    controllers: tuple[ControllerId, ...]
    oldest: int = 0
    current: int = 0


class _Event(ctypes.Structure):
    _fields_ = [("sequence", ctypes.c_uint64), ("oldest", ctypes.c_uint64),
                ("current", ctypes.c_uint64), ("kind", ctypes.c_uint32),
                ("reserved", ctypes.c_uint32)]


def _configure(lib):
    signatures = {
        "slk_client_controller_events": [ctypes.c_void_p, ctypes.c_uint64,
                                          ctypes.POINTER(ctypes.c_void_p)],
        "slk_controller_events_next": [ctypes.c_void_p, ctypes.POINTER(_Event),
                                        ctypes.POINTER(_ControllerId), ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t), ctypes.c_uint32,
                                        ctypes.c_uint64],
        "slk_controller_events_close": [ctypes.c_void_p],
    }
    for name, args in signatures.items():
        function = getattr(lib, name)
        function.argtypes = args
        function.restype = None if name.endswith("_close") else ctypes.c_int


def _decode(value, ids, count):
    kinds = {1: "snapshot", 2: "published", 3: "withdrawn", 4: "gap"}
    if value.kind not in kinds or value.reserved or not 0 <= count <= 256:
        raise OSError(errno.EPROTO, "invalid controller observation ABI")
    if ((value.kind in (2, 3) and (count != 1 or value.sequence == 0))
            or (value.kind == 4 and (count != 0 or not value.sequence < value.oldest <= value.current))
            or (value.kind != 4 and (value.oldest != 0 or value.current != 0))):
        raise OSError(errno.EPROTO, "invalid controller observation shape")
    try:
        controllers = tuple(ControllerId(row.index, row.generation) for row in ids[:count])
    except ValueError as error:
        raise OSError(errno.EPROTO, "invalid controller identity") from error
    if any(any(row.reserved) for row in ids[:count]) or len(set(controllers)) != len(controllers):
        raise OSError(errno.EPROTO, "invalid or duplicate controller identity")
    return ControllerEvent(kinds[value.kind], value.sequence, controllers, value.oldest, value.current)


class ControllerEvents:
    """Create with Client.controller_events(deadline_ns=...).

    Retains that Client's caller and bounded executor even after Client.close().
    close releases only this observer. Calls and close serialize; a waiting call
    uses the same executor queue as its Client, so do not mistake a synchronous
    observer for an independent process or nonblocking dispatcher. Absolute
    deadlines include local queue waiting and are never extended. No fork use.
    """
    def __init__(self):
        raise TypeError("use Client.controller_events(deadline_ns=...)")

    @classmethod
    def _open(cls, client, deadline_ns):
        deadline_ns = _deadline(deadline_ns)
        client._live()
        value = cls.__new__(cls)
        value._lock = threading.RLock()
        value._pid = os.getpid()
        value._handle = ctypes.c_void_p()
        value._lib = client._lib
        _configure(value._lib)
        with client._lock:
            client._live()
            try:
                _result(value._lib.slk_client_controller_events(client._handle, deadline_ns,
                                                               ctypes.byref(value._handle)))
            except BaseException:
                value.close()
                raise
        return value

    def _live(self):
        if self._pid != os.getpid():
            raise RuntimeError("exec/spawn before opening a new observer after fork")
        if not self._handle:
            raise ValueError("ControllerEvents is closed")

    def next(self, *, deadline_ns, peek=False):
        """Return a typed Snapshot/Published/Withdrawn/Gap observation.

        peek=True retains it; timeout also retains any locally received row.
        A consumed Gap makes future next calls ESTALE. Identity loss/malformed
        remote batches remain terminal in the Rust stream. No automatic retry.
        This operation neither acquires a management lease nor stops discovery.
        """
        deadline_ns = _deadline(deadline_ns)
        if type(peek) is not bool:
            raise ValueError("peek must be bool")
        self._live()
        with self._lock:
            self._live()
            output = _Event()
            ids = (_ControllerId * 256)()
            count = ctypes.c_size_t()
            _result(self._lib.slk_controller_events_next(self._handle, ctypes.byref(output),
                                                        ids, len(ids), ctypes.byref(count),
                                                        int(peek), deadline_ns))
            try:
                return _decode(output, ids, count.value)
            except OSError:
                self.close()  # A broken ABI cannot be silently retried/resnapshotted.
                raise

    def close(self):
        if self._pid != os.getpid():
            raise RuntimeError("cannot close an inherited observer after fork")
        with self._lock:
            if self._handle:
                self._lib.slk_controller_events_close(self._handle)
                self._handle = ctypes.c_void_p()

    def __enter__(self):
        self._live()
        with self._lock:
            self._live()
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        if getattr(self, "_pid", None) == os.getpid() and hasattr(self, "_lock"):
            self.close()
