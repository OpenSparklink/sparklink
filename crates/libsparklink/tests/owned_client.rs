//! Actual SDK/private bus. Bounded local registration fixtures only; no service
//! database, callback policy, Native admission, crypto or wire Engine is faked.
mod support;
use libsparklink::Client;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, AtomicU8, AtomicU64, Ordering},
};
use zbus::{Connection, zvariant::OwnedObjectPath};
const BASE: &str = "/org/sparklink/slk2_g7";
const LINK: &str = "/org/sparklink/slk2_g7/peer_t00_010203040506/link_000000000000000d";
#[derive(Default)]
struct State {
    generation: AtomicU64,
    owner: Mutex<String>,
    removals: AtomicU64,
    agent_epoch: AtomicU64,
    cancellations: AtomicU64,
    owned_mode: AtomicU8,
    registrations: AtomicU64,
    stamps: Mutex<Vec<slk_contract::Deadline>>,
    read_only_property: AtomicBool,
    provider_mode: AtomicU8,
    provider_bindings: Mutex<Vec<(u16, String, slk_contract::Deadline)>>,
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
struct Services(Arc<State>);
#[zbus::interface(name = "org.sparklink.ServiceManager")]
impl Services {
    async fn register_owned_local_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<(Vec<u8>, u32, u32, Vec<u8>)>,
        authorizer: OwnedObjectPath,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<(u16, u16, Vec<u16>)> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        assert_eq!(uuid, [1, 0]);
        let (operations, access) = if self.0.read_only_property.load(Ordering::SeqCst) {
            (1, 32)
        } else {
            (5, 36)
        };
        assert_eq!(properties, [(vec![2, 0], operations, access, vec![0xab])]);
        assert_eq!(authorizer.as_str(), "/test/authorizer");
        *self.0.owner.lock().unwrap() = h.sender().unwrap().to_string();
        self.0.registrations.fetch_add(1, Ordering::SeqCst);
        self.0.stamps.lock().unwrap().push(deadline);
        match self.0.owned_mode.load(Ordering::SeqCst) {
            1 => tokio::time::sleep(std::time::Duration::from_millis(100)).await,
            2 => return Ok((16, 17, vec![999])),
            3 => {
                self.0.generation.store(8, Ordering::SeqCst);
            }
            _ => {}
        }
        Ok((16, 17, vec![17]))
    }
    fn read_owned_local_value(
        &self,
        handle: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> Vec<u8> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        assert_eq!(handle, 17);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        vec![0xab]
    }
    async fn bind_owned_read_provider(
        &self,
        handle: u16,
        provider: OwnedObjectPath,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<()> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        assert_eq!(handle, 17);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        self.0
            .provider_bindings
            .lock()
            .unwrap()
            .push((handle, provider.to_string(), deadline));
        match self.0.provider_mode.load(Ordering::SeqCst) {
            1 => tokio::time::sleep(std::time::Duration::from_millis(100)).await,
            2 => return Err(zbus::fdo::Error::NotSupported("fixture refusal".into())),
            _ => {}
        }
        Ok(())
    }
    fn unregister_owned_local_service(
        &self,
        start: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        assert_eq!(start, 16);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        self.0.stamps.lock().unwrap().push(deadline);
        self.0.removals.fetch_add(1, Ordering::SeqCst);
    }
}
struct Security(Arc<State>);
#[zbus::interface(name = "org.sparklink.Security")]
impl Security {
    fn register_agent(&self, path: OwnedObjectPath, method: &str) -> u64 {
        assert_eq!(path.as_str(), "/test/agent");
        assert_eq!(method, "sdk111-no-mitm");
        self.0.agent_epoch.fetch_add(1, Ordering::SeqCst) + 1
    }
    fn unregister_agent(&self, path: OwnedObjectPath, epoch: u64) -> zbus::fdo::Result<()> {
        assert_eq!(path.as_str(), "/test/agent");
        if epoch != self.0.agent_epoch.load(Ordering::SeqCst) {
            return Err(zbus::fdo::Error::AccessDenied("stale registration".into()));
        }
        self.0.removals.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}
type RawObservation = (
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
);
struct Link(Arc<State>);
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
    fn get_info(&self) -> (u64, u64, u16, u8, u8, String, bool, bool) {
        (7, 13, 1, 0, 0, "01:02:03:04:05:06".into(), true, true)
    }
    fn allocate_reference_security(&self, timeout_ms: u32) -> u64 {
        assert_eq!(timeout_ms, 100);
        42
    }
    fn begin_reference_security(&self, id: u64, method: &str) {
        assert_eq!(id, 42);
        assert_eq!(method, "sdk111-no-mitm");
    }
    // Literal allocated-only envelope: no native admission/install/Complete.
    fn get_reference_security_result(&self, id: u64) -> RawObservation {
        assert_eq!(id, 42);
        (42, 7, 13, 1, 0, 123, false, false, 0, 0, 0, 0, 0)
    }
    fn cancel_reference_security(&self, id: u64) -> bool {
        assert_eq!(id, 42);
        self.0.cancellations.fetch_add(1, Ordering::SeqCst);
        true
    }
}
async fn fixture(bus: &support::Bus, state: Arc<State>) -> Connection {
    zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink", Manager)
        .unwrap()
        .serve_at(BASE, Adapter(state.clone()))
        .unwrap()
        .serve_at(format!("{BASE}/services"), Services(state.clone()))
        .unwrap()
        .serve_at(LINK, Link(state.clone()))
        .unwrap()
        .serve_at(format!("{BASE}/security"), Security(state))
        .unwrap()
        .build()
        .await
        .unwrap()
}
#[tokio::test]
async fn owner_loss_blocks_new_work_but_original_receipts_withdraw_only_original_owner()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = Arc::new(State {
        generation: AtomicU64::new(7),
        ..Default::default()
    });
    let original = fixture(&bus, state.clone()).await;
    let connection = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let client = Client::from_connection(connection).await?;
    let view = client.controller(BASE).await?;
    let mut service = view
        .local_services()
        .register_service(
            vec![1, 0],
            vec![(vec![2, 0], 5, 36, vec![0xab])],
            "/test/authorizer".try_into()?,
            libsparklink::Deadline::after(std::time::Duration::from_secs(2))?,
        )
        .await?;
    assert_eq!(service.receipt(), &(16, 17, vec![17]));
    assert_eq!(
        service
            .read_local(
                17,
                libsparklink::Deadline::after(std::time::Duration::from_secs(2))?
            )
            .await?,
        [0xab]
    );
    assert!(
        service
            .read_local(
                18,
                libsparklink::Deadline::after(std::time::Duration::from_secs(2))?
            )
            .await
            .is_err()
    );
    let mut agent = view
        .register_agent("/test/agent".try_into()?, "sdk111-no-mitm")
        .await?;
    assert_eq!(agent.epoch(), 1);
    let link = client.connection(BASE, LINK).await?;
    let request = link.allocate_reference_security(100).await?;
    assert_eq!(request.id(), 42);
    let observation = request.observation().await?;
    assert_eq!(
        (observation.phase, observation.deadline_monotonic_ns),
        (1, 123)
    );
    assert!(!observation.native_admitted);
    request.begin("sdk111-no-mitm").await?;
    let mut lost = client.owner_loss();
    original.release_name("org.sparklink").await?;
    tokio::time::timeout(std::time::Duration::from_secs(1), lost.changed()).await??;
    let replacement_state = Arc::new(State {
        generation: AtomicU64::new(7),
        ..Default::default()
    });
    let _replacement = fixture(&bus, replacement_state.clone()).await;
    assert!(
        service
            .read_local(
                17,
                libsparklink::Deadline::after(std::time::Duration::from_secs(2))?
            )
            .await
            .is_err()
    );
    assert!(
        view.register_agent("/test/agent".try_into()?, "sdk111-no-mitm")
            .await
            .is_err()
    );
    assert!(request.begin("sdk111-no-mitm").await.is_err());
    assert!(request.observation().await.is_err());
    assert!(request.cancel().await?);
    assert_eq!(state.cancellations.load(Ordering::SeqCst), 1);
    assert_eq!(replacement_state.cancellations.load(Ordering::SeqCst), 0);
    service
        .unregister(libsparklink::Deadline::after(
            std::time::Duration::from_secs(2),
        )?)
        .await?;
    agent.unregister().await?;
    assert!(
        service
            .read_local(
                17,
                libsparklink::Deadline::after(std::time::Duration::from_secs(2))?
            )
            .await
            .is_err()
    );
    assert!(
        service
            .unregister(libsparklink::Deadline::after(
                std::time::Duration::from_secs(2)
            )?)
            .await
            .is_err()
    );
    assert!(agent.unregister().await.is_err());
    assert_eq!(state.removals.load(Ordering::SeqCst), 2);
    assert_eq!(replacement_state.removals.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn owned_registration_original_wait_receipt_validation_and_cleanup_target()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = Arc::new(State {
        generation: AtomicU64::new(7),
        ..Default::default()
    });
    let _server = fixture(&bus, state.clone()).await;
    let connection = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let client = Client::from_connection(connection).await?;
    let view = client.controller(BASE).await?;
    let original = libsparklink::Deadline::after(std::time::Duration::from_millis(5))?;
    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    assert!(
        view.local_services()
            .register_service(
                vec![1, 0],
                vec![(vec![2, 0], 5, 36, vec![0xab])],
                "/test/authorizer".try_into()?,
                original
            )
            .await
            .is_err()
    );
    assert_eq!(state.registrations.load(Ordering::SeqCst), 0);
    state.owned_mode.store(1, Ordering::SeqCst);
    let original = libsparklink::Deadline::after(std::time::Duration::from_millis(20))?;
    let result = view
        .local_services()
        .register_service(
            vec![1, 0],
            vec![(vec![2, 0], 5, 36, vec![0xab])],
            "/test/authorizer".try_into()?,
            original,
        )
        .await;
    assert!(
        matches!(result,Err(libsparklink::ApplicationError::Io(ref e)) if e.raw_os_error()==Some(nix::libc::ETIMEDOUT))
    );
    assert_eq!(
        state.stamps.lock().unwrap()[0].0,
        original.stamp().monotonic_ns
    );
    assert_eq!(
        state.removals.load(Ordering::SeqCst),
        0,
        "no receipt:never guess cleanup handle"
    );
    tokio::time::sleep(std::time::Duration::from_millis(110)).await;
    state.owned_mode.store(2, Ordering::SeqCst);
    assert!(
        view.local_services()
            .register_service(
                vec![1, 0],
                vec![(vec![2, 0], 5, 36, vec![0xab])],
                "/test/authorizer".try_into()?,
                libsparklink::Deadline::after(std::time::Duration::from_secs(2))?
            )
            .await
            .is_err()
    );
    assert_eq!(
        state.removals.load(Ordering::SeqCst),
        0,
        "malformed receipt:never remove a foreign owned handle"
    );
    state.owned_mode.store(3, Ordering::SeqCst);
    assert!(
        view.local_services()
            .register_service(
                vec![1, 0],
                vec![(vec![2, 0], 5, 36, vec![0xab])],
                "/test/authorizer".try_into()?,
                libsparklink::Deadline::after(std::time::Duration::from_secs(2))?
            )
            .await
            .is_err()
    );
    assert_eq!(
        state.removals.load(Ordering::SeqCst),
        1,
        "known valid receipt:withdraw at original unique owner"
    );
    Ok(())
}

