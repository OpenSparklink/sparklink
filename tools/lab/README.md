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
