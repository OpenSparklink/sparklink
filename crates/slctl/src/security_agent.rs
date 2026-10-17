// SPDX-License-Identifier: GPL-2.0-only
//! Explicit human consent client. No wire/crypto engine or automatic approval.
use anyhow::{Context, bail, ensure};
use std::{io::Read, os::unix::fs::OpenOptionsExt, sync::Arc, time::Duration};
use tokio::{
    io::unix::AsyncFd,
    sync::{Semaphore, mpsc, oneshot, watch},
};
use zbus::{Connection, export::ordered_stream::OrderedStreamExt, zvariant::OwnedObjectPath};

const SERVICE: &str = "org.sparklink";
pub(crate) const METHOD: &str = "sdk111-no-mitm";
const NUMERIC_METHOD: &str = "sdk111-numeric-comparison";
fn supported(method: &str) -> bool {
    matches!(method, METHOD | NUMERIC_METHOD)
}
const AGENT_PATH: &str = "/org/sparklink/slctl/agent";
type Info = (u64, u64, u16, u8, u8, String, bool, bool);
type Prompt = (String, u64, u64, u64, u16, u8, u8, String, String, u64);

/// D-Bus observation, not an authenticated identity or a live security property.
#[derive(Debug, serde::Deserialize, serde::Serialize, zbus::zvariant::Type)]
struct Observation {
    request_id: u64,
    generation: u64,
    lifetime: u64,
    phase: u32,
    error: i32,
    deadline_monotonic_ns: u64,
    agent_approved: bool,
    native_admitted: bool,
    kernel_state: u32,
    kernel_error: i32,
    kernel_flags: u32,
    kernel_status: u8,
    cleanup_error: i32,
}

