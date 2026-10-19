//! Actual SDK/D-Bus serialization and identity checks. The service is an
//! explicit finite argument/result fixture, never SSAP, firmware or RF.
mod support;
use libsparklink::{ApplicationError, Client};
use std::time::Duration;
fn deadline() -> libsparklink::Deadline {
    libsparklink::Deadline::after(std::time::Duration::from_secs(5)).unwrap()
}
use std::sync::{
    Arc,
    atomic::{AtomicU8, AtomicU64, AtomicUsize, Ordering},
};
use tokio::sync::Notify;
const BASE: &str = "/org/sparklink/slk2_g7";
const PATH: &str = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b";
#[derive(Default)]
struct State {
    generation: AtomicU64,
    role: AtomicU8,
    calls: AtomicUsize,
    malformed_update: AtomicU8,
    entered: Notify,
    release: Notify,
}
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into()]
    }
}
struct Adapter(Arc<State>);
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        self.0.generation.load(Ordering::SeqCst)
    }
}
struct Link(Arc<State>);
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
    fn get_info(&self) -> (u64, u64, u16, u8, u8, String, bool, bool) {
        (
            7,
            11,
            3,
            self.0.role.load(Ordering::SeqCst),
            1,
            "01:02:03:04:05:06".into(),
            true,
            true,
        )
    }
    async fn read_ssap_value(
        &self,
        handle: u16,
        minimum: u32,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<Vec<u8>> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        if handle == 99 {
            self.0.entered.notify_one();
            self.0.release.notified().await;
        } else if (handle, minimum) != (17, 2) {
            return Err(zbus::fdo::Error::NotSupported(
                "fixture rejects unmatched request".into(),
            ));
        }
        Ok(vec![0x34, 0x78])
    }
    fn write_ssap_value(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<Vec<u8>> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        if (handle, minimum, value) != (17, 1, vec![0x56, 0x12]) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "exact fixture write required".into(),
            ));
        }
        Ok(vec![0x90]) // Deliberately differs from input: no local method echo.
    }
    fn discover_ssap(
        &self,
        uuid: Vec<u8>,
        kind: u8,
    ) -> zbus::fdo::Result<slk_contract::ssap::Discovery> {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        if (uuid, kind) != (vec![1, 2], 3) {
            return Err(zbus::fdo::Error::NotSupported(
                "unsupported fixture discovery".into(),
            ));
        }
        Ok((
            vec![(3, 17, 18, vec![1, 2], 4, vec![0x80], 1)],
            vec![(vec![0x11], vec![0x22])],
        ))
    }
    fn get_cached_ssap(&self) -> Vec<slk_contract::ssap::Entry> {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        vec![(3, 17, 18, vec![1, 2], 4, vec![0x80], 1)]
    }
    fn read_ssap_by_uuid(
        &self,
        start: u16,
        end: u16,
        data_type: u8,
        uuid: Vec<u8>,
        minimum: u32,
    ) -> zbus::fdo::Result<slk_contract::ssap::UuidValues> {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        if (start, end, data_type, uuid, minimum) != (17, 20, 0, vec![1, 2], 2) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "exact UUID fixture required".into(),
            ));
        }
        Ok((vec![(17, true, 0, vec![0xab])], vec![0x12], vec![0x34]))
    }
    fn receive_ssap_update(
        &self,
        handles: Vec<u16>,
        modes: u8,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<slk_contract::ssap::Incoming> {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        let original =
            slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
                .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        if (handles, modes) != (vec![17, 18], 2)
            || original.remaining().unwrap() > Duration::from_millis(1234)
        {
            return Err(zbus::fdo::Error::InvalidArgs(
                "exact incoming fixture required".into(),
            ));
        }
        let raw = match self.0.malformed_update.load(Ordering::SeqCst) {
            1 => vec![0x24, 1, 2],
            2 => vec![16, 3, 19, 0, 1, 0, 0xab],
            3 => vec![15, 3, 17, 0, 1, 0, 0xab],
            _ => vec![16, 3, 17, 0, 1, 0, 0xab],
        };
        Ok((true, raw))
    }
    fn send_owned_ssap_update(
        &self,
        handle: u16,
        indication: bool,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<slk_contract::ssap::UpdateReceipt> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        if handle != 17 {
            return Err(zbus::fdo::Error::AccessDenied(
                "foreign fixture owner".into(),
            ));
        }
        Ok(slk_contract::ssap::UpdateReceipt {
            stage: if indication { 2 } else { 1 },
            pdu: vec![if indication { 16 } else { 15 }, 3, 17, 0, 1, 0, 0xab],
            acknowledgement: if indication { vec![17, 3, 1] } else { vec![] },
        })
    }
    fn get_owned_ssap_configuration(
        &self,
        handle: u16,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<u8> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        if handle != 17 {
            return Err(zbus::fdo::Error::AccessDenied(
                "foreign fixture owner".into(),
            ));
        }
        Ok(3)
    }
    fn get_ssap_info(&self) -> slk_contract::ssap::ExchangeInfo {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        (2, 7, 11, 3, 256, 240, vec![1], vec![2], vec![3], vec![4])
    }
    fn get_transport_status(&self) -> slk_contract::TransportInfo {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        (2, 7, 11, 3, 4, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1)
    }
}
async fn fixture(
    address: &str,
) -> anyhow::Result<(zbus::Connection, zbus::Connection, Arc<State>)> {
    let state = Arc::new(State::default());
    state.generation.store(7, Ordering::SeqCst);
    let server = zbus::connection::Builder::address(address)?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter(state.clone()))?
        .serve_at(PATH, Link(state.clone()))?
        .build()
        .await?;
    let caller = zbus::connection::Builder::address(address)?.build().await?;
    Ok((server, caller, state))
}
#[tokio::test]
async fn actual_ssap_client_serializes_all_existing_methods_without_echo_or_fallback()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let (_server, caller, state) = fixture(&bus.address).await?;
    let client = Client::from_connection(caller).await?;
    let link = client.connection(BASE, PATH).await?;
    let remote = link.ssap();
    assert_eq!(remote.read(17, 2, deadline()).await?, [0x34, 0x78]);
    assert!(
        matches!(remote.read(18,2,deadline()).await,Err(ApplicationError::Bus(zbus::Error::MethodError(name,_,_))) if name.as_str()=="org.freedesktop.DBus.Error.NotSupported")
    );
    assert_eq!(
        remote.write(17, vec![0x56, 0x12], 1, deadline()).await?,
        [0x90]
    );
    let (entries, trace) = remote.discover(vec![1, 2], 3).await?;
    assert_eq!(entries, remote.cached().await?);
    assert_eq!(trace, [(vec![0x11], vec![0x22])]);
    assert_eq!(
        remote.read_by_uuid(17, 20, 0, vec![1, 2], 2).await?,
        (vec![(17, true, 0, vec![0xab])], vec![0x12], vec![0x34])
    );
    assert_eq!(
        remote.receive_update(vec![17, 18], 2, 1234).await?,
        (true, vec![16, 3, 17, 0, 1, 0, 0xab])
    );
    assert_eq!(remote.exchange_info().await?.5, 240);
    assert_eq!(link.transport_status().await?.5, 1);
    assert_eq!(state.calls.load(Ordering::SeqCst), 9); // No hidden retry, fallback or engine calls.
    state.role.store(1, Ordering::SeqCst);
    assert!(matches!(
        remote.read(17, 2, deadline()).await,
        Err(ApplicationError::Identity(_))
    ));
    assert_eq!(state.calls.load(Ordering::SeqCst), 9);
    Ok(())
}
#[tokio::test]
async fn late_reply_cannot_complete_under_changed_generation_and_old_owner() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let (server, caller, state) = fixture(&bus.address).await?;
    let client = Client::from_connection(caller).await?;
    let link = client.connection(BASE, PATH).await?;
    let call = async { link.ssap().read(99, 0, deadline()).await };
    let interleave = async {
        state.entered.notified().await;
        state.generation.store(8, Ordering::SeqCst);
        state.release.notify_one();
    };
    let (result, ()) = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        tokio::join!(call, interleave)
    })
    .await?;
    assert!(matches!(result, Err(ApplicationError::Identity(_))));
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    state.generation.store(7, Ordering::SeqCst);
    server.release_name("org.sparklink").await?;
    let replacement = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .build()
        .await?;
    assert_ne!(
        replacement.unique_name().unwrap().as_str(),
        client.daemon_owner()
    );
    assert!(matches!(
        link.ssap().read(17, 2, deadline()).await,
        Err(ApplicationError::Identity(_))
    ));
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn malformed_foreign_or_wrong_kind_update_never_becomes_application_delivery()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let (_server, caller, state) = fixture(&bus.address).await?;
    let client = Client::from_connection(caller).await?;
    let link = client.connection(BASE, PATH).await?;
    for kind in 1..=3 {
        state.malformed_update.store(kind, Ordering::SeqCst);
        assert!(matches!(
            link.ssap().receive_update(vec![17, 18], 2, 1234).await,
            Err(ApplicationError::Identity(_))
        ));
    }
    assert_eq!(state.calls.load(Ordering::SeqCst), 3);
    Ok(())
}

