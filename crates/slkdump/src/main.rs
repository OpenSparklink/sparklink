use std::process;

use clap::Parser;
use libsparklink::Adapter;

#[derive(Parser)]
#[command(name = "slkdump", about = "SparkLink frame dump tool")]
struct Cli {
    /// Device path
    #[arg(short = 'i', long, default_value = "/dev/sparklink")]
    interface: String,

    /// Show ASCII alongside hex
    #[arg(short = 'X', long)]
    hexascii: bool,

    /// Only show hex bytes, no decoding
    #[arg(short, long)]
    raw: bool,

    /// Filter: only DLI events of this type (hex)
    #[arg(short, long)]
    filter: Option<String>,

    /// Maximum frames to capture (0 = unlimited)
    #[arg(short, long, default_value_t = 0)]
    count: u64,

    /// Write raw frames to binary file
    #[arg(short, long)]
    write: Option<String>,
}

fn main() {
    let cli = Cli::parse();

    let adapter = match Adapter::open(&cli.interface) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("failed to open {}: {e}", cli.interface);
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

    eprintln!("Dumping frames from {} — Ctrl-C to stop", cli.interface);

    let mut captured = 0u64;

    loop {
        match adapter.poll_event() {
            Ok(Some(event)) => {
                if let Some(ft) = filter_type {
                    if event.event_type != ft {
                        continue;
                    }
                }

                captured += 1;
                let data = &event.data[..event.data_len as usize];
                let direction = if event.event_type <= 0x06 { ">" } else { "<" };

                if cli.raw {
                    // Raw hex output
                    let all_bytes = raw_frame_bytes(&event);
                    let hex: String = all_bytes.iter().map(|b| format!("{:02X}", b)).collect::<Vec<_>>().join(" ");
                    println!("{direction} {hex}");
                } else {
                    // Decoded output
                    let type_tag = match event.event_type {
                        0x01 => "EVT",
                        0x02 => "ADV",
                        0x03 => "DAT",
                        0x04 => "SEC",
                        0x05 => "PWR",
                        0x06 => "ERR",
                        _ => "UNK",
                    };

                    let hex: String = data.iter().map(|b| format!("{:02X}", b)).collect::<Vec<_>>().join(" ");

                    if cli.hexascii {
                        let ascii: String = data.iter()
                            .map(|&b| if b.is_ascii_graphic() || b == b' ' { b as char } else { '.' })
                            .collect();
                        println!(
                            "{direction} {:02X} {:04X} {:02X} {:02X} {:<48} {}",
                            event.event_type, event.handle, event.status, event.data_len,
                            hex, ascii
                        );
                    } else {
                        println!(
                            "{direction} {type_tag} h={:04X} s={:02X} [{}] {}",
                            event.handle, event.status, event.data_len, hex
                        );
                    }
                }

                if let Some(ref mut out) = output {
                    use std::io::Write;
                    let frame = raw_frame_bytes(&event);
                    let _ = out.write_all(&frame);
                }

                if cli.count > 0 && captured >= cli.count {
                    eprintln!("Captured {captured} frame(s)");
                    break;
                }
            }
            Ok(None) => {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            Err(e) => {
                eprintln!("read error: {e}");
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
        }
    }
}

fn raw_frame_bytes(event: &slk_protocol::SleDliEvent) -> Vec<u8> {
    let mut buf = Vec::with_capacity(12 + event.data_len as usize);
    buf.push(event.event_type);
    buf.extend_from_slice(&event.handle.to_le_bytes());
    buf.push(event.status);
    buf.extend_from_slice(&event.addr);
    buf.extend_from_slice(&event.data_len.to_le_bytes());
    buf.extend_from_slice(&event.data[..event.data_len as usize]);
    buf
}
