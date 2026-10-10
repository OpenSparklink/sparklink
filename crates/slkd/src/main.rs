#[cfg(feature = "experimental-legacy-profiles")]
use slk_experimental::hid;
#[cfg(any(test, feature = "experimental-legacy-profiles"))]
use slk_experimental::profile;
mod adapters;
mod bonding;
mod config;
mod controller;
mod dbus_iface;
mod event_loop;
mod extadv;
#[cfg(any(test, feature = "experimental-legacy-profiles"))]
mod profile_runtime;
mod radio;
mod security;
mod service;
mod state;

use std::{path::PathBuf, sync::Arc};

use clap::Parser;
use tokio::sync::Mutex;
use tracing::info;
use tracing_subscriber::{EnvFilter, layer::SubscriberExt, util::SubscriberInitExt};

use crate::adapters::AdapterManager;
use crate::config::DaemonConfig;
use crate::dbus_iface::Root;
use crate::state::AdapterDirectory;

#[derive(Parser)]
#[command(name = "slkd", about = "SparkLink daemon")]
struct Cli {
    /// Explicit configuration path (required if supplied; implicit default: /etc/sparklink/main.conf)
    #[arg(short, long)]
    config: Option<PathBuf>,

    /// Bond metadata directory (no native key persistence is claimed).
    #[arg(long, default_value = "/var/lib/sparklink")]
    storage: String,

    /// Use a session bus for isolated tests.
    #[arg(long)]
    session: bool,

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

    // Validate before publishing D-Bus objects or acquiring controller authority.
    let config = DaemonConfig::startup(cli.config.as_deref())?;

    let directory: AdapterDirectory = Arc::new(Mutex::new(Default::default()));
    let builder = if cli.session {
        zbus::connection::Builder::session()?
    } else {
        zbus::connection::Builder::system()?
    };
    let connection = builder
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Root::new(directory.clone()))?
        .build()
        .await?;
    let manager = AdapterManager::start(
        cli.device,
        config,
        cli.storage,
        connection.clone(),
        directory,
    );
    info!("D-Bus service registered; watching controller registrations");
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    let shutdown_signal = tokio::select! {
        result = tokio::signal::ctrl_c() => result,
        _ = terminate.recv() => Ok(()),
    };
    let result = manager.shutdown().await;
    drop(connection);
    result?;
    shutdown_signal?;
    info!("slkd stopped");
    Ok(())
}

#[cfg(test)]
mod cli_tests {
    use super::*;
    #[test]
    fn implicit_and_explicit_default_paths_remain_distinct() {
        assert!(Cli::try_parse_from(["slkd"]).unwrap().config.is_none());
        assert_eq!(
            Cli::try_parse_from(["slkd", "--config", config::DEFAULT_CONFIG])
                .unwrap()
                .config,
            Some(PathBuf::from(config::DEFAULT_CONFIG))
        );
    }
}
