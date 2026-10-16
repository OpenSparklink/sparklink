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
    SleDiagnosticResult, SleDiagnosticSubmit, SleConnectionSubmit, SleConnectionResult,
    SleLinkSnapshot, SleRegistrationSnapshot, SleChannelInfo, SleChannelTxStatus, SleSessionTxStatus,
    SleSecurityNegotiationSubmit, SleSecurityNegotiationResult, SleSecurityNegotiationCancel, SleSecurityNumericConfirm, SleConnectionSecurity,
)

_native_library = None


def _get_native_lib():
    global _native_library
    lib = _get_lib()
    if _native_library is lib:
        return lib
    if any(ctypes.alignment(t) != 8 for t in (
        SleControllerSnapshot, SleRegistrationSnapshot, SleManagementQuery, SleDiscoverySubmit,
        SleDiscoveryResult, SleDiscoveryTiming, SleControllerEventQuery, SleSnoopQuery,
        SleDiagnosticResult, SleDiagnosticSubmit, SleConnectionSubmit, SleConnectionResult,
        SleSecurityNegotiationSubmit, SleSecurityNegotiationResult, SleSecurityNegotiationCancel, SleSecurityNumericConfirm, SleConnectionSecurity,
    )):
        raise OSError("native UAPI requires ctypes with 8-byte structure alignment")
    handle = ctypes.c_void_p
    u64, u32 = ctypes.c_uint64, ctypes.c_uint32
    signatures = {
        "slk_channel_info": [ctypes.c_int, ctypes.POINTER(SleChannelInfo)],
        "slk_channel_tx_status": [ctypes.c_int, ctypes.POINTER(SleChannelTxStatus)],
        "slk_session_tx_status": [ctypes.c_int, ctypes.POINTER(SleSessionTxStatus)],
        "slk_adapter_select": [handle, ctypes.c_uint16],
        "slk_adapter_fd": [handle],
        "slk_device_mask": [handle, ctypes.POINTER(ctypes.c_uint16)],
        "slk_registration_snapshot": [handle, ctypes.c_uint16, u64, ctypes.POINTER(SleRegistrationSnapshot)],
        "slk_controller_snapshot": [handle, u64, ctypes.POINTER(SleControllerSnapshot)],
        "slk_link_snapshot": [handle, u64, ctypes.POINTER(SleLinkSnapshot)],
        "slk_security_negotiation_submit": [handle, ctypes.POINTER(SleSecurityNegotiationSubmit)],
        "slk_security_negotiation_cancel": [handle, ctypes.POINTER(SleSecurityNegotiationCancel)],
        "slk_security_numeric_confirm": [handle,ctypes.POINTER(SleSecurityNumericConfirm)],
        "slk_connection_security": [handle,u64,u64,ctypes.c_uint16,ctypes.POINTER(SleConnectionSecurity)],
        "slk_security_negotiation_result": [handle,u64,u64,ctypes.c_uint16,u64,ctypes.POINTER(SleSecurityNegotiationResult)],
        "slk_management_acquire": [handle, u64, u32, ctypes.POINTER(u64)],
        "slk_management_query": [handle, u64, ctypes.POINTER(SleManagementQuery)],
        "slk_management_release": [handle, u64, u64, u32],
        "slk_connection_submit_v2": [handle, ctypes.POINTER(SleConnectionSubmit)],
        "slk_connection_result": [handle, u64, u64, ctypes.POINTER(SleConnectionResult)],
        "slk_discovery_submit": [handle, ctypes.POINTER(SleDiscoverySubmit)],
        "slk_discovery_timing": [handle, u64, u64, ctypes.POINTER(SleDiscoveryTiming)],
        "slk_discovery_result": [handle, u64, u64, ctypes.POINTER(SleDiscoveryResult)],
        "slk_controller_event": [handle, ctypes.POINTER(SleControllerEventQuery)],
        "slk_snoop": [handle, ctypes.POINTER(SleSnoopQuery)],
        "slk_diagnostic_submit": [handle, ctypes.POINTER(SleDiagnosticSubmit)],
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


def registration_snapshot(index, generation=0, dev_path="/dev/sparklink"):
    """Observe Core pending/fault/installed/retiring without selecting a Runtime.

    Installed is not Host Ready. A nonzero generation requires that exact
    registration; observation does not keep the device present or grant authority.
    """
    index = _unsigned(index, 4, "index")
    generation = _unsigned(generation, 64, "generation")
    lib = _get_native_lib()
    path = dev_path.encode('utf-8') if isinstance(dev_path, str) else dev_path
    handle = lib.slk_adapter_open(path)
    if not handle:
        raise SparkLinkError(f'Failed to open adapter: {dev_path}')
    try:
        result = SleRegistrationSnapshot()
        code = lib.slk_registration_snapshot(handle, index, generation, ctypes.byref(result))
        if code < 0:
            raise OSError(-code, f"registration snapshot: {os.strerror(-code)}")
        return result
    finally:
        lib.slk_adapter_free(handle)


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

    def connection_security(self, generation, lifetime, handle):
        """Current scalar mechanism snapshot; never identity/Bond/authorization."""
        _unsigned(generation, 64, "generation", nonzero=True)
        _unsigned(lifetime, 64, "lifetime", nonzero=True)
        _unsigned(handle, 12, "handle")
        value = SleConnectionSecurity()
        self._invoke('slk_connection_security', generation, lifetime, handle, ctypes.byref(value))
        if ((value.generation,value.lifetime,value.handle,value.version) != (generation,lifetime,handle,1)
                or not value.security_epoch or value.profile != 1 or value.error
                or (value.level,value.flags,value.method,value.key_size) not in
                   [(0,0,0,0),(1,13,3,16),(2,15,4,16)]):
            raise OSError(errno.EPROTO, "invalid connection security snapshot")
        return value

    def submit_security_negotiation(self, request):
        """Explicit known no-MITM approval; no Agent, authenticated identity or Bond promise."""
        if not isinstance(request,SleSecurityNegotiationSubmit):
            raise TypeError("SleSecurityNegotiationSubmit required")
        if request.generation!=self.generation or not request.lifetime or not request.request_id:raise ValueError("exact nonzero selected generation/lifetime/request required")
        self._invoke('slk_security_negotiation_submit',ctypes.byref(request))

    def cancel_security_negotiation(self, request):
        """Local request withdrawal, never release/disconnect or physical success."""
        if not isinstance(request, SleSecurityNegotiationCancel):
            raise TypeError("SleSecurityNegotiationCancel required")
        if request.generation != self.generation or not request.lifetime or not request.request_id:
            raise ValueError("exact nonzero selected generation/lifetime/request required")
        self._invoke('slk_security_negotiation_cancel', ctypes.byref(request))

    def confirm_security_numeric(self, request):
        """Decide one original privileged prompt, never restart its deadline."""
        if not isinstance(request,SleSecurityNumericConfirm):raise TypeError("SleSecurityNumericConfirm required")
        if request.generation!=self.generation or not request.lifetime or not request.request_id or request.accept>1 or request.comparison_code>=1000000:raise ValueError("exact original prompt/decision required")
        self._invoke('slk_security_numeric_confirm',ctypes.byref(request))

    def security_negotiation(self, lifetime, handle, request_id):
        """Original Managed File observes local Complete/peer RX only."""
        for value,maximum in [(lifetime,(1<<64)-1),(request_id,(1<<64)-1)]:
            if type(value) is not int or not 0<value<=maximum:raise ValueError("nonzero uint64 identity required")
        if type(handle) is not int or not 0<=handle<=0x0fff:raise ValueError("12bit handle required")
        result=SleSecurityNegotiationResult()
        self._invoke('slk_security_negotiation_result',self.generation,lifetime,handle,request_id,ctypes.byref(result))
        return result

    def link_snapshot(self):
        """Observed physical table with an atomic event replay barrier."""
        result = SleLinkSnapshot()
        self._invoke('slk_link_snapshot', self.generation, ctypes.byref(result))
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

    def submit_connection(self, request):
        """Typed admission only; operation=3 cancels author, not physical I/O."""
        if not isinstance(request, SleConnectionSubmit):
            raise TypeError("SleConnectionSubmit required")
        if request.generation != self.generation or request.request_id == 0:
            raise ValueError("request must have this generation and a nonzero request id")
        self._invoke('slk_connection_submit_v2', ctypes.byref(request))

    def connection_result(self, generation, request_id):
        """Same-fd bounded result; None means absent/evicted, never success."""
        result = SleConnectionResult()
        generation = _unsigned(generation, 64, "generation", True)
        request_id = _unsigned(request_id, 64, "request_id", True)
        if generation != self.generation:
            raise ValueError("result must have this generation")
        status = self._invoke('slk_connection_result', generation, request_id, ctypes.byref(result))
        return result if status == 1 else None

    def discovery_result(self, request_id):
        request_id = _unsigned(request_id, 64, "request_id", True)
        result = SleDiscoveryResult()
        present = self._invoke('slk_discovery_result', self.generation, request_id, ctypes.byref(result))
        return result if present else None

    def submit_diagnostic(self, request):
        """Submit/cancel using a caller-known ID; reuse the same ID after EFAULT.

        New IDs increase on this open fd. Cancellation preserves any on-wire
        reservation; it cannot make a late reply belong to a subsequent query.
        """
        if not isinstance(request, SleDiagnosticSubmit):
            raise TypeError("SleDiagnosticSubmit required")
        if request.generation != self.generation or request.request_id == 0:
            raise ValueError("request must have this generation and a nonzero request id")
        self._invoke('slk_diagnostic_submit', ctypes.byref(request))
        return request.seq

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


def channel_info(fd):
    """Snapshot of a delegated channel fd, not NativeAdapter's control fd.

    Fixed or negotiated dynamic local/remote TCIDs are returned separately.
    Pending dynamic setup returns EAGAIN; metadata is not a peer delivery ACK.
    No lease acquisition, traffic consumption or permission escalation.
    Metadata is coherent at admission; it does not promise future connectivity.
    """
    if type(fd) is not int or not -(1 << 31) <= fd < (1 << 31):
        raise ValueError("channel fd must be a signed 32-bit integer")
    if ctypes.sizeof(SleChannelInfo) != 40 or ctypes.alignment(SleChannelInfo) != 8:
        raise RuntimeError("channel snapshot requires exact 40-byte/8-aligned ABI")
    value = SleChannelInfo()
    result = _get_native_lib().slk_channel_info(fd, ctypes.byref(value))
    if result < 0:
        raise OSError(-result, "channel capability query")
    return value


def channel_tx_status(fd):
    """No lease or payload; reservations/queue do not mean USB/peer completion."""
    if type(fd) is not int or not -(1 << 31) <= fd < (1 << 31):
        raise ValueError("channel fd must be a signed 32-bit integer")
    if ctypes.sizeof(SleChannelTxStatus) != 64 or ctypes.alignment(SleChannelTxStatus) != 8:
        raise RuntimeError("TX snapshot requires exact64-byte/8-aligned ABI")
    value=SleChannelTxStatus()
    result=_get_native_lib().slk_channel_tx_status(fd,ctypes.byref(value))
    if result < 0:
        raise OSError(-result,"channel TX observation")
    return value

def session_tx_status(fd):
    """No lease or payload; reservations/queue do not mean USB/peer completion."""
    if type(fd) is not int or not -(1 << 31) <= fd < (1 << 31):
        raise ValueError("channel fd must be a signed 32-bit integer")
    if ctypes.sizeof(SleSessionTxStatus) != 64 or ctypes.alignment(SleSessionTxStatus) != 8:
        raise RuntimeError("TX snapshot requires exact64-byte/8-aligned ABI")
    value=SleSessionTxStatus()
    result=_get_native_lib().slk_session_tx_status(fd,ctypes.byref(value))
    if result < 0:
        raise OSError(-result,"Session TX observation")
    return value
