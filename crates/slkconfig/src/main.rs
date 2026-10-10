use clap::{Parser, Subcommand, ValueEnum};
use libsparklink::Adapter;

#[derive(Parser)]
#[command(name = "slkconfig", about = "SparkLink offline configuration tool")]
struct Cli {
    /// Device path
    #[arg(short, long, default_value = "/dev/sparklink")]
    device: String,

    /// Registered adapter index (use adapters to list); never switches the global default
    #[arg(long, global = true)]
    adapter: Option<u16>,

    /// Require this registration generation; mandatory for native diagnostic queries
    #[arg(long, global = true)]
    generation: Option<u64>,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// List registered controllers and their generations without acquiring ownership
    Adapters,
    /// Observe the selected controller and its command queue
    Controller,
    /// Observe native management ownership (does not acquire a lease)
    Management,
    /// Execute one whitelisted WS73 query with an exclusive Diagnostic lease
    Query {
        #[arg(value_enum)]
        query: NativeQuery,
    },
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

    /// Start scanning and print discovered devices
    Scan {
        /// Scan duration in seconds (default: 5)
        #[arg(short, long, default_value_t = 5)]
        duration: u64,
    },

    /// Connect to a peer by address
    Connect {
        /// Peer address in AA:BB:CC:DD:EE:FF format
        address: String,
    },

    /// Disconnect a connection by handle
    Disconnect {
        /// Connection handle (hex, e.g. 0x0001)
        handle: String,
    },

    /// Show security state
    Security,

    /// Initiate pairing
    Pair {
        /// Pairing method: just_works, psk, none
        #[arg(short, long, default_value = "just_works")]
        method: String,
    },

    /// Enable encryption on active connection
    Encrypt,

    /// Set Pre-Shared Key (32-char hex string = 16 bytes)
    SetPsk {
        /// PSK as hex, e.g. 00112233445566778899aabbccddeeff
        psk: String,
    },

    /// Reset security state
    SecReset,

    /// Show SSAP service summary
    Services,

    /// List local services
    ListServices,

    /// Read a local property value
    ReadProp {
        /// Property handle (hex, e.g. 0x0001)
        handle: String,
    },

    /// Write a local property value
    WriteProp {
        /// Property handle (hex, e.g. 0x0001)
        handle: String,
        /// Value as hex bytes
        value: String,
    },

    /// Discover services on a remote peer
    RemoteDiscover {
        /// Connection handle (hex, e.g. 0x0001)
        conn: String,
    },

    /// Read a property on a remote peer
    RemoteRead {
        /// Connection handle
        conn: String,
        /// Property handle
        handle: String,
    },

    /// Write a property on a remote peer
    RemoteWrite {
        /// Connection handle
        conn: String,
        /// Property handle
        handle: String,
        /// Value as hex bytes
        value: String,
    },

    /// Call a method on a remote peer
    CallMethod {
        /// Connection handle
        conn: String,
        /// Method handle
        handle: String,
        /// Input data as hex bytes
        input: String,
    },

    /// Find a remote service by UUID
    FindByUuid {
        /// Connection handle
        conn: String,
        /// 16-bit UUID in hex (e.g. 0x1800)
        uuid: String,
    },

