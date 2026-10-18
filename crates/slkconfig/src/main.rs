use clap::{Parser, Subcommand, ValueEnum};
use slk_native::Adapter;

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
    /// Observe Core registration before Runtime binding; no management lease
    Registration,
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

    /// Show confirmed physical-link summary from a generation-bound snapshot
    Stats,
    /// List physical connections using generation/lifetime references
    Connections,
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
            let registration = match adapter.registration_snapshot(index, 0) {
                Ok(value) => value,
                Err(slk_native::Error::Ioctl(nix::errno::Errno::ENODEV)) => continue,
                Err(error) => return Err(error.into()),
            };
            print_registration(&registration);
            if registration.state != slk_protocol::REGISTRATION_INSTALLED {
                continue;
            }
            adapter.select_device(index)?;
            let snapshot = adapter.controller_snapshot(registration.generation)?;
            print_controller(&snapshot);
        }
        return Ok(());
    }
    let index = cli.adapter.ok_or_else(|| {
        anyhow::anyhow!("select a registration with --adapter; use adapters to list")
    })?;
    anyhow::ensure!(index < 16, "adapter index must be 0..15");
    anyhow::ensure!(cli.generation != Some(0), "generation must be nonzero");
    if matches!(cli.command, Command::Registration) {
        let adapter = Adapter::open(&cli.device)?;
        print_registration(&adapter.registration_snapshot(index, cli.generation.unwrap_or(0))?);
        return Ok(());
    }
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
    let result = match cli.command {
        Command::Adapters
        | Command::Registration
        | Command::Controller
        | Command::Management
        | Command::Query { .. } => {
            unreachable!()
        }
        Command::Info => cmd_info(&adapter),
        Command::Dli => cmd_dli(&adapter),
        Command::Stats => cmd_stats(&adapter),
        Command::Connections => cmd_connections(&adapter),
    };

    result?;
    Ok(())
}

