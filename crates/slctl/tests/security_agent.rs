// SPDX-License-Identifier: GPL-2.0-only
//! Actual slctl subprocess/callbacks on a private bus. Server metadata and Agent
//! registration are fixtures. No native ioctl, crypto, successful Complete or
//! hardware delivery is simulated; real broker/WS73 gates remain separate.
mod support;
use std::{sync::Arc, time::Duration};
use support::Bus;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader, Lines},
    process::{Child, ChildStdout, Command},
    sync::Mutex,
};
use zbus::{Connection, zvariant::OwnedObjectPath};
const CONTROLLER: &str = "/org/sparklink/slk0_g7";
const LINK: &str = "/org/sparklink/slk0_g7/peer_t00_010203040506/link_000000000000000d";
type Prompt = (String, u64, u64, u64, u16, u8, u8, String, String, u64);
fn clock() -> u64 {
    let mut t = nix::libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: live writable timespec, explicit same Linux monotonic clock.
    assert_eq!(
        unsafe { nix::libc::clock_gettime(nix::libc::CLOCK_MONOTONIC, &mut t) },
        0
    );
    t.tv_sec as u64 * 1_000_000_000 + t.tv_nsec as u64
}
fn prompt(id: u64) -> Prompt {
    (
        LINK.into(),
        id,
        7,
        13,
        1,
        0,
        0,
        "01:02:03:04:05:06".into(),
        "sdk111-no-mitm".into(),
        clock() + 2_000_000_000,
    )
}
#[derive(Clone, Default)]
struct Registration(Arc<Mutex<Option<(String, OwnedObjectPath)>>>);
#[zbus::interface(name = "org.sparklink.Security")]
impl Registration {
    async fn register_agent(
        &self,
        path: OwnedObjectPath,
        method: &str,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> u64 {
        assert_eq!(method, "sdk111-no-mitm");
        *self.0.lock().await = Some((h.sender().unwrap().to_string(), path));
        41
    }
    async fn unregister_agent(
        &self,
        path: OwnedObjectPath,
        epoch: u64,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        assert_eq!(epoch, 41);
        let mut held = self.0.lock().await;
        let original = held.as_ref().unwrap();
        assert_eq!(original.0, h.sender().unwrap().as_str());
        assert_eq!(original.1, path);
        held.take();
    }
}
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![CONTROLLER.into()]
    }
}
struct Adapter;
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        7
    }
}
struct Link;
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
    fn get_info(&self) -> (u64, u64, u16, u8, u8, String, bool, bool) {
        (7, 13, 1, 0, 0, "01:02:03:04:05:06".into(), true, true)
    }
}
struct AgentProcess {
    child: Child,
    lines: Lines<BufReader<ChildStdout>>,
}
impl AgentProcess {
    async fn start(bus: &Bus) -> Self {
        let binary = std::env::var_os("SPARKLINK_TEST_SLCTL")
            .unwrap_or_else(|| env!("CARGO_BIN_EXE_slctl").into());
        let mut child = Command::new(binary)
            .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
            .args(["--session", "--adapter", CONTROLLER, "agent"])
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .unwrap();
        let lines = BufReader::new(child.stdout.take().unwrap()).lines();
        let mut p = Self { child, lines };
        p.until("AgentReady:").await;
        p
    }
    async fn until(&mut self, needle: &str) -> String {
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                let line = self
                    .lines
                    .next_line()
                    .await
                    .unwrap()
                    .expect("CLI stdout ended");
                if line.contains(needle) {
                    return line;
                }
            }
        })
        .await
        .unwrap()
    }
    async fn write(&mut self, s: &str) {
        self.child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(s.as_bytes())
            .await
            .unwrap();
    }
    async fn exit(&mut self, success: bool) {
        let status = tokio::time::timeout(Duration::from_secs(4), self.child.wait())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(status.success(), success, "{status}");
    }
}
async fn bus_fixture() -> (Bus, Connection, Registration) {
    let bus = Bus::start();
    let registration = Registration::default();
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink", Manager)
        .unwrap()
        .serve_at(CONTROLLER, Adapter)
        .unwrap()
        .serve_at(LINK, Link)
        .unwrap()
        .serve_at(format!("{CONTROLLER}/security"), registration.clone())
        .unwrap()
        .build()
        .await
        .unwrap();
    (bus, server, registration)
}
async fn callback(c: &Connection, r: &Registration, p: Prompt) -> zbus::Result<bool> {
    let (owner, path) = r.0.lock().await.clone().unwrap();
    zbus::Proxy::new(c, owner, path, "org.sparklink.Agent")
        .await?
        .call("AuthorizeReferenceSecurity", &(p,))
        .await
}
fn launch_callback(
    c: &Connection,
    r: &Registration,
    p: Prompt,
) -> tokio::task::JoinHandle<zbus::Result<bool>> {
    let c = c.clone();
    let r = r.clone();
    tokio::spawn(async move { callback(&c, &r, p).await })
}
#[tokio::test]
async fn explicit_decisions_identity_deadline_and_eof_on_actual_cli() {
    let (bus, server, registration) = bus_fixture().await;
    let mut cli = AgentProcess::start(&bus).await;
    let other = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    assert!(
        callback(&other, &registration, prompt(1)).await.is_err(),
        "wrong sender must fail"
    );
    let mut bad = prompt(1);
    bad.3 = 14;
    assert!(!callback(&server, &registration, bad).await.unwrap());
    let mut bad = prompt(1);
    bad.8 = "unknown".into();
    assert!(!callback(&server, &registration, bad).await.unwrap());
    for (id, yes) in [(2, true), (3, false)] {
        let call = launch_callback(&server, &registration, prompt(id));
        cli.until(&format!("AgentPrompt: request={id} ")).await;
        tokio::time::sleep(Duration::from_millis(30)).await;
        assert!(!call.is_finished(), "no default approval");
        assert!(
            !callback(&server, &registration, prompt(99)).await.unwrap(),
            "bounded single pending"
        );
        cli.write("approve 999\n").await;
        tokio::time::sleep(Duration::from_millis(30)).await;
        assert!(!call.is_finished(), "wrong request cannot answer");
        cli.write(&format!(
            "{} {id}\n",
            if yes { "approve" } else { "reject" }
        ))
        .await;
        assert_eq!(call.await.unwrap().unwrap(), yes);
    }
    let mut expiring = prompt(4);
    expiring.9 = clock() + 200_000_000;
    let call = launch_callback(&server, &registration, expiring);
    cli.until("AgentPrompt: request=4 ").await;
    assert!(
        !tokio::time::timeout(Duration::from_secs(2), call)
            .await
            .unwrap()
            .unwrap()
            .unwrap()
    );
    cli.write("approve 4\n").await; // late answer cannot approve a future request.
    let call = launch_callback(&server, &registration, prompt(5));
    cli.until("AgentPrompt: request=5 ").await;
    cli.child.stdin.take(); // EOF must unregister, not hang the current-thread runtime.
    assert!(!call.await.unwrap().unwrap());
    cli.exit(true).await;
    assert!(registration.0.lock().await.is_none());
}
#[tokio::test]
async fn daemon_ownership_loss_exits_without_following_replacement() {
    let (bus, server, registration) = bus_fixture().await;
    let mut cli = AgentProcess::start(&bus).await;
    let call = launch_callback(&server, &registration, prompt(1));
    cli.until("AgentPrompt:").await;
    server.release_name("org.sparklink").await.unwrap();
    // Reacquisition by the same unique owner is still a new ownership epoch.
    server.request_name("org.sparklink").await.unwrap();
    cli.exit(false).await;
    assert!(!call.await.unwrap().unwrap());
    assert!(registration.0.lock().await.is_none());
}

