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

    /// Native WS73 opcode/event code in hex, e.g. 0x180b
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
    let mut adapter = Adapter::open(&cli.device)?;
    adapter.select_device(cli.adapter)?;
    let snapshot = adapter.controller_snapshot(cli.generation)?;
    anyhow::ensure!(
        snapshot.profile == 1,
        "native snoop currently requires WS73 profile 1"
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
