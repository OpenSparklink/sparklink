"""Synchronous application broker client over the existing Rust Client.

No Python D-Bus dispatch, Native lease, authorization cache or Host Engine.
Deadlines are original absolute time.monotonic_ns() values, at most 30s ahead.
Timeout ends local waiting only; remote effects may already have happened.
"""
import ctypes
from dataclasses import dataclass
import os
import socket
import threading

from .channel import _get_channel_lib


@dataclass(frozen=True)
class ControllerId:
    """Registration identity; neither Ready nor an application authorization."""
    index: int
    generation: int

    def __post_init__(self):
        _integer(self.index, 16, "index")
        _integer(self.generation, 64, "generation", nonzero=True)


class _ControllerId(ctypes.Structure):
    _fields_ = [("generation", ctypes.c_uint64), ("index", ctypes.c_uint16),
                ("reserved", ctypes.c_uint8 * 6)]


def _integer(value, bits, name, nonzero=False):
    if type(value) is not int or not int(nonzero) <= value < (1 << bits):
        raise ValueError(f"{name} must be an unsigned {bits}-bit integer")
    return value


def _deadline(value):
    return _integer(value, 64, "deadline_ns", nonzero=True)


def _result(value):
    if value < 0:
        raise OSError(-value, os.strerror(-value))


