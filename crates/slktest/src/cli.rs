use crate::{
    benchmark, channel,
    connection::{Client, DynamicExercise},
};
use clap::{Args, Parser, Subcommand, ValueEnum};
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    name = "slktest",
    version,
    about = "SparkLink application channel correctness and load tests",
    long_about = "Application tests on ordinary delegated channel fds. Basic CUTC measurements only; dynamic routes are limited correctness exercises. Not a Host, packet capture, kernel selftest, formal prover or performance qualification. Load modes require stdin start after both Armed, then finish after both Quiescent; each control wait is bounded."
)]
struct Cli {
    /// Use a private session bus for integration tests, never hardware qualification.
    #[arg(long, global = true)]
    session: bool,
    /// Current immutable adapter object path, selected and managed with slctl.
    #[arg(long)]
    adapter: String,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Channel {
        #[command(subcommand)]
        command: Channel,
    },
}
#[derive(Subcommand)]
enum Channel {
    /// Initiate ping-pong measurement, or existing correctness receipts with --check.
    Ping(Pair),
    /// Reply to ping (default), rate/window (--load), or correctness (--check).
    Peer(Pair),
    /// Absolute schedule; never slow the offered plan waiting for replies.
    Rate(Rate),
    /// Bounded number of outstanding application requests.
    Window(Load),
    /// Both endpoints independently send, validate and reply. Run on both ends.
    Duplex(Load),
}
#[derive(Clone, Copy, PartialEq, Eq, ValueEnum)]
enum Exercise {
    Regular,
    Boundaries,
    PrefixClose,
    Burst,
}
impl Exercise {
    fn mode(self) -> channel::Mode {
        match self {
            Self::Regular => channel::Mode::Regular,
            Self::Boundaries => channel::Mode::Boundaries,
            Self::PrefixClose => channel::Mode::PrefixClose,
            Self::Burst => channel::Mode::Burst,
        }
    }
}
#[derive(Args)]
struct Pair {
    /// Exact live Connection object path under --adapter.
    connection: String,
    #[arg(long, default_value_t = 4)]
    count: usize,
    #[arg(long, default_value_t = 61)]
    bytes: usize,
    /// Existing bounded correctness exercise and original evidence receipts.
    #[arg(long, conflicts_with = "load")]
    check: bool,
    /// Peer only: respond to rate/window; explicit stdin start barrier.
    #[arg(long)]
    load: bool,
    /// New JSON file (required for measurements, forbidden for --check).
    #[arg(long, required_unless_present = "check")]
    report: Option<PathBuf>,
    /// Only --load: default min(16,count). Application window, not credit.
    #[arg(long)]
    window: Option<usize>,
    #[arg(long, value_enum, default_value = "regular")]
    exercise: Exercise,
    /// Dynamic correctness only; must supply all three route fields.
    #[arg(long,requires_all=["destination_port","aid","check"])]
    source_port: Option<u16>,
    #[arg(long,requires_all=["source_port","aid","check"])]
    destination_port: Option<u16>,
    #[arg(long,requires_all=["source_port","destination_port","check"])]
    aid: Option<u16>,
    /// Dynamic correctness: keep fd reference until an explicit close line.
    #[arg(long,requires_all=["source_port","check"])]
    hold: bool,
    /// Dynamic correctness: after real negotiation, await exact start line (30s).
    #[arg(long, requires_all=["source_port", "check"])]
    start_barrier: bool,
}
#[derive(Args)]
struct Load {
    connection: String,
    #[arg(long, default_value_t = 100)]
    count: usize,
    #[arg(long, default_value_t = 61)]
    bytes: usize,
    /// Default min(16,count); independent of controller credit.
    #[arg(long)]
    window: Option<usize>,
    #[arg(long)]
    report: PathBuf,
}
#[derive(Args)]
struct Rate {
    #[command(flatten)]
    load: Load,
    /// Absolute scheduled interval in microseconds, 10..1000000; plan <=600s.
    #[arg(long)]
    interval_us: u64,
}
impl Load {
    fn config(&self, mode: benchmark::LoadMode, interval_us: u64) -> benchmark::LoadConfig {
        benchmark::LoadConfig {
            mode,
            count: self.count,
            bytes: self.bytes,
            window: self.window.unwrap_or(self.count.min(16)),
            interval_us,
        }
    }
}
impl Pair {
    fn validate(&self, peer: bool) -> anyhow::Result<()> {
        benchmark::Config {
            count: self.count,
            bytes: self.bytes,
        }
        .validate()?;
        if self.check {
            if self.count > 20 || self.report.is_some() || self.window.is_some() {
                anyhow::bail!("--check:1..20 messages,no report/window");
            }
            if matches!(self.exercise, Exercise::Burst | Exercise::PrefixClose)
                && (peer
                    || self.bytes != 2042
                    || self.count
                        != if self.exercise == Exercise::Burst {
                            16
                        } else {
                            1
                        })
            {
                anyhow::bail!(
                    "burst requires initiator16x2042;prefix-close requires initiator1x2042"
                );
            }
            if self.source_port.is_some()
                && matches!(self.exercise, Exercise::Boundaries | Exercise::PrefixClose)
            {
                anyhow::bail!("dynamic correctness supports regular/burst only");
            }
        } else {
            if self.report.is_none()
                || self.exercise != Exercise::Regular
                || self.source_port.is_some()
                || self.hold
                || self.start_barrier
            {
                anyhow::bail!(
                    "measurements require --report;route/exercise/hold are correctness-only"
                );
            }
            if self.load {
                if !peer {
                    anyhow::bail!(
                        "--load is the rate/window responder;use channel rate/window/duplex to initiate"
                    );
                }
                benchmark::LoadConfig {
                    mode: benchmark::LoadMode::Peer,
                    count: self.count,
                    bytes: self.bytes,
                    window: self.window.unwrap_or(self.count.min(16)),
                    interval_us: 0,
                }
                .validate()?;
            } else if self.window.is_some() {
                anyhow::bail!("--window for peer requires --load");
            }
        }
        Ok(())
    }
}
impl Cli {
    fn validate(&self) -> anyhow::Result<()> {
        if !self.adapter.starts_with("/org/sparklink/") {
            anyhow::bail!("--adapter requires the exact current object path");
        }
        let Command::Channel { command } = &self.command;
        match command {
            Channel::Ping(p) => p.validate(false),
            Channel::Peer(p) => p.validate(true),
            Channel::Rate(r) => r
                .load
                .config(benchmark::LoadMode::Rate, r.interval_us)
                .validate(),
            Channel::Window(l) => l.config(benchmark::LoadMode::Window, 0).validate(),
            Channel::Duplex(l) => l.config(benchmark::LoadMode::Duplex, 0).validate(),
        }
    }
    async fn execute(self) -> anyhow::Result<()> {
        let conn = if self.session {
            zbus::Connection::session().await?
        } else {
            zbus::Connection::system().await?
        };
        let client = Client::new(conn, self.adapter);
        let Command::Channel { command } = self.command;
        match command {
            Channel::Ping(p) => run_pair(client, p, false).await,
            Channel::Peer(p) => run_pair(client, p, true).await,
            Channel::Rate(r) => {
                run_load(
                    client,
                    &r.load,
                    r.load.config(benchmark::LoadMode::Rate, r.interval_us),
                )
                .await
            }
            Channel::Window(l) => {
                run_load(client, &l, l.config(benchmark::LoadMode::Window, 0)).await
            }
            Channel::Duplex(l) => {
                run_load(client, &l, l.config(benchmark::LoadMode::Duplex, 0)).await
            }
        }
    }
}
async fn run_load(
    client: Client,
    args: &Load,
    config: benchmark::LoadConfig,
) -> anyhow::Result<()> {
    let fd = client.open_application_channel(&args.connection).await?;
    benchmark::run_load(fd, config, &args.report)
}
async fn run_pair(client: Client, p: Pair, peer: bool) -> anyhow::Result<()> {
    if p.check {
        if let (Some(source), Some(destination), Some(aid)) =
            (p.source_port, p.destination_port, p.aid)
        {
            client
                .cmd_dynamic_channel(
                    &p.connection,
                    peer,
                    (source, destination, aid),
                    DynamicExercise {
                        rounds: p.count as u32,
                        bytes: p.bytes,
                        hold: p.hold,
                        start_barrier: p.start_barrier,
                        mode: p.exercise.mode(),
                    },
                )
                .await
        } else {
            client
                .cmd_channel(
                    &p.connection,
                    peer,
                    p.count as u32,
                    p.bytes,
                    p.exercise.mode(),
                )
                .await
        }
    } else {
        let fd = client.open_application_channel(&p.connection).await?;
        let path = p.report.expect("validated required report");
        if p.load {
            benchmark::run_load(
                fd,
                benchmark::LoadConfig {
                    mode: benchmark::LoadMode::Peer,
                    count: p.count,
                    bytes: p.bytes,
                    window: p.window.unwrap_or(p.count.min(16)),
                    interval_us: 0,
                },
                &path,
            )
        } else {
            benchmark::run(
                fd,
                peer,
                benchmark::Config {
                    count: p.count,
                    bytes: p.bytes,
                },
                &path,
            )
        }
    }
}
pub(crate) fn main_entry() -> anyhow::Result<()> {
    let cli = Cli::parse();
    cli.validate()?;
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?
        .block_on(cli.execute())
}
#[cfg(test)]
mod tests {
    use super::*;
    fn parse(args: &[&str]) -> anyhow::Result<Cli> {
        let mut words = vec!["slktest", "--adapter", "/org/sparklink/slk0_g7", "channel"];
        words.extend_from_slice(args);
        let c = Cli::try_parse_from(words)?;
        c.validate()?;
        Ok(c)
    }
    #[test]
    fn command_tree_keeps_all_measurement_and_correctness_modes() {
        for args in [
            vec!["ping", "/link", "--report", "new.json"],
            vec!["peer", "/link", "--report", "new.json"],
            vec!["peer", "/link", "--load", "--report", "new.json"],
            vec![
                "rate",
                "/link",
                "--interval-us",
                "1000",
                "--report",
                "new.json",
            ],
            vec!["window", "/link", "--report", "new.json"],
            vec!["duplex", "/link", "--report", "new.json"],
            vec!["ping", "/link", "--check"],
            vec!["peer", "/link", "--check"],
            vec![
                "ping",
                "/link",
                "--check",
                "--count",
                "16",
                "--bytes",
                "2042",
                "--exercise",
                "burst",
                "--source-port",
                "24576",
                "--destination-port",
                "24577",
                "--aid",
                "29441",
                "--hold",
                "--start-barrier",
            ],
        ] {
            assert!(parse(&args).is_ok(), "{args:?}");
        }
    }
    #[test]
    fn invalid_modes_and_ambiguous_or_incomplete_parameters_fail_before_bus() {
        for args in [
            vec!["ping", "/link"],
            vec!["ping", "/link", "--check", "--report", "bad.json"],
            vec!["ping", "/link", "--check", "--count", "21"],
            vec!["ping", "/link", "--check", "--source-port", "1"],
            vec!["ping", "/link", "--check", "--hold"],
            vec!["ping", "/link", "--check", "--start-barrier"],
            vec!["peer", "/link", "--report", "bad.json", "--start-barrier"],
            vec!["peer", "/link", "--check", "--exercise", "burst"],
            vec!["ping", "/link", "--load", "--report", "bad.json"],
            vec!["peer", "/link", "--check", "--load"],
            vec!["window", "/link", "--window", "0", "--report", "bad.json"],
            vec![
                "rate",
                "/link",
                "--interval-us",
                "18446744073709551615",
                "--report",
                "bad.json",
            ],
            vec!["ping", "/link", "--count", "0", "--report", "bad.json"],
            vec!["peer", "/link", "--window", "4", "--report", "bad.json"],
        ] {
            assert!(parse(&args).is_err(), "{args:?}");
        }
    }
}
