//! Finite application load on the same delegated datagram fd. No protocol state.
use super::{Config, Prepared, distribution, hex, ns};
use serde::Serialize;
use std::collections::{HashMap, VecDeque};
use std::io::Write;
use std::os::fd::{AsRawFd, OwnedFd};
use std::path::Path;
use std::time::{Duration, Instant};

const REQUEST_NS: u64 = 10_000_000_000;
const GRACE_NS: u64 = 1_000_000_000;
const RUN_NS: u64 = 612_000_000_000;
const STEP_PACKETS: usize = 32;

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Mode {
    Rate,
    Window,
    Duplex,
    Peer,
}

#[derive(Clone, Copy, Serialize)]
pub(crate) struct LoadConfig {
    pub mode: Mode,
    pub count: usize,
    pub bytes: usize,
    pub window: usize,
    pub interval_us: u64,
}
impl LoadConfig {
    pub(crate) fn validate(self) -> anyhow::Result<()> {
        Config {
            count: self.count,
            bytes: self.bytes,
        }
        .validate()?;
        if !(1..=self.count.min(256)).contains(&self.window) {
            anyhow::bail!("load window must be1..min(count,256)");
        }
        if self.mode == Mode::Rate {
            if !(10..=1_000_000).contains(&self.interval_us)
                || self.interval_us * self.count as u64 > 600_000_000
            {
                anyhow::bail!("absolute interval must be10..1000000us, schedule at most600s");
            }
        } else if self.interval_us != 0 {
            anyhow::bail!("interval only applies to absolute-rate mode");
        }
        Ok(())
    }
    fn active(self) -> bool {
        self.mode != Mode::Peer
    }
    fn duplex(self) -> bool {
        self.mode == Mode::Duplex
    }
}

#[derive(Default, Serialize)]
struct Outgoing {
    index: usize,
    planned_ns: Option<u64>,
    dispatch_ns: Option<u64>,
    first_syscall_ns: Option<u64>,
    admitted_ns: Option<u64>,
    syscall_ns: Option<u64>,
    deadline_ns: Option<u64>,
    read_ns: Option<u64>,
    validated_ns: Option<u64>,
    send_attempts: u64,
    would_block: u64,
    errno: Option<i32>,
    local_budget_rejected: bool,
    timed_out: bool,
    late: bool,
    reply_count: u64,
    frame_hex: String,
}
#[derive(Default, Serialize)]
struct Incoming {
    index: usize,
    read_ns: Option<u64>,
    validated_ns: Option<u64>,
    deadline_ns: Option<u64>,
    reply_syscall_ns: Option<u64>,
    reply_admitted_ns: Option<u64>,
    send_attempts: u64,
    would_block: u64,
    errno: Option<i32>,
    timed_out: bool,
    frame_hex: String,
}
#[derive(Default, Serialize)]
struct Counters {
    rx_packets: usize,
    duplicate_requests: usize,
    duplicate_replies: usize,
    reordered_replies: usize,
    corrupt_packets: usize,
    unknown_replies: usize,
    unsolicited_requests: usize,
    receiver_record_overflow: usize,
    reply_queue_overflow: usize,
    inflight_peak: usize,
    reply_queue_peak: usize,
    poll_calls: usize,
    iterations: usize,
}
struct State {
    config: LoadConfig,
    prepared: Prepared,
    peer: Prepared,
    outgoing: Vec<Outgoing>,
    incoming: Vec<Incoming>,
    source_index: HashMap<u32, usize>,
    peer_index: HashMap<u32, usize>,
    reply_queue: VecDeque<usize>,
    outstanding: VecDeque<usize>,
    last_unique_request_ns: Option<u64>,
    next: usize,
    seen: usize,
    inflight: usize,
    maximum_reply_index: Option<usize>,
    counters: Counters,
}
impl State {
    fn new(config: LoadConfig) -> anyhow::Result<Self> {
        config.validate()?;
        let core = Config {
            count: config.count,
            bytes: config.bytes,
        };
        let prepared = Prepared::new(core, !config.active())?;
        let peer = Prepared::new(core, true)?;
        let source_index = if config.active() {
            prepared
                .frames
                .iter()
                .enumerate()
                .map(|(i, b)| {
                    (
                        u32::from_le_bytes(b[24..28].try_into().expect("bounded frame")),
                        i,
                    )
                })
                .collect()
        } else {
            HashMap::new()
        };
        Ok(Self {
            config,
            prepared,
            peer,
            outgoing: (0..config.count)
                .map(|index| Outgoing {
                    index,
                    planned_ns: (config.mode == Mode::Rate)
                        .then_some(index as u64 * config.interval_us * 1000),
                    ..Outgoing::default()
                })
                .collect(),
            incoming: (0..config.count)
                .map(|index| Incoming {
                    index,
                    ..Incoming::default()
                })
                .collect(),
            source_index,
            peer_index: HashMap::with_capacity(config.count),
            reply_queue: VecDeque::with_capacity(config.window),
            outstanding: VecDeque::with_capacity(config.window),
            last_unique_request_ns: None,
            next: 0,
            seen: 0,
            inflight: 0,
            maximum_reply_index: None,
            counters: Counters::default(),
        })
    }
    fn correctness(&self) -> bool {
        let source_ok = !self.config.active()
            || (self.next == self.config.count
                && self.outgoing.iter().all(|r| {
                    r.validated_ns.is_some()
                        && !r.timed_out
                        && !r.late
                        && !r.local_budget_rejected
                        && r.errno.is_none()
                }));
        let peer_ok = (self.config.active() && !self.config.duplex())
            || (self.seen == self.config.count
                && self.incoming.iter().all(|r| {
                    r.validated_ns.is_some()
                        && r.reply_admitted_ns.is_some()
                        && !r.timed_out
                        && r.errno.is_none()
                }));
        let c = &self.counters;
        source_ok
            && peer_ok
            && c.duplicate_requests == 0
            && c.duplicate_replies == 0
            && c.reordered_replies == 0
            && c.corrupt_packets == 0
            && c.unknown_replies == 0
            && c.unsolicited_requests == 0
            && c.receiver_record_overflow == 0
            && c.reply_queue_overflow == 0
    }

