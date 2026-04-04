mod config;
mod dbus_iface;
mod kernel;

use clap::Parser;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use crate::config::DaemonConfig;
use crate::kernel::KernelLink;

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
    let env_filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info"));

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

    // D-Bus session
    let connection = zbus::connection::Builder::system()?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", dbus_iface::Root::new(config))?
        .build()
        .await?;

    info!("D-Bus service registered on org.sparklink");

    // Main event loop
    let event_loop = tokio::spawn(event_loop(link));

    // Wait for shutdown signal
    tokio::signal::ctrl_c().await?;
    info!("shutdown signal received");

    event_loop.abort();
    drop(connection);

    info!("slkd stopped");
    Ok(())
}

async fn event_loop(link: KernelLink) {
    loop {
        match link.adapter().next_event().await {
            Ok(event) => {
                tracing::debug!(?event, "kernel event");
                // TODO: dispatch to D-Bus signals, update object tree
            }
            Err(e) => {
                error!(%e, "event read error");
                tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            }
        }
    }
}
