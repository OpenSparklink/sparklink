//! Direct production bounded() tests with the real local clock and private bus.
//! The bus supplies only daemon-name ownership. Work futures are explicit SDK
//! boundary fixtures, never Native, firmware, protocol or hardware stand-ins.
use crate::test_support as support;

use super::{ApplicationError, Client, Result, bounded};
use slk_channel::deadline::Deadline;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

async fn client(bus: &support::Bus) -> anyhow::Result<(zbus::Connection, Client)> {
    let server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .build()
        .await?;
    let caller = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    Ok((server, Client::from_connection(caller).await?))
}
fn timed_out<T>(result: Result<T>) -> bool {
    matches!(result, Err(ApplicationError::Io(error))
        if error.raw_os_error() == Some(nix::libc::ETIMEDOUT))
}

#[tokio::test]
async fn live_deadline_preserves_success_and_typed_inner_errors() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let (_server, client) = client(&bus).await?;
    let original = Deadline::after(Duration::from_secs(2))?;
    assert_eq!(bounded(&client, original, async { Ok(42) }).await?, 42);
    assert!(matches!(
        bounded::<()>(&client, original, async {
            Err(zbus::Error::from(zbus::fdo::Error::NotSupported("capability denial".into())).into())
        }).await,
        Err(ApplicationError::Bus(zbus::Error::FDO(error)))
            if matches!(*error, zbus::fdo::Error::NotSupported(_))
    ));
    assert!(matches!(
        bounded::<()>(&client, original, async {
            Err(ApplicationError::Invalid("explicit pre-deadline refusal"))
        })
        .await,
        Err(ApplicationError::Invalid("explicit pre-deadline refusal"))
    ));
    assert!(matches!(
        bounded::<()>(&client, original, async {
            Err(std::io::Error::from_raw_os_error(nix::libc::EACCES).into())
        }).await,
        Err(ApplicationError::Io(error)) if error.raw_os_error() == Some(nix::libc::EACCES)
    ));
    Ok(())
}

#[tokio::test]
async fn a_ready_inner_result_cannot_bypass_the_original_deadline() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let (_server, client) = client(&bus).await?;
    for outcome in [
        Ok(()),
        Err(zbus::Error::from(zbus::fdo::Error::NotSupported("capability denial".into())).into()),
        Err(ApplicationError::Invalid("explicit ready error")),
        Err(std::io::Error::from_raw_os_error(nix::libc::EACCES).into()),
    ] {
        let original = Deadline::after(Duration::from_millis(100))?;
        let calls = AtomicUsize::new(0);
        let result = bounded(&client, original, async {
            calls.fetch_add(1, Ordering::SeqCst);
            // Deliberately one non-yielding poll: the real deadline expires
            // before the inner future returns Ready, including Ready(Err).
            // This is a bounded scheduler fixture, not production blocking I/O.
            std::thread::sleep(
                original.instant().saturating_duration_since(Instant::now())
                    + Duration::from_millis(1),
            );
            assert!(original.remaining().is_err());
            outcome
        })
        .await;
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert!(timed_out(result));
    }
    Ok(())
}