    fn expired(&mut self, now: u64) {
        while let Some(&i) = self.outstanding.front() {
            if self.outgoing[i].deadline_ns.is_some_and(|d| now >= d) {
                self.outgoing[i].timed_out = true;
                self.outstanding.pop_front();
                self.inflight -= 1;
            } else {
                break;
            }
        }
        while let Some(&i) = self.reply_queue.front() {
            if self.incoming[i].deadline_ns.is_some_and(|d| now >= d) {
                self.incoming[i].timed_out = true;
                self.reply_queue.pop_front();
            } else {
                break;
            }
        }
    }
    fn all_source_done(&self) -> bool {
        !self.config.active() || (self.next == self.config.count && self.inflight == 0)
    }
    fn all_peer_done(&self) -> bool {
        (self.config.active() && !self.config.duplex())
            || (self.seen == self.config.count && self.reply_queue.is_empty())
    }
    fn earliest(&self, now: u64, grace: Option<u64>, request_ns: u64) -> u64 {
        let mut next = grace.unwrap_or(RUN_NS);
        if self.config.mode == Mode::Rate && self.next < self.config.count {
            next = next.min(self.next as u64 * self.config.interval_us * 1000);
        }
        if let Some(&i) = self.outstanding.front() {
            next = next.min(self.outgoing[i].deadline_ns.expect("outstanding deadline"));
        }
        if self.config.active() && self.next < self.config.count {
            let pending = &self.outgoing[self.next];
            if let Some(d) = pending.deadline_ns {
                next = next.min(d);
            }
        }
        if let Some(&i) = self.reply_queue.front() {
            next = next.min(self.incoming[i].deadline_ns.expect("queued reply deadline"));
        }
        // Only new validated requests advance the peer progress budget. Each
        // queued reply keeps its own arrival-based original deadline unchanged.
        if !self.all_peer_done() {
            next = next.min(self.last_unique_request_ns.unwrap_or(0) + request_ns);
        }
        next.max(now)
    }
    fn try_source(&mut self, fd: &OwnedFd, origin: Instant, request_ns: u64) -> anyhow::Result<()> {
        if !self.config.active() {
            return Ok(());
        }
        for _ in 0..STEP_PACKETS {
            if self.next == self.config.count {
                break;
            }
            let now = ns(origin);
            let i = self.next;
            let rate = self.config.mode == Mode::Rate;
            if rate && now < i as u64 * self.config.interval_us * 1000 {
                break;
            }
            if !rate && self.inflight == self.config.window {
                break;
            }
            let row = &mut self.outgoing[i];
            let planned = *row.planned_ns.get_or_insert(if rate {
                i as u64 * self.config.interval_us * 1000
            } else {
                now
            });
            row.dispatch_ns.get_or_insert(now);
            row.deadline_ns.get_or_insert(planned + request_ns);
            if now >= planned + request_ns {
                row.timed_out = true;
                self.next += 1;
                continue;
            }
            if self.inflight == self.config.window {
                // A local load-generator budget, never attributed to kernel errno.
                row.local_budget_rejected = true;
                self.next += 1;
                continue;
            }
            row.first_syscall_ns.get_or_insert(ns(origin));
            let started = ns(origin);
            let bytes = &self.prepared.frames[i];
            // SAFETY: live owned fd and complete immutable preallocated datagram.
            let result = unsafe {
                nix::libc::send(
                    fd.as_raw_fd(),
                    bytes.as_ptr().cast(),
                    bytes.len(),
                    nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
                )
            };
            let returned = ns(origin);
            row.send_attempts += 1;
            if result == bytes.len() as isize {
                row.syscall_ns = Some(started);
                row.admitted_ns = Some(returned);
                self.inflight += 1;
                self.outstanding.push_back(i);
                self.counters.inflight_peak = self.counters.inflight_peak.max(self.inflight);
                self.next += 1;
            } else if result < 0 {
                let error = std::io::Error::last_os_error();
                if error.kind() == std::io::ErrorKind::WouldBlock {
                    row.would_block += 1;
                    if rate {
                        row.errno = error.raw_os_error();
                        self.next += 1;
                    } else {
                        break;
                    }
                } else {
                    row.errno = error.raw_os_error();
                    self.next += 1;
                }
            } else {
                anyhow::bail!("partial application datagram");
            }
        }
        Ok(())
    }
    fn try_replies(&mut self, fd: &OwnedFd, origin: Instant) -> anyhow::Result<()> {
        for _ in 0..STEP_PACKETS {
            let Some(&i) = self.reply_queue.front() else {
                break;
            };
            let row = &mut self.incoming[i];
            let started = ns(origin);
            if started >= row.deadline_ns.expect("queued reply deadline") {
                row.timed_out = true;
                self.reply_queue.pop_front();
                continue;
            }
            let bytes = &self.peer.frames[i];
            // SAFETY: queued preallocated peer buffer remains owned until admission.
            let result = unsafe {
                nix::libc::send(
                    fd.as_raw_fd(),
                    bytes.as_ptr().cast(),
                    bytes.len(),
                    nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
                )
            };
            let returned = ns(origin);
            row.send_attempts += 1;
            if result == bytes.len() as isize {
                row.reply_syscall_ns = Some(started);
                row.reply_admitted_ns = Some(returned);
                row.timed_out = returned >= row.deadline_ns.expect("reply original deadline");
                self.reply_queue.pop_front();
            } else if result < 0 {
                let error = std::io::Error::last_os_error();
                if error.kind() == std::io::ErrorKind::WouldBlock {
                    row.would_block += 1;
                    break;
                }
                row.errno = error.raw_os_error();
                self.reply_queue.pop_front();
            } else {
                anyhow::bail!("partial application reply");
            }
        }
        Ok(())
    }
    fn packet(
        &mut self,
        bytes: &[u8],
        read_ns: u64,
        mut clock: impl FnMut() -> u64,
        request_ns: u64,
    ) -> anyhow::Result<()> {
        self.counters.rx_packets += 1;
        if self.counters.rx_packets > self.config.count * 4 + 16 {
            anyhow::bail!("bounded receive observation budget exhausted");
        }
        if bytes.len() != self.config.bytes || bytes.len() < 29 {
            self.counters.corrupt_packets += 1;
            return Ok(());
        }
        let sequence = u32::from_le_bytes(bytes[24..28].try_into()?);
        if bytes[28] == 1 {
            let Some(&i) = self.source_index.get(&sequence) else {
                self.counters.unknown_replies += 1;
                return Ok(());
            };
            let expected = &self.prepared.frames[i];
            if expected[..28] != bytes[..28]
                || expected[29..] != bytes[29..]
                || self.outgoing[i].admitted_ns.is_none()
            {
                self.counters.corrupt_packets += 1;
                return Ok(());
            }
            let now = clock();
            let row = &mut self.outgoing[i];
            row.reply_count += 1;
            if row.validated_ns.is_some() {
                self.counters.duplicate_replies += 1;
                return Ok(());
            }
            row.read_ns = Some(read_ns);
            row.validated_ns = Some(now);
            row.late = now >= row.deadline_ns.expect("admitted request deadline");
            if !row.timed_out {
                self.inflight -= 1;
                let position = self
                    .outstanding
                    .iter()
                    .position(|&id| id == i)
                    .expect("live outstanding identity");
                self.outstanding.remove(position);
            }
            if row.late {
                row.timed_out = true;
            }
            if self
                .maximum_reply_index
                .is_some_and(|previous| i < previous)
            {
                self.counters.reordered_replies += 1;
            }
            self.maximum_reply_index = Some(
                self.maximum_reply_index
                    .map_or(i, |previous| previous.max(i)),
            );
            self.prepared.received[i].copy_from_slice(bytes);
        } else if bytes[28] == 0 {
            if self.config.active() && !self.config.duplex() {
                self.counters.unsolicited_requests += 1;
                return Ok(());
            }
            if crate::channel::validate(bytes, sequence, false, self.config.bytes).is_err() {
                self.counters.corrupt_packets += 1;
                return Ok(());
            }
            let nonce: [u8; 16] = bytes[8..24].try_into()?;
            if self.peer_index.contains_key(&sequence) || self.peer.seen_nonces.contains(&nonce) {
                self.counters.duplicate_requests += 1;
                return Ok(());
            }
            if self.seen == self.config.count {
                self.counters.receiver_record_overflow += 1;
                return Ok(());
            }
            let now = clock();
            let i = self.seen;
            self.seen += 1;
            self.peer_index.insert(sequence, i);
            self.peer.seen_nonces.insert(nonce);
            self.peer.frames[i].copy_from_slice(bytes);
            self.peer.frames[i][28] = 1;
            self.incoming[i].read_ns = Some(read_ns);
            self.incoming[i].validated_ns = Some(now);
            self.incoming[i].deadline_ns = Some(read_ns + request_ns);
            self.last_unique_request_ns = Some(now);
            if self.reply_queue.len() == self.config.window {
                self.counters.reply_queue_overflow += 1;
                // Valid request receipt remains, but no invented successful reply.
            } else {
                self.reply_queue.push_back(i);
                self.counters.reply_queue_peak =
                    self.counters.reply_queue_peak.max(self.reply_queue.len());
            }
        } else {
            self.counters.corrupt_packets += 1;
        }
        Ok(())
    }
    fn read(&mut self, fd: &OwnedFd, origin: Instant, request_ns: u64) -> anyhow::Result<()> {
        let mut buffer = [0u8; 2042];
        for _ in 0..STEP_PACKETS {
            // SAFETY: exclusively borrowed bounded writable buffer; TRUNC detects oversize.
            let result = unsafe {
                nix::libc::recv(
                    fd.as_raw_fd(),
                    buffer.as_mut_ptr().cast(),
                    buffer.len(),
                    nix::libc::MSG_DONTWAIT | nix::libc::MSG_TRUNC,
                )
            };
            let at = ns(origin);
            if result < 0 {
                let e = std::io::Error::last_os_error();
                if e.kind() == std::io::ErrorKind::WouldBlock {
                    break;
                }
                if e.kind() == std::io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(e.into());
            }
            if result as usize > buffer.len() {
                self.packet(&[], at, || ns(origin), request_ns)?;
                continue;
            }
            self.packet(&buffer[..result as usize], at, || ns(origin), request_ns)?;
        }
        Ok(())
    }
}

