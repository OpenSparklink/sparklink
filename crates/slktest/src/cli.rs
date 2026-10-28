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
    long_about = "Application tests on ordinary delegated channel fds. Basic CUTC or explicitly negotiated basic dynamic load channels; dynamic ping measurements and protected load modes are unsupported. Not a Host, packet capture, kernel selftest, formal prover or performance qualification. Load modes require stdin start after both Armed, then finish after both Quiescent; each control wait is bounded. Dynamic load channels require explicit active/passive negotiation roles independent of traffic direction."
)]
struct Cli {
    /// Use a private session bus for integration tests, never hardware qualification.
    #[arg(long, global = true)]
    session: bool,
    /// Current immutable adapter object path, selected and managed with slctl.
    #[arg(long)]
    adapter: String,
    /// Minimum kernel-enforced mechanism for fixed --check: 0 none,1 encryption,2 numeric.
    #[arg(long, global=true, default_value_t=0,value_parser=clap::value_parser!(u32).range(0..=2))]
    security: u32,
    /// Fixed regular/boundaries --check only: verify kernel receipt scope and current mechanism.
    #[arg(long, global = true)]
    message_security: bool,
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
    #[command(flatten)]
    channel: ChannelSelection,
    /// Dynamic correctness: keep fd reference until an explicit close line.
    #[arg(long,requires_all=["source_port","check"])]
    hold: bool,
    /// Dynamic correctness: after real negotiation, await exact start line (30s).
    #[arg(long, requires_all=["source_port", "check"])]
    start_barrier: bool,
}
#[derive(Clone, Copy, PartialEq, Eq, ValueEnum)]
enum ChannelRole {
    Active,
    Passive,
}
#[derive(Args)]
struct ChannelSelection {
    /// Dynamic routing only with all three nonzero fields; never a TCID or identity.
    #[arg(long,requires_all=["destination_port","aid"])]
    source_port: Option<u16>,
    #[arg(long,requires_all=["source_port","aid"])]
    destination_port: Option<u16>,
    #[arg(long,requires_all=["source_port","destination_port"])]
    aid: Option<u16>,
    /// Dynamic load negotiation role, independent of which endpoint sends business data.
    #[arg(long, value_enum, requires = "source_port")]
    channel_role: Option<ChannelRole>,
}
impl ChannelSelection {
    fn route(
        &self,
        bytes: usize,
        correctness_peer: Option<bool>,
    ) -> anyhow::Result<Option<channel::DynamicRoute>> {
        let (Some(source_port), Some(destination_port), Some(aid)) =
            (self.source_port, self.destination_port, self.aid)
        else {
            anyhow::ensure!(
                self.source_port.is_none()
                    && self.destination_port.is_none()
                    && self.aid.is_none()
                    && self.channel_role.is_none(),
                "complete dynamic route required"
            );
            return Ok(None);
        };
        let passive = if let Some(peer) = correctness_peer {
            anyhow::ensure!(
                self.channel_role.is_none(),
                "--check derives negotiation role from ping/peer"
            );
            peer
        } else {
            self.channel_role.ok_or_else(|| {
                anyhow::anyhow!("dynamic load requires --channel-role active|passive")
            })? == ChannelRole::Passive
        };
        let route = channel::DynamicRoute {
            source_port,
            destination_port,
            aid,
            passive,
        };
        route.request(bytes)?;
        Ok(Some(route))
    }
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
    #[command(flatten)]
    channel: ChannelSelection,
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
    fn validate(&self, mode: benchmark::LoadMode, interval_us: u64) -> anyhow::Result<()> {
        self.config(mode, interval_us).validate()?;
        self.channel.route(self.bytes, None)?;
        Ok(())
    }
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
            self.channel.route(self.bytes, Some(peer))?;
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
            if self.channel.source_port.is_some()
                && matches!(self.exercise, Exercise::Boundaries | Exercise::PrefixClose)
            {
                anyhow::bail!("dynamic correctness supports regular/burst only");
            }
        } else {
            if self.report.is_none()
                || self.exercise != Exercise::Regular
                || self.hold
                || self.start_barrier
            {
                anyhow::bail!("measurements require --report;exercise/hold are correctness-only");
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
                self.channel.route(self.bytes, None)?;
            } else if self.window.is_some() {
                anyhow::bail!("--window for peer requires --load");
            } else if self.channel.source_port.is_some() || self.channel.channel_role.is_some() {
                anyhow::bail!("dynamic measurements require rate/window/duplex or peer --load");
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
        if self.message_security {
            match command {
                Channel::Ping(p) | Channel::Peer(p)
                    if p.check
                        && p.channel.source_port.is_none()
                        && matches!(p.exercise, Exercise::Regular | Exercise::Boundaries) => {}
                _ => anyhow::bail!(
                    "--message-security requires fixed regular/boundaries --check; no performance or dynamic qualification"
                ),
            }
        }
        if self.security != 0 {
            match command {
                Channel::Ping(p) | Channel::Peer(p)
                    if p.check
                        && p.channel.source_port.is_none()
                        && p.channel.destination_port.is_none()
                        && p.channel.aid.is_none() => {}
                _ => anyhow::bail!(
                    "--security currently requires a fixed --check exercise; protected performance reports/dynamic modes are not supported"
                ),
            }
        }
        match command {
            Channel::Ping(p) => p.validate(false),
            Channel::Peer(p) => p.validate(true),
            Channel::Rate(r) => r.load.validate(benchmark::LoadMode::Rate, r.interval_us),
            Channel::Window(l) => l.validate(benchmark::LoadMode::Window, 0),
            Channel::Duplex(l) => l.validate(benchmark::LoadMode::Duplex, 0),
        }
    }
    async fn execute(self) -> anyhow::Result<()> {
        let conn = if self.session {
            zbus::Connection::session().await?
        } else {
            zbus::Connection::system().await?
        };
        let client = Client::new(conn, self.adapter)
            .requiring_security(self.security)?
            .observing_message_security(self.message_security);
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
    let route = args.channel.route(args.bytes, None)?;
    let fd = client
        .open_application_channel(&args.connection, route, args.bytes)
        .await?;
    benchmark::run_load(fd, config, &args.report, route)
}
async fn run_pair(client: Client, p: Pair, peer: bool) -> anyhow::Result<()> {
    if p.check {
        if let (Some(source), Some(destination), Some(aid)) = (
            p.channel.source_port,
            p.channel.destination_port,
            p.channel.aid,
        ) {
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
        let route = p.channel.route(p.bytes, None)?;
        let fd = client
            .open_application_channel(&p.connection, route, p.bytes)
            .await?;
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
                route,
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
    fn fixed_correctness_requires_explicit_supported_security_without_downgrade() {
        for level in ["0", "1", "2"] {
            assert!(parse(&["ping", "/link", "--check", "--security", level]).is_ok());
            assert!(parse(&["peer", "/link", "--check", "--security", level]).is_ok());
        }
        for args in [
            vec!["ping", "/link", "--check", "--security", "3"],
            vec!["ping", "/link", "--security", "1", "--report", "new.json"],
            vec!["window", "/link", "--security", "2", "--report", "new.json"],
            vec![
                "peer",
                "/link",
                "--check",
                "--security",
                "2",
                "--source-port",
                "10",
                "--destination-port",
                "11",
                "--aid",
                "12",
            ],
        ] {
            assert!(parse(&args).is_err(), "{args:?}");
        }
    }
    #[test]
    fn receipt_observation_requires_fixed_correctness_and_no_false_performance() {
        for role in ["ping", "peer"] {
            assert!(parse(&[role, "/link", "--check", "--message-security"]).is_ok());
            assert!(
                parse(&[
                    role,
                    "/link",
                    "--check",
                    "--message-security",
                    "--security",
                    "2",
                    "--exercise",
                    "boundaries"
                ])
                .is_ok()
            );
        }
        for args in [
            vec![
                "ping",
                "/link",
                "--message-security",
                "--report",
                "new.json",
            ],
            vec![
                "window",
                "/link",
                "--message-security",
                "--report",
                "new.json",
            ],
            vec![
                "ping",
                "/link",
                "--message-security",
                "--check",
                "--exercise",
                "burst",
                "--count",
                "16",
                "--bytes",
                "2042",
            ],
            vec![
                "peer",
                "/link",
                "--message-security",
                "--check",
                "--source-port",
                "10",
                "--destination-port",
                "11",
                "--aid",
                "12",
            ],
        ] {
            assert!(parse(&args).is_err(), "{args:?}");
        }
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
    fn dynamic_load_requires_explicit_negotiation_role_independent_of_data_role() {
        for command in ["window", "rate", "duplex", "peer"] {
            for role in ["active", "passive"] {
                let mut args = vec![
                    command,
                    "/link",
                    "--report",
                    "new.json",
                    "--source-port",
                    "24576",
                    "--destination-port",
                    "24577",
                    "--aid",
                    "29441",
                    "--channel-role",
                    role,
                ];
                if command == "rate" {
                    args.extend(["--interval-us", "1000"]);
                }
                if command == "peer" {
                    args.push("--load");
                }
                assert!(parse(&args).is_ok(), "{args:?}");
                let mut missing_role = args.clone();
                let i = missing_role
                    .iter()
                    .position(|x| *x == "--channel-role")
                    .unwrap();
                missing_role.drain(i..i + 2);
                assert!(parse(&missing_role).is_err(), "{missing_role:?}");
                for (key, value) in [
                    ("--source-port", "0"),
                    ("--destination-port", "0"),
                    ("--aid", "0"),
                    ("--channel-role", "guess"),
                ] {
                    let mut bad = args.clone();
                    let i = bad.iter().position(|x| *x == key).unwrap();
                    bad[i + 1] = value;
                    assert!(parse(&bad).is_err(), "{bad:?}");
                }
                let mut protected = args.clone();
                protected.extend(["--security", "1"]);
                assert!(parse(&protected).is_err());
            }
        }
        for role in ["ping", "peer"] {
            let mut args = vec![
                role,
                "/link",
                "--report",
                "new.json",
                "--source-port",
                "10",
                "--destination-port",
                "11",
                "--aid",
                "12",
                "--channel-role",
                "passive",
            ];
            assert!(
                parse(&args).is_err(),
                "schema1 dynamic measurement is unsupported"
            );
            args.retain(|x| !["--report", "new.json"].contains(x));
            args.push("--check");
            assert!(
                parse(&args).is_err(),
                "old correctness role must not change"
            );
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
