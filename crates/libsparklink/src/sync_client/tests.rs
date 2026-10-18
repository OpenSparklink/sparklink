//! Real Client and executor with a private D-Bus fixture, never a controller.
use super::*;
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
#[path = "../../tests/support/mod.rs"]
mod support;

struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec!["/org/sparklink/slk2_g7".into()]
    }
}
fn after(duration: Duration) -> Deadline {
    at(Instant::now() + duration)
}
fn at(point: Instant) -> Deadline {
    let deadline = slk_channel::deadline::Deadline::at(point).unwrap();
    Deadline(deadline.instant(), deadline.stamp().monotonic_ns)
}
fn open(address: String) -> Result<SyncClient> {
    SyncClient::start(after(Duration::from_secs(3)), move || async move {
        Client::from_connection(
            zbus::connection::Builder::address(address.as_str())?
                .build()
                .await?,
        )
        .await
    })
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_executor_keeps_owner_watch_alive_and_joins_on_final_release() -> anyhow::Result<()>
{
    let bus = support::Bus::start();
    let server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .build()
        .await?;
    let name = Arc::new(std::sync::Mutex::new(String::new()));
    let stored = name.clone();
    let address = bus.address.clone();
    let client = SyncClient::start(after(Duration::from_secs(3)), move || async move {
        let connection = zbus::connection::Builder::address(address.as_str())?
            .build()
            .await?;
        *stored.lock().unwrap() = connection.unique_name().unwrap().to_string();
        Client::from_connection(connection).await
    })
    .map_err(std::io::Error::from_raw_os_error)?;
    let caller_name = name.lock().unwrap().clone();
    assert_eq!(
        client
            .call(after(Duration::from_secs(2)), |c| async move {
                c.controllers().await
            })
            .unwrap()[0]
            .generation,
        7
    );
    server.release_name("org.sparklink").await?;
    server.request_name("org.sparklink").await?; // Same unique process is still a lost scope.
    assert_eq!(
        client
            .call(after(Duration::from_secs(2)), |c| async move {
                c.controllers().await
            })
            .unwrap_err(),
        nix::libc::ESTALE
    );
    drop(client); // Join, not detached shutdown_background.
    let manager = zbus::fdo::DBusProxy::new(&server).await?;
    let limit = tokio::time::Instant::now() + Duration::from_secs(2);
    while manager
        .name_has_owner(caller_name.as_str().try_into()?)
        .await?
    {
        assert!(
            tokio::time::Instant::now() < limit,
            "client bus connection retained after join"
        );
        tokio::task::yield_now().await;
    }
    assert!(manager.name_has_owner("org.sparklink".try_into()?).await?);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queue_is_bounded_expired_jobs_never_invoke_operations_and_time_is_not_reset()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .build()
        .await?;
    let client = Arc::new(open(bus.address.clone()).map_err(std::io::Error::from_raw_os_error)?);
    let (started, seen) = mpsc::sync_channel(1);
    let gate = Arc::new(tokio::sync::Notify::new());
    let blocking_client = client.clone();
    let blocked_gate = gate.clone();
    let blocked = thread::spawn(move || {
        blocking_client.call(after(Duration::from_secs(5)), move |_| async move {
            started.send(()).unwrap();
            blocked_gate.notified().await;
            Ok(())
        })
    });
    seen.recv_timeout(Duration::from_secs(2)).unwrap();
    let called = Arc::new(AtomicUsize::new(0));
    let queued: Vec<_> = (0..QUEUED)
        .map(|_| {
            let c = client.clone();
            let count = called.clone();
            thread::spawn(move || {
                c.call(after(Duration::from_millis(600)), move |_| async move {
                    count.fetch_add(1, Ordering::SeqCst);
                    Ok(())
                })
            })
        })
        .collect();
    let limit = Instant::now() + Duration::from_secs(2);
    while client.sender.as_ref().unwrap().capacity() != 0 {
        assert!(Instant::now() < limit);
        thread::yield_now();
    }
    assert_eq!(
        client.call(after(Duration::from_secs(1)), |_| async { Ok(()) }),
        Err(nix::libc::EAGAIN)
    );
    for waiter in queued {
        assert_eq!(waiter.join().unwrap(), Err(nix::libc::ETIMEDOUT));
    }
    gate.notify_one();
    assert_eq!(blocked.join().unwrap(), Ok(()));
    client
        .call(after(Duration::from_secs(2)), |c| async move {
            c.controllers().await
        })
        .unwrap();
    assert_eq!(called.load(Ordering::SeqCst), 0);
    Ok(())
}

#[test]
fn expired_connect_is_rejected_before_dependency_and_current_runtime_can_call() {
    let called = Arc::new(AtomicUsize::new(0));
    let count = called.clone();
    assert!(matches!(
        SyncClient::start(at(Instant::now()), move || async move {
            count.fetch_add(1, Ordering::SeqCst);
            Err(ApplicationError::Invalid("fixture"))
        }),
        Err(nix::libc::ETIMEDOUT)
    ));
    assert_eq!(called.load(Ordering::SeqCst), 0);
    assert!(matches!(
        Deadline::from_monotonic_ns(0),
        Err(nix::libc::ETIMEDOUT)
    ));
    assert!(matches!(
        Deadline::from_monotonic_ns(u64::MAX),
        Err(nix::libc::EINVAL)
    ));
    let runtime = tokio::runtime::Runtime::new().unwrap();
    runtime.block_on(async {
        // A caller already running Tokio must not block_on/drop a nested runtime.
        assert!(matches!(
            SyncClient::start(after(Duration::from_secs(2)), || async {
                Err(ApplicationError::Invalid("fixture"))
            }),
            Err(nix::libc::EINVAL)
        ));
    });
}
