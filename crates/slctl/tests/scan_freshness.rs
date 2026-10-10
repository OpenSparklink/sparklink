// SPDX-License-Identifier: GPL-2.0-only
//! Explicit synthetic D-Bus peer, exercising the actual one-shot slctl binary.
//! Delayed daemon delivery must not turn pre-scan kernel RX into a fresh match.
use slk_protocol::{DiscoveryResultRecord, TimedDiscoveryReportRecord};
use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    time::Duration,
};
const PATH: &str = "/org/sparklink/slk0_g7";
const ADDRESS: &str = "02:73:00:00:00:01";
const MARKER: &str = "01010101010101010101010101010101";
struct Bus {
    child: Child,
    address: String,
}
impl Bus {
    fn start() -> Self {
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
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![PATH.into()]
    }
}
struct ScanPeer {
    request: Arc<Mutex<u64>>,
}
#[zbus::interface(name = "org.sparklink.Adapter")]
impl ScanPeer {
    #[zbus(property)]
    fn profile(&self) -> u32 {
        1
    }
    #[zbus(property)]
    fn generation(&self) -> u64 {
        7
    }
    fn submit_scanning(&self, request_id: u64) {
        *self.request.lock().unwrap() = request_id;
    }
    fn get_discovery_result(&self, request_id: u64) -> DiscoveryResultRecord {
        assert_eq!(request_id, *self.request.lock().unwrap());
        (7, request_id, 3, 3, 0, 0, 0x1002, 1, 2, 0, false, 1, 2, 1)
    }
    fn get_timed_reports(&self) -> Vec<TimedDiscoveryReportRecord> {
        if *self.request.lock().unwrap() == 0 {
            return Vec::new();
        }
        let mut time = nix::libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        // SAFETY: valid writable timespec; CLOCK_BOOTTIME is Linux's RX clock.
        assert_eq!(
            unsafe { nix::libc::clock_gettime(nix::libc::CLOCK_BOOTTIME, &mut time) },
            0
        );
        let fresh = time.tv_sec as u64 * 1_000_000_000 + time.tv_nsec as u64;
        let data = libsparklink::ws73_marker_data(&[1; 16]);
        let row = |seq, generation, timestamp, address: &str, bytes, lost| {
            (
                seq,
                generation,
                timestamp,
                0,
                address.into(),
                -42,
                vec![],
                bytes,
                lost,
            )
        };
        vec![
            row(1, 7, 1, ADDRESS, data.clone(), 0),
            row(2, 7, u64::MAX, ADDRESS, data.clone(), 0),
            row(3, 7, fresh, ADDRESS, data.clone(), 1),
            row(4, 8, fresh, ADDRESS, data.clone(), 0),
            row(5, 7, fresh, "02:73:00:00:00:02", data.clone(), 0),
            row(
                6,
                7,
                fresh,
                ADDRESS,
                libsparklink::ws73_marker_data(&[2; 16]),
                0,
            ),
            row(7, 7, fresh, ADDRESS, data, 0),
        ]
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn delayed_old_rx_is_rejected_by_actual_cli() {
    let bus = Bus::start();
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink", Manager)
        .unwrap()
        .serve_at(
            PATH,
            ScanPeer {
                request: Arc::new(Mutex::new(0)),
            },
        )
        .unwrap()
        .build()
        .await
        .unwrap();
    let address = bus.address.clone();
    let output = tokio::time::timeout(
        Duration::from_secs(15),
        tokio::task::spawn_blocking(move || {
            let binary = std::env::var_os("SPARKLINK_TEST_SLCTL")
                .unwrap_or_else(|| env!("CARGO_BIN_EXE_slctl").into());
            Command::new(binary)
                .env("DBUS_SESSION_BUS_ADDRESS", address)
                .args([
                    "--session",
                    "--adapter",
                    PATH,
                    "scan",
                    "on",
                    MARKER,
                    ADDRESS,
                ])
                .output()
                .unwrap()
        }),
    )
    .await
    .unwrap()
    .unwrap();
    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(output.status.success(), "{stdout} {:?}", output.stderr);
    assert!(
        stdout.contains("NativeDiscoveryMatch: generation=7 seq=7 "),
        "pre-scan report was accepted: {stdout}"
    );
    assert!(!stdout.contains("seq=1 "), "{stdout}");
    drop(server);
}
