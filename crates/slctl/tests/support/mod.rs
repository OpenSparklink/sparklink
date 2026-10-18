// SPDX-License-Identifier: GPL-2.0-only
// Shared private D-Bus fixture; never a controller or protocol Engine.
use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
pub struct Bus {
    child: Child,
    pub address: String,
}
impl Bus {
    pub fn start() -> Self {
        let executable =
            std::env::var_os("SPARKLINK_TEST_DBUS_DAEMON").unwrap_or_else(|| "dbus-daemon".into());
        let mut child = Command::new(executable)
            .args(["--session", "--nofork", "--print-address=1"])
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let mut address = String::new();
        BufReader::new(child.stdout.take().unwrap())
            .read_line(&mut address)
            .unwrap();
        assert!(!address.trim().is_empty());
        Self {
            child,
            address: address.trim().into(),
        }
    }
}
impl Drop for Bus {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