    /// Read a remote property by UUID
    ReadByUuid {
        /// Connection handle
        conn: String,
        /// 16-bit UUID in hex (e.g. 0x2A00)
        uuid: String,
    },
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum NativeQuery {
    Mac,
    Features,
    Version,
    Buffers,
}
impl NativeQuery {
    fn wire(self) -> (u16, usize) {
        match self {
            Self::Mac => (0x0406, 6),
            Self::Features => (0x0403, 10),
            Self::Version => (0x0404, 5),
            Self::Buffers => (0x0402, 6),
        }
    }
}

impl Command {
    fn native_observation(&self) -> bool {
        matches!(
            self,
            Self::Info | Self::Dli | Self::Controller | Self::Management | Self::Stats
        )
    }
}

fn main() {
    let cli = Cli::parse();
    if let Err(error) = run(cli) {
        eprintln!("error: {error:#}");
        std::process::exit(1);
    }
}

fn run(cli: Cli) -> anyhow::Result<()> {
    if matches!(cli.command, Command::Adapters) {
        anyhow::ensure!(
            cli.adapter.is_none() && cli.generation.is_none(),
            "adapters lists registrations; omit --adapter/--generation"
        );
        let mut adapter = Adapter::open(&cli.device)?;
        for index in adapter.device_indices()? {
            adapter.select_device(index)?;
            let snapshot = adapter.controller_snapshot(0)?;
            print_controller(&snapshot);
        }
        return Ok(());
    }
    let index = cli.adapter.ok_or_else(|| {
        anyhow::anyhow!("select a registration with --adapter; use adapters to list")
    })?;
    anyhow::ensure!(index < 16, "adapter index must be 0..15");
    anyhow::ensure!(cli.generation != Some(0), "generation must be nonzero");
    if matches!(cli.command, Command::Query { .. }) {
        anyhow::ensure!(
            cli.generation.is_some(),
            "native query requires --generation from controller/adapters"
        );
    }
    let mut adapter = Adapter::open(&cli.device)?;
    adapter.select_device(index)?;
    let snapshot = adapter.controller_snapshot(cli.generation.unwrap_or(0))?;
    match cli.command {
        Command::Controller => {
            print_controller(&snapshot);
            let stats = adapter.mgmt_stats()?;
            println!(
                "ManagementQueue: pending={} submitted={} resolved={} timeouts={}",
                stats.pending, stats.total_submitted, stats.total_resolved, stats.total_timeouts
            );
            return Ok(());
        }
        Command::Management => {
            let state = adapter.management_status(snapshot.generation)?;
            println!(
                "Management: index={} generation={} state={} mode={} owning_fd={} error={} status={} opcode=0x{:04x}",
                index,
                state.generation,
                state.state,
                state.mode,
                state.flags & 1,
                state.error,
                state.status,
                state.opcode
            );
            return Ok(());
        }
        Command::Query { query } => {
            return cmd_native_query(
                &adapter,
                snapshot.generation,
                index,
                snapshot.profile,
                query,
            );
        }
        _ => {}
    }
    anyhow::ensure!(
        snapshot.profile == 0 || cli.command.native_observation(),
        "legacy management command is unsupported on this native controller; use slctl for discovery or query for exclusive diagnostics"
    );
    let result = match cli.command {
        Command::Adapters | Command::Controller | Command::Management | Command::Query { .. } => {
            unreachable!()
        }
        Command::Info => cmd_info(&adapter),
        Command::Dli => cmd_dli(&adapter),
        Command::Phy => cmd_phy(&adapter),
        Command::Role { value } => cmd_role(&adapter, value),
        Command::Reset => cmd_reset(&adapter),
        Command::Stats => cmd_stats(&adapter),
        Command::Connections => cmd_connections(&adapter),
        Command::Scan { duration } => cmd_scan(&adapter, duration),
        Command::Connect { address } => cmd_connect(&adapter, &address),
        Command::Disconnect { handle } => cmd_disconnect(&adapter, &handle),
        Command::Security => cmd_security(&adapter),
        Command::Pair { method } => cmd_pair(&adapter, &method),
        Command::Encrypt => cmd_encrypt(&adapter),
        Command::SetPsk { psk } => cmd_set_psk(&adapter, &psk),
        Command::SecReset => cmd_sec_reset(&adapter),
        Command::Services => cmd_services(&adapter),
        Command::ListServices => cmd_list_services(&adapter),
        Command::ReadProp { handle } => cmd_read_prop(&adapter, &handle),
        Command::WriteProp { handle, value } => cmd_write_prop(&adapter, &handle, &value),
        Command::RemoteDiscover { conn } => cmd_remote_discover(&adapter, &conn),
        Command::RemoteRead { conn, handle } => cmd_remote_read(&adapter, &conn, &handle),
        Command::RemoteWrite {
            conn,
            handle,
            value,
        } => cmd_remote_write(&adapter, &conn, &handle, &value),
        Command::CallMethod {
            conn,
            handle,
            input,
        } => cmd_call_method(&adapter, &conn, &handle, &input),
        Command::FindByUuid { conn, uuid } => cmd_find_by_uuid(&adapter, &conn, &uuid),
        Command::ReadByUuid { conn, uuid } => cmd_read_by_uuid(&adapter, &conn, &uuid),
    };

    result?;
    Ok(())
}

fn print_controller(s: &slk_protocol::SleControllerSnapshot) {
    let state = match s.flags {
        slk_protocol::CONTROLLER_READY => "Ready",
        slk_protocol::CONTROLLER_SETUP => "Setup",
        slk_protocol::CONTROLLER_FAULT => "Fault",
        _ => "Unknown",
    };
    println!(
        "ControllerSnapshot: index={} generation={} profile={} state={} error={} address={} metadata_valid={} credits={}",
        s.dev_index,
        s.generation,
        s.profile,
        state,
        s.error,
        fmt_addr(&s.address),
        s.valid_fields,
        s.command_credits
    );
}

fn validate_reply(
    query: NativeQuery,
    event: &slk_protocol::SleDliEvent,
) -> anyhow::Result<Option<&[u8]>> {
    let (opcode, len) = query.wire();
    // The validated WS73 zero-opcode credit notification can arrive between
    // commands. Host owns credits; this legacy projection is not a query reply.
    if event.event_type == 1 && event.opcode == 0 && event.status == 0 && event.data_len == 0 {
        return Ok(None);
    }
    anyhow::ensure!(
        event.opcode == opcode && matches!(event.event_type, 1 | 2),
        "unexpected diagnostic reply: type={} opcode=0x{:04x}",
        event.event_type,
        event.opcode
    );
    anyhow::ensure!(
        event.status == 0,
        "diagnostic controller status=0x{:02x} opcode=0x{:04x}",
        event.status,
        event.opcode
    );
    if event.event_type == 2 {
        anyhow::ensure!(
            event.data_len == 0,
            "diagnostic Status contains response data"
        );
        return Ok(None); // Accepted Status is not a completed query.
    }
    anyhow::ensure!(
        event.data_len as usize == len,
        "diagnostic payload length: expected={len} actual={}",
        event.data_len
    );
    Ok(Some(&event.data[..len]))
}

fn cmd_native_query(
    adapter: &Adapter,
    generation: u64,
    index: u16,
    profile: u32,
    query: NativeQuery,
) -> anyhow::Result<()> {
    use slk_protocol::*;
    use std::time::{Duration, Instant};
    anyhow::ensure!(
        profile == 1,
        "native diagnostic query currently requires WS73 profile 1"
    );
    let lease = adapter.acquire_management(generation, MANAGEMENT_DIAGNOSTIC)?;
    let result = (|| -> anyhow::Result<_> {
        // The legacy reply ABI has no sequence. Exclusive ownership and an
        // empty reply baseline establish this single command's provenance.
        let mut drained = 0;
        while adapter.poll_event()?.is_some() {
            drained += 1;
            anyhow::ensure!(
                drained <= 256,
                "diagnostic stale reply drain exceeded bound"
            );
        }
        anyhow::ensure!(
            adapter.mgmt_stats()?.pending == 0,
            "diagnostic command queue is not quiet"
        );
        let (opcode, _) = query.wire();
        let mut cmd = SleDliCmd {
            opcode,
            param_len: u16::from(matches!(query, NativeQuery::Mac)),
            seq: 0,
            params: [0; 240],
        };
        adapter.dli_send_cmd(&mut cmd)?;
        anyhow::ensure!(cmd.seq != 0, "diagnostic admission has no sequence");
        let deadline = Instant::now() + Duration::from_secs(6);
        loop {
            if let Some(event) = adapter.poll_event()?
                && let Some(data) = validate_reply(query, &event)?
            {
                return Ok((opcode, cmd.seq, drained, data.to_vec()));
            }
            anyhow::ensure!(Instant::now() < deadline, "diagnostic reply timeout");
            std::thread::sleep(Duration::from_millis(10));
        }
    })();
    // Release even on malformed/error replies; last-close remains a crash
    // fallback. Never print a successful query if its cleanup did not settle.
    let cleanup = (|| -> anyhow::Result<()> {
        adapter.release_management(generation, lease, MANAGEMENT_DIAGNOSTIC)?;
        let deadline = Instant::now() + Duration::from_secs(6);
        loop {
            let status = adapter.management_status(generation)?;
            match status.state {
                MANAGEMENT_FREE => return Ok(()),
                MANAGEMENT_HELD if status.flags & 1 == 0 => return Ok(()),
                MANAGEMENT_REVOKING => {}
                _ => anyhow::bail!(
                    "diagnostic cleanup state={} error={} status={} opcode=0x{:04x}",
                    status.state,
                    status.error,
                    status.status,
                    status.opcode
                ),
            }
            anyhow::ensure!(Instant::now() < deadline, "diagnostic cleanup timeout");
            std::thread::sleep(Duration::from_millis(10));
        }
    })();
    if let Err(error) = cleanup {
        return match result {
            Err(original) => Err(original.context(format!("cleanup also failed: {error:#}"))),
            Ok(_) => Err(error),
        };
    }
    let (opcode, seq, drained, data) = result?;
    let hex: String = data.iter().map(|b| format!("{b:02x}")).collect();
    println!(
        "NativeDiagnosticQuery: index={index} generation={generation} opcode=0x{opcode:04x} admission_seq={seq} status=0x00 drained={drained} data={hex}"
    );
    Ok(())
}

fn fmt_addr(addr: &[u8; 6]) -> String {
    format!(
        "{:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X}",
        addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
    )
}

fn cmd_info(adapter: &Adapter) -> libsparklink::Result<()> {
    let info = adapter.device_info()?;
    let name_end = info
        .name
        .iter()
        .position(|&b| b == 0)
        .unwrap_or(info.name.len());
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
    let name_end = info
        .name
        .iter()
        .position(|&b| b == 0)
        .unwrap_or(info.name.len());
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
    println!(
        "  Code rate:     {}/{}",
        info.code_rate_num, info.code_rate_den
    );
    println!("  MIMO mode:     {}", info.mimo_mode);
    println!(
        "  Antennas:      TX={} RX={}",
        info.num_tx_ant, info.num_rx_ant
    );
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

fn cmd_scan(adapter: &Adapter, duration: u64) -> libsparklink::Result<()> {
    use slk_protocol::SleScanParams;

    let params = SleScanParams {
        dev_index: adapter.device_info()?.index,
        window_ms: 100,
        interval_ms: 200,
        filter_discovery_level: 0,
        _reserved: [0; 9],
    };
    adapter.start_scan(&params)?;
    println!("Scanning for {duration} seconds...\n");

    let start = std::time::Instant::now();
    let mut count = 0u32;

    while start.elapsed().as_secs() < duration {
        match adapter.poll_event()? {
            Some(event) => {
                let name_end = event
                    .data
                    .iter()
                    .position(|&b| b == 0)
                    .unwrap_or(event.data_len as usize);
                let name = std::str::from_utf8(&event.data[..name_end]).unwrap_or("");
                count += 1;
                println!(
                    "  [{count}] {} RSSI={:>4} Level={} Name=\"{name}\"",
                    fmt_addr(&event.addr),
                    event.status as i8,
                    event.data[name_end.saturating_add(1).min(event.data.len() - 1)],
                );
            }
            None => {
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
        }
    }

    adapter.stop_scan()?;
    println!("\nScan complete: {count} report(s)");
    Ok(())
}

fn cmd_connect(adapter: &Adapter, address: &str) -> libsparklink::Result<()> {
    use slk_protocol::SleConnectParams;

    let addr = parse_addr(address)
        .map_err(|_| libsparklink::Error::InvalidParam("address must be AA:BB:CC:DD:EE:FF"))?;

    let params = SleConnectParams {
        peer_addr: addr,
        gt_role: 0,
        bandwidth: 0,
        mcs_index: 0,
        _pad: 0,
        timeout_10ms: 100,
        _reserved: [0; 4],
    };
    adapter.connect(&params)?;
    println!("Connection initiated to {address}");
    Ok(())
}

fn cmd_disconnect(adapter: &Adapter, handle_str: &str) -> libsparklink::Result<()> {
    let handle = if let Some(hex) = handle_str.strip_prefix("0x") {
        u16::from_str_radix(hex, 16)
            .map_err(|_| libsparklink::Error::InvalidParam("invalid hex handle"))?
    } else {
        handle_str
            .parse::<u16>()
            .map_err(|_| libsparklink::Error::InvalidParam("invalid handle number"))?
    };

    adapter.disconnect(handle)?;
    println!("Disconnected handle {handle:#06x}");
    Ok(())
}

fn parse_addr(s: &str) -> Result<[u8; 6], &'static str> {
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 6 {
        return Err("address must be AA:BB:CC:DD:EE:FF");
    }
    let mut addr = [0u8; 6];
    for (i, part) in parts.iter().enumerate() {
        addr[i] = u8::from_str_radix(part, 16).map_err(|_| "invalid hex byte")?;
    }
    Ok(addr)
}

fn cmd_security(adapter: &Adapter) -> libsparklink::Result<()> {
    let info = adapter.sec_info()?;

    let state_label = match info.state {
        0 => "none",
        1 => "pairing",
        2 => "paired",
        3 => "encrypted",
        _ => "unknown",
    };
    let method_label = match info.method {
        0 => "none",
        1 => "just_works",
        2 => "psk",
        _ => "unknown",
    };

    println!("Security State:");
    println!("  State:       {state_label} ({})", info.state);
    println!("  Method:      {method_label} ({})", info.method);
    println!("  Mode:        {}", info.mode);
    println!("  Encrypted:   {}", info.enc_enabled != 0);
    println!(
        "  Key fingerprint: {:02x}{:02x}{:02x}{:02x}",
        info.enc_key_fingerprint[0],
        info.enc_key_fingerprint[1],
        info.enc_key_fingerprint[2],
        info.enc_key_fingerprint[3]
    );

    Ok(())
}

fn cmd_pair(adapter: &Adapter, method: &str) -> libsparklink::Result<()> {
    use slk_protocol::SlePairParams;

    let m = match method {
        "just_works" => 1u8,
        "psk" => 2,
        "none" => 0,
        _ => {
            return Err(libsparklink::Error::InvalidParam(
                "method must be 'just_works', 'psk', or 'none'",
            ));
        }
    };

    let params = SlePairParams {
        method: m,
        _reserved: [0; 3],
    };
    adapter.pair(&params)?;
    println!("Pairing initiated (method: {method})");
    Ok(())
}

fn cmd_encrypt(adapter: &Adapter) -> libsparklink::Result<()> {
    adapter.encrypt_on()?;
    println!("Encryption enabled");
    Ok(())
}

fn cmd_set_psk(adapter: &Adapter, psk_hex: &str) -> libsparklink::Result<()> {
    use slk_protocol::SlePskParams;

    let hex = psk_hex.strip_prefix("0x").unwrap_or(psk_hex);
    if hex.len() != 32 {
        return Err(libsparklink::Error::InvalidParam(
            "PSK must be exactly 32 hex chars (16 bytes)",
        ));
    }

    let mut params = SlePskParams { psk: [0; 16] };
    for i in 0..16 {
        params.psk[i] = u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16)
            .map_err(|_| libsparklink::Error::InvalidParam("invalid hex character in PSK"))?;
    }

    adapter.set_psk(&params)?;
    println!("PSK set successfully");
    Ok(())
}

fn cmd_sec_reset(adapter: &Adapter) -> libsparklink::Result<()> {
    adapter.sec_reset()?;
    println!("Security state reset");
    Ok(())
}

fn cmd_services(adapter: &Adapter) -> libsparklink::Result<()> {
    let info = adapter.ssap_info()?;

    println!("SSAP Summary:");
    println!("  Services:       {}", info.service_count);
    println!("  Properties:     {}", info.property_count);
    println!("  Total entries:  {}", info.total_entries);
    println!("  MTU:            {}", info.mtu);
    println!("  Notifications:  {}", info.notification_count);

    Ok(())
}

fn cmd_list_services(adapter: &Adapter) -> libsparklink::Result<()> {
    let list = adapter.ssap_find_svc()?;

    if list.count == 0 {
        println!("No services registered");
        return Ok(());
    }

    println!("{} service(s):", list.count);
    for i in 0..list.count as usize {
        let s = &list.services[i];
        let kind = if s.primary != 0 {
            "Primary"
        } else {
            "Secondary"
        };
        println!(
            "  [{:#06x}-{:#06x}] UUID={:#06x} {kind}",
            s.start_handle, s.end_handle, s.uuid16
        );
    }

    Ok(())
}

fn cmd_read_prop(adapter: &Adapter, handle_str: &str) -> libsparklink::Result<()> {
    let handle = parse_handle(handle_str)?;
    let rw = adapter.ssap_read(handle)?;

    let data = &rw.data[..rw.length as usize];
    println!("Property {:#06x} ({} bytes):", handle, rw.length);
    print!("  ");
    for b in data {
        print!("{:02x} ", b);
    }
    println!();

    if let Ok(s) = std::str::from_utf8(data) {
        println!("  UTF-8: \"{s}\"");
    }

    Ok(())
}

fn cmd_write_prop(
    adapter: &Adapter,
    handle_str: &str,
    value_hex: &str,
) -> libsparklink::Result<()> {
    let handle = parse_handle(handle_str)?;
    let value = parse_hex_bytes(value_hex)?;
    let len = value.len().min(252);

    let mut rw = slk_protocol::SsapReadWrite {
        handle,
        length: len as u16,
        data: [0; 252],
    };
    rw.data[..len].copy_from_slice(&value[..len]);

    adapter.ssap_write(&rw)?;
    println!("Written {} bytes to property {:#06x}", len, handle);
    Ok(())
}

fn cmd_remote_discover(adapter: &Adapter, conn_str: &str) -> libsparklink::Result<()> {
    use slk_protocol::SsapRemoteCmd;

    let conn_handle = parse_handle(conn_str)?;

    // Exchange info first
    let cmd = SsapRemoteCmd {
        conn_handle,
        _reserved: [0; 2],
    };
    adapter.ssap_exchange_info(&cmd)?;
    println!("SSAP info exchanged with connection {:#06x}", conn_handle);

    // Discover all services 0x0001..0xFFFF
    let mut disc = slk_protocol::SsapRemoteDiscover {
        conn_handle,
        start_handle: 0x0001,
        end_handle: 0xFFFF,
        count: 0,
    };
    adapter.ssap_remote_discover(&mut disc)?;
    println!("Discovered {} service(s)", disc.count);

    Ok(())
}

fn cmd_remote_read(
    adapter: &Adapter,
    conn_str: &str,
    handle_str: &str,
) -> libsparklink::Result<()> {
    let conn_handle = parse_handle(conn_str)?;
    let handle = parse_handle(handle_str)?;

    let mut rw = slk_protocol::SsapRemoteReadWrite {
        conn_handle,
        handle,
        length: 0,
        _pad: [0; 2],
        data: [0; 248],
    };
    adapter.ssap_remote_read(&mut rw)?;

    let data = &rw.data[..rw.length as usize];
    println!("Remote property {:#06x} ({} bytes):", handle, rw.length);
    print!("  ");
    for b in data {
        print!("{:02x} ", b);
    }
    println!();

    if let Ok(s) = std::str::from_utf8(data) {
        println!("  UTF-8: \"{s}\"");
    }

    Ok(())
}

fn cmd_remote_write(
    adapter: &Adapter,
    conn_str: &str,
    handle_str: &str,
    value_hex: &str,
) -> libsparklink::Result<()> {
    let conn_handle = parse_handle(conn_str)?;
    let handle = parse_handle(handle_str)?;
    let value = parse_hex_bytes(value_hex)?;
    let len = value.len().min(248);

    let rw = slk_protocol::SsapRemoteReadWrite {
        conn_handle,
        handle,
        length: len as u16,
        _pad: [0; 2],
        data: {
            let mut d = [0u8; 248];
            d[..len].copy_from_slice(&value[..len]);
            d
        },
    };
    adapter.ssap_remote_write(&rw)?;
    println!("Written {} bytes to remote property {:#06x}", len, handle);
    Ok(())
}

fn cmd_call_method(
    adapter: &Adapter,
    conn_str: &str,
    handle_str: &str,
    input_hex: &str,
) -> libsparklink::Result<()> {
    let conn_handle = parse_handle(conn_str)?;
    let handle = parse_handle(handle_str)?;
    let input = parse_hex_bytes(input_hex)?;
    let len = input.len().min(248);

    let mut rw = slk_protocol::SsapRemoteReadWrite {
        conn_handle,
        handle,
        length: len as u16,
        _pad: [0; 2],
        data: {
            let mut d = [0u8; 248];
            d[..len].copy_from_slice(&input[..len]);
            d
        },
    };
    adapter.ssap_call_method(&mut rw)?;

    let out_len = (rw.length as usize).min(rw.data.len());
    let data = &rw.data[..out_len];
    println!("Method {:#06x} returned {} bytes:", handle, out_len);
    for chunk in data.chunks(16) {
        let hex: Vec<String> = chunk.iter().map(|b| format!("{b:02x}")).collect();
        println!("  {}", hex.join(" "));
    }
    Ok(())
}

fn cmd_find_by_uuid(adapter: &Adapter, conn_str: &str, uuid_str: &str) -> libsparklink::Result<()> {
    let conn_handle = parse_handle(conn_str)?;
    let uuid16 = parse_handle(uuid_str)?;

    let mut op: slk_protocol::SsapUuidOp = unsafe { std::mem::zeroed() };
    op.conn_handle = conn_handle;
    op.uuid16 = uuid16;
    adapter.ssap_find_by_uuid(&mut op)?;
    println!("UUID {:#06x} found at handle {:#06x}", uuid16, op.handle);
    Ok(())
}

fn cmd_read_by_uuid(adapter: &Adapter, conn_str: &str, uuid_str: &str) -> libsparklink::Result<()> {
    let conn_handle = parse_handle(conn_str)?;
    let uuid16 = parse_handle(uuid_str)?;

    let mut op: slk_protocol::SsapUuidOp = unsafe { std::mem::zeroed() };
    op.conn_handle = conn_handle;
    op.uuid16 = uuid16;
    adapter.ssap_read_by_uuid(&mut op)?;

    let out_len = (op.length as usize).min(op.data.len());
    let data = &op.data[..out_len];
    println!(
        "UUID {:#06x} at handle {:#06x} ({} bytes):",
        uuid16, op.handle, out_len
    );
    for chunk in data.chunks(16) {
        let hex: Vec<String> = chunk.iter().map(|b| format!("{b:02x}")).collect();
        println!("  {}", hex.join(" "));
    }
    if let Ok(s) = std::str::from_utf8(data) {
        println!("  UTF-8: \"{s}\"");
    }
    Ok(())
}

fn parse_handle(s: &str) -> libsparklink::Result<u16> {
    let s = s.strip_prefix("0x").unwrap_or(s);
    u16::from_str_radix(s, 16).map_err(|_| libsparklink::Error::InvalidParam("invalid hex handle"))
}

fn parse_hex_bytes(hex: &str) -> libsparklink::Result<Vec<u8>> {
    let hex = hex.strip_prefix("0x").unwrap_or(hex);
    if !hex.len().is_multiple_of(2) {
        return Err(libsparklink::Error::InvalidParam(
            "hex string must have even length",
        ));
    }
    if !hex.is_ascii() {
        return Err(libsparklink::Error::InvalidParam("invalid hex character"));
    }
    let mut bytes = Vec::with_capacity(hex.len() / 2);
    for i in (0..hex.len()).step_by(2) {
        let byte = u8::from_str_radix(&hex[i..i + 2], 16)
            .map_err(|_| libsparklink::Error::InvalidParam("invalid hex character"))?;
        bytes.push(byte);
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn diagnostic_reply_requires_complete_opcode_status_and_exact_length() {
        let mut event = slk_protocol::SleDliEvent {
            event_type: 1,
            status: 0,
            handle: 0,
            opcode: 0x0403,
            data_len: 10,
            data: [0x80; 240],
            addr: [0; 6],
            _pad: [0; 2],
        };
        assert_eq!(
            validate_reply(NativeQuery::Features, &event).unwrap(),
            Some(&[0x80; 10][..])
        );
        event.data_len = 9;
        assert!(validate_reply(NativeQuery::Features, &event).is_err());
        event.data_len = 11;
        assert!(validate_reply(NativeQuery::Features, &event).is_err());
        event.data_len = 10;
        event.event_type = 2;
        assert!(validate_reply(NativeQuery::Features, &event).is_err());
        event.data_len = 0;
        assert_eq!(validate_reply(NativeQuery::Features, &event).unwrap(), None);
        event.data_len = 10;
        event.event_type = 1;
        event.opcode = 0x0404;
        assert!(validate_reply(NativeQuery::Features, &event).is_err());
        event.opcode = 0x0403;
        event.status = 0xfd;
        assert!(
            format!(
                "{:#}",
                validate_reply(NativeQuery::Features, &event).unwrap_err()
            )
            .contains("status=0xfd")
        );
        event.status = 0;
        event.opcode = 0;
        event.data_len = 0;
        assert_eq!(validate_reply(NativeQuery::Features, &event).unwrap(), None);
        event.data_len = 1;
        assert!(validate_reply(NativeQuery::Features, &event).is_err());
    }

    #[test]
    fn native_query_requires_explicit_target_before_open() {
        let cli = Cli::try_parse_from([
            "slkconfig",
            "--device",
            "/missing-sparklink-test-device",
            "query",
            "mac",
            "--generation",
            "5",
        ])
        .unwrap();
        assert!(run(cli).unwrap_err().to_string().contains("--adapter"));
        let cli = Cli::try_parse_from([
            "slkconfig",
            "--device",
            "/missing-sparklink-test-device",
            "query",
            "mac",
            "--adapter",
            "0",
        ])
        .unwrap();
        assert!(run(cli).unwrap_err().to_string().contains("--generation"));
        assert!(
            Cli::try_parse_from([
                "slkconfig",
                "query",
                "reset",
                "--adapter",
                "0",
                "--generation",
                "5"
            ])
            .is_err()
        );
    }

    #[test]
    fn test_fmt_addr() {
        assert_eq!(
            fmt_addr(&[0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]),
            "AA:BB:CC:DD:EE:FF"
        );
        assert_eq!(
            fmt_addr(&[0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
            "00:00:00:00:00:00"
        );
        assert_eq!(
            fmt_addr(&[0x01, 0x23, 0x45, 0x67, 0x89, 0xAB]),
            "01:23:45:67:89:AB"
        );
    }

    #[test]
    fn test_parse_addr_valid() {
        let addr = parse_addr("AA:BB:CC:DD:EE:FF").unwrap();
        assert_eq!(addr, [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]);

        let addr = parse_addr("00:00:00:00:00:00").unwrap();
        assert_eq!(addr, [0; 6]);

        // Lowercase
        let addr = parse_addr("ab:cd:ef:01:23:45").unwrap();
        assert_eq!(addr, [0xAB, 0xCD, 0xEF, 0x01, 0x23, 0x45]);
    }

    #[test]
    fn test_parse_addr_invalid() {
        assert!(parse_addr("AA:BB:CC:DD:EE").is_err()); // too short
        assert!(parse_addr("AA:BB:CC:DD:EE:FF:00").is_err()); // too long
        assert!(parse_addr("GG:BB:CC:DD:EE:FF").is_err()); // invalid hex
        assert!(parse_addr("").is_err());
        assert!(parse_addr("AABBCCDDEEFF").is_err()); // no colons
    }

    #[test]
    fn test_parse_handle() {
        assert_eq!(parse_handle("0x0001").unwrap(), 1);
        assert_eq!(parse_handle("0xFFFF").unwrap(), 0xFFFF);
        assert_eq!(parse_handle("00AB").unwrap(), 0x00AB);
        assert_eq!(parse_handle("0xab").unwrap(), 0xAB);

        assert!(parse_handle("GGGG").is_err());
        assert!(parse_handle("0xGGGG").is_err());
    }

    #[test]
    fn test_parse_hex_bytes_valid() {
        assert_eq!(parse_hex_bytes("AABB").unwrap(), vec![0xAA, 0xBB]);
        assert_eq!(parse_hex_bytes("0xAABB").unwrap(), vec![0xAA, 0xBB]);
        assert_eq!(
            parse_hex_bytes("0x0102030405").unwrap(),
            vec![1, 2, 3, 4, 5]
        );
        assert_eq!(parse_hex_bytes("").unwrap(), Vec::<u8>::new());
    }

    #[test]
    fn test_parse_hex_bytes_invalid() {
        assert!(parse_hex_bytes("A").is_err()); // odd length
        assert!(parse_hex_bytes("0xA").is_err()); // odd length after prefix
        assert!(parse_hex_bytes("GGXX").is_err()); // invalid hex chars
        assert!(parse_hex_bytes("aéa").is_err()); // even byte count, invalid UTF-8 slice boundary
    }

    #[test]
    fn test_fmt_addr_roundtrip() {
        let original = [0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC];
        let formatted = fmt_addr(&original);
        let parsed = parse_addr(&formatted).unwrap();
        assert_eq!(original, parsed);
    }
}
