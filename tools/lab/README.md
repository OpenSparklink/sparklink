# WS73 ACB transport selftest

`ws73_acb_transport_probe.c` is an explicitly built, signed, external kernel
selftest module for the private VM. It is never a production driver/backend and
must never be loaded on the host. It calls the actual native ACB seam using two
independently observed controller/generation/lifetime/handle tuples. A finite
probe sends fresh random nonces and payloads, takes bytes from the opposite
controller, validates them and sends a reply, alternating directions.

The experimental CUTC/PI framing does not establish CMTC negotiation, dynamic
TCID support, ordinary-user sockets or SSAP interoperability. A successful USB
write is insufficient: the verifier requires exact payloads at both USB/HCC/A3
ends and four real NOCP-completed packets per controller and phase.

Preparation requires `--acb-probe-module` plus matching signed module/build
provenance. Execution additionally requires `--acb-transport-probe`, a native
VM and the ordinary connection gate. The root supervisor independently checks
the actual canonical link tables before/after loading the test; ordinary
slctl still establishes and disconnects each link. Normal qualification keeps
taint zero. Only this explicit test expects exactly 4096 (external module),
records that value and does not promote its result to socket qualification.
No `intree` tag, fabricated event, completion or RX data hides that distinction.

The module is built separately against the verified VM kernel, stripped and
signed with that build's key. Its `.build.json` records terminal build status,
source and module SHA256 values. Preparation freezes these files; a changed
module, mismatched source, missing signature or release mismatch is rejected.
All buffers and waits have finite limits. Failed probes remain failed evidence.

## Pending-initialization USB barrier (test fixture candidate)

`ws73_cmtc_hold_selector.h` and `qemu_cmtc_capability_hold.patch` extend the
existing immutable two-second real-IN81 hold fixture. Apply the patch to its
reviewed baseline `host-libusb.c` (SHA256
`4443a20194d4b2584cd234306c43deedb5a3f77d396c44f79370054e495955ed`),
with the header beside the copied source. Keep the original artifact unchanged.
The patch changes only selection: all nonmatches pass through unchanged;
matched real transfers retain the existing request/buffer/timer/drop/drain
ownership. The selector clears on transport close, rejects frame-skip/error
composition, and remains disabled by default. It cannot establish generation,
lifetime, readiness or proof of cleanup.

The current source profile is SDK110 HCC service A/queue8, A3 complete PDU,
CMTC TCID2 CapabilityRsp id0/basic MTU2042/MPS2047. Other formats are nonmatches;
changing the profile needs a reviewed fixture and new source identity. Tests
compile the actual header and use synthetic bytes. A separate local audit
checks retained real RX bytes against the existing independent capture decoder;
it is not a new device run. No raw private captures or firmware are copied here.
The fixture is not yet a qualified VM initialization gate. See the canonical
R5f9 plan for staged ownership, original deadlines and remaining real checks.

## Bounded libusb event-loop observation fixture

`tools/ws73_qemu_event_observer.py` derives a **separate test-only** QEMU host
source from the exact guarded baseline hash in the tool. It writes exclusively
to a new file. The selected observer binary rejects USB host devices without
the existing explicit WS73 port and reset/detach opt-outs. Preserve the original
source, object closure, binary, preparation and all failed runs.

The fixture counts existing libusb event-pump calls/returns and native callback
entry before the canceled-packet branch, plus request allocation/free. It adds
a 100 ms metadata heartbeat, limited to 4096 ticks per device and a scan of 128
pending requests. Closing retires the observer timer before the original abort
loop; a separate `drained` snapshot means that loop returned, **not** that
hardware, Linux callbacks, references or protocol debt are proven drained.
No packet bytes, keys, USB operations, protocol results or credit are generated.

`ws73_usb_lifecycle.parse_native(text, explicit_targets)` checks the closed log,
finite sequence, endpoint budgets, counters and terminal snapshots. It does not
replace the original logical-request or application verifier. A budget marker,
missing endpoint/terminal, held/injected callback, or inconsistent counters fails
closed. The actual run must independently verify the original QMP no-injection
contract. The heartbeat itself changes scheduling; results cannot qualify a
performance improvement. Fixture tests are source/metadata tests, not a BQL,
kernel-concurrency, libusb, firmware or RF proof. Compile/link provenance and
real-device execution are separate gates, always VM-only on allocated leaves.

`tools/ws73_qemu_poll_observer.py` derives a further **separate** fixture from
the pinned complete native-observer source. It reuses that timer; it adds no
second timer or event pump. For each native sample it snapshots at most eight
libusb pollfds, calls `poll(..., 0)`, and identifies USB fds using bounded local
`/proc/self/fd` readlink plus matching `fstat/stat` device/inode metadata. It
never reads/reaps an URB or opens a device. Null lookup, overflow, syscall or
identity errors are explicit; they are not successful zero-ready samples.

`ws73_usb_lifecycle.parse_native_poll` requires every original native sample's
following poll record, fd/readiness cardinality and declared USB identities.
Error/hangup bits remain errors; readiness is not a completed data packet or
endpoint attribution. Sampling cannot prove continuous absence between ticks.
The host's usbfs poll semantics and source identity must be recorded separately
from the VM kernel; an experiment kernel source is not host-source attestation.
The additional syscalls also perturb scheduling. No performance, RF root cause,
physical drain, generation authentication or business delivery is implied.
