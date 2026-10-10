//! Actual CLI failures must occur before bus/controller startup.
use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf, process::Command};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let base = std::env::temp_dir().join(format!(
            "slkd-config-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        fs::create_dir(&base).unwrap();
        Self(base)
    }
    fn reject(&self, path: &std::path::Path, expected: &str) {
        let output = Command::new(env!("CARGO_BIN_EXE_slkd"))
            .args(["--session", "--config"])
            .arg(path)
            .env(
                "DBUS_SESSION_BUS_ADDRESS",
                "unix:path=/nonexistent/slkd-config-test-bus",
            )
            .output()
            .unwrap();
        assert!(!output.status.success());
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(stderr.contains(expected), "wrong failure: {stderr}");
        assert!(!stderr.contains("using defaults") && !stderr.contains("D-Bus service registered"));
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
#[test]
fn explicit_missing_invalid_and_unknown_config_do_not_start_daemon() {
    let f = Fixture::new();
    f.reject(&f.0.join("missing"), "cannot read configuration");
    for (n, text) in [
        "[bad",
        "[policy]\nauto_par=true",
        "[general]\nauto_enable='true'",
    ]
    .iter()
    .enumerate()
    {
        let path = f.0.join(n.to_string());
        fs::write(&path, text).unwrap();
        f.reject(&path, "invalid configuration");
    }
}
#[test]
fn unsupported_policies_do_not_start_daemon() {
    let f = Fixture::new();
    for (n, text) in [
        "[policy]\nauto_pair=true",
        "[policy]\nmin_encryption=2",
        "[general]\nauto_enable=false",
    ]
    .iter()
    .enumerate()
    {
        let path = f.0.join(n.to_string());
        fs::write(&path, text).unwrap();
        f.reject(&path, "unsupported configuration");
    }
}
#[test]
fn unreadable_explicit_config_does_not_fall_back() {
    let f = Fixture::new();
    let path = f.0.join("unreadable");
    fs::write(&path, "").unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0)).unwrap();
    f.reject(&path, "cannot read configuration");
}
