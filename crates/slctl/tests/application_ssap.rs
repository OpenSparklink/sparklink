//! Actual new CLI -> application SDK -> private D-Bus calls. The service is a
//! finite argument fixture, not a second SSAP Engine or WS73 qualification.
mod support;
use std::sync::{
    Arc,
    atomic::{AtomicU64, AtomicUsize, Ordering},
};
const BASE: &str = "/org/sparklink/slk2_g7";
const PATH: &str = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b";
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into()]
    }
}
struct Adapter(Arc<AtomicU64>);
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        self.0.load(Ordering::SeqCst)
    }
}
struct Link {
    generation: Arc<AtomicU64>,
    calls: Arc<AtomicUsize>,
}
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
    fn get_info(&self) -> (u64, u64, u16, u8, u8, String, bool, bool) {
        (7, 11, 3, 0, 1, "01:02:03:04:05:06".into(), true, true)
    }
    fn read_ssap_value(&self, handle: u16, minimum: u32) -> zbus::fdo::Result<Vec<u8>> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        match (handle, minimum) {
            (17, 2) => Ok(vec![0x34, 0x78]),
            (99, 2) => {
                self.generation.store(8, Ordering::SeqCst);
                Ok(vec![0xde, 0xad])
            }
            _ => Err(zbus::fdo::Error::NotSupported(
                "finite fixture refuses unsupported read".into(),
            )),
        }
    }
    fn write_ssap_value(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
    ) -> zbus::fdo::Result<Vec<u8>> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if (handle, minimum, value) != (17, 1, vec![0x56, 0x12]) {
            return Err(zbus::fdo::Error::InvalidArgs("exact fixture write".into()));
        }
        Ok(vec![0x90])
    }
}
#[tokio::test]
async fn actual_cli_uses_sdk_and_refuses_late_identity_without_relabelling_success()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let generation = Arc::new(AtomicU64::new(7));
    let calls = Arc::new(AtomicUsize::new(0));
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter(generation.clone()))?
        .serve_at(
            PATH,
            Link {
                generation: generation.clone(),
                calls: calls.clone(),
            },
        )?
        .build()
        .await?;
    for (command, handle, rest, expected) in [
        ("ssap-read", "17", vec!["2"], Some("value=3478")),
        ("ssap-write", "17", vec!["5612", "1"], Some("value=90")),
        ("ssap-read", "18", vec!["2"], None),
        ("ssap-read", "99", vec!["2"], None),
    ] {
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            tokio::process::Command::new(env!("CARGO_BIN_EXE_slctl"))
                .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
                .args(["--session", "--adapter", BASE, command, PATH, handle])
                .args(rest)
                .output(),
        )
        .await??;
        let stdout = String::from_utf8(result.stdout)?;
        let stderr = String::from_utf8(result.stderr)?;
        if let Some(value) = expected {
            assert!(result.status.success(), "{stderr}");
            assert!(stdout.contains(value), "{stdout}");
        } else {
            assert!(!result.status.success());
            assert!(!stdout.contains("SsapPeerValue:"), "{stdout}");
            assert!(
                stderr.contains(if handle == "99" {
                    "controller generation"
                } else {
                    "NotSupported"
                }),
                "{stderr}"
            );
        }
    }
    assert_eq!(calls.load(Ordering::SeqCst), 4);
    Ok(())
}
