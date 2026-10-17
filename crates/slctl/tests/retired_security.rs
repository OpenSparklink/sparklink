//! Actual CLI entry; private bus only, deliberately no daemon/device fixture.
mod support;
use std::process::Command;
#[test]
fn retired_security_commands_are_unknown_before_any_controller_request() {
    let bus = support::Bus::start();
    for args in [
        vec!["pair", "01:02:03:04:05:06"],
        vec!["security"],
        vec!["services"],
        vec!["remote-services"],
        vec!["read", "1"],
        vec!["write", "1", "ab"],
    ] {
        let out = Command::new(env!("CARGO_BIN_EXE_slctl"))
            .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
            .args(["--session"])
            .args(&args)
            .output()
            .unwrap();
        assert!(!out.status.success());
        let error = String::from_utf8(out.stderr).unwrap();
        assert!(
            error.contains(&format!("unknown command '{}'", args[0])),
            "{error}"
        );
    }
}
