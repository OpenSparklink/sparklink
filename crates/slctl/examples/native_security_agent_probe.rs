//! Explicit disposable-VM Agent witness, never a default daemon policy.
//! No keys, wire packets, cryptography or simulated kernel results.
use anyhow::{Context, bail, ensure};
use clap::{Parser, ValueEnum};
use serde_json::json;
use std::{
    collections::BTreeMap,
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::sync::{Mutex, mpsc};
use zbus::{Connection, fdo::DBusProxy, zvariant::OwnedObjectPath};

const METHOD: &str = "sdk111-no-mitm";
const SERVICE: &str = "org.sparklink";
const AGENT: &str = "/test/explicit_reference_agent";
type Prompt = (String, u64, u64, u64, u16, u8, u8, String, String, u64);
type Info = (u64, u64, u16, u8, u8, String, bool, bool);
type Raw = (
    u64,
    u64,
    u64,
    u32,
    i32,
    u64,
    bool,
    bool,
    u32,
    i32,
    u32,
    u8,
    i32,
);
type Expected = Arc<Mutex<BTreeMap<String, (Info, u64, u64)>>>;
#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
enum Mode {
    Approve,
    Reject,
    Timeout,
    Cancel,
    AgentExit,
    CallerExit,
}
#[derive(Parser)]
struct Args {
    #[arg(long, num_args = 2, required = true)]
    connections: Vec<String>,
    #[arg(long, value_enum)]
    mode: Mode,
    #[arg(long, default_value_t = 5000)]
    timeout_ms: u32,
    #[arg(long, default_value_t = 0)]
    approval_delay_ms: u64,
}
fn wall() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos() as u64
}
struct Agent {
    owner: String,
    expected: Expected,
    yes: bool,
    delay: Duration,
    seen: mpsc::UnboundedSender<Prompt>,
}
#[zbus::interface(name = "org.sparklink.Agent")]
impl Agent {
    async fn authorize_reference_security(
        &self,
        prompt: Prompt,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<bool> {
        if header.sender().map(|n| n.as_str()) != Some(self.owner.as_str()) {
            return Err(zbus::fdo::Error::AccessDenied(
                "not the original daemon".into(),
            ));
        }
        let expected = self.expected.lock().await;
        let (info, id, deadline) = expected.get(&prompt.0).ok_or_else(|| {
            zbus::fdo::Error::InvalidArgs("not an explicitly selected connection".into())
        })?;
        if (
            prompt.1,
            prompt.2,
            prompt.3,
            prompt.4,
            prompt.5,
            prompt.6,
            prompt.7.as_str(),
            prompt.8.as_str(),
            prompt.9,
        ) != (
            *id,
            info.0,
            info.1,
            info.2,
            info.3,
            info.4,
            info.5.as_str(),
            METHOD,
            *deadline,
        ) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "identity/method/original deadline mismatch".into(),
            ));
        }
        drop(expected);
        println!(
            "{}",
            json!({"stage":"agent_callback","wall_ns":wall(),"prompt":prompt,"daemon_owner":self.owner})
        );
        self.seen
            .send(prompt)
            .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?;
        tokio::time::sleep(self.delay).await;
        Ok(self.yes)
    }
}
async fn security<'a>(c: &Connection, path: &'a str) -> zbus::Result<zbus::Proxy<'a>> {
    zbus::Proxy::new(c, SERVICE, path, "org.sparklink.Security").await
}
async fn link<'a>(c: &Connection, path: &'a str) -> zbus::Result<zbus::Proxy<'a>> {
    zbus::Proxy::new(c, SERVICE, path, "org.sparklink.Connection").await
}
async fn read(c: &Connection, path: &str, id: u64) -> anyhow::Result<Raw> {
    Ok(link(c, path)
        .await?
        .call("GetReferenceSecurityResult", &(id,))
        .await?)
}
fn observation(path: &str, raw: &Raw) -> serde_json::Value {
    json!({"stage":"policy_result","wall_ns":wall(),"path":path,"request_id":raw.0,"generation":raw.1,
        "lifetime":raw.2,"phase":raw.3,"error":raw.4,"deadline_monotonic_ns":raw.5,"agent_approved":raw.6,
        "native_admitted":raw.7,"kernel_state":raw.8,"kernel_error":raw.9,"kernel_flags":raw.10,
        "kernel_status":raw.11,"cleanup_error":raw.12})
}
fn unsupported(result: zbus::Result<zbus::Message>) -> anyhow::Result<()> {
    match result {
        Err(zbus::Error::MethodError(n, _, _))
            if n.as_str() == "org.freedesktop.DBus.Error.NotSupported" =>
        {
            Ok(())
        }
        other => bail!("expected explicit NotSupported, got {other:?}"),
    }
}
fn controller_path(path: &str) -> anyhow::Result<&str> {
    let (controller, peer) = path
        .split_once("/peer_t")
        .context("canonical peer parent")?;
    let (peer, lifetime) = peer
        .split_once("/link_")
        .context("canonical lifetime child")?;
    let (kind, address) = peer.split_once('_').context("typed peer address")?;
    let (index, generation) = controller
        .strip_prefix("/org/sparklink/slk")
        .context("controller prefix")?
        .split_once("_g")
        .context("controller generation")?;
    ensure!(
        !index.is_empty()
            && index.bytes().all(|b| b.is_ascii_digit())
            && index.parse::<u16>().is_ok()
            && generation.parse::<u64>().is_ok_and(|n| n > 0)
            && kind.len() == 2
            && address.len() == 12
            && lifetime.len() == 16
            && [kind, address, lifetime]
                .iter()
                .all(|s| s.bytes().all(|b| b.is_ascii_hexdigit()))
            && u64::from_str_radix(lifetime, 16).is_ok_and(|n| n > 0),
        "canonical connection identity required"
    );
    Ok(controller)
}