#[tokio::test]
async fn expired_scope_never_polls_the_operation_and_pending_work_times_out() -> anyhow::Result<()>
{
    let bus = support::Bus::start();
    let (_server, client) = client(&bus).await?;
    let expired = Deadline::at(Instant::now() - Duration::from_millis(1))?;
    let calls = AtomicUsize::new(0);
    assert!(timed_out(
        bounded(&client, expired, async {
            calls.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
        .await
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let original = Deadline::after(Duration::from_millis(20))?;
    assert!(timed_out(
        bounded(&client, original, std::future::pending::<Result<()>>()).await
    ));
    Ok(())
}

#[tokio::test]
async fn real_owner_loss_before_deadline_still_refuses_work() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let (server, client) = client(&bus).await?;
    let entered = tokio::sync::Notify::new();
    let original = Deadline::after(Duration::from_secs(2))?;
    let call = bounded(&client, original, async {
        entered.notify_one();
        std::future::pending::<Result<()>>().await
    });
    let release = async {
        entered.notified().await;
        server.release_name("org.sparklink").await
    };
    let (result, released) = tokio::time::timeout(Duration::from_secs(3), async {
        tokio::join!(call, release)
    })
    .await?;
    released?;
    assert!(original.remaining().is_ok());
    assert!(matches!(result, Err(ApplicationError::Identity(_))));
    let calls = AtomicUsize::new(0);
    assert!(matches!(
        bounded(&client, original, async {
            calls.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
        .await,
        Err(ApplicationError::Identity(_))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    Ok(())
}

/// The method and disconnect use a real private bus. Only delivery of the
/// Client's ownership watch is held back, to force the RPC-error-first order.
/// This does not stand in for a real slkd, kernel, transport or hardware test.
struct PendingCall {
    entered: std::sync::Arc<tokio::sync::Notify>,
}
#[zbus::interface(name = "org.sparklink.TestPending")]
impl PendingCall {
    async fn wait(&self) -> u8 {
        self.entered.notify_one();
        std::future::pending().await
    }
    fn no_reply(&self) -> zbus::fdo::Result<u8> {
        Err(zbus::fdo::Error::NoReply(
            "explicit live-owner fixture error".into(),
        ))
    }
}

#[tokio::test]
async fn actual_no_reply_before_owner_watch_is_stale_without_renewing_deadline()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let entered = std::sync::Arc::new(tokio::sync::Notify::new());
    let server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at(
            "/test",
            PendingCall {
                entered: entered.clone(),
            },
        )?
        .build()
        .await?;
    let connection = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let mut client = Client::from_connection(connection).await?;
    // Explicit watch-delivery fixture: the bus still supplies authoritative
    // ownership, and the pending method really loses its peer connection.
    let (terminal, lost) = tokio::sync::watch::channel(false);
    let scope = std::sync::Arc::get_mut(&mut client.scope).expect("unshared fixture client");
    scope.terminal = terminal;
    scope.lost = lost;
    let original = Deadline::after(Duration::from_secs(2))?;
    let call = bounded(&client, original, async {
        Ok(client
            .original_proxy("/test", "org.sparklink.TestPending")
            .await?
            .call::<_, _, u8>("Wait", &())
            .await?)
    });
    let disconnect = async {
        entered.notified().await;
        server.close().await
    };
    let (result, closed) = tokio::time::timeout(Duration::from_secs(3), async {
        tokio::join!(call, disconnect)
    })
    .await?;
    closed?;
    assert!(
        original.remaining().is_ok(),
        "owner loss must not consume original deadline"
    );
    assert!(
        matches!(result, Err(ApplicationError::Identity(_))),
        "actual reply-first result: {result:?}"
    );
    assert!(
        client.daemon_lost(),
        "authoritative missing owner is terminal for this scope"
    );
    Ok(())
}

#[tokio::test]
async fn actual_live_owner_no_reply_is_not_invented_owner_loss() -> anyhow::Result<()> {
    let bus = support::Bus::start();
    let server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at(
            "/test",
            PendingCall {
                entered: Default::default(),
            },
        )?
        .build()
        .await?;
    let connection = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let client = Client::from_connection(connection).await?;
    let original = Deadline::after(Duration::from_secs(2))?;
    let result = bounded(&client, original, async {
        Ok(client
            .original_proxy("/test", "org.sparklink.TestPending")
            .await?
            .call::<_, _, u8>("NoReply", &())
            .await?)
    })
    .await;
    assert!(
        matches!(result, Err(ApplicationError::Bus(zbus::Error::MethodError(ref name, _, _)))
        if name.as_str() == "org.freedesktop.DBus.Error.NoReply")
    );
    assert!(!client.daemon_lost());
    assert!(original.remaining().is_ok());
    server.close().await?;
    Ok(())
}
