mod commands;
mod security_agent;
mod ssap_server;
mod ssap_subscription;

use std::process;

use clap::Parser;
use rustyline::DefaultEditor;
use rustyline::error::ReadlineError;

const PROMPT: &str = "[slk]# ";

#[derive(Debug, Parser)]
#[command(name = "slctl", version, about = "SparkLink control tool", after_help = COMMAND_HELP)]
struct Cli {
    /// Use the session bus for isolated tests.
    #[arg(long)]
    session: bool,

    /// Select an adapter for a one-shot command.
    #[arg(long, value_name = "PATH", requires = "command")]
    adapter: Option<String>,

    /// Run one command, or start the interactive shell when omitted.
    #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
    command: Vec<String>,
}

fn main() {
    let cli = Cli::parse();
    if cli.command == ["help"] {
        print_help();
        return;
    }
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap_or_else(|e| {
            eprintln!("failed to create runtime: {e}");
            process::exit(1);
        });

    if let Err(e) = rt.block_on(run(cli)) {
        eprintln!("error: {e}");
        process::exit(1);
    }
}

async fn run(cli: Cli) -> anyhow::Result<()> {
    let conn = if cli.session {
        zbus::Connection::session().await?
    } else {
        zbus::Connection::system().await?
    };
    let mut ctx = commands::Context::new(conn);

    // One-shot commands make automation reproducible.
    if !cli.command.is_empty() {
        if let Some(adapter) = &cli.adapter {
            ctx.dispatch(&["select", adapter]).await?;
        }
        let parts = cli.command.iter().map(String::as_str).collect::<Vec<_>>();
        return ctx.dispatch(&parts).await;
    }
    let mut rl = DefaultEditor::new()?;
    let history_path = dirs_history_path();
    if let Some(ref path) = history_path {
        let _ = rl.load_history(path);
    }

    println!("SparkLink interactive tool — type 'help' for commands, 'quit' to exit");

    loop {
        match rl.readline(PROMPT) {
            Ok(line) => {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }
                let _ = rl.add_history_entry(line);

                let parts: Vec<&str> = line.split_whitespace().collect();
                match parts[0] {
                    "quit" | "exit" => break,
                    "help" => print_help(),
                    _ => {
                        if let Err(e) = ctx.dispatch(&parts).await {
                            eprintln!("error: {e}");
                        }
                    }
                }
            }
            Err(ReadlineError::Interrupted | ReadlineError::Eof) => break,
            Err(e) => {
                eprintln!("readline error: {e}");
                break;
            }
        }
    }

    if let Some(ref path) = history_path {
        let _ = rl.save_history(path);
    }

    Ok(())
}

fn print_help() {
    println!("{COMMAND_HELP}");
}

const COMMAND_HELP: &str = "\
Commands:
  registrations                 Observe live Core registrations including early faults
  registration <path>           Read exact Core lifecycle (Installed is not Ready)
  daemon                        Show the bus-authenticated slkd owner/PID/UID
  list                          List adapters
  controller-events [count] [ms] Observe bounded daemon-directory changes (not Native Ready/Down)
  discover [prefix|-] [count] [ms] [RSSI] Caller-owned bounded passive scan; release only own lease
  select <path>                 Select a live adapter registration
  reports                       Show exact native discovery reports
  show                          Show adapter details
  scan on [marker address]|off  Scan and optionally await a fresh matching report
  advertise on [32-hex-marker]   Start native beacon with a fresh random marker
  advertise connectable [marker] Start explicit fixed-T connectable announcement
  advertise negotiable [marker]  Start explicit negotiable-T announcement
  advertise off                 Stop native beacon
  advertise initialized-off     Query real initializer OFF for untouched advertising
  scan initialized-off          Query real initializer OFF for untouched scanning
  result <request-id>           Inspect retained native operation result
  cancel-discovery              Cancel both native policies and drain this device
  management                    Query native kernel management state without token
  peers                         List typed peers and observation validity
  peer-observation <path>        Show one typed Peer advertisement (unknown RSSI explicit)
  agent [method]                Foreground Agent [sdk111-no-mitm|sdk111-numeric-comparison], no auto-approval
  security-request <path> [ms] [method]  Request exact Connection security (1..5000ms)
  connect <address>             Connect to device
  connections                   Show canonical native links and lifetimes
  connection-objects            List typed physical connection objects
  peer-info <path>               Show a typed peer and its connection lifetimes
  connection-info <path>        Show one immutable connection identity
  link-measurement <path> <rssi|phy> [timeout-ms]  Read a real Managed link observation
  link-payload-preference <path> <octets> [timeout-ms]  Request link payload preference; acknowledgment only
  disconnect-object <path>      Disconnect the exact physical lifetime
  ssap-discover <path> [structure|service|property uuid-hex] Discover actual peer metadata
  ssap-list                            Inspect local service metadata only
  ssap-register <service-hex> <property-hex> <ops> <access> <value-hex> Configure local database only
  ssap-serve <service-hex> <property-hex> <ops> <access> <value-hex> [ask|allow|deny] Own a foreground local service; policy decision is not peer receipt
  ssap-remove <start-handle>                 Remove local service (handles not reused)
  ssap-local-read <handle>                   Inspect local database, not peer receipt
  ssap-receive <path> <handle> [notify|indicate|both] [wait-ms] Authenticated CPCD enable, one update, verified disable
  ssap-subscribe <path> <handle> [notify|indicate|both] [count] [lease-ms] Finite leased updates, explicit cleanup; no auto-renew
  ssap-read-uuid <path> <start> <end> <uuid-hex> [minimum] Read actual peer values by UUID
  ssap-read <path> <handle> [minimum]                  Read actual peer value on SMTC
  ssap-write <path> <handle> <value-hex> [minimum]      Write with peer verification and reply
  transport-status <path>                    Read current Session queues/debt/state (not drain/reuse proof)
  ssap-info <path>                           Read peer-validated SMTC ExchangeInfo (not services)
  disconnect <address> [type]    Disconnect an unambiguous current peer
  disconnect-link <addr> <type> <handle> <lifetime> <role>  Disconnect exact link
  stats                         Show confirmed physical-link summary
  events                        Show selected registration event watermark
  help                          Print this help
  quit                          Exit";

fn dirs_history_path() -> Option<String> {
    std::env::var("HOME")
        .ok()
        .map(|h| format!("{h}/.slctl_history"))
}
