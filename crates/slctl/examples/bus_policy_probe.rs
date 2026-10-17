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

fn credentials(uid: u32, gid: u32) -> anyhow::Result<()> {
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
    Ok(())
}

async fn probe(path: &str, mode: &str, native_phase: Option<&str>) -> anyhow::Result<()> {
    let (uid, gid) = match mode {
        "observer" => (1001, 1001),
        "control" => (1000, 1002),
        _ => anyhow::bail!("unknown mode"),
    };
    credentials(uid, gid)?;
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
    if let Some(phase) = native_phase {
        native_observations(&connection, path, phase, &owner).await?;
    }
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
    if native_phase.is_some() {
        denied(
            "CancelDiscoveryPolicies",
            connection
                .call_method(
                    Some(SERVICE),
                    path,
                    Some(ADAPTER),
                    "CancelDiscoveryPolicies",
                    &(),
                )
                .await,
        )?;
    }

    for method in ["StartControllerScan", "StopControllerScan"] {
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
            .call_method(
                Some(SERVICE),
                path,
                None::<&str>,
                "StartControllerScan",
                &(),
            )
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
    for property in ["Ready", "Generation", "AdvertisingState", "ScanningState"] {
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

// Native-only read qualification. Original legacy fixture calls deliberately
// keep their old method set and cannot qualify these real WS73 observations.
async fn native_observations(
    connection: &Connection,
    path: &str,
    phase: &str,
    owner: &zbus::names::OwnedUniqueName,
) -> anyhow::Result<()> {
    ensure!(
        matches!(phase, "native-initial" | "native-business"),
        "explicit native phase required"
    );
    for destination in [SERVICE, owner.as_str()] {
        let policy: (u32, u32, u32, i32, u32, u32) = connection
            .call_method(
                Some(destination),
                path,
                Some(ADAPTER),
                "GetDiscoveryPolicy",
                &(),
            )
            .await?
            .body()
            .deserialize()?;
        let management: (u64, u32, u32, u32, i32, u32, u32) = connection
            .call_method(
                Some(destination),
                path,
                Some(ADAPTER),
                "GetManagementStatus",
                &(),
            )
            .await?
            .body()
            .deserialize()?;
        ensure!(
            policy.0 == 3
                && management.0 != 0
                && management.1 == 1
                && management.2 == 1
                && management.3 == 1
                && management.4 == 0
                && management.5 == 0
                && management.6 == 0,
            "actual owned native observations required"
        );
        let mut initializers = Vec::new();
        for operation in [5u32, 6] {
            let result = connection
                .call_method(
                    Some(destination),
                    path,
                    Some(ADAPTER),
                    "GetInitializationOff",
                    &(operation,),
                )
                .await;
            if phase == "native-initial" {
                let value: slk_protocol::DiscoveryResultRecord = result?.body().deserialize()?;
                ensure!(
                    value.0 == management.0
                        && value.1 != 0
                        && value.2 == operation
                        && value.3 == 3
                        && value.4 == 0
                        && value.5 == 0
                        && value.6 == if operation == 5 { 0x0c05 } else { 0x1002 }
                        && value.7 == if operation == 5 { 1 } else { 2 }
                        && value.8 == if operation == 5 { 2 } else { 3 }
                        && value.10 == (operation == 5)
                        && value.11 == 1
                        && value.12 == 1
                        && value.13 == 1,
                    "actual successful initializer with its own ID required"
                );
                let history: slk_protocol::DiscoveryResultRecord = connection
                    .call_method(
                        Some(destination),
                        path,
                        Some(ADAPTER),
                        "GetDiscoveryResult",
                        &(value.1,),
                    )
                    .await?
                    .body()
                    .deserialize()?;
                ensure!(
                    serde_json::to_value(history)? == serde_json::to_value(value)?,
                    "readonly initializer/history must retain original result"
                );
                initializers.push(serde_json::json!({"operation": operation, "result": value, "history": history}));
            } else {
                match result {
                    Err(zbus::Error::MethodError(name, Some(description), _))
                        if name.as_str() == "org.freedesktop.DBus.Error.UnknownObject"
                            && description
                                .contains("initializer provenance absent or invalidated") =>
                    {
                        initializers.push(serde_json::json!({"operation": operation, "outcome": "invalidated", "reason": description}));
                    }
                    _ => anyhow::bail!(
                        "business-used initializer must refuse provenance rather than bus permission or cached success"
                    ),
                }
            }
        }
        println!(
            "AUTH_NATIVE_READ: {}",
            serde_json::json!({"destination": destination, "phase": phase, "policy": policy, "management": management, "initializers": initializers})
        );
    }
    Ok(())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        matches!(args.len(), 3..=5),
        "usage: bus_policy_probe ADAPTER observer|control [native-initial|native-business], or ADAPTER service-only|service-channel|service-observer START HANDLE"
    );
    if args[2].starts_with("service-") {
        ensure!(
            args.len() == 5,
            "service role requires foreign start and handle"
        );
        tokio::time::timeout(
            std::time::Duration::from_secs(10),
            service_policy(&args[1], &args[2], args[3].parse()?, args[4].parse()?),
        )
        .await
        .context("service role original deadline")??;
        return Ok(());
    }
    ensure!(
        matches!(args.len(), 3 | 4),
        "legacy role takes at most one explicit native phase"
    );
    tokio::time::timeout(
        std::time::Duration::from_secs(20),
        probe(&args[1], &args[2], args.get(3).map(String::as_str)),
    )
    .await
    .context("policy probe timeout")??;
    Ok(())
}

async fn service_policy(path: &str, role: &str, start: u16, handle: u16) -> anyhow::Result<()> {
    let (uid, gid) = match role {
        "service-only" => (1005, 1005),
        "service-channel" => (1004, 1004),
        "service-observer" => (1001, 1001),
        _ => anyhow::bail!("unknown service role"),
    };
    credentials(uid, gid)?;
    for path in ["/dev/sparklink", "/dev/usbmon1"] {
        ensure!(
            std::fs::metadata(path).is_ok(),
            "expected actual VM kernel device absent"
        );
        let path = std::ffi::CString::new(path)?;
        for mode in [nix::libc::R_OK, nix::libc::W_OK] {
            // SAFETY: valid terminated device path; access does not perform I/O.
            ensure!(
                unsafe { nix::libc::access(path.as_ptr(), mode) } != 0,
                "service role has direct kernel device access"
            );
        }
    }
    println!("AUTH_SERVICE_KERNEL_ACCESS: denied");
    ensure!(
        start != 0 && handle > start,
        "actual foreign registration required"
    );
    let connection = Connection::session().await?;
    let bus = DBusProxy::new(&connection).await?;
    let owner = bus.get_name_owner(SERVICE.try_into()?).await?;
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
    let server = format!("{path}/services");
    let definition = (
        vec![1u8, 2],
        vec![(vec![3u8, 4], 5u32, 0u32, vec![7u8])],
        zbus::zvariant::OwnedObjectPath::try_from("/")?,
    );
    let own = connection
        .call_method(
            Some(SERVICE),
            server.as_str(),
            Some("org.sparklink.ServiceManager"),
            "RegisterOwnedLocalService",
            &definition,
        )
        .await;
    if role == "service-only" {
        let (begin, _, handles): (u16, u16, Vec<u16>) = own?.body().deserialize()?;
        ensure!(handles.len() == 1, "one actual owned value required");
        let value: Vec<u8> = connection
            .call_method(
                Some(SERVICE),
                server.as_str(),
                Some("org.sparklink.ServiceManager"),
                "ReadOwnedLocalValue",
                &(handles[0],),
            )
            .await?
            .body()
            .deserialize()?;
        ensure!(value == [7], "actual owner read required");
        denied(
            "interface-less-own-read",
            connection
                .call_method(
                    Some(SERVICE),
                    server.as_str(),
                    None::<&str>,
                    "ReadOwnedLocalValue",
                    &(handles[0],),
                )
                .await,
        )?;

        connection
            .call_method(
                Some(SERVICE),
                server.as_str(),
                Some("org.sparklink.ServiceManager"),
                "UnregisterOwnedLocalService",
                &(begin,),
            )
            .await?;
        println!(
            "AUTH_SERVICE_OWNED: start={begin} property={} value=07 removed=true",
            handles[0]
        );
    } else {
        denied("RegisterOwnedLocalService", own)?;
    }
    for destination in [SERVICE, owner.as_str()] {
        for (method, label) in [
            ("ReadOwnedLocalValue", "foreign-owned-read"),
            ("ReadLocalValue", "global-value-read"),
        ] {
            denied(
                label,
                connection
                    .call_method(
                        Some(destination),
                        server.as_str(),
                        Some("org.sparklink.ServiceManager"),
                        method,
                        &(handle,),
                    )
                    .await,
            )?;
        }
        denied(
            "foreign-owned-remove",
            connection
                .call_method(
                    Some(destination),
                    server.as_str(),
                    Some("org.sparklink.ServiceManager"),
                    "UnregisterOwnedLocalService",
                    &(start,),
                )
                .await,
        )?;
        if role == "service-only" {
            denied(
                "RemoveLocalService",
                connection
                    .call_method(
                        Some(destination),
                        server.as_str(),
                        Some("org.sparklink.ServiceManager"),
                        "RemoveLocalService",
                        &(start,),
                    )
                    .await,
            )?;
            denied(
                "RegisterLocalService",
                connection
                    .call_method(
                        Some(destination),
                        server.as_str(),
                        Some("org.sparklink.ServiceManager"),
                        "RegisterLocalService",
                        &(vec![1u8, 2], vec![(vec![3u8, 4], 5u32, 0u32, vec![7u8])]),
                    )
                    .await,
            )?;
            denied(
                "StopControllerScan",
                connection
                    .call_method(
                        Some(destination),
                        path,
                        Some(ADAPTER),
                        "StopControllerScan",
                        &(),
                    )
                    .await,
            )?;
            denied(
                "interface-less-owned-read",
                connection
                    .call_method(
                        Some(destination),
                        server.as_str(),
                        None::<&str>,
                        "ReadOwnedLocalValue",
                        &(handle,),
                    )
                    .await,
            )?;
            denied(
                "OpenChannel",
                connection
                    .call_method(
                        Some(destination),
                        format!("{path}/connections/not_a_lifetime"),
                        Some("org.sparklink.Connection"),
                        "OpenChannel",
                        &(31u8, 31u8, 241u8, 3u8, 0u32),
                    )
                    .await,
            )?;
        }
    }
    println!("AUTH_SERVICE_ROLE: {role}");
    Ok(())
}