#[derive(Serialize)]
struct Observation {
    elapsed_ns: u64,
    active_elapsed_ns: u64,
    error: Option<String>,
}
fn drive(
    fd: &OwnedFd,
    state: &mut State,
    request_ns: u64,
    grace_ns: u64,
    run_ns: u64,
) -> Observation {
    let origin = Instant::now();
    let mut grace = None;
    let mut active = 0;
    let result = (|| -> anyhow::Result<()> {
        loop {
            state.counters.iterations += 1;
            let now = ns(origin);
            if now >= run_ns {
                anyhow::bail!("finite load run budget exhausted");
            }
            if !state.all_peer_done()
                && now >= state.last_unique_request_ns.unwrap_or(0) + request_ns
            {
                anyhow::bail!(
                    "peer unique-request progress budget exhausted;missing requests retained"
                );
            }
            state.expired(now);
            state.read(fd, origin, request_ns)?;
            // Small alternating budgets: do not let source TX starve real peer replies.
            state.try_replies(fd, origin)?;
            state.try_source(fd, origin, request_ns)?;
            let now = ns(origin);
            if state.all_source_done() && state.all_peer_done() && grace.is_none() {
                active = now;
                grace = Some(now + grace_ns);
            }
            if grace.is_some_and(|d| now >= d) {
                break;
            }
            let source_write = state.config.active()
                && state.config.mode != Mode::Rate
                && state.next < state.config.count
                && state.inflight < state.config.window;
            if source_write && state.outgoing[state.next].send_attempts == 0 {
                continue;
            }
            // Consume already-buffered work in finite rounds before sleeping.
            if !state.reply_queue.is_empty()
                && state.incoming[*state.reply_queue.front().unwrap()].send_attempts == 0
            {
                continue;
            }
            let target = state.earliest(now, grace, request_ns).min(run_ns);
            if target <= now {
                continue;
            }
            let mut p = nix::libc::pollfd {
                fd: fd.as_raw_fd(),
                events: nix::libc::POLLIN
                    | if source_write || !state.reply_queue.is_empty() {
                        nix::libc::POLLOUT
                    } else {
                        0
                    },
                revents: 0,
            };
            let delay = target - now;
            let timeout = nix::libc::timespec {
                tv_sec: (delay / 1_000_000_000) as _,
                tv_nsec: (delay % 1_000_000_000) as _,
            };
            state.counters.poll_calls += 1;
            // SAFETY: one live writable pollfd, finite deadline-derived wait.
            let result = unsafe { nix::libc::ppoll(&mut p, 1, &timeout, std::ptr::null()) };
            if result < 0 {
                let e = std::io::Error::last_os_error();
                if e.kind() == std::io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(e.into());
            }
            if p.revents & (nix::libc::POLLERR | nix::libc::POLLNVAL) != 0 {
                anyhow::bail!("load socket fault:{}", p.revents);
            }
            if p.revents & nix::libc::POLLHUP != 0 && p.revents & nix::libc::POLLIN == 0 {
                anyhow::bail!("load socket closed");
            }
        }
        Ok(())
    })();
    let elapsed = ns(origin);
    Observation {
        elapsed_ns: elapsed,
        active_elapsed_ns: if active == 0 { elapsed } else { active },
        error: result.err().map(|e| format!("{e:#}")),
    }
}

