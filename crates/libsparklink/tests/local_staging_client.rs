//! Actual SDK -> private bus. Finite manager reply/permission fixtures;
//! not a service database, wire Engine, Native control or peer publication.
mod support;
use libsparklink::{ApplicationError, Client};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU64, Ordering},
};
const BASE: &str = "/org/sparklink/slk2_g7";
const PATH: &str = "/org/sparklink/slk2_g7/services";
#[derive(Default)]
struct State {
    generation: AtomicU64,
    calls: Mutex<Vec<&'static str>>,
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
type Definition = (Vec<u8>, u32, u32, Vec<u8>);
type Record = (u16, u16, Vec<u8>, Vec<(u16, Vec<u8>, u32, u32)>);
struct Services(Arc<State>);
#[zbus::interface(name = "org.sparklink.ServiceManager")]
impl Services {
    fn list_local_services(&self) -> Vec<Record> {
        self.0.calls.lock().unwrap().push("list");
        vec![(16, 17, vec![1, 0], vec![(17, vec![2, 0], 1, 0)])]
    }
    fn register_local_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<Definition>,
    ) -> zbus::fdo::Result<(u16, u16, Vec<u16>)> {
        self.0.calls.lock().unwrap().push("register");
        if uuid != [1, 0] || properties != vec![(vec![2, 0], 1, 0, vec![0xab])] {
            return Err(zbus::fdo::Error::AccessDenied(
                "finite permitted arguments only".into(),
            ));
        }
        Ok((16, 17, vec![17]))
    }
    fn read_local_value(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        self.0.calls.lock().unwrap().push("read");
        if handle != 17 {
            return Err(zbus::fdo::Error::InvalidArgs("unknown handle".into()));
        }
        Ok(vec![0xab])
    }
    fn remove_local_service(&self, start: u16) -> zbus::fdo::Result<()> {
        self.0.calls.lock().unwrap().push("remove");
        if start != 16 {
            return Err(zbus::fdo::Error::AccessDenied("foreign service".into()));
        }
        Ok(())
    }
}
#[tokio::test]
async fn actual_manager_sdk_preserves_wire_errors_and_refuses_stale_scope_without_retry()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let s = Arc::new(State {
        generation: AtomicU64::new(7),
        ..Default::default()
    });
    let a = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter(s.clone()))?
        .serve_at(PATH, Services(s.clone()))?
        .build()
        .await?;
    let client = Client::from_connection(
        zbus::connection::Builder::address(bus.address.as_str())?
            .build()
            .await?,
    )
    .await?;
    let staging = client.controller(BASE).await?.management().local_services();
    let list = staging.list().await?;
    assert_eq!(
        list,
        vec![(16, 17, vec![1, 0], vec![(17, vec![2, 0], 1, 0)])]
    );
    assert_eq!(
        staging
            .register(vec![1, 0], vec![(vec![2, 0], 1, 0, vec![0xab])])
            .await?,
        (16, 17, vec![17])
    );
    assert_eq!(staging.read_local(17).await?, [0xab]);
    staging.remove(16).await?;
    assert_eq!(
        *s.calls.lock().unwrap(),
        ["list", "register", "read", "remove"]
    );
    let error = staging.remove(19).await.unwrap_err();
    assert!(
        matches!(error,ApplicationError::Bus(zbus::Error::MethodError(ref name,_,_)) if name.as_str()=="org.freedesktop.DBus.Error.AccessDenied")
    );
    let before = s.calls.lock().unwrap().len();
    s.generation.store(8, Ordering::SeqCst);
    assert!(staging.list().await.is_err());
    assert_eq!(s.calls.lock().unwrap().len(), before);
    s.generation.store(7, Ordering::SeqCst);
    let mut lost = client.owner_loss();
    a.release_name("org.sparklink").await?;
    tokio::time::timeout(std::time::Duration::from_secs(1), lost.changed()).await??;
    a.request_name("org.sparklink").await?;
    assert!(
        staging
            .register(vec![1, 0], vec![(vec![2, 0], 1, 0, vec![0xab])])
            .await
            .is_err()
    );
    assert_eq!(s.calls.lock().unwrap().len(), before);
    Ok(())
}