def _library():
    lib = _get_channel_lib()
    signatures = {
        "slk_client_open_system": [ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
        "slk_client_close": [ctypes.c_void_p],
        "slk_client_controllers": [ctypes.c_void_p, ctypes.POINTER(_ControllerId),
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.c_uint64],
        "slk_client_open_channel": [ctypes.c_void_p, ctypes.POINTER(_ControllerId), ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_uint64, ctypes.POINTER(ctypes.c_int)],
        "slk_client_connection": [ctypes.c_void_p, ctypes.POINTER(_ControllerId), ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
        "slk_connection_close": [ctypes.c_void_p],
        "slk_connection_ssap_read": [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_size_t,
                                      ctypes.POINTER(ctypes.c_size_t), ctypes.c_uint64],
        "slk_connection_ssap_write": [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint32,
                                       ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.c_uint64],
    }
    for name, arguments in signatures.items():
        function = getattr(lib, name)
        function.argtypes = arguments
        function.restype = None if name in ("slk_client_close", "slk_connection_close") else ctypes.c_int
    return lib


class Client:
    """One system-bus caller pinned to the current daemon owner.

    Use a context manager or close(). Calls and close are serialized. Cannot be
    used in a fork child; exec/spawn before creating a new Client. Sockets own their
    fds independently and keep normal dup/fork/SCM_RIGHTS/kernel Grant semantics.
    Derived Connection objects retain this caller until their final close;
    closing this Client neither closes sockets nor disconnects a physical link.
    """
    def __init__(self, *, deadline_ns):
        deadline_ns = _deadline(deadline_ns)
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._handle = ctypes.c_void_p()
        self._lib = _library()
        _result(self._lib.slk_client_open_system(deadline_ns, ctypes.byref(self._handle)))

    def _live(self):
        if self._pid != os.getpid():
            raise RuntimeError("exec/spawn before opening a new Client after fork")
        if not self._handle:
            raise ValueError("Client is closed")

    def close(self):
        if self._pid != os.getpid():
            raise RuntimeError("cannot close an inherited Client after fork")
        with self._lock:
            if self._handle:
                self._lib.slk_client_close(self._handle)
                self._handle = ctypes.c_void_p()

    def __enter__(self):
        self._live()
        with self._lock:
            self._live()
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        # Construction may have failed before any resource existed. In a fork
        # child there is no executor thread to join; never call the inherited ABI.
        if getattr(self, "_pid", None) == os.getpid() and hasattr(self, "_lock"):
            self.close()

    def controller_events(self, *, deadline_ns):
        """One directory observer on this caller; not Native state or readiness.

        The derived view retains this Client executor after Client.close().
        """
        from .controller_events import ControllerEvents
        return ControllerEvents._open(self, deadline_ns)

    def controllers(self, *, deadline_ns):
        """One bounded registration snapshot. Growth between calls can ENOBUFS.

        Count and copy reuse the same supplied deadline. No retry or Ready claim.
        """
        deadline_ns = _deadline(deadline_ns)
        self._live()  # Check fork before touching an inherited, possibly locked mutex.
        with self._lock:
            self._live()
            count = ctypes.c_size_t()
            _result(self._lib.slk_client_controllers(self._handle, None, 0,
                                                    ctypes.byref(count), deadline_ns))
            values = (_ControllerId * count.value)()
            if not count.value:
                return ()
            _result(self._lib.slk_client_controllers(self._handle, values, len(values),
                                                    ctypes.byref(count), deadline_ns))
            return tuple(ControllerId(value.index, value.generation) for value in values[:count.value])

    def register_local_service(self, controller, uuid, properties, *, deadline_ns, authorization="none"):
        """Caller-owned local metadata; not remote publication or a callback Engine.

        Derived view retains this original caller. Explicit unregister and local
        close are different; timeout does not prove rollback or remote cleanup.
        """
        from .local_services import LocalService
        return LocalService._register(self, controller, uuid, properties, deadline_ns, authorization)

    def discover(self, controller, *, prefix=b"", minimum_rssi=-128, duration_ms=20000, deadline_ns):
        """Acquire a caller discovery lease; see DiscoverySession for release semantics."""
        from .discovery import DiscoverySession
        return DiscoverySession._open(self, controller, prefix, minimum_rssi, duration_ms, deadline_ns)

    def open_channel(self, controller, connection_path, *, deadline_ns, directions=3, minimum=0):
        """Owned datagram socket for an existing exact connection object.

        TX=1/RX=2/both=3; minimum mechanism 0..2. Grant and actual security remain
        kernel enforced. A returned fd is not negotiation Ready or peer delivery.
        Same-lifetime rebinding/unsupported modes are never retried or downgraded.
        """
        deadline_ns = _deadline(deadline_ns)
        if type(directions) is not int or directions not in (1, 2, 3):
            raise ValueError("directions must be TX=1, RX=2 or both=3")
        if type(minimum) is not int or minimum not in (0, 1, 2):
            raise ValueError("minimum must be mechanism 0..2")
        identity, buffer = _connection_input(controller, connection_path)
        fd = ctypes.c_int(-1)
        self._live()
        with self._lock:
            self._live()
            try:
                _result(self._lib.slk_client_open_channel(self._handle, ctypes.byref(identity), buffer,
                                                         len(buffer), directions, minimum, deadline_ns,
                                                         ctypes.byref(fd)))
            except BaseException:
                if fd.value >= 0:
                    os.close(fd.value)
                raise
        # Transfer successful ownership directly to the standard socket object.
        # Family/type/proto are the existing fixed channel contract, not Python's
        # autodetection: this unpublished kernel family has no getname operation.
        try:
            return socket.socket(46, socket.SOCK_DGRAM, 0, fileno=fd.value)
        except BaseException:
            os.close(fd.value)
            raise

    def connection(self, controller, connection_path, *, deadline_ns):
        """Pin one real connection identity, without owning its physical lifetime.

        The view retains this caller after Client.close; it never follows a
        replacement daemon/generation/lifetime. No channel or management lease
        is created. Close the returned view explicitly or use a context manager.
        """
        deadline_ns = _deadline(deadline_ns)
        identity, path = _connection_input(controller, connection_path)
        view = Connection._empty(self._lib)
        self._live()
        with self._lock:
            self._live()
            try:
                _result(self._lib.slk_client_connection(self._handle, ctypes.byref(identity), path,
                                                        len(path), deadline_ns, ctypes.byref(view._handle)))
            except BaseException:
                view.close()
                raise
        return view


def _connection_input(controller, connection_path):
    if not isinstance(controller, ControllerId) or type(connection_path) is not str:
        raise ValueError("typed ControllerId and connection object path required")
    path = connection_path.encode("utf-8")
    if not 1 <= len(path) <= 256 or b"\0" in path:
        raise ValueError("connection object path must be 1..256 UTF-8 bytes without NUL")
    return (_ControllerId(controller.generation, controller.index),
            (ctypes.c_uint8 * len(path)).from_buffer_copy(path))


class Connection:
    """Owner/lifetime-pinned observation from Client.connection, not a lease.

    close releases this view and, when last, joins the existing caller executor;
    it never implicitly disconnects. No use/close of an inherited view after fork.
    """
    def __init__(self):
        raise TypeError("use Client.connection")

    @classmethod
    def _empty(cls, lib):
        view = object.__new__(cls)
        # Allocate the Python wrapper before native ownership exists. A later
        # ctypes success writes its owned handle directly into this object.
        view._lib, view._handle = lib, ctypes.c_void_p()
        view._pid, view._lock = os.getpid(), threading.RLock()
        return view

    def _live(self):
        if self._pid != os.getpid():
            raise RuntimeError("cannot use an inherited Connection after fork")
        if not self._handle:
            raise ValueError("Connection is closed")

    def close(self):
        if self._pid != os.getpid():
            raise RuntimeError("cannot close an inherited Connection after fork")
        with self._lock:
            if self._handle:
                self._lib.slk_connection_close(self._handle)
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

    def ssap(self):
        """A thin remote read/write view of slkd's existing unique Engine."""
        self._live()
        return RemoteSsap(self)


class RemoteSsap:
    """No wire codec, remote cache, retries or transactions in this binding.

    Methods return exactly the existing Rust RemoteSsap result bytes. This is a
    protocol result, not evidence that a peer application processed a write.
    Local timeout does not undo a possibly committed remote operation. The
    current RPC has no new cross-process original-deadline field.
    """
    def __init__(self, connection):
        self._connection = connection

    def _call(self, handle, minimum, deadline_ns, value):
        _integer(handle, 16, "handle", nonzero=True)
        if type(minimum) is not int or minimum not in (0, 1, 2):
            raise ValueError("minimum must be mechanism 0..2")
        deadline_ns = _deadline(deadline_ns)
        # Fixed memory budget, not negotiated MTU or long-write support. A
        # single operation, never count-query/retry after an executed remote read.
        output = (ctypes.c_uint8 * 65535)()
        count = ctypes.c_size_t()
        connection = self._connection
        connection._live()
        with connection._lock:
            connection._live()
            if value is None:
                status = connection._lib.slk_connection_ssap_read(
                    connection._handle, handle, minimum, output, len(output),
                    ctypes.byref(count), deadline_ns)
            else:
                data = (ctypes.c_uint8 * len(value)).from_buffer_copy(value)
                status = connection._lib.slk_connection_ssap_write(
                    connection._handle, handle, minimum, data, len(data), output,
                    len(output), ctypes.byref(count), deadline_ns)
            _result(status)
        return bytes(output[:count.value])

    def read(self, handle, *, deadline_ns, minimum=0):
        return self._call(handle, minimum, deadline_ns, None)

    def write(self, handle, value, *, deadline_ns, minimum=0):
        """Existing short write only; oversize explicitly rejected, never sliced."""
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("SSAP value must be bytes-like")
        if len(value) > 65535 or (isinstance(value, memoryview) and value.nbytes > 65535):
            import errno
            raise OSError(errno.EMSGSIZE, os.strerror(errno.EMSGSIZE))
        return self._call(handle, minimum, deadline_ns, bytes(value))
