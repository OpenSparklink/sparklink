mod config;
mod dbus_iface;
mod kernel;
mod security;
mod state;

use std::sync::Arc;

use clap::Parser;
use tokio::sync::Mutex;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use crate::config::DaemonConfig;
use crate::dbus_iface::{AdapterIface, DeviceIface, Root};
use crate::kernel::KernelLink;
use crate::security::SecurityIface;
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

    // Create shared state
    let adapter = link.into_adapter();
    let shared: SharedState = Arc::new(Mutex::new(AdapterState::new(adapter, config)));

    // D-Bus session
    let connection = zbus::connection::Builder::system()?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Root::new(shared.clone()))?
        .serve_at("/org/sparklink/slk0", AdapterIface::new(shared.clone()))?
        .serve_at("/org/sparklink/slk0/security", SecurityIface::new(shared.clone()))?
        .build()
        .await?;

    info!("D-Bus service registered on org.sparklink");

    // Main event loop
    let conn_clone = connection.clone();
    let state_clone = shared.clone();
    let event_loop = tokio::spawn(event_loop(state_clone, conn_clone));

    // Wait for shutdown signal
    tokio::signal::ctrl_c().await?;
    info!("shutdown signal received");

    event_loop.abort();
    drop(connection);

    info!("slkd stopped");
    Ok(())
}

async fn event_loop(state: SharedState, connection: zbus::Connection) {
    loop {
        let event = {
            let st = state.lock().await;
            st.adapter.next_event().await
        };

        match event {
            Ok(libsparklink::Event::AdvReport { addr, rssi, discovery_level, name }) => {
                let mut st = state.lock().await;
                let is_new = st.on_adv_report(addr, rssi, discovery_level, name.clone());
                if is_new {
                    let object_path = st.devices[&addr].object_path.clone();
                    drop(st);
                    let iface = DeviceIface::new(state.clone(), addr);
                    if let Err(e) = connection
                        .object_server()
                        .at(object_path.as_str(), iface)
                        .await
                    {
                        error!(%e, path = %object_path, "failed to register device object");
                    } else {
                        info!(
                            address = %dbus_iface::format_addr(&addr),
                            name = %name,
                            rssi,
                            "new device discovered"
                        );
                    }
                }
            }
            Ok(libsparklink::Event::ConnectionStateChanged { handle, state: conn_state, peer_addr }) => {
                let mut st = state.lock().await;
                st.on_conn_state_changed(handle, conn_state, peer_addr);
                let connected = conn_state == slk_protocol::ConnState::Connected as u8;
                info!(
                    address = %dbus_iface::format_addr(&peer_addr),
                    handle,
                    connected,
                    "connection state changed"
                );
            }
            Ok(libsparklink::Event::SecurityChanged { state: sec_state, method, encrypted }) => {
                let method_label = match method {
                    1 => "JustWorks",
                    2 => "PSK",
                    _ => "None",
                };
                info!(
                    state = sec_state,
                    method = method_label,
                    encrypted,
                    "security state changed"
                );
            }
            Ok(event) => {
                tracing::debug!(?event, "kernel event");
            }
            Err(e) => {
                error!(%e, "event read error");
                tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            }
        }
    }
}