fn read_control<const N: usize>(
    fd: nix::libc::c_int,
    budget: Duration,
    command: &[u8; N],
    phase: &str,
) -> anyhow::Result<()> {
    let deadline = Instant::now() + budget;
    let mut bytes = [0u8; N];
    let mut used = 0;
    while used < bytes.len() {
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            anyhow::bail!("original {phase}-barrier deadline expired");
        }
        let timeout = nix::libc::timespec {
            tv_sec: left.as_secs() as _,
            tv_nsec: left.subsec_nanos() as _,
        };
        let mut p = nix::libc::pollfd {
            fd,
            events: nix::libc::POLLIN,
            revents: 0,
        };
        // SAFETY: one initialized pollfd and finite timespec; no signal-mask change.
        let result = unsafe { nix::libc::ppoll(&mut p, 1, &timeout, std::ptr::null()) };
        if result < 0 {
            let e = std::io::Error::last_os_error();
            if e.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(e.into());
        }
        if p.revents & (nix::libc::POLLERR | nix::libc::POLLNVAL) != 0 {
            anyhow::bail!("{phase} barrier fd fault");
        }
        if result == 0 {
            continue;
        }
        // Sole reader; read only after readiness, bounded by remaining command.
        // SAFETY: exclusive initialized buffer suffix and live input fd.
        let n =
            unsafe { nix::libc::read(fd, bytes[used..].as_mut_ptr().cast(), bytes.len() - used) };
        if n == 0 {
            anyhow::bail!("{phase} barrier EOF is author withdrawal");
        }
        if n < 0 {
            let e = std::io::Error::last_os_error();
            if matches!(
                e.kind(),
                std::io::ErrorKind::Interrupted | std::io::ErrorKind::WouldBlock
            ) {
                continue;
            }
            return Err(e.into());
        }
        used += n as usize;
    }
    if Instant::now() >= deadline {
        anyhow::bail!("original {phase}-barrier deadline expired");
    }
    if &bytes != command {
        anyhow::bail!("load requires exact explicit {phase} line");
    }
    Ok(())
}

pub(crate) fn read_start(fd: nix::libc::c_int, budget: Duration) -> anyhow::Result<()> {
    read_control(fd, budget, b"start\n", "start")
}

#[derive(Serialize)]
struct Finalization {
    completed: bool,
    budget_ns: u64,
    elapsed_ns: u64,
    error: Option<String>,
}
fn finish(fd: nix::libc::c_int, budget: Duration) -> Finalization {
    let origin = Instant::now();
    let error = read_control(fd, budget, b"finish\n", "finish")
        .err()
        .map(|e| format!("{e:#}"));
    Finalization {
        completed: error.is_none(),
        budget_ns: budget.as_nanos() as u64,
        elapsed_ns: ns(origin),
        error,
    }
}

