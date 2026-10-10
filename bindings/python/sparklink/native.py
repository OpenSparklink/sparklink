"""Selected native kernel handles for privileged services and observation.

Ordinary applications use slctl/D-Bus. These bindings do not grant management
or capture permission; every kernel CAP/owner/generation check still applies.
"""
import ctypes
import errno
import os
import threading

from .adapter import SparkLinkError, _get_lib
from .structs import (
    SleControllerSnapshot, SleManagementQuery, SleDiscoverySubmit,
    SleDiscoveryResult, SleDiscoveryTiming, SleControllerEventQuery, SleSnoopQuery,
    SleDiagnosticResult,
)

_native_library = None


def _get_native_lib():
    global _native_library
    lib = _get_lib()
    if _native_library is lib:
        return lib
    if any(ctypes.alignment(t) != 8 for t in (
        SleControllerSnapshot, SleManagementQuery, SleDiscoverySubmit,
        SleDiscoveryResult, SleDiscoveryTiming, SleControllerEventQuery, SleSnoopQuery,
        SleDiagnosticResult,
    )):
        raise OSError("native UAPI requires ctypes with 8-byte structure alignment")
    handle = ctypes.c_void_p
    u64, u32 = ctypes.c_uint64, ctypes.c_uint32
    signatures = {
        "slk_adapter_select": [handle, ctypes.c_uint16],
        "slk_adapter_fd": [handle],
        "slk_device_mask": [handle, ctypes.POINTER(ctypes.c_uint16)],
        "slk_controller_snapshot": [handle, u64, ctypes.POINTER(SleControllerSnapshot)],
        "slk_management_acquire": [handle, u64, u32, ctypes.POINTER(u64)],
        "slk_management_query": [handle, u64, ctypes.POINTER(SleManagementQuery)],
        "slk_management_release": [handle, u64, u64, u32],
        "slk_discovery_submit": [handle, ctypes.POINTER(SleDiscoverySubmit)],
        "slk_discovery_timing": [handle, u64, u64, ctypes.POINTER(SleDiscoveryTiming)],
        "slk_discovery_result": [handle, u64, u64, ctypes.POINTER(SleDiscoveryResult)],
        "slk_controller_event": [handle, ctypes.POINTER(SleControllerEventQuery)],
        "slk_snoop": [handle, ctypes.POINTER(SleSnoopQuery)],
        "slk_diagnostic_result": [handle, u64, u32, ctypes.POINTER(SleDiagnosticResult)],
    }
    for name, arguments in signatures.items():
        try:
            function = getattr(lib, name)
        except AttributeError as error:
            raise OSError("matching native libsparklink symbols required") from error
        function.argtypes = arguments
        function.restype = ctypes.c_int
    _native_library = lib
    return lib


def _unsigned(value, bits, name, nonzero=False):
    if not isinstance(value, int) or not (int(nonzero) <= value < 1 << bits):
        raise ValueError(f"{name} must fit unsigned {bits} bits" + (" and be nonzero" if nonzero else ""))
    return value