#[tokio::test]
async fn read_provider_binding_validates_receipt_path_and_original_deadline_before_rpc()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = Arc::new(State {
        generation: AtomicU64::new(7),
        read_only_property: AtomicBool::new(true),
        ..Default::default()
    });
    let _server = fixture(&bus, state.clone()).await;
    let connection = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let client = Client::from_connection(connection).await?;
    let view = client.controller(BASE).await?;
    let mut service = view
        .local_services()
        .register_service(
            vec![1, 0],
            vec![(vec![2, 0], 1, 32, vec![0xab])],
            "/test/authorizer".try_into()?,
            libsparklink::Deadline::after(std::time::Duration::from_secs(2))?,
        )
        .await?;
    for (handle, path) in [
        (0, "/test/provider".to_string()),
        (18, "/test/provider".to_string()),
        (17, "/".to_string()),
        (17, format!("/{}", "p".repeat(255))),
    ] {
        assert!(matches!(
            service
                .bind_read_provider(
                    handle,
                    path.try_into()?,
                    libsparklink::Deadline::after(std::time::Duration::from_secs(2))?,
                )
                .await,
            Err(libsparklink::ApplicationError::Invalid(_))
        ));
    }
    let expired = libsparklink::Deadline::after(std::time::Duration::from_millis(5))?;
    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    assert!(matches!(
        service
            .bind_read_provider(17, "/test/provider".try_into()?, expired)
            .await,
        Err(libsparklink::ApplicationError::Io(ref e))
            if e.raw_os_error() == Some(nix::libc::ETIMEDOUT)
    ));
    assert!(state.provider_bindings.lock().unwrap().is_empty());

    let path = format!("/{}", "p".repeat(254));
    let original = libsparklink::Deadline::after(std::time::Duration::from_secs(2))?;
    service
        .bind_read_provider(17, path.clone().try_into()?, original)
        .await?;
    assert_eq!(
        *state.provider_bindings.lock().unwrap(),
        [(17, path, slk_contract::deadline_wire(original.stamp()))]
    );
    service
        .unregister(libsparklink::Deadline::after(
            std::time::Duration::from_secs(2),
        )?)
        .await?;
    assert!(matches!(
        service
            .bind_read_provider(
                17,
                "/test/provider".try_into()?,
                libsparklink::Deadline::after(std::time::Duration::from_secs(2))?,
            )
            .await,
        Err(libsparklink::ApplicationError::Invalid(_))
    ));
    assert_eq!(state.provider_bindings.lock().unwrap().len(), 1);
    Ok(())
}