fn print_registration(s: &slk_protocol::SleRegistrationSnapshot) {
    println!(
        "Registration: index={} generation={} state={} profile={} bus={} phase={} error={}",
        s.dev_index, s.generation, s.state, s.profile, s.bus, s.phase, s.error
    );
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
    event: &slk_protocol::SleDiagnosticResult,
) -> anyhow::Result<Option<&[u8]>> {
    let (opcode, len) = query.wire();
    anyhow::ensure!(
        event.opcode == opcode,
        "unexpected diagnostic opcode=0x{:04x}",
        event.opcode
    );
    match event.state {
        1 => {
            anyhow::ensure!(
                event.error == 0 && event.status == 0 && event.data_len == 0,
                "invalid pending diagnostic result"
            );
            return Ok(None);
        }
        2 => {}
        3 => anyhow::bail!(
            "diagnostic failed: error={} status=0x{:02x} opcode=0x{:04x}",
            event.error,
            event.status,
            event.opcode
        ),
        _ => anyhow::bail!("invalid diagnostic result state"),
    }
    anyhow::ensure!(
        event.error == 0 && event.status == 0,
        "invalid diagnostic success"
    );
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
        matches!(profile, 0 | 1),
        "diagnostic query requires a registered standard or WS73 profile"
    );
    let lease = adapter.acquire_management(generation, MANAGEMENT_DIAGNOSTIC)?;
    let result = (|| -> anyhow::Result<_> {
        // Result ownership and captured Host sequence establish provenance;
        // observation does not steal data from any controller subscription.
        // Exclusive Diagnostic lease and Host admission own the transaction;
        // a legacy private queue counter cannot prove Native quiescence.
        let (opcode, _) = query.wire();
        let mut cmd = SleDiagnosticSubmit {
            version: 1,
            generation,
            request_id: 1, // This CLI opens a new author fd and submits once.
            opcode,
            timeout_ms: 5000,
            action: 1,
            ..Default::default()
        };
        adapter.diagnostic_submit(&mut cmd)?;
        anyhow::ensure!(cmd.seq != 0, "diagnostic admission has no sequence");
        let deadline = Instant::now() + Duration::from_secs(6);
        loop {
            if let Some(event) = adapter.diagnostic_result(generation, cmd.seq)?
                && let Some(data) = validate_reply(query, &event)?
            {
                return Ok((opcode, cmd.seq, data.to_vec()));
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
    let (opcode, seq, data) = result?;
    let hex: String = data.iter().map(|b| format!("{b:02x}")).collect();
    println!(
        "NativeDiagnosticQuery: index={index} generation={generation} opcode=0x{opcode:04x} admission_seq={seq} status=0x00 data={hex}"
    );
    Ok(())
}

fn fmt_addr(addr: &[u8; 6]) -> String {
    format!(
        "{:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X}",
        addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
    )
}

fn cmd_info(adapter: &Adapter) -> slk_native::Result<()> {
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

fn cmd_dli(adapter: &Adapter) -> slk_native::Result<()> {
    print_controller(&adapter.controller_snapshot(0)?);
    Ok(())
}

fn cmd_stats(adapter: &Adapter) -> slk_native::Result<()> {
    let identity = adapter.controller_snapshot(0)?;
    let links = adapter.native_link_snapshot(identity.generation)?;
    if links.flags != slk_protocol::LINK_SNAPSHOT_KNOWN || links.error != 0 {
        return Err(slk_native::Error::InvalidParam(
            "physical link state is unknown",
        ));
    }
    println!(
        "ControllerLinkSummary: index={} generation={} revision={} event_sequence={} connections={}",
        links.dev_index, links.generation, links.revision, links.event_seq, links.count
    );
    Ok(())
}

fn cmd_connections(adapter: &Adapter) -> slk_native::Result<()> {
    let identity = adapter.controller_snapshot(0)?;
    let links = adapter.native_link_snapshot(identity.generation)?;
    if links.flags != slk_protocol::LINK_SNAPSHOT_KNOWN || links.error != 0 {
        return Err(slk_native::Error::InvalidParam(
            "physical link state is unknown",
        ));
    }
    println!(
        "NativeLinks: index={} generation={} revision={} sequence={} count={}",
        links.dev_index, links.generation, links.revision, links.event_seq, links.count
    );
    for link in &links.links[..links.count as usize] {
        println!(
            "NativeLink: lifetime={} handle={} role={} type={} address={}",
            link.lifetime,
            link.handle,
            link.role,
            link.address_type,
            fmt_addr(&link.address)
        );
    }
    Ok(())
}

#[cfg(test)]
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

#[cfg(test)]
fn parse_handle(s: &str) -> slk_native::Result<u16> {
    let s = s.strip_prefix("0x").unwrap_or(s);
    u16::from_str_radix(s, 16).map_err(|_| slk_native::Error::InvalidParam("invalid hex handle"))
}

#[cfg(test)]
fn parse_hex_bytes(hex: &str) -> slk_native::Result<Vec<u8>> {
    let hex = hex.strip_prefix("0x").unwrap_or(hex);
    if !hex.len().is_multiple_of(2) {
        return Err(slk_native::Error::InvalidParam(
            "hex string must have even length",
        ));
    }
    if !hex.is_ascii() {
        return Err(slk_native::Error::InvalidParam("invalid hex character"));
    }
    let mut bytes = Vec::with_capacity(hex.len() / 2);
    for i in (0..hex.len()).step_by(2) {
        let byte = u8::from_str_radix(&hex[i..i + 2], 16)
            .map_err(|_| slk_native::Error::InvalidParam("invalid hex character"))?;
        bytes.push(byte);
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retired_security_spellings_are_rejected_by_actual_clap_parser() {
        for command in [
            vec!["security"],
            vec!["pair"],
            vec!["encrypt"],
            vec!["set-psk", "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
            vec!["sec-reset"],
        ] {
            let error = Cli::try_parse_from(std::iter::once("slkconfig").chain(command))
                .err()
                .expect("retired command unexpectedly parsed");
            assert_eq!(error.kind(), clap::error::ErrorKind::InvalidSubcommand);
        }
    }

    #[test]
    fn diagnostic_reply_requires_complete_opcode_status_and_exact_length() {
        let mut event = slk_protocol::SleDiagnosticResult {
            state: 2,
            opcode: 0x0403,
            data_len: 10,
            data: [0x80; 64],
            ..Default::default()
        };
        assert_eq!(
            validate_reply(NativeQuery::Features, &event).unwrap(),
            Some(&[0x80; 10][..])
        );
        for len in [0, 9, 11, 64, 65535] {
            event.data_len = len;
            assert!(validate_reply(NativeQuery::Features, &event).is_err());
        }
        event.data_len = 10;
        event.state = 1;
        assert!(validate_reply(NativeQuery::Features, &event).is_err());
        event.data_len = 0;
        assert_eq!(validate_reply(NativeQuery::Features, &event).unwrap(), None);
        event.data_len = 10;
        event.state = 2;
        event.opcode = 0x0404;
        assert!(validate_reply(NativeQuery::Features, &event).is_err());
        event.opcode = 0x0403;
        event.state = 3;
        event.status = 0xfd;
        assert!(
            validate_reply(NativeQuery::Features, &event)
                .unwrap_err()
                .to_string()
                .contains("status=0xfd")
        );
        event.status = 0;
        event.error = -110;
        assert!(
            validate_reply(NativeQuery::Features, &event)
                .unwrap_err()
                .to_string()
                .contains("error=-110")
        );
        event.state = 2;
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
    fn retired_service_commands_are_absent_before_device_open() {
        for args in [
            vec!["services"],
            vec!["phy"],
            vec!["role"],
            vec!["reset"],
            vec!["scan"],
            vec!["connect"],
            vec!["disconnect"],
            vec!["list-services"],
            vec!["read-prop", "1"],
            vec!["write-prop", "1", "ab"],
            vec!["remote-discover", "1"],
            vec!["remote-read", "1", "1"],
            vec!["remote-write", "1", "1", "ab"],
            vec!["call-method", "1", "1", "ab"],
            vec!["find-by-uuid", "1", "1"],
            vec!["read-by-uuid", "1", "1"],
        ] {
            let result = Cli::try_parse_from(std::iter::once("slkconfig").chain(args));
            assert!(
                matches!(result, Err(error) if error.kind() == clap::error::ErrorKind::InvalidSubcommand)
            );
        }
    }

    #[test]
    fn test_fmt_addr_roundtrip() {
        let original = [0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC];
        let formatted = fmt_addr(&original);
        let parsed = parse_addr(&formatted).unwrap();
        assert_eq!(original, parsed);
    }
}