class NativeAdapter:
    """Explicitly selected registration; never follows a reused device index.

    Open a new instance after removal. Events/snoop each use an independent
    cursor on this handle; open separate instances for their incompatible fd
    modes. Call poll_event/poll_snoop once before registering fileno with epoll.
    """

    def __init__(self, index, generation=0, dev_path="/dev/sparklink"):
        self._handle = None
        self._lock = threading.RLock()
        index = _unsigned(index, 16, "index")
        generation = _unsigned(generation, 64, "generation")
        lib = _get_native_lib()
        path = dev_path.encode('utf-8') if isinstance(dev_path, str) else dev_path
        self._handle = lib.slk_adapter_open(path)
        if not self._handle:
            raise SparkLinkError(f'Failed to open adapter: {dev_path}')
        try:
            self._invoke('slk_adapter_select', index)
            snapshot = self.snapshot(generation)
            self.index, self.generation = snapshot.dev_index, snapshot.generation
            self._events = SleControllerEventQuery(version=1, generation=self.generation)
            self._snoop = SleSnoopQuery(version=1, generation=self.generation)
        except BaseException:
            self.close()
            raise

    def close(self):
        # ctypes releases the GIL during C calls; serialize free against every
        # call on this handle rather than relying on Python object lifetime.
        lock = getattr(self, '_lock', None)
        if lock is None:
            return
        with lock:
            if self._handle:
                _get_lib().slk_adapter_free(self._handle)
                self._handle = None

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()

    def _invoke(self, name, *arguments):
        with self._lock:
            function = getattr(_get_native_lib(), name)
            return self._native_check(function(self._live(), *arguments), name)

    def _live(self):
        if not self._handle:
            raise OSError(errno.EBADF, "native adapter is closed")
        return self._handle

    @staticmethod
    def _native_check(result, operation):
        if result < 0:
            raise OSError(-result, f"{operation}: {os.strerror(-result)}")
        return result

    def fileno(self):
        """Borrow the fd; do not close it or alter its affinity."""
        return self._invoke('slk_adapter_fd')

    def device_indices(self):
        mask = ctypes.c_uint16()
        self._invoke('slk_device_mask', ctypes.byref(mask))
        return [i for i in range(16) if mask.value & (1 << i)]

    def snapshot(self, generation=None):
        generation = self.generation if generation is None else _unsigned(generation, 64, "generation")
        result = SleControllerSnapshot()
        self._invoke('slk_controller_snapshot', generation, ctypes.byref(result))
        return result

    def management_status(self):
        result = SleManagementQuery()
        self._invoke('slk_management_query', self.generation, ctypes.byref(result))
        return result

    def acquire_management(self, mode):
        if mode not in (1, 2):
            raise ValueError("management mode must be Managed(1) or Diagnostic(2)")
        lease = ctypes.c_uint64()
        self._invoke('slk_management_acquire', self.generation, mode, ctypes.byref(lease))
        return lease.value

    def release_management(self, lease, mode):
        lease = _unsigned(lease, 64, "lease", True)
        if mode not in (1, 2):
            raise ValueError("management mode must be Managed(1) or Diagnostic(2)")
        self._invoke('slk_management_release', self.generation, lease, mode)

    def submit_discovery(self, request):
        if not isinstance(request, SleDiscoverySubmit):
            raise TypeError("SleDiscoverySubmit required")
        if request.generation != self.generation or request.request_id == 0:
            raise ValueError("request must have this generation and a nonzero request id")
        self._invoke('slk_discovery_submit', ctypes.byref(request))

    def discovery_result(self, request_id):
        request_id = _unsigned(request_id, 64, "request_id", True)
        result = SleDiscoveryResult()
        present = self._invoke('slk_discovery_result', self.generation, request_id, ctypes.byref(result))
        return result if present else None

    def diagnostic_result(self, seq):
        """Non-consuming result for this fd, generation and admitted raw sequence.

        Requires Diagnostic ownership and CAP_NET_ADMIN; missing/evicted is
        None. This method does not grant raw submission or management rights.
        """
        seq = _unsigned(seq, 32, "seq", True)
        result = SleDiagnosticResult()
        present = self._invoke('slk_diagnostic_result', self.generation, seq, ctypes.byref(result))
        return result if present else None

    def discovery_timing(self, request_id):
        """Read correlated final successful Complete clock; no permission grant."""
        request_id = _unsigned(request_id, 64, "request_id", True)
        result = SleDiscoveryTiming()
        self._invoke('slk_discovery_timing', self.generation, request_id, ctypes.byref(result))
        return result

    def poll_event(self):
        with self._lock:
            present = self._invoke('slk_controller_event', ctypes.byref(self._events))
            # Copy before unlocking, including concurrent Python readers.
            return type(self._events.event).from_buffer_copy(self._events.event) if present else None

    def poll_snoop(self):
        with self._lock:
            present = self._invoke('slk_snoop', ctypes.byref(self._snoop))
            return type(self._snoop.record).from_buffer_copy(self._snoop.record) if present else None