fn monotonic_ns() -> anyhow::Result<u64> {
    let mut time = nix::libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: live writable timespec; same explicit clock as native submit v2.
    if unsafe { nix::libc::clock_gettime(nix::libc::CLOCK_MONOTONIC, &mut time) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    u64::try_from(time.tv_sec)
        .ok()
        .and_then(|v| v.checked_mul(1_000_000_000))
        .and_then(|v| v.checked_add(time.tv_nsec as u64))
        .context("monotonic clock overflow")
}
pub(crate) fn remaining(deadline: u64) -> anyhow::Result<Duration> {
    let ns = deadline.saturating_sub(monotonic_ns()?);
    ensure!(ns > 0, "original request deadline expired");
    Ok(Duration::from_nanos(ns))
}

/// Original unique owner, with subscription established before lookup. Never
/// follow a replacement daemon, even if it reuses paths and request numbers.
pub(crate) struct Daemon {
    owner: String,
    lost: watch::Receiver<bool>,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for Daemon {
    fn drop(&mut self) {
        self.task.abort();
    }
}
impl Daemon {
    pub(crate) async fn pin(conn: &Connection) -> anyhow::Result<Self> {
        let bus = zbus::fdo::DBusProxy::new(conn).await?;
        let mut changes = bus
            .receive_name_owner_changed_with_args(&[(0, SERVICE)])
            .await?;
        let owner = bus.get_name_owner(SERVICE.try_into()?).await?.to_string();
        let (tx, lost) = watch::channel(false);
        let task = tokio::spawn(async move {
            // Any transition (including release/reacquire by the same owner)
            // invalidates this client's scope. A closed stream also fails closed.
            let _ = changes.next().await;
            tx.send_replace(true);
        });
        Ok(Self { owner, lost, task })
    }
    pub(crate) fn owner(&self) -> &str {
        &self.owner
    }
    pub(crate) fn loss(&self) -> watch::Receiver<bool> {
        self.lost.clone()
    }
    pub(crate) async fn proxy(
        &self,
        conn: &Connection,
        path: &str,
        interface: &str,
    ) -> anyhow::Result<zbus::Proxy<'static>> {
        ensure!(!*self.lost.borrow(), "original daemon ownership lost");
        Ok(zbus::Proxy::new(
            conn,
            self.owner.clone(),
            path.to_owned(),
            interface.to_owned(),
        )
        .await?)
    }
}

pub(crate) fn controller_generation(controller: &str) -> anyhow::Result<u64> {
    let (index, generation) = controller
        .strip_prefix("/org/sparklink/slk")
        .and_then(|v| v.split_once("_g"))
        .context("canonical controller required")?;
    let parsed_index: u32 = index.parse()?;
    let parsed_generation: u64 = generation.parse()?;
    ensure!(
        controller == format!("/org/sparklink/slk{parsed_index}_g{parsed_generation}")
            && parsed_generation > 0,
        "canonical controller required"
    );
    Ok(parsed_generation)
}
fn validate_identity(controller: &str, path: &str, info: &Info) -> anyhow::Result<()> {
    let generation = controller_generation(controller)?;
    ensure!(
        info.0 == generation && info.1 > 0 && info.3 <= 1 && info.4 <= 1 && info.6 && info.7,
        "known connected original generation/lifetime required"
    );
    let parts: Vec<_> = info.5.split(':').collect();
    ensure!(
        parts.len() == 6
            && parts
                .iter()
                .all(|p| p.len() == 2 && p.bytes().all(|c| c.is_ascii_hexdigit())),
        "invalid peer address"
    );
    let expected = format!(
        "{controller}/peer_t{:02x}_{}/link_{:016x}",
        info.4,
        parts.join("").to_ascii_lowercase(),
        info.1
    );
    ensure!(
        path == expected,
        "canonical full connection identity required"
    );
    Ok(())
}
fn validate_prompt(
    controller: &str,
    prompt: &Prompt,
    info: &Info,
    method: &str,
) -> anyhow::Result<()> {
    validate_identity(controller, &prompt.0, info)?;
    ensure!(
        prompt.1 > 0
            && (prompt.2, prompt.3, prompt.4, prompt.5, prompt.6, &prompt.7)
                == (info.0, info.1, info.2, info.3, info.4, &info.5)
            && supported(method)
            && prompt.8 == method,
        "prompt identity or method mismatch"
    );
    let duration = remaining(prompt.9)?;
    ensure!(
        duration <= Duration::from_secs(5),
        "unbounded prompt deadline"
    );
    Ok(())
}
#[derive(Clone, Copy, Debug)]
enum DecisionKind {
    Consent,
    Numeric(u32),
}
struct Pending {
    prompt: Prompt,
    kind: DecisionKind,
    reply: oneshot::Sender<bool>,
}
struct Agent {
    method: String,
    controller: String,
    owner: String,
    lost: watch::Receiver<bool>,
    pending: mpsc::Sender<Pending>,
    slot: Arc<Semaphore>,
}
impl Agent {
    async fn decide(
        &self,
        prompt: Prompt,
        kind: DecisionKind,
        conn: &Connection,
        header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<bool> {
        if let DecisionKind::Numeric(code) = kind
            && (self.method != NUMERIC_METHOD || code >= 1_000_000)
        {
            return Err(zbus::fdo::Error::InvalidArgs(
                "invalid numeric method/code".into(),
            ));
        }
        if header.sender().map(|s| s.as_str()) != Some(self.owner.as_str()) || *self.lost.borrow() {
            return Err(zbus::fdo::Error::AccessDenied(
                "not the original daemon owner".into(),
            ));
        }
        let Ok(_permit) = self.slot.clone().try_acquire_owned() else {
            return Ok(false);
        };
        let verify = async {
            let proxy = zbus::Proxy::new(
                conn,
                self.owner.as_str(),
                prompt.0.as_str(),
                "org.sparklink.Connection",
            )
            .await?;
            let info: Info = proxy.call("GetInfo", &()).await?;
            validate_prompt(&self.controller, &prompt, &info, &self.method)?;
            anyhow::Ok(())
        };
        let Ok(budget) = remaining(prompt.9) else {
            return Ok(false);
        };
        if !matches!(
            tokio::time::timeout(budget.min(Duration::from_secs(5)), verify).await,
            Ok(Ok(()))
        ) {
            return Ok(false);
        }
        let (reply, result) = oneshot::channel();
        let deadline = prompt.9;
        if self
            .pending
            .try_send(Pending {
                prompt,
                kind,
                reply,
            })
            .is_err()
        {
            return Ok(false);
        }
        let Ok(budget) = remaining(deadline) else {
            return Ok(false);
        };
        let mut lost = self.lost.clone();
        let approved = tokio::select! {biased;
            _ = lost.changed() => false,
            result = tokio::time::timeout(budget, result) => matches!(result, Ok(Ok(true))),
        };
        Ok(approved && !*lost.borrow() && remaining(deadline).is_ok())
    }
}
#[zbus::interface(name = "org.sparklink.Agent")]
impl Agent {
    async fn authorize_reference_security(
        &self,
        prompt: Prompt,
        #[zbus(connection)] conn: &Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<bool> {
        self.decide(prompt, DecisionKind::Consent, conn, header)
            .await
    }
    async fn confirm_numeric_comparison(
        &self,
        prompt: Prompt,
        code: u32,
        #[zbus(connection)] conn: &Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<bool> {
        self.decide(prompt, DecisionKind::Numeric(code), conn, header)
            .await
    }
}

/// A separate open file description avoids changing the shell's shared stdin
/// flags. AsyncFd keeps D-Bus and signals live while waiting for human input.
pub(crate) struct Input {
    fd: AsyncFd<std::fs::File>,
    bytes: Vec<u8>,
}
impl Input {
    pub(crate) fn stdin() -> anyhow::Result<Self> {
        let fd = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(nix::libc::O_NONBLOCK | nix::libc::O_CLOEXEC)
            .open("/proc/self/fd/0")?;
        Ok(Self {
            fd: AsyncFd::new(fd).context("Agent requires a pollable terminal or pipe")?,
            bytes: Vec::new(),
        })
    }
    pub(crate) fn discard_before_prompt(&mut self) -> anyhow::Result<()> {
        self.bytes.clear();
        let mut consumed = 0usize;
        let mut buffer = [0u8; 256];
        loop {
            match self.fd.get_ref().read(&mut buffer) {
                Ok(0) => bail!("Agent input closed"),
                Ok(n) => {
                    consumed += n;
                    ensure!(consumed <= 4096, "excessive pre-prompt input");
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => return Ok(()),
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => (),
                Err(e) => return Err(e.into()),
            }
        }
    }
    pub(crate) async fn line(&mut self) -> anyhow::Result<Option<String>> {
        loop {
            if let Some(end) = self.bytes.iter().position(|&b| b == b'\n') {
                let line = self.bytes.drain(..=end).collect::<Vec<_>>();
                return Ok(Some(String::from_utf8(line)?.trim().to_owned()));
            }
            let mut ready = self.fd.readable().await?;
            match ready.try_io(|inner| {
                let mut buffer = [0; 128];
                let n = inner.get_ref().read(&mut buffer)?;
                Ok(buffer[..n].to_vec())
            }) {
                Ok(Ok(bytes)) if bytes.is_empty() => return Ok(None),
                Ok(Ok(bytes)) => {
                    self.bytes.extend(bytes);
                    ensure!(
                        self.bytes.len() <= 512,
                        "Agent input line exceeds 512 bytes"
                    );
                }
                Ok(Err(e)) => return Err(e.into()),
                Err(_) => (),
            }
        }
    }
}
fn answer(line: &str, id: u64) -> Option<bool> {
    let words = line.split_whitespace().collect::<Vec<_>>();
    if words.len() != 2 || words[1].parse::<u64>().ok() != Some(id) {
        return None;
    }
    match words[0] {
        "approve" => Some(true),
        "reject" => Some(false),
        _ => None,
    }
}

fn decision(line: &str, id: u64, kind: DecisionKind) -> Option<bool> {
    if matches!(kind, DecisionKind::Consent) {
        return answer(line, id);
    }
    if answer(line, id) == Some(false) {
        return Some(false);
    }
    let DecisionKind::Numeric(code) = kind else {
        return None;
    };
    let words = line.split_whitespace().collect::<Vec<_>>();
    (words.len() == 3
        && words[0] == "confirm"
        && words[1].parse::<u64>().ok() == Some(id)
        && words[2] == format!("{code:06}"))
    .then_some(true)
}

/// Foreground explicit human Agent for one controller, never a daemon default.
pub(crate) async fn run_agent(
    conn: &Connection,
    controller: &str,
    method: &str,
) -> anyhow::Result<()> {
    ensure!(supported(method), "unsupported Agent method; no fallback");
    controller_generation(controller)?;
    let mut input = Input::stdin()?;
    let mut daemon = Daemon::pin(conn).await?;
    let (pending, mut prompts) = mpsc::channel(1);
    let path = format!("{controller}/security");
    let proxy = daemon.proxy(conn, &path, "org.sparklink.Security").await?;
    let object_path = OwnedObjectPath::try_from(AGENT_PATH)?;
    conn.object_server()
        .at(
            AGENT_PATH,
            Agent {
                method: method.to_owned(),
                controller: controller.to_owned(),
                owner: daemon.owner.clone(),
                lost: daemon.lost.clone(),
                pending,
                slot: Arc::new(Semaphore::new(1)),
            },
        )
        .await?;
    let register_args = (object_path.clone(), method);
    let register = proxy.call::<_, _, ()>("RegisterAgent", &register_args);
    let result = async {
        tokio::time::timeout(Duration::from_secs(5), register).await??;
        if method==METHOD {
            println!("AgentReady: controller={controller} daemon={} method={method}; explicit per-request consent only; unauthenticated, no Bond",daemon.owner);
        } else {
            println!("AgentReady: controller={controller} daemon={} method={method}; explicit initial consent AND six-digit confirmation; no trusted Grant or Bond",daemon.owner);
        }
        let mut current: Option<Pending> = None;
        loop {
            let budget = current.as_ref().map(|p| remaining(p.prompt.9).unwrap_or_default()).unwrap_or(Duration::from_secs(3600));
            tokio::select! {biased;
                _ = daemon.lost.changed() => bail!("original daemon ownership lost"),
                signal = tokio::signal::ctrl_c() => { signal?; break; },
                _ = tokio::time::sleep(budget), if current.is_some() => {
                    println!("AgentExpired: request={}", current.as_ref().unwrap().prompt.1);
                    current.take(); // oneshot drop rejects the request, no controller release.
                },
                next = prompts.recv() => {
                    let next = next.context("Agent callback stream closed")?;
                    if let Some(previous) = current.take() { let _ = previous.reply.send(false); }
                    if next.reply.is_closed() || remaining(next.prompt.9).is_err() { continue; }
                    input.discard_before_prompt()?;
                    let p = &next.prompt;
                    println!("AgentPrompt: request={} path={} generation={} lifetime={} handle={} role={} address_type={} address={} method={} deadline_monotonic_ns={}", p.1,p.0,p.2,p.3,p.4,p.5,p.6,p.7,p.8,p.9);
                    match next.kind {
                        DecisionKind::Consent=>println!("Type approve {} or reject {} before the ORIGINAL deadline (maximum 5 seconds); approval does not authenticate the peer",p.1,p.1),
                        DecisionKind::Numeric(code)=> {
                            println!("AgentNumericPrompt: request={} path={} generation={} lifetime={} code={code:06} deadline_monotonic_ns={}",p.1,p.0,p.2,p.3,p.9);
                            println!("Compare with the intended peer; type confirm {} {code:06} or reject {} before the ORIGINAL deadline; no trusted Grant or Bond",p.1,p.1);
                        }
                    }
                    current = Some(next);
                },
                line = input.line() => {
                    let Some(line) = line? else { break; };
                    if line == "quit" { break; }
                    if let Some(p) = current.as_ref()
                        && !p.reply.is_closed() && remaining(p.prompt.9).is_ok()
                        && let Some(yes) = decision(&line, p.prompt.1, p.kind)
                    {
                        let p = current.take().unwrap();
                        let _ = p.reply.send(yes);
                        println!("AgentDecision: request={} approved={yes}; policy result only", p.prompt.1);
                    } else { eprintln!("No decision: use approve/reject with the current request id; quit unregisters only this Agent"); }
                },
            }
        }
        anyhow::Ok(())
    }.await;
    // No controller release/reset/connection close. Original broker owns any
    // physical obligations; unregister and object removal are independently tried.
    let unregister_args = (object_path,);
    let unregister = proxy.call::<_, _, ()>("UnregisterAgent", &unregister_args);
    let cleanup = tokio::time::timeout(Duration::from_secs(1), unregister).await;
    conn.object_server().remove::<Agent, _>(AGENT_PATH).await?;
    result?;
    cleanup??;
    Ok(())
}

/// Retain one bus connection for Allocate/Begin/Result/Cancel: requests are
/// author-owned and cannot be resumed from a later slctl process.
pub(crate) async fn request(
    conn: &Connection,
    controller: &str,
    path: &str,
    timeout_ms: u32,
    method: &str,
) -> anyhow::Result<()> {
    ensure!(
        (1..=5000).contains(&timeout_ms),
        "timeout must be 1..5000 ms"
    );
    ensure!(supported(method), "unsupported method; no fallback");
    let mut daemon = Daemon::pin(conn).await?;
    let proxy = daemon.proxy(conn, path, "org.sparklink.Connection").await?;
    let info: Info =
        tokio::time::timeout(Duration::from_secs(5), proxy.call("GetInfo", &())).await??;
    validate_identity(controller, path, &info)?;
    let mut id = None;
    let operation = async {
        let allocated: u64 = proxy
            .call("AllocateReferenceSecurity", &(timeout_ms,))
            .await?;
        id = Some(allocated);
        let allocated_observation: Observation = proxy
            .call("GetReferenceSecurityResult", &(allocated,))
            .await?;
        let deadline = allocated_observation.deadline_monotonic_ns;
        ensure!(
            allocated_observation.request_id == allocated
                && allocated_observation.generation == info.0
                && allocated_observation.lifetime == info.1
                && remaining(deadline)? <= Duration::from_millis(u64::from(timeout_ms)),
            "invalid allocated identity/deadline"
        );
        println!(
            "ReferenceSecurityAllocated: request={allocated} path={path} deadline_monotonic_ns={deadline}"
        );
        proxy
            .call::<_, _, ()>("BeginReferenceSecurity", &(allocated, method))
            .await?;
        loop {
            let observation: Observation = proxy
                .call("GetReferenceSecurityResult", &(allocated,))
                .await?;
            ensure!(
                observation.request_id == allocated
                    && observation.generation == info.0
                    && observation.lifetime == info.1
                    && observation.deadline_monotonic_ns == deadline,
                "original request identity/deadline changed"
            );
            if observation.phase >= 4 {
                println!(
                    "ReferenceSecurityResult: {}",
                    serde_json::to_string(&observation)?
                );
                ensure!(
                    observation.phase == 4
                        && observation.error == 0
                        && observation.agent_approved
                        && observation.native_admitted
                        && observation.kernel_state
                            == if method == NUMERIC_METHOD { 11 } else { 9 }
                        && observation.kernel_error == 0
                        && observation.kernel_flags
                            == if method == NUMERIC_METHOD { 119 } else { 7 }
                        && observation.kernel_status == 0
                        && observation.cleanup_error == 0,
                    "reference security did not complete successfully (phase={})",
                    observation.phase
                );
                if method == NUMERIC_METHOD {
                    println!(
                        "NumericSecurityCompleted: original comparison confirmation, peer proof and observed installation; trusted Grant/Bond and application delivery require separate qualification"
                    );
                } else {
                    println!(
                        "ReferenceSecurityCompleted: unauthenticated SDK111 reference only; not peer identity, trusted Grant or Bond; peer application delivery requires its own test"
                    );
                }
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        anyhow::Ok(())
    };
    // Local watchdog bounds failed IPC, not a replacement protocol deadline.
    let result = tokio::select! {biased;
        _ = daemon.lost.changed() => Err(anyhow::anyhow!("original daemon ownership lost")),
        signal = tokio::signal::ctrl_c() => match signal {
            Ok(()) => Err(anyhow::anyhow!("request interrupted")),
            Err(error) => Err(error.into()),
        },
        result = tokio::time::timeout(Duration::from_millis(u64::from(timeout_ms) + 1000), operation) => match result {
            Ok(result) => result,
            Err(error) => Err(anyhow::Error::from(error).context("client watchdog expired")),
        },
    };
    if result.is_err()
        && let Some(id) = id
    {
        // Only withdraw this request. Never release the controller or erase debt.
        let _ = tokio::time::timeout(
            Duration::from_millis(250),
            proxy.call::<_, _, bool>("CancelReferenceSecurity", &(id,)),
        )
        .await;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    const CONTROLLER: &str = "/org/sparklink/slk0_g7";
    const LINK: &str = "/org/sparklink/slk0_g7/peer_t00_010203040506/link_000000000000000d";
    fn info() -> Info {
        (7, 13, 1, 0, 0, "01:02:03:04:05:06".into(), true, true)
    }
    #[test]
    fn canonical_full_identity_required() {
        assert!(validate_identity(CONTROLLER, LINK, &info()).is_ok());
        for controller in [
            "/org/sparklink/slk00_g7",
            "/org/sparklink/slk0_g07",
            "/org/sparklink/slk0_g0",
            "/org/sparklink/slk0_g+7",
            "/org/sparklink/adapter0",
        ] {
            assert!(validate_identity(controller, LINK, &info()).is_err());
        }
        for field in 0..8 {
            let mut wrong = info();
            match field {
                0 => wrong.0 += 1,
                1 => wrong.1 += 1,
                2 => wrong.3 = 2,
                3 => wrong.4 = 2,
                4 => wrong.5 = "broken".into(),
                5 => wrong.6 = false,
                6 => wrong.7 = false,
                _ => wrong.1 = 0,
            }
            assert!(validate_identity(CONTROLLER, LINK, &wrong).is_err());
        }
    }
    #[test]
    fn decision_is_explicit_and_request_bound() {
        assert_eq!(answer("approve 17", 17), Some(true));
        assert_eq!(answer("reject 17", 17), Some(false));
        for line in [
            "",
            "yes",
            "approve",
            "approve 16",
            "approve 17 extra",
            "yes 17",
            "approve -17",
        ] {
            assert_eq!(answer(line, 17), None);
        }
    }
    #[test]
    fn prompt_requires_reference_method_and_bounded_original_clock() {
        let mut p: Prompt = (
            LINK.into(),
            17,
            7,
            13,
            1,
            0,
            0,
            "01:02:03:04:05:06".into(),
            METHOD.into(),
            monotonic_ns().unwrap() + 1_000_000_000,
        );
        assert!(validate_prompt(CONTROLLER, &p, &info(), METHOD).is_ok());
        p.8 = "unknown".into();
        assert!(validate_prompt(CONTROLLER, &p, &info(), METHOD).is_err());
        p.8 = METHOD.into();
        p.4 = 2;
        assert!(validate_prompt(CONTROLLER, &p, &info(), METHOD).is_err());
        p.4 = 1;
        p.9 = 1;
        assert!(validate_prompt(CONTROLLER, &p, &info(), METHOD).is_err());
        p.9 = monotonic_ns().unwrap() + 6_000_000_000;
        assert!(validate_prompt(CONTROLLER, &p, &info(), METHOD).is_err());
    }
    #[test]
    fn numeric_decision_requires_original_id_and_exact_six_digit_code() {
        assert_eq!(
            decision("confirm 17 000000", 17, DecisionKind::Numeric(0)),
            Some(true)
        );
        assert_eq!(
            decision("confirm 17 759201", 17, DecisionKind::Numeric(759201)),
            Some(true)
        );
        assert_eq!(
            decision("reject 17", 17, DecisionKind::Numeric(759201)),
            Some(false)
        );
        for line in [
            "approve 17",
            "confirm 18 759201",
            "confirm 17 759202",
            "confirm 17 0",
            "confirm 17 000000 extra",
            "yes 17 759201",
        ] {
            assert_eq!(decision(line, 17, DecisionKind::Numeric(759201)), None);
        }
        assert!(supported(NUMERIC_METHOD));
        assert!(!supported("numeric-comparison"));
    }
}
