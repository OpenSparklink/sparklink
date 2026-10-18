use std::process;

use clap::Parser;
use slk_native::Adapter;

#[derive(Parser)]
#[command(name = "slkdump", about = "SparkLink frame dump tool")]
struct Cli {
    /// Device path
    #[arg(short = 'i', long, default_value = "/dev/sparklink")]
    interface: String,

    /// Explicit registration index (list with slkconfig adapters)
    #[arg(long)]
    adapter: u16,
    /// Exact observed registration generation
    #[arg(long)]
    generation: u64,

    /// Native WS73 opcode/event code in hex, e.g. 0x180b
    #[arg(short, long)]
    filter: Option<String>,

    /// Maximum frames to capture (0 = unlimited)
    #[arg(short, long, default_value_t = 0)]
    count: u64,

    /// Create a private native SLKSNP01 capture (existing files are refused)
    #[arg(short, long)]
    write: Option<String>,
}

fn main() {
    let cli = Cli::parse();
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
    let mut adapter = Adapter::open(&cli.interface)?;
    adapter.select_device(cli.adapter)?;
    let snapshot = adapter.controller_snapshot(cli.generation)?;
    anyhow::ensure!(
        matches!(snapshot.profile, 0 | 1),
        "snoop requires registered standard or WS73 profile"
    );
    let mut receiver = adapter.into_snoop_receiver(cli.generation)?;
    let mut output = cli
        .write
        .as_ref()
        .map(slk_native::create_snoop_capture)
        .transpose()?;
    if let Some(out) = &mut output {
        slk_native::write_snoop_header(out)?;
        out.flush()?;
    }
    let mut captured = 0;
    loop {
        let record = receiver.next_record().await?;
        if filter.is_some_and(|code| slk_native::snoop_packet_code(&record) != Some(code)) {
            continue;
        }
        println!("{}", slk_native::describe_snoop(&record));
        if let Some(out) = &mut output {
            slk_native::write_snoop_record(out, &record)?;
            out.flush()?;
        }
        captured += 1;
        if cli.count > 0 && captured >= cli.count {
            return Ok(());
        }
    }
}
