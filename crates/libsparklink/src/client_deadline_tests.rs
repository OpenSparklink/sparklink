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
