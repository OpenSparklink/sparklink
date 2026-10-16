use std::process::Command;
mod support;
#[test]
fn removed_test_commands_are_not_management_aliases() {
    let bus = support::Bus::start();
    for command in [
        "benchmark-ping",
        "benchmark-peer",
        "benchmark-rate",
        "benchmark-window",
        "benchmark-duplex",
        "benchmark-load-peer",
        "channel-peer",
        "channel-roundtrip",
        "dynamic-peer",
        "dynamic-roundtrip",
        "dynamic-burst",
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_slctl"))
            .args(["--session", command])
            .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
            .output()
            .unwrap();
        assert!(!output.status.success(), "{command}");
        assert!(
            String::from_utf8_lossy(&output.stderr).contains("Unknown command")
                || String::from_utf8_lossy(&output.stderr).contains("unknown command"),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
}
