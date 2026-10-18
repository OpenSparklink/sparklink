//! Actual binary argument/error boundary. No controller, D-Bus fixture or Host.
use std::process::Command;
#[test]
fn real_slktest_binary_exposes_only_the_explicit_channel_tree() {
    for command in [
        vec!["--help"],
        vec!["channel", "--help"],
        vec!["channel", "ping", "--help"],
        vec!["channel", "peer", "--help"],
    ] {
        let r = Command::new(env!("CARGO_BIN_EXE_slktest"))
            .args(command)
            .output()
            .unwrap();
        assert!(r.status.success(), "{}", String::from_utf8_lossy(&r.stderr));
        assert!(String::from_utf8_lossy(&r.stdout).contains("slktest"));
    }
}
#[test]
fn actual_binary_rejects_invalid_modes_before_opening_a_bus() {
    for tail in [
        vec!["channel", "ping", "/link", "--report", "x", "--count", "0"],
        vec!["channel", "peer", "/link", "--check", "--load"],
        vec![
            "channel",
            "rate",
            "/link",
            "--interval-us",
            "1",
            "--report",
            "x",
        ],
        vec!["benchmark-ping"],
        vec!["channel", "ping", "/link", "--check", "--source-port", "1"],
    ] {
        let r = Command::new(env!("CARGO_BIN_EXE_slktest"))
            .args(["--adapter", "/org/sparklink/slk0_g7"])
            .args(&tail)
            .env(
                "DBUS_SYSTEM_BUS_ADDRESS",
                "unix:path=/not-a-real-bus-slktest.sock",
            )
            .output()
            .unwrap();
        assert!(!r.status.success(), "{tail:?}");
        assert!(
            !String::from_utf8_lossy(&r.stderr).contains("No such file or directory"),
            "{}",
            String::from_utf8_lossy(&r.stderr)
        );
    }
}
