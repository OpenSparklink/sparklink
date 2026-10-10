# Unqualified development models

This unpublished crate preserves the legacy Profile/HID and transport code and
its codec/lifecycle regressions. It is outside the default slkd dependency graph;
public modules are experimental development APIs, not supported application APIs.
Neither workspace compilation nor unit tests qualify the protocols or hardware.

`experimental-legacy-profiles` (a **build** feature, not a runtime option) retains legacy profile0 registration and connection callbacks for
controlled experiments. Native profile1 never registers these services. Default
slkd has no built-in Profile registration or Profile actor. Development tests
still exercise actual actor blocking/cancellation/drain/panic behavior.

Request read/write/notify/indication routing is absent. Legacy UUIDs, property
permissions, firmware metadata and transport negotiation remain unqualified.
Do not deploy this feature as production services. R07 and the user-space SSAP
Engine/per-connection socket migration remain open. No `allow(dead_code)` hides
unused production functionality; test-only Bond lookups are compiled for tests.

Build the controlled experiment with:

```
cargo build -p slkd --features experimental-legacy-profiles
```

Run regressions with:

```
RUSTFLAGS='-D warnings' cargo test --workspace --all-features
```
