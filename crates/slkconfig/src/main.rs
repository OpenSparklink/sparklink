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
        Command::RemoteWrite { conn, handle, value } => cmd_remote_write(&adapter, &conn, &handle, &value),
        Command::CallMethod { conn, handle, input } => cmd_call_method(&adapter, &conn, &handle, &input),
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

fn cmd_scan(adapter: &Adapter, duration: u64) -> libsparklink::Result<()> {
    use slk_protocol::SleScanParams;

    let params = SleScanParams {
        dev_index: 0,
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
                let name_end = event.data.iter().position(|&b| b == 0).unwrap_or(event.data_len as usize);
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

    let addr = parse_addr(address).map_err(|_| {
        libsparklink::Error::InvalidParam("address must be AA:BB:CC:DD:EE:FF")
    })?;

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
        u16::from_str_radix(hex, 16).map_err(|_| {
            libsparklink::Error::InvalidParam("invalid hex handle")
        })?
    } else {
        handle_str.parse::<u16>().map_err(|_| {
            libsparklink::Error::InvalidParam("invalid handle number")
        })?
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
        params.psk[i] = u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).map_err(|_| {
            libsparklink::Error::InvalidParam("invalid hex character in PSK")
        })?;
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
        let kind = if s.primary != 0 { "Primary" } else { "Secondary" };
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

fn cmd_write_prop(adapter: &Adapter, handle_str: &str, value_hex: &str) -> libsparklink::Result<()> {
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

fn cmd_remote_read(adapter: &Adapter, conn_str: &str, handle_str: &str) -> libsparklink::Result<()> {
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

fn cmd_remote_write(adapter: &Adapter, conn_str: &str, handle_str: &str, value_hex: &str) -> libsparklink::Result<()> {
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

fn cmd_call_method(adapter: &Adapter, conn_str: &str, handle_str: &str, input_hex: &str) -> libsparklink::Result<()> {
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

fn parse_handle(s: &str) -> libsparklink::Result<u16> {
    let s = s.strip_prefix("0x").unwrap_or(s);
    u16::from_str_radix(s, 16).map_err(|_| {
        libsparklink::Error::InvalidParam("invalid hex handle")
    })
}

fn parse_hex_bytes(hex: &str) -> libsparklink::Result<Vec<u8>> {
    let hex = hex.strip_prefix("0x").unwrap_or(hex);
    if hex.len() % 2 != 0 {
        return Err(libsparklink::Error::InvalidParam("hex string must have even length"));
    }
    let mut bytes = Vec::with_capacity(hex.len() / 2);
    for i in (0..hex.len()).step_by(2) {
        let byte = u8::from_str_radix(&hex[i..i + 2], 16).map_err(|_| {
            libsparklink::Error::InvalidParam("invalid hex character")
        })?;
        bytes.push(byte);
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fmt_addr() {
        assert_eq!(fmt_addr(&[0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]), "AA:BB:CC:DD:EE:FF");
        assert_eq!(fmt_addr(&[0x00, 0x00, 0x00, 0x00, 0x00, 0x00]), "00:00:00:00:00:00");
        assert_eq!(fmt_addr(&[0x01, 0x23, 0x45, 0x67, 0x89, 0xAB]), "01:23:45:67:89:AB");
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
        assert_eq!(parse_hex_bytes("0x0102030405").unwrap(), vec![1, 2, 3, 4, 5]);
        assert_eq!(parse_hex_bytes("").unwrap(), Vec::<u8>::new());
    }

    #[test]
    fn test_parse_hex_bytes_invalid() {
        assert!(parse_hex_bytes("A").is_err()); // odd length
        assert!(parse_hex_bytes("0xA").is_err()); // odd length after prefix
        assert!(parse_hex_bytes("GGXX").is_err()); // invalid hex chars
    }

    #[test]
    fn test_fmt_addr_roundtrip() {
        let original = [0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC];
        let formatted = fmt_addr(&original);
        let parsed = parse_addr(&formatted).unwrap();
        assert_eq!(original, parsed);
    }
}
