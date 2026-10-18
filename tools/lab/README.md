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