async fn execute(args: Args) -> anyhow::Result<()> {
    ensure!(
        args.connections.len() == 2 && args.connections[0] != args.connections[1],
        "two distinct logical connection objects required"
    );
    ensure!(
        (1..=5000).contains(&args.timeout_ms),
        "bounded original deadline required"
    );
    ensure!(
        args.approval_delay_ms <= 6000,
        "bounded test Agent required"
    );
    match args.mode {
        Mode::Approve | Mode::Reject => ensure!(
            args.approval_delay_ms == 0,
            "immediate explicit decision required"
        ),
        Mode::Timeout => ensure!(
            args.approval_delay_ms > u64::from(args.timeout_ms),
            "approval must be late"
        ),
        _ => ensure!(
            args.approval_delay_ms >= 500 && args.timeout_ms >= 1000,
            "observable live callback required"
        ),
    }
    let process = std::fs::read_to_string("/proc/self/status")?;
    for name in ["Uid:", "Gid:"] {
        let values = process
            .lines()
            .find(|v| v.starts_with(name))
            .context("missing identity")?
            .split_whitespace()
            .skip(1)
            .map(str::parse::<u32>)
            .collect::<Result<Vec<_>, _>>()?;
        ensure!(
            values.len() == 4
                && values
                    .iter()
                    .all(|v| *v == if name == "Uid:" { 1000 } else { 1002 }),
            "actual ordinary control user required"
        );
    }
    for name in ["CapEff:", "CapPrm:", "CapInh:", "CapAmb:"] {
        ensure!(
            u64::from_str_radix(
                process
                    .lines()
                    .find(|v| v.starts_with(name))
                    .context("missing caps")?
                    .split_whitespace()
                    .nth(1)
                    .context("caps")?,
                16
            )? == 0,
            "no process capabilities allowed"
        );
    }
    // Connect to the actual isolated guest SYSTEM bus with EXTERNAL credentials.
    let requester = Connection::system().await?;
    let bus = DBusProxy::new(&requester).await?;
    let daemon = bus.get_name_owner(SERVICE.try_into()?).await?;
    ensure!(
        bus.get_connection_unix_user(daemon.as_str().try_into()?)
            .await?
            == 0,
        "root daemon required"
    );
    let daemon_pid = bus
        .get_connection_unix_process_id(daemon.as_str().try_into()?)
        .await?;
    let mut infos = Vec::new();
    let mut security_paths = Vec::new();
    for path in &args.connections {
        let info: Info = link(&requester, path).await?.call("GetInfo", &()).await?;
        ensure!(
            info.0 > 0 && info.1 > 0 && info.6 && info.7 && info.3 <= 1,
            "canonical known connected reference required"
        );
        let controller = controller_path(path)?;
        ensure!(
            controller.ends_with(&format!("_g{}", info.0)),
            "controller generation mismatch"
        );
        let security_path = format!("{controller}/security");
        unsupported(
            link(&requester, path)
                .await?
                .call_method("AllocateReferenceSecurity", &(args.timeout_ms,))
                .await,
        )?;
        unsupported(
            security(&requester, &security_path)
                .await?
                .call_method(
                    "RegisterAgent",
                    &(OwnedObjectPath::try_from(AGENT)?, "unknown"),
                )
                .await,
        )?;
        security_paths.push(security_path);
        infos.push(info);
    }
    ensure!(infos[0].3 != infos[1].3, "opposite physical roles required");
    println!(
        "{}",
        json!({"stage":"probe_identity","wall_ns":wall(),"process_status":process,"requester":requester.unique_name().unwrap().as_str(),"daemon_owner":daemon.as_str(),"daemon_pid":daemon_pid,"mode":format!("{:?}",args.mode),"connections":args.connections,"infos":infos,"missing_agent_refusals":2,"unknown_registration_refusals":2})
    );
    let expected: Expected = Arc::new(Mutex::new(BTreeMap::new()));
    let (seen, mut incoming) = mpsc::unbounded_channel();
    let agent = Connection::system().await?;
    agent
        .object_server()
        .at(
            AGENT,
            Agent {
                owner: daemon.to_string(),
                expected: expected.clone(),
                yes: args.mode != Mode::Reject,
                delay: Duration::from_millis(args.approval_delay_ms),
                seen,
            },
        )
        .await?;
    for path in &security_paths {
        security(&agent, path)
            .await?
            .call::<_, _, ()>(
                "RegisterAgent",
                &(OwnedObjectPath::try_from(AGENT)?, METHOD),
            )
            .await?;
    }
    let mut ids = Vec::new();
    let mut deadlines = Vec::new();
    for (path, info) in args.connections.iter().zip(&infos) {
        let start = wall();
        let id: u64 = link(&requester, path)
            .await?
            .call("AllocateReferenceSecurity", &(args.timeout_ms,))
            .await?;
        let raw = read(&requester, path, id).await?;
        ensure!(
            raw.0 == id && raw.1 == info.0 && raw.2 == info.1 && raw.3 == 1 && !raw.6 && !raw.7,
            "original allocation required"
        );
        expected
            .lock()
            .await
            .insert(path.clone(), (info.clone(), id, raw.5));
        unsupported(
            link(&requester, path)
                .await?
                .call_method("BeginReferenceSecurity", &(id, "unknown"))
                .await,
        )?;
        println!(
            "{}",
            json!({"stage":"allocated","path":path,"request_id":id,"generation":info.0,"lifetime":info.1,"start_wall_ns":start,"wall_ns":wall(),"deadline_monotonic_ns":raw.5,"timeout_ms":args.timeout_ms,"unknown_begin_refused":true})
        );
        ids.push(id);
        deadlines.push(raw.5);
    }
    // Arm passive T first, then the existing physical G Session starts relays.
    for role in [1, 0] {
        let i = infos.iter().position(|v| v.3 == role).unwrap();
        link(&requester, &args.connections[i])
            .await?
            .call::<_, _, ()>("BeginReferenceSecurity", &(ids[i], METHOD))
            .await?;
    }
    let mut callbacks = Vec::new();
    for _ in 0..2 {
        callbacks.push(
            tokio::time::timeout(Duration::from_secs(2), incoming.recv())
                .await?
                .context("Agent callback absent")?,
        );
    }
    ensure!(
        callbacks[0].0 != callbacks[1].0,
        "two distinct real Agent callbacks required"
    );
    if args.mode == Mode::CallerExit {
        // Old caller cannot query after death. A distinct caller must be denied
        // access to old IDs and may only allocate fresh non-native operations.
        drop(bus);
        requester.close().await?;
        let replacement = Connection::system().await?;
        for (i, path) in args.connections.iter().enumerate() {
            let until = Instant::now() + Duration::from_secs(2);
            let id = loop {
                if let Ok(id) = link(&replacement, path)
                    .await?
                    .call::<_, _, u64>("AllocateReferenceSecurity", &(1000u32,))
                    .await
                {
                    break id;
                }
                ensure!(
                    Instant::now() < until,
                    "caller-loss cleanup did not converge before original deadline"
                );
                tokio::time::sleep(Duration::from_millis(5)).await;
            };
            ensure!(id > ids[i], "fresh author namespace required");
            match link(&replacement, path)
                .await?
                .call_method("GetReferenceSecurityResult", &(ids[i],))
                .await
            {
                Err(zbus::Error::MethodError(n, _, _))
                    if n.as_str() == "org.freedesktop.DBus.Error.AccessDenied" => {}
                other => bail!("old caller result must stay private: {other:?}"),
            }
            ensure!(
                link(&replacement, path)
                    .await?
                    .call::<_, _, bool>("CancelReferenceSecurity", &(id,))
                    .await?,
                "cancel fresh allocated request"
            );
            ensure!(
                read(&replacement, path, id).await?.3 == 6,
                "fresh request cancelled without native work"
            );
            println!(
                "{}",
                json!({"stage":"caller_loss_cleanup","path":path,"old_request":ids[i],"new_request":id,"old_result_access_denied":true,"fresh_cancelled":true,"wall_ns":wall()})
            );
        }
    } else {
        if args.mode == Mode::AgentExit {
            agent.close().await?;
        }
        if args.mode == Mode::Cancel {
            for (path, id) in args.connections.iter().zip(&ids) {
                ensure!(
                    link(&requester, path)
                        .await?
                        .call::<_, _, bool>("CancelReferenceSecurity", &(*id,))
                        .await?,
                    "withdraw original request"
                );
            }
        }
        let expected_phase = match args.mode {
            Mode::Approve => 4,
            Mode::Reject => 5,
            Mode::Timeout => 7,
            Mode::Cancel => 6,
            Mode::AgentExit => 10,
            _ => unreachable!(),
        };
        let until = Instant::now() + Duration::from_secs(7);
        let mut results = Vec::new();
        for (i, path) in args.connections.iter().enumerate() {
            let raw = loop {
                let raw = read(&requester, path, ids[i]).await?;
                if raw.3 >= 4 {
                    break raw;
                }
                ensure!(
                    Instant::now() < until,
                    "bounded observer deadline exhausted"
                );
                tokio::time::sleep(Duration::from_millis(2)).await;
            };
            ensure!(
                raw.0 == ids[i]
                    && raw.1 == infos[i].0
                    && raw.2 == infos[i].1
                    && raw.5 == deadlines[i],
                "original operation identity required"
            );
            println!("{}", observation(path, &raw));
            ensure!(
                raw.3 == expected_phase,
                "unexpected policy phase{}, expected{expected_phase}",
                raw.3
            );
            if args.mode == Mode::Approve {
                ensure!(
                    raw.6
                        && raw.7
                        && raw.8 == 9
                        && raw.4 == 0
                        && raw.9 == 0
                        && raw.11 == 0
                        && raw.12 == 0,
                    "actual native success required, policy yes insufficient"
                );
            } else {
                ensure!(
                    !raw.7 && raw.8 == 0,
                    "negative pre-admission path must not enter native mechanism"
                );
            }
            results.push(raw);
        }
        if matches!(args.mode, Mode::Cancel | Mode::Timeout) {
            tokio::time::sleep(Duration::from_millis(args.approval_delay_ms + 20)).await;
            for (i, path) in args.connections.iter().enumerate() {
                ensure!(
                    serde_json::to_value(read(&requester, path, ids[i]).await?)?
                        == serde_json::to_value(results[i])?,
                    "late approval must not rewrite a terminal result"
                );
            }
        }
    }
    println!(
        "{}",
        json!({"stage":"probe_complete","wall_ns":wall(),"status":"PENDING_INDEPENDENT_USB_AND_BUSINESS_CORROBORATION","mode":format!("{:?}",args.mode),"physical_recovery_acceptance":false,"authenticated_identity":false,"bond":false})
    );
    Ok(())
}
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tokio::time::timeout(Duration::from_secs(15), execute(Args::parse())).await?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn captured_peer_lifetime_shape_resolves_its_controller() {
        // Shape from the first real failure; peer identity sanitized.
        assert_eq!(
            controller_path("/org/sparklink/slk0_g1/peer_t00_010203040506/link_0000000000000001")
                .unwrap(),
            "/org/sparklink/slk0_g1"
        );
        assert_eq!(
            controller_path("/org/sparklink/slk12_g23/peer_t01_112233445566/link_0000000000000013")
                .unwrap(),
            "/org/sparklink/slk12_g23"
        );
    }
    #[test]
    fn old_alias_and_malformed_identity_cannot_select_another_controller() {
        for path in [
            "/org/sparklink/slk0_g1/connection_1",
            "/org/sparklink/slk0_g0/peer_t00_010203040506/link_0000000000000001",
            "/org/sparklink/slk0_g1/peer_t00_010203040506/link_0000000000000000",
            "/org/sparklink/slk0_g1/peer_t00_010203040506/link_0000000000000001/other",
            "/org/sparklink/slk0_g1/peer_t00_010203040506/link_bad",
        ] {
            assert!(controller_path(path).is_err(), "accepted{path}");
        }
    }
}
