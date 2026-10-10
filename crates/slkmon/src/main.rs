mod decode;

use std::process;

use clap::Parser;
use libsparklink::Adapter;

#[derive(Parser)]
#[command(name = "slkmon", about = "SparkLink protocol monitor")]
struct Cli {
    /// Device path
    #[arg(short, long, default_value = "/dev/sparklink")]
    device: String,

    /// Explicit registration index (list with slkconfig adapters)
    #[arg(long)]
    adapter: u16,
    /// Exact observed registration generation
    #[arg(long)]
    generation: u64,
    /// Deprecated destructive profile-0 capture; native capture is independent
    #[arg(long)]
    legacy: bool,

    /// Show legacy decoded hex dump (native records always include exact hex)
    #[arg(short = 'X', long)]
    hexdump: bool,

    /// Native WS73 opcode/event code in hex, e.g. 0x180b; legacy u8 event type
    #[arg(short, long)]
    filter: Option<String>,

    /// Create a private native SLKSNP01 capture (existing files are refused)
    #[arg(short, long)]
    write: Option<String>,

    /// Maximum number of events to capture (0 = unlimited)
    #[arg(short, long, default_value_t = 0)]
    count: u64,
}

fn main() {
    let cli = Cli::parse();
    if !cli.legacy {
        let result = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .and_then(|rt| {
                rt.block_on(capture_native(&cli))
                    .map_err(std::io::Error::other)
            });
        if let Err(error) = result {
            eprintln!("capture error: {error}");
            process::exit(1);
        }
        return;
    }

    let adapter = match Adapter::open(&cli.device) {
        Ok(mut a) => {
            if let Err(error) = a
                .select_device(cli.adapter)
                .and_then(|_| a.controller_snapshot(cli.generation))
                .and_then(|s| {
                    if s.profile == 0 && cli.generation != 0 {
                        Ok(())
                    } else {
                        Err(libsparklink::Error::InvalidParam(
                            "legacy capture requires profile 0 and exact generation",
                        ))
                    }
                })
            {
                eprintln!("capture error: {error}");
                process::exit(1);
            }
            a
        }
        Err(e) => {
            eprintln!("failed to open {}: {e}", cli.device);
            process::exit(1);
        }
    };

    let filter_type: Option<u8> = cli.filter.as_ref().and_then(|f| {
        let f = f.strip_prefix("0x").unwrap_or(f);
        u8::from_str_radix(f, 16).ok()
    });

    let mut output: Option<std::io::BufWriter<std::fs::File>> = cli.write.as_ref().map(|path| {
        let file = std::fs::File::create(path).unwrap_or_else(|e| {
            eprintln!("cannot create {path}: {e}");
            process::exit(1);
        });
        std::io::BufWriter::new(file)
    });

    eprintln!("Monitoring {} — press Ctrl-C to stop", cli.device);

    let mut captured = 0u64;

    loop {
        match adapter.poll_event() {
            Ok(Some(event)) => {
                if let Some(ft) = filter_type
                    && event.event_type != ft
                {
                    continue;
                }

                captured += 1;
                let ts = chrono::Local::now().format("%H:%M:%S%.3f");

                decode::print_event(&event, &ts.to_string(), cli.hexdump);

                if let Some(ref mut out) = output {
                    use std::io::Write;
                    let _ = writeln!(
                        out,
                        "{ts} type={:#04x} handle={:#06x} status={} len={}",
                        event.event_type, event.handle, event.status, event.data_len
                    );
                    if cli.hexdump {
                        let hex: String = event.data[..event.data_len as usize]
                            .iter()
                            .map(|b| format!("{:02x}", b))
                            .collect::<Vec<_>>()
                            .join(" ");
                        let _ = writeln!(out, "  {hex}");
                    }
                }

                if cli.count > 0 && captured >= cli.count {
                    eprintln!("Captured {captured} event(s), stopping");
                    break;
                }
            }
            Ok(None) => {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            Err(e) => {
                eprintln!("event read error: {e}");
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
        }
    }
}

async fn capture_native(cli: &Cli) -> anyhow::Result<()> {
    use std::io::Write;
    anyhow::ensure!(
        cli.adapter < 16 && cli.generation != 0,
        "capture requires adapter 0..15 and nonzero generation"
    );
    let filter = cli
        .filter
        .as_ref()
        .map(|v| u16::from_str_radix(v.strip_prefix("0x").unwrap_or(v), 16))
        .transpose()?;
    let mut adapter = Adapter::open(&cli.device)?;
    adapter.select_device(cli.adapter)?;
    let snapshot = adapter.controller_snapshot(cli.generation)?;
    anyhow::ensure!(
        snapshot.profile == 1,
        "native snoop currently requires WS73 profile 1; --legacy is deprecated profile-0 capture"
    );
    let mut receiver = adapter.into_snoop_receiver(cli.generation)?;
    let mut output = cli
        .write
        .as_ref()
        .map(libsparklink::create_snoop_capture)
        .transpose()?;
    if let Some(out) = &mut output {
        libsparklink::write_snoop_header(out)?;
        out.flush()?;
    }
    let mut captured = 0;
    loop {
        let record = receiver.next_record().await?;
        if filter.is_some_and(|code| libsparklink::snoop_packet_code(&record) != Some(code)) {
            continue;
        }
        println!("{}", libsparklink::describe_snoop(&record));
        if let Some(out) = &mut output {
            libsparklink::write_snoop_record(out, &record)?;
            out.flush()?;
        }
        captured += 1;
        if cli.count > 0 && captured >= cli.count {
            return Ok(());
        }
    }
}
