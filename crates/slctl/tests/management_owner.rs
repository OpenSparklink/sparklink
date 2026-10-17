//! New CLI -> SDK -> actual private D-Bus. An argument/reply fixture is not a
//! real controller, management lease, protocol Complete or peer delivery.
mod support;
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use tokio::sync::Notify;
const BASE: &str = "/org/sparklink/slk2_g7";
// Explicit test-only historical binary input; normal CI always executes the
// newly compiled CLI. Counterexample runners must record its exact hash.
fn cli_binary() -> std::path::PathBuf {
    std::env::var_os("SPARKLINK_TEST_SLCTL_BINARY")
        .map(Into::into)
        .unwrap_or_else(|| std::path::PathBuf::from(env!("CARGO_BIN_EXE_slctl")))
}

struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into()]
    }
    fn list_registrations(&self) -> Vec<String> {
        vec![BASE.into()]
    }
}
#[derive(Default)]
struct State {
    submits: AtomicUsize,
    results: AtomicUsize,
    entered: Notify,
    release: Notify,
}
struct Adapter(Arc<State>);
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        7
    }
    #[zbus(property(emits_changed_signal = "false"))]
    fn profile(&self) -> u32 {
        1
    }
    fn allocate_connection_request(&self) -> u64 {
        101
    }
    fn submit_connect(&self, id: u64, address: &str, kind: u8) -> zbus::fdo::Result<()> {
        if (id, address, kind) != (101, "01:02:03:04:05:06", 1) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "finite arguments only".into(),
            ));
        }
        self.0.submits.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
    async fn get_connection_result(
        &self,
        id: u64,
    ) -> (u64, u64, u32, u32, i32, i32, u32, u32, u32, u32) {
        assert_eq!(id, 101);
        self.0.results.fetch_add(1, Ordering::SeqCst);
        self.0.entered.notify_one();
        self.0.release.notified().await;
        (7, 101, 1, 4, 0, 0, 0, 0, 3, 7) // Explicit reply shape, no hardware event.
    }
}
async fn server(address: &str, state: Arc<State>) -> anyhow::Result<zbus::Connection> {
    Ok(zbus::connection::Builder::address(address)?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter(state))?
        .build()
        .await?)
}
#[tokio::test]
async fn actual_cli_rejects_late_old_reply_and_never_queries_replacement() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let old = Arc::new(State::default());
    let a = server(&bus.address, old.clone()).await?;
    let child = tokio::process::Command::new(cli_binary())
        .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
        .args([
            "--session",
            "--adapter",
            BASE,
            "connect",
            "01:02:03:04:05:06",
            "1",
        ])
        .output();
    let switch = async {
        old.entered.notified().await;
        a.release_name("org.sparklink").await?;
        let new = Arc::new(State::default());
        let b = server(&bus.address, new.clone()).await?;
        old.release.notify_one();
        Ok::<_, anyhow::Error>((b, new))
    };
    let (out, b) = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        tokio::join!(child, switch)
    })
    .await?;
    let out = out?;
    let (_b, new) = b?;
    let text = String::from_utf8(out.stdout)?;
    let error = String::from_utf8(out.stderr)?;
    assert!(
        !out.status.success(),
        "old-owner observation accepted; old_submits={} old_results={} replacement_calls={} stdout={text} stderr={error}",
        old.submits.load(Ordering::SeqCst),
        old.results.load(Ordering::SeqCst),
        new.submits.load(Ordering::SeqCst) + new.results.load(Ordering::SeqCst)
    );
    assert!(error.contains("daemon owner replaced"), "{error}");
    assert!(
        text.contains("NativeConnectionRequest: request=101"),
        "{text}"
    );
    assert!(!text.contains("NativeConnectionResult:"), "{text}");
    assert!(!text.contains("procedure completed"), "{text}");
    assert_eq!(old.submits.load(Ordering::SeqCst), 1);
    assert_eq!(old.results.load(Ordering::SeqCst), 1);
    assert_eq!(
        new.submits.load(Ordering::SeqCst) + new.results.load(Ordering::SeqCst),
        0
    );
    Ok(())
}
struct Registration;
#[zbus::interface(name = "org.sparklink.Registration")]
impl Registration {
    fn get_snapshot(&self) -> (u64, u32, u32, u32, u32, i32, u16, u8) {
        (7, 1, 1, 1, 0, 0, 2, 4)
    }
}
#[tokio::test]
async fn actual_cli_can_observe_core_pending_without_adapter_or_ready() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Registration)?
        .build()
        .await?;
    let out = tokio::process::Command::new(cli_binary())
        .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
        .args(["--session", "registrations"])
        .output()
        .await?;
    let text = String::from_utf8(out.stdout)?;
    assert!(out.status.success(), "{}", String::from_utf8(out.stderr)?);
    assert!(text.contains("state=Pending"), "{text}");
    assert!(!text.contains("state=Ready"));
    Ok(())
}

#[tokio::test]
async fn scan_missing_argument_is_usage_before_any_controller_or_daemon_lookup()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let out = tokio::process::Command::new(cli_binary())
        .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
        .args(["--session", "scan"])
        .output()
        .await?;
    let error = String::from_utf8(out.stderr)?;
    assert!(!out.status.success());
    assert!(error.contains("usage: scan on|off"), "{error}");
    assert!(!error.contains("panicked"));
    assert!(!error.contains("NameHasNoOwner"));
    Ok(())
}