#[derive(Clone, Default)]
struct RequestFixture {
    state: Arc<Mutex<(String, u64, bool, bool)>>,
}
#[zbus::interface(name = "org.sparklink.Connection")]
impl RequestFixture {
    fn get_info(&self) -> (u64, u64, u16, u8, u8, String, bool, bool) {
        (7, 13, 1, 0, 0, "01:02:03:04:05:06".into(), true, true)
    }
    async fn allocate_reference_security(
        &self,
        timeout: u32,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> u64 {
        assert_eq!(timeout, 100);
        *self.state.lock().await = (
            h.sender().unwrap().to_string(),
            clock() + 100_000_000,
            false,
            false,
        );
        42
    }
    async fn begin_reference_security(
        &self,
        id: u64,
        method: &str,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        assert_eq!(id, 42);
        assert_eq!(method, "sdk111-no-mitm");
        {
            let mut state = self.state.lock().await;
            assert_eq!(state.0, h.sender().unwrap().as_str());
            state.2 = true;
        }
        // Deliberately slow IPC fixture, not a successful kernel submission.
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
    async fn get_reference_security_result(
        &self,
        id: u64,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> (
        u64,
        u64,
        u64,
        u32,
        i32,
        u64,
        bool,
        bool,
        u32,
        i32,
        u32,
        u8,
        i32,
    ) {
        let state = self.state.lock().await;
        assert_eq!(id, 42);
        assert_eq!(state.0, h.sender().unwrap().as_str());
        (42, 7, 13, 1, 0, state.1, false, false, 0, 0, 0, 0, 0)
    }
    async fn cancel_reference_security(
        &self,
        id: u64,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> bool {
        let mut state = self.state.lock().await;
        assert_eq!(id, 42);
        assert_eq!(state.0, h.sender().unwrap().as_str());
        state.3 = true;
        true
    }
}
#[tokio::test]
async fn client_watchdog_withdraws_only_original_request_after_slow_begin() {
    let bus = Bus::start();
    let fixture = RequestFixture::default();
    let _server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink", Manager)
        .unwrap()
        .serve_at(CONTROLLER, Adapter)
        .unwrap()
        .serve_at(LINK, fixture.clone())
        .unwrap()
        .build()
        .await
        .unwrap();
    let binary = std::env::var_os("SPARKLINK_TEST_SLCTL")
        .unwrap_or_else(|| env!("CARGO_BIN_EXE_slctl").into());
    let started = std::time::Instant::now();
    let output = tokio::time::timeout(
        Duration::from_secs(4),
        Command::new(binary)
            .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
            .args([
                "--session",
                "--adapter",
                CONTROLLER,
                "security-request",
                LINK,
                "100",
            ])
            .kill_on_drop(true)
            .output(),
    )
    .await
    .unwrap()
    .unwrap();
    assert!(!output.status.success());
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("client watchdog expired"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(started.elapsed() < Duration::from_secs(2));
    let state = fixture.state.lock().await;
    assert!(
        state.2 && state.3,
        "Begin and Cancel must have the original author, not a new bus connection"
    );
}
