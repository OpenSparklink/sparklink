//! Real private D-Bus SDK entry tests with explicit server observations and
//! Unix fd fixtures. No fixture is accepted as a real SparkLink channel.
mod support;
use libsparklink::{ApplicationError, Client};
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
    calls: Arc<AtomicUsize>,
}
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
    fn get_info(&self) -> (u64, u64, u16, u8, u8, String, bool, bool) {
        (7, 11, 3, 0, 1, "01:02:03:04:05:06".into(), true, true)
    }
    fn open_channel(&self) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Err(zbus::fdo::Error::AccessDenied(
            "explicit fixture denial".into(),
        ))
    }
    fn open_channel_scoped(
        &self,
        directions: u32,
        minimum: u32,
    ) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
        assert_eq!((directions, minimum), (3, 2));
        self.calls.fetch_add(10, Ordering::SeqCst);
        let fd: std::os::fd::OwnedFd = std::os::unix::net::UnixDatagram::unbound()
            .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?
            .into();
        Ok(fd.into())
    }
}
async fn fixture(
    address: &str,
) -> anyhow::Result<(
    zbus::Connection,
    zbus::Connection,
    Arc<AtomicU64>,
    Arc<AtomicUsize>,
)> {
    let generation = Arc::new(AtomicU64::new(7));
    let calls = Arc::new(AtomicUsize::new(0));
    let server = zbus::connection::Builder::address(address)?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter(generation.clone()))?
        .serve_at(
            PATH,
            Link {
                calls: calls.clone(),
            },
        )?
        .build()
        .await?;
    let caller = zbus::connection::Builder::address(address)?.build().await?;
    Ok((server, caller, generation, calls))
}
#[tokio::test]
async fn actual_sdk_pins_identity_and_does_not_fallback_or_accept_unix_fd() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let (_server, caller, generation, calls) = fixture(&bus.address).await?;
    let client = Client::from_connection(caller).await?;
    let ids = client.controllers().await?;
    assert_eq!(ids.len(), 1);
    assert_eq!(ids[0].generation, 7);
    let link = client.connection(BASE, PATH).await?;
    assert!(
        client
            .connection(BASE, &PATH.replace("000000000000000b", "000000000000000c"))
            .await
            .is_err()
    );
    assert!(matches!(
        link.open_channel(3, 3).await,
        Err(ApplicationError::Invalid(_))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert!(
        matches!(link.open_channel(3,0).await,Err(ApplicationError::Bus(zbus::Error::MethodError(name,_,_))) if name.as_str()=="org.freedesktop.DBus.Error.AccessDenied")
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(
        matches!(link.open_channel(3,2).await,Err(ApplicationError::Io(error)) if error.raw_os_error()==Some(nix::libc::EAFNOSUPPORT))
    );
    assert_eq!(calls.load(Ordering::SeqCst), 11); // No weaker OpenChannel fallback.
    generation.store(8, Ordering::SeqCst);
    assert!(matches!(
        link.open_channel(3, 0).await,
        Err(ApplicationError::Identity(_))
    )); // Fresh selected-generation check refuses actual fd admission,not just a list.
    assert_eq!(calls.load(Ordering::SeqCst), 11);
    Ok(())
}
#[tokio::test]
async fn actual_sdk_does_not_follow_replacement_daemon() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let (server, caller, _, _) = fixture(&bus.address).await?;
    let client = Client::from_connection(caller).await?;
    assert!(!client.controllers().await?.is_empty());
    server.release_name("org.sparklink").await?;
    let replacement = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .build()
        .await?;
    assert_ne!(
        replacement.unique_name().unwrap().as_str(),
        client.daemon_owner()
    );
    assert!(matches!(
        client.controllers().await,
        Err(ApplicationError::Identity(_))
    ));
    Ok(())
}

struct ManagerWithUnavailablePeer;
#[zbus::interface(name = "org.sparklink.Manager")]
impl ManagerWithUnavailablePeer {
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into(), "/org/sparklink/slk3_g9".into()]
    }
}
#[tokio::test]
async fn selected_controller_does_not_query_an_unavailable_other_controller() -> anyhow::Result<()>
{
    let bus = support::Bus::start();
    let calls = Arc::new(AtomicUsize::new(0));
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", ManagerWithUnavailablePeer)?
        .serve_at(BASE, Adapter(Arc::new(AtomicU64::new(7))))?
        .serve_at(
            PATH,
            Link {
                calls: calls.clone(),
            },
        )?
        .build()
        .await?;
    let caller = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let client = Client::from_connection(caller).await?;
    // There is deliberately no object for the other registered controller.
    let selected = client.connection(BASE, PATH).await?;
    assert!(
        matches!(selected.open_channel(3,0).await,Err(ApplicationError::Bus(zbus::Error::MethodError(name,_,_))) if name.as_str()=="org.freedesktop.DBus.Error.AccessDenied")
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    Ok(())
}
