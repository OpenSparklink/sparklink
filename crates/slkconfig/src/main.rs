use clap::{Parser, Subcommand};
use libsparklink::Adapter;

#[derive(Parser)]
#[command(name = "slkconfig", about = "SparkLink offline configuration tool")]
struct Cli {
    /// Device path
    #[arg(short, long, default_value = "/dev/sparklink")]
    device: String,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Show adapter information
    Info,

    /// Show DLI controller information
    Dli,

    /// Show PHY parameters
    Phy,

    /// Get or set device role
    Role {
        /// Set role: 0=G-node, 1=T-node (omit to query)
        value: Option<u8>,
    },

    /// Reset the controller
    Reset,

    /// Show subsystem statistics
    Stats,

    /// List active connections
    Connections,
}

fn main() {
    let cli = Cli::parse();

    let adapter = match Adapter::open(&cli.device) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("failed to open {}: {e}", cli.device);
            std::process::exit(1);
        }
    };

    let result = match cli.command {
        Command::Info => cmd_info(&adapter),
        Command::Dli => cmd_dli(&adapter),
        Command::Phy => cmd_phy(&adapter),
        Command::Role { value } => cmd_role(&adapter, value),
        Command::Reset => cmd_reset(&adapter),
        Command::Stats => cmd_stats(&adapter),
        Command::Connections => cmd_connections(&adapter),
    };

    if let Err(e) = result {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}

fn fmt_addr(addr: &[u8; 6]) -> String {
    format!(
        "{:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X}",
        addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
    )
}

fn cmd_info(adapter: &Adapter) -> libsparklink::Result<()> {
    let info = adapter.device_info()?;
    let name_end = info.name.iter().position(|&b| b == 0).unwrap_or(info.name.len());
    let name = std::str::from_utf8(&info.name[..name_end]).unwrap_or("<invalid>");

    println!("Device #{}", info.index);
    println!("  Name:    {name}");
    println!("  Address: {}", fmt_addr(&info.addr));
    println!("  Bus:     {}", info.bus);
    println!("  State:   {:#04x}", info.state);

    let count = adapter.device_count()?;
    println!("  Total devices: {count}");

    Ok(())
}

fn cmd_dli(adapter: &Adapter) -> libsparklink::Result<()> {
    let info = adapter.dli_info()?;
    let name_end = info.name.iter().position(|&b| b == 0).unwrap_or(info.name.len());
    let name = std::str::from_utf8(&info.name[..name_end]).unwrap_or("<invalid>");

    println!("DLI Controller: {name}");
    println!("  Bus:              {}", info.bus);
    println!("  Firmware:         {:#010x}", info.firmware_version);
    println!("  Features:         {:#010x}", info.features);
    println!("  Max connections:  {}", info.max_connections);
    println!("  Max ADV sets:     {}", info.max_adv_sets);
    println!("  Max MTU:          {}", info.max_mtu);
    println!("  Max MPS:          {}", info.max_mps);
    println!("  Transport modes:  {:#04x}", info.transport_modes);
    println!("  Security cap:     {:#04x}", info.security_cap);
    println!("  Measurement cap:  {:#04x}", info.measurement_cap);

    Ok(())
}

fn cmd_phy(adapter: &Adapter) -> libsparklink::Result<()> {
    let info = adapter.phy_info()?;

    println!("PHY Configuration:");
    println!("  MCS index:     {}", info.mcs_index);
    println!("  Bandwidth:     {} MHz", info.bandwidth_mhz);
    println!("  TX power:      {} dBm", info.tx_power_dbm);
    println!("  Data rate:     {} kbps", info.data_rate_kbps);
    println!("  Modulation:    {}", info.modulation);
    println!("  Code rate:     {}/{}", info.code_rate_num, info.code_rate_den);
    println!("  MIMO mode:     {}", info.mimo_mode);
    println!("  Antennas:      TX={} RX={}", info.num_tx_ant, info.num_rx_ant);
    println!("  Hop channel:   {}", info.hop_channel);

    Ok(())
}

fn cmd_role(adapter: &Adapter, value: Option<u8>) -> libsparklink::Result<()> {
    match value {
        Some(v) => {
            adapter.set_role(v)?;
            let label = if v == 0 { "G-node" } else { "T-node" };
            println!("Role set to {label}");
        }
        None => {
            let role = adapter.get_role()?;
            let label = if role == 0 { "G-node" } else { "T-node" };
            println!("Current role: {label} ({role})");
        }
    }
    Ok(())
}

fn cmd_reset(adapter: &Adapter) -> libsparklink::Result<()> {
    // DLI reset
    use slk_protocol::ioctl;
    use std::os::fd::AsRawFd;
    unsafe { ioctl::sl_dli_reset(adapter.as_fd().as_raw_fd())? };
    println!("Controller reset complete");
    Ok(())
}

fn cmd_stats(adapter: &Adapter) -> libsparklink::Result<()> {
    let stats = adapter.subsys_stats()?;

    println!("Subsystem Statistics:");
    println!("  Devices:          {}", stats.dev_count);
    println!("  Protocols:        {}", stats.proto_count);
    println!("  Bindings:         {}", stats.binding_count);
    println!("  Active conns:     {}", stats.active_connections);
    println!("  Mgmt pending:     {}", stats.mgmt_pending);
    println!("  Conns created:    {}", stats.total_conn_created);
    println!("  Conns completed:  {}", stats.total_conn_completed);
    println!("  Mgmt submitted:   {}", stats.total_mgmt_submitted);
    println!("  Mgmt timeouts:    {}", stats.total_mgmt_timeouts);
    println!("  Power state:      {}", stats.power_state);
    println!("  Power transitions:{}", stats.power_transitions);
    println!("  CRC errors:       {}", stats.crc_errors);

    Ok(())
}

fn cmd_connections(adapter: &Adapter) -> libsparklink::Result<()> {
    let list = adapter.conn_list()?;

    if list.count == 0 {
        println!("No active connections");
        return Ok(());
    }

    println!("{} active connection(s):", list.count);
    for i in 0..list.count as usize {
        let handle = list.handles[i];
        match adapter.conn_info(handle) {
            Ok(info) => {
                let state = match info.state {
                    0 => "IDLE",
                    1 => "CONNECTING",
                    2 => "CONNECTED",
                    3 => "DISCONNECTING",
                    _ => "UNKNOWN",
                };
                println!(
                    "  [{:#06x}] {} peer={} role={} BW={}MHz MCS={} MTU={}",
                    handle,
                    state,
                    fmt_addr(&info.peer_addr),
                    info.local_role,
                    info.bandwidth_mhz,
                    info.mcs_index,
                    info.data_mtu
                );
            }
            Err(e) => {
                println!("  [{:#06x}] error: {e}", handle);
            }
        }
    }

    Ok(())
}
