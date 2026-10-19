//! Actual migrated CLI with local registration/permission fixtures. No remote
//! publication, authorization decision, wire Engine or hardware is simulated.
mod support;
use std::sync::{Arc, Mutex};
use tokio::{io::AsyncWriteExt, process::Command};
const BASE: &str = "/org/sparklink/slk0_g7";
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
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
}
#[derive(Default)]
struct State {
    owner: String,
    removed: bool,
    reads: usize,
}
struct Services(Arc<Mutex<State>>);
#[zbus::interface(name = "org.sparklink.ServiceManager")]
impl Services {
    fn register_owned_local_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<(Vec<u8>, u32, u32, Vec<u8>)>,
        authorizer: zbus::zvariant::OwnedObjectPath,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> (u16, u16, Vec<u16>) {
        libsparklink::Deadline::from_stamp(slk_contract::deadline_stamp(deadline)).unwrap();
        assert_eq!(uuid, [1, 0]);
        assert_eq!(properties, [(vec![2, 0], 5, 36, vec![0xab])]);
        assert_eq!(authorizer.as_str(), "/org/sparklink/slctl/ssap_authorizer");
        self.0.lock().unwrap().owner = h.sender().unwrap().to_string();
        (16, 17, vec![17])
    }
    fn read_owned_local_value(
        &self,
        handle: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> Vec<u8> {
        libsparklink::Deadline::from_stamp(slk_contract::deadline_stamp(deadline)).unwrap();
        let mut s = self.0.lock().unwrap();
        assert_eq!(handle, 17);
        assert_eq!(s.owner, h.sender().unwrap().as_str());
        s.reads += 1;
        vec![0xab]
    }
    fn unregister_owned_local_service(
        &self,
        start: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        libsparklink::Deadline::from_stamp(slk_contract::deadline_stamp(deadline)).unwrap();
        let mut s = self.0.lock().unwrap();
        assert_eq!(start, 16);
        assert_eq!(s.owner, h.sender().unwrap().as_str());
        s.removed = true;
    }
}
#[tokio::test]
async fn actual_owned_cli_uses_one_caller_for_register_read_and_explicit_cleanup()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = Arc::new(Mutex::new(State::default()));
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter)?
        .serve_at(format!("{BASE}/services"), Services(state.clone()))?
        .build()
        .await?;
    let mut child = Command::new(env!("CARGO_BIN_EXE_slctl"))
        .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
        .args([
            "--session",
            "--adapter",
            BASE,
            "ssap-serve",
            "0100",
            "0200",
            "5",
            "36",
            "ab",
            "allow",
        ])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()?;
    child
        .stdin
        .as_mut()
        .unwrap()
        .write_all(b"value\nquit\n")
        .await?;
    let output =
        tokio::time::timeout(std::time::Duration::from_secs(5), child.wait_with_output()).await??;
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8(output.stdout)?;
    assert!(
        text.contains("SsapOwnedService: start=16 end=17 property=17; local registration only"),
        "{text}"
    );
    assert!(
        text.contains("SsapOwnedValue: handle=17 value=ab"),
        "{text}"
    );
    let s = state.lock().unwrap();
    assert!(s.removed);
    assert_eq!(s.reads, 1);
    Ok(())
}
