//! Actual CLI/SDK over a private D-Bus. The finite broker fixture is not a
//! controller, command Complete, effective link length or hardware evidence.
mod support;
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
const BASE: &str = "/org/sparklink/slk2_g7";
const LINK: &str = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b";
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
struct Adapter;
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
}
#[derive(Default)]
struct State {
    mode: AtomicUsize,
    calls: AtomicUsize,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
struct Link(Arc<State>);
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
    fn get_info(&self) -> (u64, u64, u16, u8, u8, String, bool, bool) {
        (7, 11, 3, 0, 1, "01:02:03:04:05:06".into(), true, true)
    }
    async fn set_link_payload_preference(
        &self,
        octets: u16,
        wire: slk_contract::Deadline,
    ) -> zbus::fdo::Result<slk_contract::link_parameter::Acknowledgment> {
        assert_eq!(octets, 1526);
        let deadline =
            libsparklink::Deadline::from_stamp(slk_contract::deadline_stamp(wire)).unwrap();
        assert!(deadline.remaining().unwrap() <= std::time::Duration::from_secs(5));
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        let mode = self.0.mode.load(Ordering::SeqCst);
        if mode == 6 {
            return Err(zbus::fdo::Error::AccessDenied(
                "explicit fixture denial".into(),
            ));
        }
        if mode == 7 {
            self.0.entered.notify_one();
            self.0.release.notified().await;
        }
        Ok(slk_contract::link_parameter::Acknowledgment {
            generation: 7,
            lifetime: if mode == 2 { 12 } else { 11 },
            handle: 3,
            role: 0,
            address_type: 1,
            address: "01:02:03:04:05:06".into(),
            request_id: 19,
            deadline_monotonic_ns: wire.0 + u64::from(mode == 5),
            requested_octets: octets + u16::from(mode == 1),
            state: if mode == 4 { 3 } else { 2 },
            error: if mode == 4 { -110 } else { 0 },
            status: 0,
            flags: if mode == 3 {
                7
            } else if mode == 4 {
                1
            } else {
                5
            },
        })
    }
}
async fn invoke(address: &str, octets: &str, timeout: &str) -> std::process::Output {
    tokio::process::Command::new(env!("CARGO_BIN_EXE_slctl"))
        .env("DBUS_SESSION_BUS_ADDRESS", address)
        .args([
            "--session",
            "--adapter",
            BASE,
            "link-payload-preference",
            LINK,
            octets,
            timeout,
        ])
        .output()
        .await
        .unwrap()
}
#[tokio::test]
async fn actual_cli_and_sdk_keep_original_argument_identity_deadline_and_error()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = Arc::new(State::default());
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter)?
        .serve_at(LINK, Link(state.clone()))?
        .build()
        .await?;
    let output = invoke(&bus.address, "1526", "5000").await;
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8(output.stdout)?;
    assert!(text.contains("NativeLinkPayloadAcknowledgment:"));
    assert!(text.contains("\"requested_octets\":1526"));
    assert!(!text.contains("effective_octets"));
    for mode in 1..=6 {
        state.mode.store(mode, Ordering::SeqCst);
        let output = invoke(&bus.address, "1526", if mode == 7 { "30" } else { "5000" }).await;
        assert!(!output.status.success(), "fixture mode{mode} accepted");
        assert!(!output.stderr.is_empty());
    }
    state.mode.store(7, Ordering::SeqCst);
    let delayed = invoke(&bus.address, "1526", "200");
    let entered = async {
        tokio::time::timeout(std::time::Duration::from_secs(2), state.entered.notified())
            .await
            .unwrap();
    };
    let (output, ()) = tokio::join!(delayed, entered);
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("timed out"));
    assert_eq!(state.calls.load(Ordering::SeqCst), 8);
    state.release.notify_one();
    let before = state.calls.load(Ordering::SeqCst);
    for (octets, timeout) in [
        ("0", "5000"),
        ("65536", "5000"),
        ("1526", "0"),
        ("1526", "5001"),
    ] {
        assert!(!invoke(&bus.address, octets, timeout).await.status.success());
    }
    assert_eq!(state.calls.load(Ordering::SeqCst), before);
    Ok(())
}
