//! Disposable-guest test client for the installed production D-Bus policy.
//! This is deliberately separate from the normal slctl user interface.
use anyhow::{Context, ensure};
use std::collections::HashMap;
use zbus::{Connection, fdo::DBusProxy, zvariant::Value};

const SERVICE: &str = "org.sparklink";
const ADAPTER: &str = "org.sparklink.Adapter";

fn denied(label: &str, result: zbus::Result<zbus::Message>) -> anyhow::Result<()> {
    match result {
        Err(zbus::Error::MethodError(name, _, _))
            if name.as_str() == "org.freedesktop.DBus.Error.AccessDenied" =>
        {
            println!("AUTH_DENIED: {label}");
            Ok(())
        }
        other => anyhow::bail!("{label}: expected bus AccessDenied, got {other:?}"),
    }
}

async fn probe(path: &str, mode: &str) -> anyhow::Result<()> {
    let (uid, gid) = match mode {
        "observer" => (1001, 1001),
        "control" => (1000, 1002),
        _ => anyhow::bail!("unknown mode"),
    };
    let status = std::fs::read_to_string("/proc/self/status")?;
    for (field, expected) in [("Uid:", uid), ("Gid:", gid)] {
        let values = status
            .lines()
            .find(|line| line.starts_with(field))
            .context("missing credentials")?
            .split_whitespace()
            .skip(1)
            .map(str::parse::<u32>)
            .collect::<Result<Vec<_>, _>>()?;
        ensure!(values == vec![expected; 4], "unexpected {field}");
    }
    for field in ["CapInh:", "CapPrm:", "CapEff:", "CapAmb:"] {
        let value = status
            .lines()
            .find(|line| line.starts_with(field))
            .context("missing capability field")?
            .split_whitespace()
            .nth(1)
            .context("missing capability value")?;
        ensure!(
            u64::from_str_radix(value, 16)? == 0,
            "application has {field}"
        );
    }
    println!("AUTH_CREDENTIALS: uid={uid} gid={gid} caps=0");
    let connection = Connection::session().await?;
    let bus = DBusProxy::new(&connection).await?;
    let owner = bus.get_name_owner(SERVICE.try_into()?).await?;
    let message = connection
        .call_method(
            Some(SERVICE),
            "/org/sparklink",
            Some("org.sparklink.Manager"),
            "ListAdapters",
            &(),
        )
        .await?;
    let paths: Vec<String> = message.body().deserialize()?;
    ensure!(paths.contains(&path.to_owned()), "selected adapter absent");
    for method in ["GetDevices", "GetReports", "GetTimedReports"] {
        connection
            .call_method(Some(SERVICE), path, Some(ADAPTER), method, &())
            .await?;
    }
    connection
        .call_method(
            Some(owner.as_str()),
            path,
            Some("org.freedesktop.DBus.Properties"),
            "GetAll",
            &(ADAPTER,),
        )
        .await?;
    connection
        .call_method(
            Some(SERVICE),
            path,
            Some("org.freedesktop.DBus.Introspectable"),
            "Introspect",
            &(),
        )
        .await?;
    println!("AUTH_OBSERVE: {mode}");
    let properties = zbus::Proxy::new(
        &connection,
        SERVICE,
        path,
        "org.freedesktop.DBus.Properties",
    )
    .await?;
    let before: HashMap<String, zbus::zvariant::OwnedValue> =
        properties.call("GetAll", &(ADAPTER,)).await?;
    denied(
        "own-service",
        connection
            .call_method(
                Some("org.freedesktop.DBus"),
                "/org/freedesktop/DBus",
                Some("org.freedesktop.DBus"),
                "RequestName",
                &(SERVICE, 4u32),
            )
            .await,
    )?;
    if mode == "control" {
        // The normal slctl radio/hotplug test exercises actual group writes.
        return Ok(());
    }
    ensure!(mode == "observer", "unknown mode");
    for method in ["StartDiscovery", "StopDiscovery"] {
        denied(
            method,
            connection
                .call_method(Some(SERVICE), path, Some(ADAPTER), method, &())
                .await,
        )?;
    }
    for method in [
        "SubmitScanning",
        "SubmitStopScanning",
        "SubmitStopAdvertising",
    ] {
        denied(
            method,
            connection
                .call_method(Some(SERVICE), path, Some(ADAPTER), method, &(991u64,))
                .await,
        )?;
    }
    denied(
        "SubmitAdvertising",
        connection
            .call_method(
                Some(SERVICE),
                path,
                Some(ADAPTER),
                "SubmitAdvertising",
                &(992u64, vec![0u8; 16]),
            )
            .await,
    )?;
    denied(
        "unique-owner-write",
        connection
            .call_method(
                Some(owner.as_str()),
                path,
                Some(ADAPTER),
                "SubmitScanning",
                &(993u64,),
            )
            .await,
    )?;
    denied(
        "interface-less-write",
        connection
            .call_method(Some(SERVICE), path, None::<&str>, "StartDiscovery", &())
            .await,
    )?;
    denied(
        "interface-less-read",
        connection
            .call_method(Some(SERVICE), path, None::<&str>, "GetReports", &())
            .await,
    )?;
    denied(
        "Properties.Set",
        connection
            .call_method(
                Some(SERVICE),
                path,
                Some("org.freedesktop.DBus.Properties"),
                "Set",
                &(ADAPTER, "Powered", Value::Bool(false)),
            )
            .await,
    )?;
    denied(
        "future-method",
        connection
            .call_method(Some(SERVICE), path, Some(ADAPTER), "FutureControl", &())
            .await,
    )?;
    denied(
        "foreign-interface",
        connection
            .call_method(
                Some(SERVICE),
                path,
                Some("org.example.Other"),
                "GetReports",
                &(),
            )
            .await,
    )?;
    denied(
        "RemoteService.Read",
        connection
            .call_method(
                Some(SERVICE),
                path,
                Some("org.sparklink.RemoteService"),
                "Read",
                &(1u16,),
            )
            .await,
    )?;
    denied(
        "DequeueNotification",
        connection
            .call_method(
                Some(SERVICE),
                path,
                Some("org.sparklink.ServiceManager"),
                "DequeueNotification",
                &(),
            )
            .await,
    )?;
    denied(
        "GetPasskey",
        connection
            .call_method(
                Some(SERVICE),
                path,
                Some("org.sparklink.Security"),
                "GetPasskey",
                &(),
            )
            .await,
    )?;
    // Bus denial must leave the daemon's state and native admission untouched.
    let after: HashMap<String, zbus::zvariant::OwnedValue> =
        properties.call("GetAll", &(ADAPTER,)).await?;
    for property in [
        "Ready",
        "Powered",
        "Generation",
        "AdvertisingState",
        "ScanningState",
    ] {
        ensure!(before.contains_key(property), "missing observed {property}");
        ensure!(
            before.get(property) == after.get(property),
            "denied call changed {property}"
        );
    }
    match connection
        .call_method(
            Some(SERVICE),
            path,
            Some(ADAPTER),
            "GetDiscoveryResult",
            &(991u64,),
        )
        .await
    {
        Err(zbus::Error::MethodError(name, _, _))
            if name.as_str() == "org.freedesktop.DBus.Error.UnknownObject" => {}
        other => anyhow::bail!("readable result should report no denied admission, got {other:?}"),
    }
    Ok(())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        args.len() == 3,
        "usage: bus_policy_probe ADAPTER observer|control"
    );
    tokio::time::timeout(
        std::time::Duration::from_secs(20),
        probe(&args[1], &args[2]),
    )
    .await
    .context("policy probe timeout")??;
    Ok(())
}
