//! Actual typed client through a private bus. Finite argument/result fixtures,
//! not Native management, hardware completion, RF or a second Host.
mod support;
use libsparklink::{ApplicationError, Client};
use std::sync::{
    Arc,
    atomic::{AtomicU64, AtomicUsize, Ordering},
};
use tokio::sync::Notify;
const BASE: &str = "/org/sparklink/slk2_g7";
#[derive(Default)]
struct State {
    generation: AtomicU64,
    result_generation: AtomicU64,
    allocations: AtomicUsize,
    submissions: AtomicUsize,
    results: AtomicUsize,
    entered: Notify,
    release: Notify,
    hold: bool,
}
impl State {
    fn new(hold: bool) -> Arc<Self> {
        Arc::new(Self {
            generation: AtomicU64::new(7),
            result_generation: AtomicU64::new(7),
            hold,
            ..Default::default()
        })
    }
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
struct Adapter(Arc<State>);
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        self.0.generation.load(Ordering::SeqCst)
    }
    fn allocate_connection_request(&self) -> u64 {
        self.0.allocations.fetch_add(1, Ordering::SeqCst);
        101
    }
    fn submit_connect(&self, id: u64, address: &str, kind: u8) -> zbus::fdo::Result<()> {
        if (id, address, kind) != (101, "01:02:03:04:05:06", 1) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "exact argument fixture only".into(),
            ));
        }
        self.0.submissions.fetch_add(1, Ordering::SeqCst);
        Ok(()) // Software RPC admission only.
    }
    async fn get_connection_result(&self, id: u64) -> slk_contract::controller::ConnectionResult {
        assert_eq!(id, 101);
        self.0.results.fetch_add(1, Ordering::SeqCst);
        if self.0.hold {
            self.0.entered.notify_one();
            self.0.release.notified().await;
        }
        // Explicit result-shape fixture, never a protocol Complete event.
        (
            self.0.result_generation.load(Ordering::SeqCst),
            id,
            1,
            4,
            0,
            0,
            0,
            0,
            3,
            7,
        )
    }
    fn submit_scanning(&self, _id: u64) -> zbus::fdo::Result<()> {
        Err(zbus::fdo::Error::AccessDenied(
            "management is distinct from ordinary observation".into(),
        ))
    }
}
struct Registration;
#[zbus::interface(name = "org.sparklink.Registration")]
impl Registration {
    fn get_snapshot(&self) -> slk_protocol::RegistrationSnapshotRecord {
        (
            7,
            1,
            slk_protocol::REGISTRATION_PENDING,
            1,
            0,
            0,
            2,
            slk_protocol::BusType::Usb as u8,
        )
    }
}
async fn server(address: &str, state: Arc<State>) -> anyhow::Result<zbus::Connection> {
    Ok(zbus::connection::Builder::address(address)?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter(state))?
        .serve_at(BASE, Registration)?
        .build()
        .await?)
}
async fn client(address: &str) -> anyhow::Result<Client> {
    Ok(
        Client::from_connection(zbus::connection::Builder::address(address)?.build().await?)
            .await?,
    )
}
#[tokio::test]
async fn existing_typed_calls_propagate_policy_and_reject_payload_identity_changes()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = State::new(false);
    let _server = server(&bus.address, state.clone()).await?;
    let client = client(&bus.address).await?;
    let c = client.controller(BASE).await?;
    assert_eq!(c.id().generation, 7);
    let m = c.management();
    assert_eq!(m.allocate_connection_request().await?, 101);
    m.connect(101, "01:02:03:04:05:06", 1).await?;
    assert_eq!(m.connection_result(101).await?.3, 4);
    assert!(
        matches!(m.scan(5).await,Err(ApplicationError::Bus(zbus::Error::MethodError(name,_,_))) if name.as_str()=="org.freedesktop.DBus.Error.AccessDenied")
    );
    state.result_generation.store(8, Ordering::SeqCst);
    assert!(matches!(
        m.connection_result(101).await,
        Err(ApplicationError::Identity(_))
    ));
    state.generation.store(8, Ordering::SeqCst);
    assert!(matches!(
        m.connect(101, "01:02:03:04:05:06", 1).await,
        Err(ApplicationError::Identity(_))
    ));
    assert_eq!(state.submissions.load(Ordering::SeqCst), 1);
    Ok(())
}
#[tokio::test]
async fn owner_change_after_allocate_cannot_submit_or_read_under_replacement() -> anyhow::Result<()>
{
    let bus = support::Bus::start();
    let old = State::new(false);
    let a = server(&bus.address, old.clone()).await?;
    let c = client(&bus.address).await?.controller(BASE).await?;
    let m = c.management();
    let id = m.allocate_connection_request().await?;
    a.release_name("org.sparklink").await?;
    let new = State::new(false);
    let _b = server(&bus.address, new.clone()).await?;
    assert!(matches!(
        m.connect(id, "01:02:03:04:05:06", 1).await,
        Err(ApplicationError::Identity(_))
    ));
    assert!(matches!(
        m.connection_result(id).await,
        Err(ApplicationError::Identity(_))
    ));
    assert_eq!(old.allocations.load(Ordering::SeqCst), 1);
    assert_eq!(old.submissions.load(Ordering::SeqCst), 0);
    assert_eq!(
        new.allocations.load(Ordering::SeqCst)
            + new.submissions.load(Ordering::SeqCst)
            + new.results.load(Ordering::SeqCst),
        0
    );
    Ok(())
}
#[tokio::test]
async fn late_result_after_admission_never_relabels_replacement_as_original_author()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let old = State::new(true);
    let a = server(&bus.address, old.clone()).await?;
    let c = client(&bus.address).await?.controller(BASE).await?;
    let m = c.management();
    let id = m.allocate_connection_request().await?;
    m.connect(id, "01:02:03:04:05:06", 1).await?;
    let query = m.connection_result(id);
    let replacement = async {
        old.entered.notified().await;
        a.release_name("org.sparklink").await?;
        let new = State::new(false);
        let b = server(&bus.address, new.clone()).await?;
        old.release.notify_one();
        Ok::<_, anyhow::Error>((b, new))
    };
    let (result, b) = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        tokio::join!(query, replacement)
    })
    .await?;
    let (_b, new) = b?;
    assert!(matches!(result, Err(ApplicationError::Identity(_))));
    assert_eq!(old.submissions.load(Ordering::SeqCst), 1);
    assert_eq!(old.results.load(Ordering::SeqCst), 1);
    assert_eq!(new.results.load(Ordering::SeqCst), 0);
    Ok(())
}
#[tokio::test]
async fn core_pending_registration_does_not_require_ready_adapter_properties() -> anyhow::Result<()>
{
    let bus = support::Bus::start();
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Registration)?
        .build()
        .await?;
    let client = client(&bus.address).await?;
    assert_eq!(client.registrations().await?, [BASE]);
    let v = client.registration(BASE).await?;
    assert_eq!(v.state, slk_protocol::REGISTRATION_PENDING);
    assert!(client.controller(BASE).await.is_err());
    Ok(())
}

struct ForeignPeer(Arc<AtomicUsize>);
#[zbus::interface(name = "org.sparklink.Peer")]
impl ForeignPeer {
    fn get_info(&self) -> (u64, u8, String, bool, bool, Vec<String>) {
        self.0.fetch_add(1, Ordering::SeqCst);
        (9, 1, "01:02:03:04:05:06".into(), true, false, vec![])
    }
}
#[tokio::test]
async fn foreign_peer_path_is_rejected_without_querying_the_other_controller() -> anyhow::Result<()>
{
    let bus = support::Bus::start();
    let count = Arc::new(AtomicUsize::new(0));
    let foreign = "/org/sparklink/slk3_g9/peer_t01_010203040506";
    let server = server(&bus.address, State::new(false)).await?;
    server
        .object_server()
        .at(foreign, ForeignPeer(count.clone()))
        .await?;
    let c = client(&bus.address).await?;
    assert!(matches!(
        c.peer_info(BASE, foreign).await,
        Err(ApplicationError::Identity(_))
    ));
    assert_eq!(count.load(Ordering::SeqCst), 0);
    Ok(())
}
