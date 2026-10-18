# Unqualified development models

This unpublished crate preserves the legacy Profile/HID and transport code and
its codec/lifecycle regressions. It is outside the default slkd dependency graph;
public modules are experimental development APIs, not supported application APIs.
Neither workspace compilation nor unit tests qualify the protocols or hardware.

The old daemon `experimental-legacy-profiles` build feature is retired. It
initialized a profile0 registry with no current Native consumer; it must not
reintroduce the removed handle-only event path. The independent development
crate and actual callback blocking/cancellation/drain/panic tests remain.
The daemon uses this crate only as a dev-dependency, including all-features builds.

Legacy UUIDs, permissions and transport models are not current service support.
The sole userspace SSAP Engine is already connected to real channels within
its source-bound capability limits; it does not use these legacy Profile models.
Do not deploy the experimental crate as production services. Full Profile routing,
notifications/indications and trusted Bond still require their original gates.

Run the preserved development regressions with the locked qualification toolchain:

```
python3 tools/build_resources.py -- cargo +1.96.1 test --locked --workspace --all-features
```