#[tokio::test]
async fn read_provider_binding_wait_is_bounded_without_retry_or_error_fallback()
-> anyhow::Result<()> {
    for mode in [1, 2] {
        let bus = support::Bus::start();
        let state = Arc::new(State {
            generation: AtomicU64::new(7),
            read_only_property: AtomicBool::new(true),
            provider_mode: AtomicU8::new(mode),
            ..Default::default()
        });
        let server = fixture(&bus, state.clone()).await;
        let connection = zbus::connection::Builder::address(bus.address.as_str())?
            .build()
            .await?;
        let client = Client::from_connection(connection).await?;
        let service = client
            .controller(BASE)
            .await?
            .local_services()
            .register_service(
                vec![1, 0],
                vec![(vec![2, 0], 1, 32, vec![0xab])],
                "/test/authorizer".try_into()?,
                libsparklink::Deadline::after(std::time::Duration::from_secs(2))?,
            )
            .await?;
        let original =
            libsparklink::Deadline::after(std::time::Duration::from_millis(if mode == 1 {
                30
            } else {
                2000
            }))?;
        let result = service
            .bind_read_provider(17, "/test/provider".try_into()?, original)
            .await;
        if mode == 1 {
            assert!(
                matches!(result, Err(libsparklink::ApplicationError::Io(ref e))
                if e.raw_os_error() == Some(nix::libc::ETIMEDOUT))
            );
        } else {
            assert!(matches!(result, Err(libsparklink::ApplicationError::Bus(
                zbus::Error::MethodError(ref name, _, _)))
                if name.as_str() == "org.freedesktop.DBus.Error.NotSupported"));
        }
        assert_eq!(
            *state.provider_bindings.lock().unwrap(),
            [(
                17,
                "/test/provider".into(),
                slk_contract::deadline_wire(original.stamp())
            )]
        );
        let mut lost = client.owner_loss();
        server.release_name("org.sparklink").await?;
        tokio::time::timeout(std::time::Duration::from_secs(1), lost.changed()).await??;
        assert!(
            service
                .bind_read_provider(
                    17,
                    "/test/provider".try_into()?,
                    libsparklink::Deadline::after(std::time::Duration::from_secs(2))?,
                )
                .await
                .is_err()
        );
        assert_eq!(state.provider_bindings.lock().unwrap().len(), 1);
    }
    Ok(())
}
