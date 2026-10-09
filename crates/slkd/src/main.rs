mod bonding;
mod config;
mod controller;
mod dbus_iface;
mod event_loop;
mod extadv;
mod hid;
mod kernel;
mod profile;
mod profile_runtime;
mod security;
mod service;
mod state;
mod transport;

use std::sync::Arc;

use clap::Parser;
use tokio::sync::Mutex;
use tracing::info;
use tracing_subscriber::{EnvFilter, layer::SubscriberExt, util::SubscriberInitExt};

use crate::bonding::BondingStore;
use crate::config::DaemonConfig;
use crate::controller::ControllerIface;
use crate::dbus_iface::{AdapterIface, Root};
use crate::event_loop::EventTask;
use crate::extadv::ExtAdvIface;
use crate::kernel::KernelLink;
use crate::profile::{BatteryProfile, DeviceInfoProfile, ProfileRegistry};
use crate::security::SecurityIface;
use crate::service::SsapManagerIface;
use crate::state::{AdapterState, SharedState};

#[derive(Parser)]
#[command(name = "slkd", about = "SparkLink daemon")]
struct Cli {
    /// Path to config file
    #[arg(short, long, default_value = "/etc/sparklink/main.conf")]
    config: String,

    /// Device path
    #[arg(short, long, default_value = "/dev/sparklink")]
    device: String,

    /// Run in foreground (don't daemonize)
    #[arg(short = 'n', long)]
    nodetach: bool,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    // Logging: prefer journald, fall back to stderr
    let env_filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));

    let registry = tracing_subscriber::registry().with(env_filter);

    if let Ok(journald) = tracing_journald::layer() {
        registry.with(journald).init();
    } else {
        registry
            .with(tracing_subscriber::fmt::layer().with_target(true))
            .init();
    }

    info!(version = env!("CARGO_PKG_VERSION"), "slkd starting");

    // Load config
    let config = DaemonConfig::load(&cli.config).unwrap_or_else(|e| {
        info!("no config file, using defaults: {e}");
        DaemonConfig::default()
    });

    // Open kernel device
    let link = KernelLink::open(&cli.device)?;
    let dev_count = link.adapter().device_count()?;
    info!(dev_count, device = %cli.device, "kernel link established");

    // Load bonding store
    let bonding_dir = std::path::PathBuf::from("/var/lib/sparklink");
    let (bonding, loaded) = tokio::task::spawn_blocking(move || {
        let mut bonding = BondingStore::new(&bonding_dir, "slk0");
        let loaded = bonding.load();
        (bonding, loaded)
    })
    .await?;
    match loaded {
        Ok(n) => info!(count = n, "bonded devices loaded"),
        Err(e) => info!(%e, "no bonding data (first run?)"),
    }

    // Create shared state
    let adapter = link.into_adapter();

    // Initialize profile framework
    let mut profiles = ProfileRegistry::new();
    profiles.add(Box::new(BatteryProfile::new(100)));
    profiles.add(Box::new(DeviceInfoProfile::new()));
    profiles.add(Box::new(hid::HidProfile::boot_keyboard()));
    let profile_count = profiles.init_all(&adapter);
    info!(count = profile_count, "profiles registered");

    let shared: SharedState = Arc::new(Mutex::new(AdapterState::new(
        adapter, config, bonding, profiles,
    )));

    // D-Bus session
    let connection = zbus::connection::Builder::system()?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Root::new(shared.clone()))?
        .serve_at("/org/sparklink/slk0", AdapterIface::new(shared.clone()))?
        .serve_at(
            "/org/sparklink/slk0/security",
            SecurityIface::new(shared.clone()),
        )?
        .serve_at(
            "/org/sparklink/slk0/services",
            SsapManagerIface::new(shared.clone()),
        )?
        .serve_at(
            "/org/sparklink/slk0/extadv",
            ExtAdvIface::new(shared.clone()),
        )?
        .serve_at(
            "/org/sparklink/slk0/controller",
            ControllerIface::new(shared.clone()),
        )?
        .build()
        .await?;

    info!("D-Bus service registered on org.sparklink");

    // Separate open-file ownership; waiting never borrows SharedState.
    // This still uses the legacy DLI ring until independent subscriptions land.
    let receiver = libsparklink::Adapter::open(&cli.device)?.into_event_receiver()?;
    let event_loop = EventTask::start(receiver, shared.clone(), connection.clone());

    // Wait for shutdown signal
    let shutdown_signal = tokio::signal::ctrl_c().await;
    info!("shutdown signal received");

    let event_result = event_loop.shutdown().await;
    drop(connection);
    let (bonding, profiles) = {
        let state = shared.lock().await;
        (state.bonding.clone(), state.profiles.clone())
    };
    tokio::join!(bonding.shutdown(), profiles.shutdown());
    event_result?;
    shutdown_signal?;

    info!("slkd stopped");
    Ok(())
}
