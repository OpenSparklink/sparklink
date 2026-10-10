mod commands;

use std::process;

use rustyline::DefaultEditor;
use rustyline::error::ReadlineError;

const PROMPT: &str = "[slk]# ";

fn main() {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap_or_else(|e| {
            eprintln!("failed to create runtime: {e}");
            process::exit(1);
        });

    if let Err(e) = rt.block_on(run()) {
        eprintln!("error: {e}");
        process::exit(1);
    }
}

async fn run() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1).collect::<Vec<_>>();
    let session = args.first().is_some_and(|a| a == "--session");
    if session {
        args.remove(0);
    }
    let conn = if session {
        zbus::Connection::session().await?
    } else {
        zbus::Connection::system().await?
    };
    let mut ctx = commands::Context::new(conn);

    // One-shot commands make automation reproducible.
    if !args.is_empty() {
        if args.len() >= 2 && args[0] == "--adapter" {
            ctx.dispatch(&["select", &args[1]]).await?;
            args.drain(..2);
        }
        if args.is_empty() {
            anyhow::bail!("missing command");
        }
        let parts = args.iter().map(String::as_str).collect::<Vec<_>>();
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
    println!(
        "\
Commands:
  list                          List adapters
  select <path>                 Select a live adapter registration
  reports                       Show exact native discovery reports
  show                          Show adapter details
  scan on [marker address]|off  Scan and optionally await a fresh matching report
  advertise on [32-hex-marker]   Start native beacon with a fresh random marker
  advertise off                 Stop native beacon
  result <request-id>           Inspect retained native operation result
  devices                       List discovered devices
  info <address>                Show device details
  pair <address>                Pair with device
  connect <address>             Connect to device
  disconnect [address]          Disconnect
  services                      List local SSAP services
  remote-services               List remote services
  read <handle>                 Read property value
  write <handle> <hex>          Write property value
  security                      Show security state
  role [g|t]                    Get/set role
  phy                           Show PHY parameters
  stats                         Show subsystem statistics
  events                        Show event queue statistics
  mgmt                          Show management plane statistics
  extadv <sub>                  Extended advertising management
  power                         Show power management state
  dli                           Show DLI controller info
  mcs <index>                   Set MCS index
  txpower <dBm>                 Set TX power
  bandwidth <MHz>               Set bandwidth
  afh <sub>                     AFH channel map management
  ral <sub>                     Resolving address list management
  rpa <sub>                     Resolvable private address control
  sync <sub>                    Sync link management
  meas <sub>                    Measurement / ranging control
  peer <sub>                    Peer capability queries
  bonded [list|remove <addr>]   Manage bonded devices
  help                          Print this help
  quit                          Exit"
    );
}

fn dirs_history_path() -> Option<String> {
    std::env::var("HOME")
        .ok()
        .map(|h| format!("{h}/.slctl_history"))
}