#[tokio::test]
async fn actual_owned_update_rpc_has_literal_signatures_and_distinct_stages() -> anyhow::Result<()>
{
    let bus = support::Bus::start();
    let (_server, caller, state) = fixture(&bus.address).await?;
    let proxy = zbus::Proxy::new(
        &caller,
        "org.sparklink",
        PATH,
        "org.freedesktop.DBus.Introspectable",
    )
    .await?;
    let xml: String = proxy.call("Introspect", &()).await?;
    for (method, inputs, outputs) in [
        (
            "SendOwnedSsapUpdate",
            vec!["q", "b", "(ttttt)"],
            vec!["(yayay)"],
        ),
        ("GetOwnedSsapConfiguration", vec!["q", "(ttttt)"], vec!["y"]),
        (
            "ReceiveSsapUpdate",
            vec!["aq", "y", "(ttttt)"],
            vec!["(bay)"],
        ),
    ] {
        let part = xml
            .split_once(&format!("<method name=\"{method}\">"))
            .unwrap()
            .1
            .split_once("</method>")
            .unwrap()
            .0;
        let types = |direction: &str| {
            part.lines()
                .filter(|l| {
                    l.contains("<arg ") && l.contains(&format!("direction=\"{direction}\""))
                })
                .map(|l| {
                    l.split_once("type=\"")
                        .unwrap()
                        .1
                        .split_once('"')
                        .unwrap()
                        .0
                })
                .collect::<Vec<_>>()
        };
        assert_eq!(types("in"), inputs);
        assert_eq!(types("out"), outputs);
    }
    assert!(!xml.contains("ObserveSsapIncoming"));
    let client = Client::from_connection(caller).await?;
    let link = client.connection(BASE, PATH).await?;
    let remote = link.ssap();
    assert_eq!(remote.owned_configuration(17, deadline()).await?, 3);
    let notification = remote.send_owned_update(17, false, deadline()).await?;
    assert_eq!(
        (
            notification.stage,
            notification.pdu,
            notification.acknowledgement
        ),
        (1, vec![15, 3, 17, 0, 1, 0, 0xab], vec![])
    );
    let indication = remote.send_owned_update(17, true, deadline()).await?;
    assert_eq!(
        (indication.stage, indication.pdu, indication.acknowledgement),
        (2, vec![16, 3, 17, 0, 1, 0, 0xab], vec![17, 3, 1])
    );
    assert!(
        matches!(remote.send_owned_update(18,false,deadline()).await,Err(ApplicationError::Bus(zbus::Error::MethodError(name,_,_))) if name.as_str()=="org.freedesktop.DBus.Error.AccessDenied")
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 4);
    Ok(())
}
