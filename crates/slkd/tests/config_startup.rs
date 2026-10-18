//! Actual CLI failures must occur before bus/controller startup.
use std::{
    fs,
    os::unix::{fs::PermissionsExt, process::CommandExt},
    path::PathBuf,
    process::Command,
};

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
        Self::assert_rejected(&mut self.command(path), expected);
    }
    fn command(&self, path: &std::path::Path) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_slkd"));
        command.args(["--session", "--config"]).arg(path).env(
            "DBUS_SESSION_BUS_ADDRESS",
            "unix:path=/nonexistent/slkd-config-test-bus",
        );
        command
    }
    fn assert_rejected(command: &mut Command, expected: &str) {
        let output = command.output().unwrap();
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
    fs::set_permissions(&path, fs::Permissions::from_mode(0o000)).unwrap();
    let mut command = f.command(&path);
    // Permission denial needs an actually unprivileged reader. Root may read
    // mode 000 and must not be given a new, artificial production restriction.
    // Read kernel credentials rather than fakeroot's interposed geteuid().
    let status = fs::read_to_string("/proc/self/status").unwrap();
    let euid: u32 = status
        .lines()
        .find(|line| line.starts_with("Uid:"))
        .unwrap()
        .split_whitespace()
        .nth(2)
        .unwrap()
        .parse()
        .unwrap();
    if euid == 0 {
        command.gid(65534).uid(65534);
    }
    Fixture::assert_rejected(&mut command, "cannot read configuration");
}

#[test]
fn check_config_uses_real_validation_without_bus_or_controller_startup() {
    let f = Fixture::new();
    let path = f.0.join("policy.conf");
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_slkd"))
            .args([
                "--check-config",
                "--session",
                "--device",
                "/nonexistent/ws73",
                "--config",
            ])
            .arg(&path)
            .env(
                "DBUS_SESSION_BUS_ADDRESS",
                "unix:path=/nonexistent/slkd-check-bus",
            )
            .output()
            .unwrap()
    };
    fs::write(&path, "[[ws73.adapters]]\naddress='00:01:09:32:54:F9'\n[ws73.adapters.policy]\nadvertising_interval_min_slots=1237\nadvertising_interval_max_slots=1237\n").unwrap();
    let valid = run();
    assert!(valid.status.success(), "{:?}", valid);
    assert!(String::from_utf8_lossy(&valid.stdout).contains("syntax and host policy only"));
    assert!(!String::from_utf8_lossy(&valid.stderr).contains("D-Bus service registered"));
    for text in [
        "[ws73.defaults]\nscan_window_slots=1601",
        "[ws73.defaults]\ntx_power_dbm=21",
        "[ws73.defaults]\nscan_interva_slots=1600",
        "[policy]\nauto_pair=true",
    ] {
        fs::write(&path, text).unwrap();
        let invalid = run();
        assert!(!invalid.status.success());
        assert!(!String::from_utf8_lossy(&invalid.stdout).contains("Configuration valid"));
        assert!(!String::from_utf8_lossy(&invalid.stderr).contains("D-Bus service registered"));
    }
    fs::remove_file(&path).unwrap();
    assert!(!run().status.success());
    let implicit = Command::new(env!("CARGO_BIN_EXE_slkd"))
        .arg("--check-config")
        .output()
        .unwrap();
    assert!(!implicit.status.success());
    assert!(String::from_utf8_lossy(&implicit.stderr).contains("--config"));
}

#[test]
fn normalized_dump_resolves_overrides_with_the_actual_daemon_parser() {
    let f = Fixture::new();
    let path = f.0.join("normalized.conf");
    fs::write(&path, "[ws73.defaults]\ntx_power_dbm=10\n[[ws73.adapters]]\naddress='00:01:09:32:54:cd'\n[ws73.adapters.policy]\nadvertising_interval_min_slots=1237\nadvertising_interval_max_slots=1237\n").unwrap();
    let result = Command::new(env!("CARGO_BIN_EXE_slkd"))
        .args(["--check-config", "--dump-ws73-policies", "--config"])
        .arg(&path)
        .env(
            "DBUS_SYSTEM_BUS_ADDRESS",
            "unix:path=/nonexistent/check-only-bus",
        )
        .output()
        .unwrap();
    assert!(result.status.success());
    assert_eq!(
        String::from_utf8(result.stdout).unwrap(),
        "Ws73DefaultPolicy: version=3 adv_slots=1200..1200 tx_power_dbm=10 scan_slots=1600/800\nWs73AdapterPolicy: address=00:01:09:32:54:CD version=3 adv_slots=1237..1237 tx_power_dbm=127 scan_slots=1600/800\n"
    );
    let missing_mode = Command::new(env!("CARGO_BIN_EXE_slkd"))
        .args(["--dump-ws73-policies", "--config"])
        .arg(&path)
        .output()
        .unwrap();
    assert!(!missing_mode.status.success());
}
