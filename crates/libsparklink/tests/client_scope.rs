//! Real private bus and production Client; read-only RPC fixtures only.
//! No Native controller, security state, hardware or delivery is synthesized.
mod support;
use libsparklink::Client;
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use std::time::Duration;
use zbus::export::ordered_stream::OrderedStreamExt;
struct Manager(Arc<AtomicUsize>);
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        self.0.fetch_add(1, Ordering::SeqCst);
        vec!["/org/sparklink/slk2_g7".into()]
    }
}
#[tokio::test]
async fn original_scope_does_not_revive_when_same_unique_owner_reacquires_name()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let calls = Arc::new(AtomicUsize::new(0));
    let server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager(calls.clone()))?
        .build()
        .await?;
    let conn = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let client = Client::from_connection(conn.clone()).await?;
    assert_eq!(client.controllers().await?.len(), 1);
    let original = client.daemon_owner().to_owned();
    let monitor = zbus::fdo::DBusProxy::new(&conn).await?;
    let mut changes = monitor
        .receive_name_owner_changed_with_args(&[(0, "org.sparklink")])
        .await?;
    server.release_name("org.sparklink").await?;
    server.request_name("org.sparklink").await?;
    tokio::time::timeout(Duration::from_secs(1), async {
        assert!(changes.next().await.is_some());
        assert!(changes.next().await.is_some());
    })
    .await?;
    let now = monitor.get_name_owner("org.sparklink".try_into()?).await?;
    assert_eq!(now.as_str(), original); // Same process, unique name, path and values.
    // A finite diagnostic poll permits notification delivery. Once invalidated,
    // later identical name/values cannot reactivate this Client or its clones.
    let invalidated = tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            if client.controllers().await.is_err() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert!(
        invalidated.is_ok(),
        "production Client scope revived/never invalidated; accepted readonly calls={}",
        calls.load(Ordering::SeqCst)
    );
    let before = calls.load(Ordering::SeqCst);
    assert!(client.clone().controllers().await.is_err());
    assert_eq!(calls.load(Ordering::SeqCst), before);
    Ok(())
}

#[tokio::test]
async fn clones_share_scope_and_final_release_only_terminates_local_watch() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let calls = Arc::new(AtomicUsize::new(0));
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager(calls))?
        .build()
        .await?;
    let conn = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let client = Client::from_connection(conn.clone()).await?;
    let lost = client.owner_loss();
    let clone = client.clone();
    drop(client);
    assert!(!*lost.borrow());
    assert_eq!(clone.controllers().await?.len(), 1);
    drop(clone);
    assert!(*lost.borrow()); // Immediate; not dependent on task polling.
    // Releasing a view does not stop the controller/daemon or revoke other views.
    let fresh = Client::from_connection(conn).await?;
    assert!(!fresh.daemon_lost());
    assert_eq!(fresh.controllers().await?.len(), 1);
    Ok(())
}

#[tokio::test]
async fn actual_bus_stream_termination_invalidates_scope_instead_of_staying_live()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let calls = Arc::new(AtomicUsize::new(0));
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager(calls))?
        .build()
        .await?;
    let client = Client::from_connection(
        zbus::connection::Builder::address(bus.address.as_str())?
            .build()
            .await?,
    )
    .await?;
    let mut lost = client.owner_loss();
    drop(bus);
    tokio::time::timeout(Duration::from_secs(1), async {
        while !*lost.borrow() {
            lost.changed().await?;
        }
        Ok::<_, tokio::sync::watch::error::RecvError>(())
    })
    .await??;
    assert!(client.daemon_lost());
    assert!(client.controllers().await.is_err());
    Ok(())
}
