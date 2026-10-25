// SPDX-License-Identifier: GPL-2.0-only
//! Explicit human consent client. No wire/crypto engine or automatic approval.
use anyhow::{Context, bail, ensure};
use slk_contract::{
    ConnectionInfo as Info,
    security::{Observation, Prompt},
};
use std::{
    io::{IsTerminal, Read},
    os::unix::fs::OpenOptionsExt,
    sync::Arc,
    time::Duration,
};
use tokio::{
    io::unix::AsyncFd,
    sync::{Semaphore, mpsc, oneshot, watch},
};
use zbus::{Connection, zvariant::OwnedObjectPath};

pub(crate) use slk_contract::security::METHOD;
use slk_contract::security::NUMERIC_METHOD;
fn supported(method: &str) -> bool {
    matches!(method, METHOD | NUMERIC_METHOD)
}
const AGENT_PATH: &str = "/org/sparklink/slctl/agent";

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

fn validate_identity(controller: &str, path: &str, info: &Info) -> anyhow::Result<()> {
    let id = slk_contract::ControllerId::from_path(controller)
        .context("canonical controller required")?;
    ensure!(
        slk_contract::matches_connection(id, path, info)
            && info.3 <= 1
            && info.4 <= 1
            && info.6
            && info.7,
        "known connected original generation/lifetime required"
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
    client: std::sync::Weak<libsparklink::Client>,
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
        _conn: &Connection,
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
            let client = self.client.upgrade().context("Agent caller scope ended")?;
            let link = client.connection(&self.controller, &prompt.0).await?;
            let info = link.info().await?;
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
    line_limit: usize,
}
impl Input {
    pub(crate) fn stdin() -> anyhow::Result<Self> {
        Self::stdin_with_limit(512)
    }
    pub(crate) fn stdin_with_limit(line_limit: usize) -> anyhow::Result<Self> {
        ensure!(
            (512..=4160).contains(&line_limit),
            "unsupported input line limit"
        );
        let fd = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(nix::libc::O_NONBLOCK | nix::libc::O_CLOEXEC)
            .open("/proc/self/fd/0")?;
        // Linux canonical TTY input truncates at 4095 data bytes. Reject that
        // boundary including the newline, so a truncated hex value can never
        // become a shorter successful reply. Pipes retain the full limit.
        let line_limit = if fd.is_terminal() {
            line_limit.min(4095)
        } else {
            line_limit
        };
        Ok(Self {
            fd: AsyncFd::new(fd).context("Agent requires a pollable terminal or pipe")?,
            bytes: Vec::new(),
            line_limit,
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
                    ensure!(
                        consumed <= self.line_limit.max(4096),
                        "excessive pre-prompt input"
                    );
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
                    validate_input_line(&self.bytes, self.line_limit)?;
                }
                Ok(Err(e)) => return Err(e.into()),
                Err(_) => (),
            }
        }
    }
}
fn validate_input_line(bytes: &[u8], limit: usize) -> anyhow::Result<()> {
    let first_line = bytes
        .iter()
        .position(|&byte| byte == b'\n')
        .map_or(bytes.len(), |end| end + 1);
    ensure!(first_line <= limit, "input line exceeds {limit} bytes");
    Ok(())
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
    client: &libsparklink::Client,
    controller: &str,
    method: &str,
) -> anyhow::Result<()> {
    ensure!(supported(method), "unsupported Agent method; no fallback");
    let view = client.controller(controller).await?;
    let mut input = Input::stdin()?;
    let mut lost = client.owner_loss();
    let (pending, mut prompts) = mpsc::channel(1);

    // Callback object must not retain its own bus through a strong Client cycle.
    let callback_client = Arc::new(client.clone());
    let object_path = OwnedObjectPath::try_from(AGENT_PATH)?;
    ensure!(
        conn.object_server()
            .at(
                AGENT_PATH,
                Agent {
                    method: method.to_owned(),
                    controller: controller.to_owned(),
                    client: Arc::downgrade(&callback_client),
                    owner: client.daemon_owner().to_owned(),
                    lost: lost.clone(),
                    pending,
                    slot: Arc::new(Semaphore::new(1)),
                },
            )
            .await?,
        "Agent path already registered"
    );
    let mut registration = None;
    let register = view.register_agent(object_path, method);
    let result = async {
        registration = Some(tokio::time::timeout(Duration::from_secs(5), register).await??);
        if method==METHOD {
            println!("AgentReady: controller={controller} daemon={} method={method}; explicit per-request consent only; unauthenticated, no Bond",client.daemon_owner());
        } else {
            println!("AgentReady: controller={controller} daemon={} method={method}; explicit initial consent AND six-digit confirmation; no trusted Grant or Bond",client.daemon_owner());
        }
        let mut current: Option<Pending> = None;
        loop {
            let budget = current.as_ref().map(|p| remaining(p.prompt.9).unwrap_or_default()).unwrap_or(Duration::from_secs(3600));
            tokio::select! {biased;
                _ = lost.changed() => bail!("original daemon ownership lost"),
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
    let cleanup = async {
        if let Some(registration) = registration.as_mut() {
            tokio::time::timeout(Duration::from_secs(1), registration.unregister()).await??;
        }
        anyhow::Ok(())
    }
    .await;
    conn.object_server().remove::<Agent, _>(AGENT_PATH).await?;
    result?;
    cleanup?;
    Ok(())
}

/// Retain one bus connection for Allocate/Begin/Result/Cancel: requests are
/// author-owned and cannot be resumed from a later slctl process.
pub(crate) async fn request(
    client: &libsparklink::Client,
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
    let mut lost = client.owner_loss();
    let link = client.connection(controller, path).await?;
    let info = tokio::time::timeout(Duration::from_secs(5), link.info()).await??;
    validate_identity(controller, path, &info)?;
    let mut request = None;
    let operation = async {
        request = Some(link.allocate_reference_security(timeout_ms).await?);
        let request = request.as_ref().expect("just allocated");
        let allocated = request.id();
        let allocated_observation = request.observation().await?;
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
        request.begin(method).await?;
        loop {
            let observation: Observation = request.observation().await?;
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
        _ = lost.changed() => Err(anyhow::anyhow!("original daemon ownership lost")),
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
        && let Some(request) = request
    {
        // Only withdraw this request. Never release the controller or erase debt.
        let _ = tokio::time::timeout(Duration::from_millis(250), request.cancel()).await;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn input_limit_applies_to_one_line_and_rejects_the_tty_truncation_boundary() {
        let mut pipe = vec![b'a'; 4114];
        pipe.push(b'\n');
        pipe.extend([b'b'; 100]);
        assert!(validate_input_line(&pipe, 4160).is_ok());
        assert!(validate_input_line(&pipe, 512).is_err());
        let mut terminal = vec![b'a'; 4094];
        terminal.push(b'\n');
        assert!(validate_input_line(&terminal, 4095).is_ok());
        terminal.insert(0, b'a');
        assert!(validate_input_line(&terminal, 4095).is_err());
        assert!(validate_input_line(&vec![b'a'; 4161], 4160).is_err());
    }
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