#[derive(Serialize)]
struct ProcessResources {
    user_cpu_ns: u64,
    system_cpu_ns: u64,
    process_lifetime_maxrss_kib: i64,
    open_fds: usize,
    resident_pages: u64,
    page_bytes: i64,
}
fn resources() -> anyhow::Result<ProcessResources> {
    let mut usage = std::mem::MaybeUninit::<nix::libc::rusage>::uninit();
    // SAFETY: kernel initializes full rusage on successful return.
    if unsafe { nix::libc::getrusage(nix::libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let usage = unsafe { usage.assume_init() };
    let ns = |t: nix::libc::timeval| -> anyhow::Result<u64> {
        Ok(u64::try_from(t.tv_sec)? * 1_000_000_000 + u64::try_from(t.tv_usec)? * 1000)
    };
    let statm = std::fs::read_to_string("/proc/self/statm")?;
    let rss = statm
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("missing proc rss"))?
        .parse()?;
    // SAFETY: read-only constant sysconf query.
    let page = unsafe { nix::libc::sysconf(nix::libc::_SC_PAGESIZE) };
    if page <= 0 {
        anyhow::bail!("unavailable page size");
    }
    Ok(ProcessResources {
        user_cpu_ns: ns(usage.ru_utime)?,
        system_cpu_ns: ns(usage.ru_stime)?,
        process_lifetime_maxrss_kib: usage.ru_maxrss,
        open_fds: std::fs::read_dir("/proc/self/fd")?.count(),
        resident_pages: rss,
        page_bytes: page,
    })
}

// One production serializer, also used by local report-replay tests. Identity
// comes from the actual channel ioctl in run_load; test fixtures mark theirs.
fn report(
    state: &mut State,
    observation: &Observation,
    info: &slk_protocol::channel::SleChannelInfo,
    resource_summary: serde_json::Value,
    finalization: &Finalization,
) -> serde_json::Value {
    let config = state.config;
    let mut rtts: Vec<_> = state
        .outgoing
        .iter()
        .filter(|r| !r.timed_out)
        .filter_map(|r| {
            r.validated_ns
                .zip(r.syscall_ns)
                .map(|(end, start)| end - start)
        })
        .collect();
    for (row, frame) in state.outgoing.iter_mut().zip(&state.prepared.frames) {
        if row.dispatch_ns.is_some() {
            row.frame_hex = hex(frame);
        }
    }
    for (row, frame) in state
        .incoming
        .iter_mut()
        .zip(&state.peer.frames)
        .take(state.seen)
    {
        row.frame_hex = hex(frame);
    }
    let correctness = state.correctness() && observation.error.is_none() && finalization.completed;
    let outgoing_count = if config.active() { config.count } else { 0 };
    let admitted = state
        .outgoing
        .iter()
        .filter(|r| r.admitted_ns.is_some())
        .count();
    let validated = state
        .outgoing
        .iter()
        .filter(|r| r.validated_ns.is_some())
        .count();
    let late = state.outgoing.iter().filter(|r| r.late).count();
    let timed_out = state.outgoing.iter().filter(|r| r.timed_out).count();
    let local_rejected = state
        .outgoing
        .iter()
        .filter(|r| r.local_budget_rejected)
        .count();
    let kernel_rejected = state.outgoing.iter().filter(|r| r.errno.is_some()).count();
    let unattempted = if config.active() {
        state
            .outgoing
            .iter()
            .filter(|r| r.dispatch_ns.is_none())
            .count()
    } else {
        0
    };
    let peer_replies = state
        .incoming
        .iter()
        .filter(|r| r.reply_admitted_ns.is_some())
        .count();
    let rate = |bytes: usize| {
        (observation.active_elapsed_ns > 0)
            .then(|| bytes as f64 * 1_000_000_000.0 / observation.active_elapsed_ns as f64)
    };
    serde_json::json!({"schema_version":2,"status":if observation.error.is_some() || !finalization.completed {"INCOMPLETE"}else if !correctness {"LOAD_OBSERVED_WITH_FAILURES_NOT_QUALIFIED"}else{"LOAD_OBSERVED_NOT_QUALIFIED"},"performance_qualified":false,
        "correctness":correctness,"finalization":finalization,"window_domain":"application-awaiting-validated-reply-not-protocol-credit",
        "clock":"process-local-Rust-Instant-relative-nanoseconds","wait_backend":"ppoll-relative-nanoseconds","config":config,"observation":observation,
        "request_deadline_ns":REQUEST_NS,"late_observation_grace_ns":GRACE_NS,"maximum_run_ns":RUN_NS,
        "rtt_definition":"successful send syscall entry to validated reply;success-only excludes timed-out/late;no cross-clock arithmetic",
        "percentile_method":"nearest-rank;p99.9 requires10000 successes","success_only_rtt":distribution(&mut rtts),
        "summary":{"scheduled":outgoing_count,"dispatched":outgoing_count-unattempted,"unattempted":unattempted,"admitted":admitted,"validated_replies":validated,
            "timed_out":timed_out,"late":late,"local_budget_rejected":local_rejected,"kernel_rejected":kernel_rejected,
            "missing_admitted_replies":admitted-validated,
            "expired_before_admission":state.outgoing.iter().filter(|r|r.timed_out && r.admitted_ns.is_none()).count(),
            "admitted_reply_timeouts":state.outgoing.iter().filter(|r|r.timed_out && r.admitted_ns.is_some()).count(),
            "successful_timely_replies":validated-late,"peer_reply_deadline_exceeded":state.incoming.iter().filter(|r|r.timed_out).count(),
            "peer_validated_requests":state.seen,"peer_reply_admissions":peer_replies,
            "peer_validated_application_bytes":state.seen*config.bytes},
        "rates":{"denominator":"own-process active_elapsed_ns before late-observation grace;includes timeouts and failures",
            "requested_messages_per_second":if config.mode==Mode::Rate {Some(1_000_000.0/config.interval_us as f64)}else{None},
            "admitted_messages_per_second":rate(admitted),"local_verified_datagram_goodput_Bps":rate(state.seen*config.bytes),
            "local_verified_pattern_payload_goodput_Bps":rate(state.seen*(config.bytes-29)),"benchmark_header_bytes_per_datagram":29,
            "USB_bytes":null,"USB_bytes_per_second":null},"process_resources":resource_summary,
        "counters":state.counters,"outgoing":if config.active(){&state.outgoing[..]}else{&[]},"incoming":&state.incoming[..state.seen],
        "channel_identity":{"controller":info.controller,"generation":info.generation,"lifetime":info.lifetime,"handle":info.handle,"local_tcid":info.local_tcid,"remote_tcid":info.remote_tcid,"pi":info.pi,"mtu":info.mtu,"mps":info.mps,"mode":info.mode,"directions":info.directions},
        "unmeasured":["artifact/source/firmware/peer/capture/supervisor closure","USB/Session/NOCP timeline and bytes","interval resource peaks/kernel worker/timer/URB/credit (only process endpoint snapshots collected)","trace overhead","stable VM/WS73 performance qualification"]})
}

fn resource_summary(
    before: anyhow::Result<ProcessResources>,
    after: anyhow::Result<ProcessResources>,
) -> serde_json::Value {
    match (before, after) {
        (Ok(before), Ok(after)) => {
            serde_json::json!({"scope":"process-wide snapshots bracketing drive;includes endpoint probe overhead;maxrss is process lifetime,not interval peak",
            "user_cpu_delta_ns":after.user_cpu_ns.checked_sub(before.user_cpu_ns),"system_cpu_delta_ns":after.system_cpu_ns.checked_sub(before.system_cpu_ns),
            "before":before,"after":after,"kernel_workers":null,"kernel_timers":null,"URBs":null,"protocol_credit_peak":null})
        }
        (before, after) => {
            serde_json::json!({"incomplete":true,"before_error":before.err().map(|e|e.to_string()),"after_error":after.err().map(|e|e.to_string())})
        }
    }
}

/// Load endpoints arm on `start`; stop reporting until paired `finish`.
/// The supervisor checks both credentials/Ready before start and both quiescent
/// markers before finish. Both control waits have independent finite budgets.
pub(crate) fn run_load(fd: OwnedFd, config: LoadConfig, path: &Path) -> anyhow::Result<()> {
    config.validate()?;
    let mut output = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    output.write_all(
        b"{\"schema_version\":2,\"status\":\"INCOMPLETE\",\"performance_qualified\":false}\n",
    )?;
    let mut state = State::new(config)?;
    let fd = crate::channel::prepare_application_fd(fd)?;
    crate::channel::wait(
        &fd,
        nix::libc::POLLOUT,
        Instant::now() + Duration::from_secs(10),
    )?;
    let info = slk_protocol::channel::query(fd.as_raw_fd())?;
    if info.mode != 0
        || info.directions != 3
        || info.local_tcid != 31
        || info.remote_tcid != 31
        || info.pi != 241
        || usize::from(info.mtu) < config.bytes
        || usize::from(info.mps) < config.bytes + 5
    {
        anyhow::bail!("load requires current bidirectional basic CUTC capabilities");
    }
    println!(
        "SocketBenchmarkArmed: mode={:?} count={} bytes={} window={}",
        config.mode, config.count, config.bytes, config.window
    );
    read_start(nix::libc::STDIN_FILENO, Duration::from_secs(30))?;
    let resource_before = resources();
    let observation = drive(&fd, &mut state, REQUEST_NS, GRACE_NS, RUN_NS);
    let resource_after = resources();
    // Keep the channel fd alive and avoid report allocation/hex/JSON until both
    // application loops have stopped. The supervisor verifies both markers
    // before sending finish. This cleanup budget does not renew message time.
    println!(
        "SocketBenchmarkQuiescent: mode={:?} correctness={}",
        config.mode,
        state.correctness() && observation.error.is_none()
    );
    let finalization = finish(nix::libc::STDIN_FILENO, Duration::from_secs(30));
    let correctness = state.correctness() && observation.error.is_none() && finalization.completed;
    let report = report(
        &mut state,
        &observation,
        &info,
        resource_summary(resource_before, resource_after),
        &finalization,
    );
    use std::io::Seek;
    output.rewind()?;
    output.set_len(0)?;
    serde_json::to_writer(&mut output, &report)?;
    output.write_all(b"\n")?;
    if let Some(error) = &observation.error {
        anyhow::bail!("{error}");
    }
    if let Some(error) = &finalization.error {
        anyhow::bail!("{error}");
    }
    if !correctness {
        anyhow::bail!("load correctness failures recorded;diagnostic measurements retained");
    }
    println!(
        "SocketBenchmarkLoadObserved: report={} qualified=false",
        path.display()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::net::UnixDatagram;
    use std::sync::{Arc, Barrier};
    fn config(mode: Mode) -> LoadConfig {
        LoadConfig {
            mode,
            count: 64,
            bytes: 61,
            window: 8,
            interval_us: if mode == Mode::Rate { 500 } else { 0 },
        }
    }
    fn pair() -> (OwnedFd, OwnedFd) {
        let (a, b) = UnixDatagram::pair().unwrap();
        a.set_nonblocking(true).unwrap();
        b.set_nonblocking(true).unwrap();
        (a.into(), b.into())
    }
    fn bounded(fd: &OwnedFd, state: &mut State) -> Observation {
        drive(fd, state, 1_000_000_000, 5_000_000, 2_000_000_000)
    }
    fn assert_source(state: &State) {
        assert_eq!(state.next, state.config.count);
        assert_eq!(state.inflight, 0);
        assert!(state.outstanding.is_empty());
        for row in &state.outgoing {
            assert!(row.validated_ns.is_some() && !row.timed_out && !row.late);
            assert!(row.planned_ns <= row.dispatch_ns && row.dispatch_ns <= row.first_syscall_ns);
            assert!(row.first_syscall_ns <= row.syscall_ns && row.syscall_ns <= row.admitted_ns);
            assert!(row.admitted_ns <= row.read_ns && row.read_ns <= row.validated_ns);
            assert!(row.validated_ns < row.deadline_ns);
            assert_eq!(row.reply_count, 1);
        }
        assert!(state.counters.inflight_peak <= state.config.window);
        assert!(state.correctness());
    }
    #[test]
    fn real_local_datagrams_window_and_absolute_rate_have_actual_peer_replies() {
        for mode in [Mode::Rate, Mode::Window] {
            let (a, b) = pair();
            let config = config(mode);
            let mut source = State::new(config).unwrap();
            let mut peer = State::new(LoadConfig {
                mode: Mode::Peer,
                interval_us: 0,
                ..config
            })
            .unwrap();
            let gate = Arc::new(Barrier::new(2));
            let other = gate.clone();
            let task = std::thread::spawn(move || {
                other.wait();
                let o = bounded(&b, &mut peer);
                assert!(o.error.is_none(), "{:?}", o.error);
                peer
            });
            gate.wait();
            let observed = bounded(&a, &mut source);
            assert!(observed.error.is_none(), "{:?}", observed.error);
            let peer = task.join().unwrap();
            assert_source(&source);
            assert_eq!(peer.seen, config.count);
            assert_eq!(peer.counters.reply_queue_overflow, 0);
            assert!(peer.correctness());
            assert_eq!(source.counters.corrupt_packets, 0);
            for i in 0..config.count {
                let mut expected = source.prepared.frames[i].clone();
                expected[28] = 1;
                assert_eq!(source.prepared.received[i], expected);
                assert_eq!(peer.peer.frames[i], expected);
                assert!(peer.incoming[i].reply_admitted_ns.is_some());
                if mode == Mode::Rate {
                    assert_eq!(
                        source.outgoing[i].planned_ns,
                        Some(i as u64 * config.interval_us * 1000)
                    );
                }
            }
        }
    }
    #[test]
    fn same_load_loop_validates_length_boundaries_and_long_datagrams() {
        for bytes in [249, 250, 253, 254, 255, 1024, 2042] {
            let (a, b) = pair();
            let cfg = LoadConfig {
                bytes,
                count: 16,
                ..config(Mode::Window)
            };
            let mut source = State::new(cfg).unwrap();
            let mut peer = State::new(LoadConfig {
                mode: Mode::Peer,
                ..cfg
            })
            .unwrap();
            let task = std::thread::spawn(move || {
                let o = bounded(&b, &mut peer);
                assert!(o.error.is_none(), "{:?}", o.error);
                peer
            });
            let o = bounded(&a, &mut source);
            assert!(o.error.is_none(), "{:?}", o.error);
            let peer = task.join().unwrap();
            assert_source(&source);
            assert!(peer.correctness());
            assert!(
                source
                    .prepared
                    .received
                    .iter()
                    .all(|frame| frame.len() == bytes)
            );
        }
    }

    #[test]
    fn real_local_datagrams_duplex_routes_requests_and_replies_without_echoing_wrong_lanes() {
        let (a, b) = pair();
        let cfg = config(Mode::Duplex);
        let mut left = State::new(cfg).unwrap();
        let mut right = State::new(cfg).unwrap();
        let gate = Arc::new(Barrier::new(2));
        let other = gate.clone();
        let task = std::thread::spawn(move || {
            other.wait();
            let o = bounded(&b, &mut right);
            assert!(o.error.is_none(), "{:?}", o.error);
            right
        });
        gate.wait();
        let o = bounded(&a, &mut left);
        assert!(o.error.is_none(), "{:?}", o.error);
        let right = task.join().unwrap();
        for s in [&left, &right] {
            assert_source(s);
            assert_eq!(s.seen, cfg.count);
            assert!(s.reply_queue.is_empty());
            assert_eq!(s.counters.corrupt_packets, 0);
            assert_eq!(s.counters.reply_queue_overflow, 0);
        }
        assert_ne!(left.prepared.frames[0], right.prepared.frames[0]);
    }
    #[test]
    fn absolute_rate_never_waits_for_missing_peer_and_keeps_local_budget_refusals_separate() {
        let (a, _b) = pair();
        let cfg = LoadConfig {
            mode: Mode::Rate,
            count: 16,
            bytes: 61,
            window: 2,
            interval_us: 100,
        };
        let mut s = State::new(cfg).unwrap();
        let o = drive(&a, &mut s, 20_000_000, 2_000_000, 100_000_000);
        assert!(o.error.is_none(), "{:?}", o.error);
        assert_eq!(s.next, 16);
        assert_eq!(
            s.outgoing
                .iter()
                .filter(|r| r.local_budget_rejected)
                .count(),
            14
        );
        assert_eq!(s.outgoing.iter().filter(|r| r.timed_out).count(), 2);
        for (i, r) in s.outgoing.iter().enumerate() {
            assert_eq!(r.planned_ns, Some(i as u64 * 100_000));
            if r.local_budget_rejected {
                assert!(r.errno.is_none());
                assert_eq!(r.send_attempts, 0);
            }
        }
        assert!(s.inflight == 0 && s.outstanding.is_empty());
        assert!(o.elapsed_ns < 100_000_000);
    }
    #[test]
    fn real_local_socket_backpressure_records_kernel_eagain_without_shifting_schedule() {
        let (a, _b) = pair();
        let size: nix::libc::c_int = 4096;
        // SAFETY: complete initialized integer and live test-only socket.
        assert_eq!(
            unsafe {
                nix::libc::setsockopt(
                    a.as_raw_fd(),
                    nix::libc::SOL_SOCKET,
                    nix::libc::SO_SNDBUF,
                    (&size as *const nix::libc::c_int).cast(),
                    std::mem::size_of_val(&size) as _,
                )
            },
            0
        );
        let cfg = LoadConfig {
            mode: Mode::Rate,
            count: 128,
            bytes: 2042,
            window: 128,
            interval_us: 10,
        };
        let mut s = State::new(cfg).unwrap();
        let o = drive(&a, &mut s, 20_000_000, 2_000_000, 100_000_000);
        assert!(o.error.is_none(), "{:?}", o.error);
        assert!(
            s.outgoing
                .iter()
                .any(|r| r.errno == Some(nix::libc::EAGAIN))
        );
        assert_eq!(s.next, 128);
        for (i, r) in s.outgoing.iter().enumerate() {
            assert_eq!(r.planned_ns, Some(i as u64 * 10_000));
            assert_eq!(r.send_attempts, 1);
        }
        assert!(o.elapsed_ns < 100_000_000);
        assert!(s.counters.poll_calls > 0);
    }
    #[test]
    fn production_packet_conversion_keeps_late_duplicate_corrupt_and_reordered_results_distinct() {
        let (a, _b) = pair();
        let cfg = LoadConfig {
            count: 3,
            window: 3,
            ..config(Mode::Window)
        };
        let mut s = State::new(cfg).unwrap();
        s.try_source(&a, Instant::now(), 1_000_000_000).unwrap();
        assert_eq!(s.inflight, 3);
        let mut reply = s.prepared.frames[1].clone();
        reply[28] = 1;
        let admitted = s.outgoing[1].admitted_ns.unwrap();
        s.packet(&reply, admitted + 1, || admitted + 2, 1_000_000_000)
            .unwrap();
        assert_eq!(s.inflight, 2);
        s.packet(&reply, admitted + 3, || admitted + 4, 1_000_000_000)
            .unwrap();
        assert_eq!(s.inflight, 2);
        assert_eq!(s.counters.duplicate_replies, 1);
        let deadline = s.outgoing[0].deadline_ns.unwrap();
        s.expired(u64::MAX / 2);
        assert_eq!(s.inflight, 0);
        reply = s.prepared.frames[0].clone();
        reply[28] = 1;
        s.packet(&reply, deadline + 1, || deadline + 2, 1000)
            .unwrap();
        assert!(s.outgoing[0].late && s.outgoing[0].timed_out);
        assert_eq!(s.counters.reordered_replies, 1);
        assert_eq!(s.inflight, 0);
        reply = s.prepared.frames[2].clone();
        reply[28] = 1;
        reply[60] ^= 1;
        s.packet(&reply, 4, || 5, 1000).unwrap();
        assert_eq!(s.counters.corrupt_packets, 1);
        assert!(s.outgoing[2].validated_ns.is_none());
    }
    #[test]
    fn peer_budget_overflow_does_not_invent_reply_or_extend_original_deadlines() {
        let cfg = LoadConfig {
            mode: Mode::Peer,
            count: 2,
            window: 1,
            bytes: 61,
            interval_us: 0,
        };
        let mut peer = State::new(cfg).unwrap();
        let inputs = Prepared::new(
            Config {
                count: 2,
                bytes: 61,
            },
            false,
        )
        .unwrap();
        peer.packet(&inputs.frames[0], 10, || 11, 100).unwrap();
        let deadline = peer.incoming[0].deadline_ns;
        peer.packet(&inputs.frames[0], 70, || 71, 100).unwrap();
        assert_eq!(peer.incoming[0].deadline_ns, deadline);
        assert_eq!(peer.last_unique_request_ns, Some(11));
        assert_eq!(deadline, Some(110));
        peer.packet(&inputs.frames[1], 80, || 81, 100).unwrap();
        assert_eq!(peer.seen, 2);
        assert_eq!(peer.counters.reply_queue_overflow, 1);
        assert!(
            peer.incoming[1].validated_ns.is_some() && peer.incoming[1].reply_admitted_ns.is_none()
        );
        assert!(!peer.correctness());
        assert_eq!(peer.reply_queue.len(), 1);
        assert_eq!(peer.incoming.len(), 2);
    }
    #[test]
    fn actual_start_input_is_explicit_and_partial_input_keeps_one_original_deadline() {
        use std::io::Write;
        use std::os::unix::net::UnixStream;
        for input in [b"start\n".as_slice(), b"wrong\n", b"st"] {
            let (mut writer, reader) = UnixStream::pair().unwrap();
            writer.write_all(input).unwrap();
            let result = read_start(reader.as_raw_fd(), Duration::from_millis(5));
            assert_eq!(result.is_ok(), input == b"start\n");
            if input == b"st" {
                assert!(format!("{:#}", result.unwrap_err()).contains("deadline"));
            }
        }
        let (writer, reader) = UnixStream::pair().unwrap();
        drop(writer);
        assert!(
            format!(
                "{:#}",
                read_start(reader.as_raw_fd(), Duration::from_secs(1)).unwrap_err()
            )
            .contains("EOF")
        );
    }
    #[test]
    fn resource_probe_reports_its_process_scope_without_inventing_kernel_counters() {
        let value = resources().unwrap();
        assert!(value.open_fds > 0 && value.page_bytes > 0);
        assert!(value.process_lifetime_maxrss_kib > 0);
    }

    #[test]
    fn finite_config_rejects_zero_unbounded_or_overflowing_inputs() {
        for c in [
            LoadConfig {
                window: 0,
                ..config(Mode::Window)
            },
            LoadConfig {
                window: 257,
                count: 1000,
                ..config(Mode::Window)
            },
            LoadConfig {
                interval_us: u64::MAX,
                ..config(Mode::Rate)
            },
            LoadConfig {
                interval_us: 1,
                ..config(Mode::Rate)
            },
            LoadConfig {
                interval_us: 1_000_000,
                count: 10000,
                ..config(Mode::Rate)
            },
            LoadConfig {
                interval_us: 1,
                ..config(Mode::Window)
            },
        ] {
            assert!(c.validate().is_err());
        }
    }
    #[test]
    fn actual_finish_barrier_rejects_partial_wrong_eof_and_keeps_failure_atomic() {
        use std::io::Write;
        use std::os::unix::net::UnixStream;
        for input in [b"finish\n".as_slice(), b"wrong!\n", b"fi"] {
            let (mut writer, reader) = UnixStream::pair().unwrap();
            writer.write_all(input).unwrap();
            let value = finish(reader.as_raw_fd(), Duration::from_millis(10));
            assert_eq!(value.completed, input == b"finish\n");
            assert_eq!(value.error.is_none(), value.completed);
            if input == b"fi" {
                assert!(value.error.unwrap().contains("deadline"));
            }
        }
        let (writer, reader) = UnixStream::pair().unwrap();
        drop(writer);
        let value = finish(reader.as_raw_fd(), Duration::from_secs(1));
        assert!(!value.completed && value.error.unwrap().contains("EOF"));
    }

    #[test]
    fn production_serializer_exports_real_local_pair_reports_for_independent_checker() {
        use std::io::Write;
        use std::os::unix::net::UnixStream;
        for mode in [Mode::Rate, Mode::Window, Mode::Duplex] {
            let (a, b) = pair();
            let cfg = LoadConfig {
                count: 8,
                window: 8,
                interval_us: if mode == Mode::Rate { 10000 } else { 0 },
                ..config(mode)
            };
            let mut left = State::new(cfg).unwrap();
            let right_cfg = if mode == Mode::Duplex {
                cfg
            } else {
                LoadConfig {
                    mode: Mode::Peer,
                    interval_us: 0,
                    ..cfg
                }
            };
            let mut right = State::new(right_cfg).unwrap();
            let before = resources();
            let gate = Arc::new(Barrier::new(2));
            let other = gate.clone();
            let task = std::thread::spawn(move || {
                other.wait();
                let o = drive(&b, &mut right, REQUEST_NS, GRACE_NS, RUN_NS);
                (right, o)
            });
            gate.wait();
            let observed = drive(&a, &mut left, REQUEST_NS, GRACE_NS, RUN_NS);
            let (mut right, right_observed) = task.join().unwrap();
            assert!(observed.error.is_none() && right_observed.error.is_none());
            assert!(left.correctness() && right.correctness());
            // Both actual loops are now quiescent; authorize finalization.
            let (mut control, reader) = UnixStream::pair().unwrap();
            control.write_all(b"finish\nfinish\n").unwrap();
            let end_left = finish(reader.as_raw_fd(), Duration::from_secs(1));
            let end_right = finish(reader.as_raw_fd(), Duration::from_secs(1));
            assert!(end_left.completed && end_right.completed);
            let summary = resource_summary(before, resources());
            let mut pair_reports = Vec::new();
            for (index, (state, observation, end)) in [
                (&mut left, &observed, &end_left),
                (&mut right, &right_observed, &end_right),
            ]
            .into_iter()
            .enumerate()
            {
                let info = slk_protocol::channel::SleChannelInfo {
                    version: 1,
                    size: 40,
                    controller: index as u16,
                    generation: 7 + index as u64,
                    lifetime: 11 + index as u64,
                    handle: 0,
                    mtu: 2042,
                    mps: 2047,
                    local_tcid: 31,
                    remote_tcid: 31,
                    pi: 241,
                    directions: 3,
                    ..Default::default()
                };
                info.validate().unwrap();
                let mut value = report(state, observation, &info, summary.clone(), end);
                value["test_fixture"] = serde_json::json!(
                    "AF_UNIX actual production drive/report;identity fixture,notNative or RF;finish budget1s"
                );
                assert_eq!(value["correctness"], true);
                assert_eq!(
                    value["summary"]["scheduled"],
                    if state.config.active() { 8 } else { 0 }
                );
                pair_reports.push(value);
            }
            if let Some(root) = std::env::var_os("SLKTEST_REPORT_FIXTURE_DIR") {
                let root = std::path::PathBuf::from(root);
                std::fs::create_dir_all(&root).unwrap();
                let name = format!("{mode:?}").to_lowercase();
                for (n, value) in pair_reports.iter().enumerate() {
                    let mut file = std::fs::OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .open(root.join(format!("{name}-{n}.json")))
                        .unwrap();
                    serde_json::to_writer(&mut file, value).unwrap();
                    file.write_all(b"\n").unwrap();
                }
            }
        }
    }
    #[test]
    fn failed_finish_preserves_original_observation_and_all_scheduled_rows() {
        let mut state = State::new(config(Mode::Rate)).unwrap();
        let observation = Observation {
            elapsed_ns: 20,
            active_elapsed_ns: 20,
            error: Some("original driver error fixture".into()),
        };
        let end = Finalization {
            completed: false,
            budget_ns: 30_000_000_000,
            elapsed_ns: 10,
            error: Some("finish EOF fixture".into()),
        };
        let value = report(
            &mut state,
            &observation,
            &Default::default(),
            serde_json::json!({"incomplete":true}),
            &end,
        );
        assert_eq!(value["status"], "INCOMPLETE");
        assert_eq!(value["correctness"], false);
        assert_eq!(
            value["observation"]["error"],
            "original driver error fixture"
        );
        assert_eq!(value["finalization"]["error"], "finish EOF fixture");
        assert_eq!(value["outgoing"].as_array().unwrap().len(), 64);
        assert_eq!(value["summary"]["unattempted"], 64);
    }
}
