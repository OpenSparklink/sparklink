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

    /// Show raw hex dump
    #[arg(short = 'X', long)]
    hexdump: bool,

    /// Filter by event type (hex, e.g. 0x01)
    #[arg(short, long)]
    filter: Option<String>,

    /// Write captured frames to file
    #[arg(short, long)]
    write: Option<String>,

    /// Maximum number of events to capture (0 = unlimited)
    #[arg(short, long, default_value_t = 0)]
    count: u64,
}

fn main() {
    let cli = Cli::parse();

    let adapter = match Adapter::open(&cli.device) {
        Ok(a) => a,
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
