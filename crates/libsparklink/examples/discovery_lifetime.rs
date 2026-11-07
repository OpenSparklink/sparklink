// SPDX-License-Identifier: GPL-2.0-only
//! VM test consumer of the public SDK. No Native fd, Host or cleanup worker.
//! Keep the original caller alive after TTL; only stdin permits stale close
//! and exit. A read deadline, process exit or explicit close cannot stand in
//! for the daemon's automatic TTL cleanup in the physical capture oracle.
use anyhow::{Context, ensure};
use libsparklink::{ApplicationError, Client, Deadline};
use slk_contract::ControllerId;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::io::{AsyncBufReadExt, BufReader};

fn wall_ns() -> anyhow::Result<u64> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_nanos()
        .try_into()?)
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn unhex(text: &str) -> anyhow::Result<Vec<u8>> {
    ensure!(
        text.len() <= 128 && text.len().is_multiple_of(2),
        "bounded byte prefix"
    );
    ensure!(text.is_ascii(), "ASCII hex prefix");
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).map_err(Into::into))
        .collect()
}
fn unknown(error: &ApplicationError) -> bool {
    matches!(error, ApplicationError::Bus(zbus::Error::MethodError(name, _, _))
        if name.as_str() == "org.freedesktop.DBus.Error.UnknownObject")
}
async fn live(bus: &zbus::Connection, caller: &str, client: &Client) -> anyhow::Result<()> {
    let proxy = zbus::fdo::DBusProxy::new(bus).await?;
    ensure!(
        proxy.name_has_owner(caller.try_into()?).await?,
        "original caller lost"
    );
    let owner = proxy
        .get_name_owner(slk_contract::SERVICE.try_into()?)
        .await?;
    ensure!(
        owner.as_str() == client.daemon_owner() && !client.daemon_lost(),
        "daemon replaced"
    );
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    ensure!(args.len() == 4, "PATH PREFIX_HEX LEASE_MS PEER_ADDRESS");
    let controller = ControllerId::from_path(&args[0]).context("immutable controller path")?;
    let prefix = unhex(&args[1])?;
    let lease: u32 = args[2].parse()?;
    ensure!(
        matches!(lease, 4000 | 12000),
        "fixed finite test lease only"
    );
    ensure!(args[3].len() == 17, "six-byte peer address");
    let peer = args[3]
        .split(':')
        .map(|v| {
            ensure!(v.len() == 2, "two-digit address bytes");
            Ok(u8::from_str_radix(v, 16)?)
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    ensure!(peer.len() == 6, "six-byte peer address");
    let boot = std::fs::read_to_string("/proc/cmdline")?;
    for token in [
        "ws73.application_discovery=1",
        "ws73.application_discovery_case=ttl",
    ] {
        ensure!(
            boot.split_whitespace().filter(|v| *v == token).count() == 1,
            "isolated explicit TTL VM only"
        );
    }
    let bus = zbus::Connection::system().await?;
    let caller = bus.unique_name().context("unique caller")?.to_string();
    let client = Client::from_connection(bus.clone()).await?;
    let original = Deadline::after(Duration::from_secs(20))?;
    let before = wall_ns()?;
    let mut session = client
        .discover(controller, prefix, -128, lease, original)
        .await?;
    let active = wall_ns()?;
    println!("Selected {}", args[0]);
    println!(
        "DiscoverySession: id={} path={} state=active source=broker",
        session.id(),
        args[0]
    );
    println!(
        "DiscoveryLease: session={} caller={} owner={} lease_ms={} before_wall_ns={} active_wall_ns={}",
        session.id(),
        caller,
        client.daemon_owner(),
        lease,
        before,
        active
    );
    let mut received = 0usize;
    loop {
        match session.read(true, original).await {
            Ok(batch) => {
                ensure!(
                    batch.dropped == 0 && batch.kernel_lost == 0,
                    "observation gap"
                );
                for report in batch.reports {
                    ensure!(
                        report.address_type == 0 && report.address == peer && report.rssi_known,
                        "actual selected peer and known RSSI required"
                    );
                    ensure!((-128..=20).contains(&report.rssi), "RSSI range");
                    received += 1;
                    ensure!(received <= 1024, "finite output budget");
                    println!(
                        "DiscoveryReport: session={} generation={} sequence={} address_type=0 address={} rssi={} data={}",
                        session.id(),
                        controller.generation,
                        report.sequence,
                        hex(&report.address),
                        report.rssi,
                        hex(&report.data)
                    );
                }
            }
            Err(error) if unknown(&error) => break,
            Err(ApplicationError::Bus(zbus::Error::MethodError(name, _, _)))
                if name.as_str() == "org.freedesktop.DBus.Error.Timeout"
                    && original.remaining().is_ok() => {}
            Err(error) => return Err(error.into()),
        }
    }
    let expired = wall_ns()?;
    ensure!(
        expired >= before + u64::from(lease) * 1_000_000,
        "session vanished before earliest TTL"
    );
    ensure!(received > 0, "actual report required before expiry");
    live(&bus, &caller, &client).await?;
    println!(
        "DiscoveryExpired: session={} caller_present=true owner_same=true read_error=org.freedesktop.DBus.Error.UnknownObject observed_wall_ns={}",
        session.id(),
        expired
    );
    // No close/Drop before the supervisor's observation window. Keep driving
    // this same runtime and caller connection while waiting for its input.
    let mut line = String::new();
    tokio::time::timeout_at(
        original.instant().into(),
        BufReader::new(tokio::io::stdin()).read_line(&mut line),
    )
    .await??;
    ensure!(
        line == "finish\n",
        "explicit supervisor finish after capture window"
    );
    let error = session
        .close(original)
        .await
        .expect_err("expired session cannot close successfully");
    ensure!(unknown(&error), "stale close must be UnknownObject");
    live(&bus, &caller, &client).await?;
    println!(
        "DiscoveryLeaseExit: session={} caller_present=true owner_same=true close_error=org.freedesktop.DBus.Error.UnknownObject",
        session.id()
    );
    Ok(())
}
