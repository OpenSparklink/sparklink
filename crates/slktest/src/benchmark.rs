//! Low-perturbation application ping-pong, over the normal delegated channel.
//! This is a measurement tool, not a Host, protocol Engine or qualification oracle.
mod load;
pub(crate) use load::{LoadConfig, Mode as LoadMode, read_start, run_load};

use std::collections::{BTreeSet, HashSet};
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::fd::{AsRawFd, OwnedFd};
use std::path::Path;
use std::time::{Duration, Instant};

use serde::Serialize;

const DEADLINE: Duration = Duration::from_secs(10);

#[derive(Clone, Copy, Serialize)]
pub(crate) struct Config {
    pub count: usize,
    pub bytes: usize,
}
impl Config {
    pub(crate) fn validate(self) -> anyhow::Result<()> {
        if !(1..=10_000).contains(&self.count) || !(29..=2042).contains(&self.bytes) {
            anyhow::bail!("benchmark count must be1..10000 and bytes29..2042");
        }
        Ok(())
    }
}

#[derive(Default, Serialize)]
struct Sample {
    index: usize,
    // Local relative monotonic ns. No cross-endpoint subtraction is permitted.
    planned_ns: Option<u64>,
    first_syscall_ns: Option<u64>,
    syscall_ns: Option<u64>,
    send_attempts: u32,
    would_block: u32,
    admitted_ns: Option<u64>,
    read_ns: Option<u64>,
    validated_ns: Option<u64>,
    errno: Option<i32>,
    timed_out: bool,
    late: bool,
    frame_hex: String, // Filled only after measurement, never in the hot loop.
}

#[derive(Debug, Serialize)]
struct Distribution {
    successful_samples: usize,
    min_ns: u64,
    p50_ns: u64,
    p90_ns: u64,
    p95_ns: u64,
    p99_ns: u64,
    p999_ns: Option<u64>,
    max_ns: u64,
}
fn distribution(values: &mut [u64]) -> Option<Distribution> {
    if values.is_empty() {
        return None;
    }
    values.sort_unstable();
    // Nearest-rank percentile (ceil(p*n)-1), never invented empty samples.
    let rank = |p: usize, denominator: usize| values[(p * values.len()).div_ceil(denominator) - 1];
    Some(Distribution {
        successful_samples: values.len(),
        min_ns: values[0],
        p50_ns: rank(50, 100),
        p90_ns: rank(90, 100),
        p95_ns: rank(95, 100),
        p99_ns: rank(99, 100),
        p999_ns: (values.len() >= 10_000).then(|| rank(999, 1000)),
        max_ns: values[values.len() - 1],
    })
}

fn ns(origin: Instant) -> u64 {
    origin
        .elapsed()
        .as_nanos()
        .try_into()
        .expect("bounded benchmark clock")
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

struct Prepared {
    frames: Vec<Vec<u8>>,
    received: Vec<Vec<u8>>,
    samples: Vec<Sample>,
    seen_sequences: HashSet<u32>,
    seen_nonces: HashSet<[u8; 16]>,
}
impl Prepared {
    fn new(config: Config, responder: bool) -> anyhow::Result<Self> {
        config.validate()?;
        let mut random = File::open("/dev/urandom")?;
        let mut sequences = BTreeSet::new();
        let mut nonces = BTreeSet::new();
        let mut frames = Vec::with_capacity(config.count);
        for _ in 0..config.count {
            let mut frame = vec![0; config.bytes];
            if !responder {
                frame[..8].copy_from_slice(b"SLKSOCK1");
                // Random wire sequence collisions are possible at10000 messages.
                // Retry before timing, with a finite bound; do not create flaky runs.
                let mut sequence = None;
                for _ in 0..128 {
                    random.read_exact(&mut frame[8..28])?;
                    let candidate = u32::from_le_bytes(frame[24..28].try_into()?);
                    if !sequences.contains(&candidate) && !nonces.contains(&frame[8..24]) {
                        sequences.insert(candidate);
                        nonces.insert(frame[8..24].to_vec());
                        sequence = Some(candidate);
                        break;
                    }
                }
                let sequence = sequence.ok_or_else(|| {
                    anyhow::anyhow!("random sequence/nonce budget exhausted before timing")
                })?;
                for i in 0..config.bytes - 29 {
                    frame[29 + i] = frame[8 + i % 16] ^ (sequence as u8).wrapping_add(i as u8);
                }
            }
            frames.push(frame);
        }
        Ok(Self {
            seen_sequences: HashSet::with_capacity(config.count),
            seen_nonces: HashSet::with_capacity(config.count),
            frames,
            received: vec![vec![0; config.bytes]; config.count],
            samples: (0..config.count)
                .map(|index| Sample {
                    index,
                    ..Sample::default()
                })
                .collect(),
        })
    }
}

fn send(
    fd: &OwnedFd,
    frame: &[u8],
    deadline: Instant,
    origin: Instant,
    row: &mut Sample,
) -> anyhow::Result<()> {
    loop {
        crate::channel::wait(fd, nix::libc::POLLOUT, deadline)?;
        let started = ns(origin);
        // SAFETY: complete live immutable frame and borrowed owned socket.
        let result = unsafe {
            nix::libc::send(
                fd.as_raw_fd(),
                frame.as_ptr().cast(),
                frame.len(),
                nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
            )
        };
        let returned = ns(origin);
        row.first_syscall_ns.get_or_insert(started);
        row.send_attempts += 1;
        if result == frame.len() as isize {
            row.syscall_ns = Some(started);
            row.admitted_ns = Some(returned);
            return Ok(());
        }
        if result >= 0 {
            anyhow::bail!("partial datagram admission");
        }
        let error = std::io::Error::last_os_error();
        if error.kind() == std::io::ErrorKind::WouldBlock {
            row.would_block += 1;
            continue;
        }
        row.errno = error.raw_os_error();
        return Err(error.into());
    }
}
fn receive(
    fd: &OwnedFd,
    frame: &mut [u8],
    deadline: Instant,
    origin: Instant,
    row: &mut Sample,
) -> anyhow::Result<()> {
    loop {
        crate::channel::wait(fd, nix::libc::POLLIN, deadline)?;
        // SAFETY: exclusively borrowed bounded initialized receive buffer.
        let result = unsafe {
            nix::libc::recv(
                fd.as_raw_fd(),
                frame.as_mut_ptr().cast(),
                frame.len(),
                nix::libc::MSG_DONTWAIT | nix::libc::MSG_TRUNC,
            )
        };
        let returned = ns(origin);
        if result == frame.len() as isize {
            row.read_ns = Some(returned);
            return Ok(());
        }
        if result >= 0 {
            anyhow::bail!("empty/truncated/wrong-size benchmark datagram: {result}");
        }
        let error = std::io::Error::last_os_error();
        if error.kind() == std::io::ErrorKind::WouldBlock {
            continue;
        }
        row.errno = error.raw_os_error();
        return Err(error.into());
    }
}

fn validated(row: &mut Sample, now_ns: u64, deadline_ns: u64) -> anyhow::Result<()> {
    row.validated_ns = Some(now_ns);
    if now_ns >= deadline_ns {
        row.late = true;
        row.timed_out = true;
        anyhow::bail!("validation completed after original deadline");
    }
    Ok(())
}

fn measure(
    fd: &OwnedFd,
    responder: bool,
    prepared: &mut Prepared,
    timeout: Duration,
) -> (u64, Option<String>) {
    // Allocation, random generation and report formatting are outside this interval.
    let origin = Instant::now();
    for index in 0..prepared.samples.len() {
        let row = &mut prepared.samples[index];
        let deadline = Instant::now() + timeout;
        row.planned_ns = Some(ns(origin)); // Closed-loop: next begins after preceding completion.
        let result = (|| -> anyhow::Result<()> {
            if responder {
                let frame = &mut prepared.frames[index];
                receive(fd, frame, deadline, origin, row)?;
                let sequence = u32::from_le_bytes(frame[24..28].try_into()?);
                crate::channel::validate(frame, sequence, false, frame.len())?;
                // Capacity is reserved before timing, insertion cannot grow.
                let nonce: [u8; 16] = frame[8..24].try_into()?;
                if !prepared.seen_sequences.insert(sequence) || !prepared.seen_nonces.insert(nonce)
                {
                    anyhow::bail!("duplicate peer sequence/nonce");
                }
                prepared.received[index].copy_from_slice(frame);
                validated(
                    row,
                    ns(origin),
                    deadline.duration_since(origin).as_nanos().try_into()?,
                )?;
                frame[28] = 1;
                send(fd, frame, deadline, origin, row)?;
            } else {
                send(fd, &prepared.frames[index], deadline, origin, row)?;
                receive(fd, &mut prepared.received[index], deadline, origin, row)?;
                let request = &mut prepared.frames[index];
                request[28] = 1;
                if prepared.received[index] != *request {
                    anyhow::bail!("reply differs from precomputed random request");
                }
                validated(
                    row,
                    ns(origin),
                    deadline.duration_since(origin).as_nanos().try_into()?,
                )?;
            }
            Ok(())
        })();
        if let Err(error) = result {
            row.timed_out |= Instant::now() >= deadline;
            // Stop this one-outstanding workload on first failure. Remaining
            // samples remain present/unattempted; never report a complete PASS.
            return (ns(origin), Some(format!("sample {index}: {error:#}")));
        }
    }
    (ns(origin), None)
}

#[derive(Serialize)]
struct Report {
    schema_version: u32,
    status: &'static str,
    performance_qualified: bool,
    workload: &'static str,
    responder: bool,
    config: Config,
    clock: &'static str,
    rtt_definition: &'static str,
    percentile_method: &'static str,
    // Unknown stage timings/resources stay absent, never infer them from admission.
    unmeasured: Vec<&'static str>,
    channel_identity: serde_json::Value,
    elapsed_ns: u64,
    attempted: usize,
    admitted: usize,
    validated: usize,
    timed_out: usize,
    late: usize,
    unattempted: usize,
    success_only_rtt: Option<Distribution>,
    error: Option<String>,
    samples: Vec<Sample>,
}

/// Reserve a new output file: failures/panics cannot reuse an old successful file.
/// Caller supplies the normal delegated Native fd; no alternate data path exists.
pub(crate) fn run(fd: OwnedFd, responder: bool, config: Config, path: &Path) -> anyhow::Result<()> {
    config.validate()?;
    let mut output = OpenOptions::new().write(true).create_new(true).open(path)?;
    output.write_all(
        b"{\"schema_version\":1,\"status\":\"INCOMPLETE\",\"performance_qualified\":false}\n",
    )?;
    let mut prepared = Prepared::new(config, responder)?;
    // Existing finite linger prevents final reply admission from being silently
    // discarded at peer last-close. Only source validation proves delivery.
    let fd = crate::channel::prepare_application_fd(fd)?;
    crate::channel::wait(&fd, nix::libc::POLLOUT, Instant::now() + DEADLINE)?;
    let info = slk_protocol::channel::query(fd.as_raw_fd())?;
    if info.mode != 0
        || info.directions != 3
        || usize::from(info.mtu) < config.bytes
        || usize::from(info.mps) < config.bytes + 5
        || info.local_tcid != 31
        || info.remote_tcid != 31
        || info.pi != 241
    {
        anyhow::bail!("benchmark requires the current bidirectional basic CUTC contract");
    }
    println!(
        "SocketBenchmarkReady: responder={responder} count={} bytes={}",
        config.count, config.bytes
    );
    let (elapsed_ns, error) = measure(&fd, responder, &mut prepared, DEADLINE);
    let mut values: Vec<_> = prepared
        .samples
        .iter()
        .filter_map(|s| {
            if responder || s.timed_out {
                None
            } else {
                s.validated_ns
                    .zip(s.syscall_ns)
                    .map(|(end, start)| end - start)
            }
        })
        .collect();
    for (row, frame) in prepared.samples.iter_mut().zip(&prepared.frames) {
        if row.planned_ns.is_some() {
            row.frame_hex = hex(frame);
        }
    }
    let report = Report {
        schema_version: 1,
        status: if error.is_some() {
            "INCOMPLETE"
        } else {
            "MEASURED_NOT_QUALIFIED"
        },
        performance_qualified: false,
        workload: "ping-pong-one-outstanding",
        responder,
        config,
        clock: "process-local-Rust-Instant-relative-nanoseconds",
        rtt_definition: "successful send syscall entry to validated reply, same initiator clock",
        percentile_method: "nearest-rank;success-only;p99.9 requires10000 successes",
        unmeasured: vec![
            "artifact/source/firmware provenance closure",
            "peer report/capture closure",
            "USB/Session/NOCP timeline",
            "CPU/RSS/fd/worker/timer/URB/queue/credit resources",
            "trace overhead",
            "fixed-rate and bidirectional-window workloads",
        ],
        channel_identity: serde_json::json!({"controller":info.controller,"generation":info.generation,"lifetime":info.lifetime,"handle":info.handle,"local_tcid":info.local_tcid,"remote_tcid":info.remote_tcid,"pi":info.pi,"mtu":info.mtu,"mps":info.mps,"mode":info.mode,"directions":info.directions}),
        elapsed_ns,
        attempted: prepared
            .samples
            .iter()
            .filter(|s| s.planned_ns.is_some())
            .count(),
        admitted: prepared
            .samples
            .iter()
            .filter(|s| s.admitted_ns.is_some())
            .count(),
        validated: prepared
            .samples
            .iter()
            .filter(|s| s.validated_ns.is_some())
            .count(),
        timed_out: prepared.samples.iter().filter(|s| s.timed_out).count(),
        late: prepared.samples.iter().filter(|s| s.late).count(),
        unattempted: prepared
            .samples
            .iter()
            .filter(|s| s.planned_ns.is_none())
            .count(),
        success_only_rtt: distribution(&mut values),
        error,
        samples: prepared.samples,
    };
    // Serialization and disk I/O only after the measured interval.
    use std::io::{Seek, SeekFrom};
    output.seek(SeekFrom::Start(0))?;
    output.set_len(0)?;
    serde_json::to_writer(&mut output, &report)?;
    output.write_all(b"\n")?;
    if let Some(error) = report.error {
        anyhow::bail!("{error}");
    }
    println!(
        "SocketBenchmarkMeasured: report={} qualified=false",
        path.display()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::net::UnixDatagram;

    #[test]
    fn actual_application_ping_pong_uses_per_message_clock_and_random_validation() {
        let (a, b) = UnixDatagram::pair().unwrap();
        a.set_nonblocking(true).unwrap();
        b.set_nonblocking(true).unwrap();
        let a: OwnedFd = a.into();
        let b: OwnedFd = b.into();
        let config = Config {
            count: 32,
            bytes: 61,
        };
        let mut source = Prepared::new(config, false).unwrap();
        let mut peer = Prepared::new(config, true).unwrap();
        let task = std::thread::spawn(move || {
            let (_, error) = measure(&b, true, &mut peer, Duration::from_secs(1));
            assert!(error.is_none(), "{error:?}");
            peer
        });
        let (_, error) = measure(&a, false, &mut source, Duration::from_secs(1));
        assert!(error.is_none(), "{error:?}");
        let peer = task.join().unwrap();
        for (i, (s, p)) in source.samples.iter().zip(&peer.samples).enumerate() {
            assert!(
                s.planned_ns <= s.syscall_ns
                    && s.syscall_ns <= s.admitted_ns
                    && s.admitted_ns <= s.read_ns
                    && s.read_ns <= s.validated_ns
            );
            assert!(p.read_ns <= p.validated_ns && p.validated_ns <= p.syscall_ns);
            assert_eq!(source.frames[i], peer.frames[i]);
            if i > 0 {
                assert!(source.samples[i - 1].validated_ns <= s.planned_ns);
            }
        }
    }

    #[test]
    fn absent_peer_preserves_timeout_and_unattempted_samples() {
        let (a, _b) = UnixDatagram::pair().unwrap();
        a.set_nonblocking(true).unwrap();
        let mut p = Prepared::new(
            Config {
                count: 3,
                bytes: 61,
            },
            false,
        )
        .unwrap();
        let (_, error) = measure(&a.into(), false, &mut p, Duration::from_millis(5));
        assert!(error.is_some());
        assert!(p.samples[0].timed_out);
        assert!(p.samples[0].admitted_ns.is_some());
        assert!(p.samples[0].validated_ns.is_none());
        assert!(p.samples[1].planned_ns.is_none());
        assert_eq!(p.samples.len(), 3);
    }

    #[test]
    fn modified_reply_is_not_a_successful_sample() {
        let (a, b) = UnixDatagram::pair().unwrap();
        a.set_nonblocking(true).unwrap();
        let peer = std::thread::spawn(move || {
            let mut frame = [0; 61];
            b.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
            assert_eq!(b.recv(&mut frame).unwrap(), 61);
            frame[28] = 1;
            frame[60] ^= 1;
            b.send(&frame).unwrap();
        });
        let mut p = Prepared::new(
            Config {
                count: 2,
                bytes: 61,
            },
            false,
        )
        .unwrap();
        let (_, error) = measure(&a.into(), false, &mut p, Duration::from_secs(1));
        peer.join().unwrap();
        assert!(error.unwrap().contains("differs"));
        assert!(p.samples[0].read_ns.is_some());
        assert!(p.samples[0].validated_ns.is_none());
        assert!(p.samples[1].planned_ns.is_none());
    }

    #[test]
    fn repeated_request_is_rejected_by_actual_peer_loop() {
        let (a, b) = UnixDatagram::pair().unwrap();
        b.set_nonblocking(true).unwrap();
        let frame = Prepared::new(
            Config {
                count: 1,
                bytes: 61,
            },
            false,
        )
        .unwrap()
        .frames
        .remove(0);
        a.send(&frame).unwrap();
        a.send(&frame).unwrap();
        let mut p = Prepared::new(
            Config {
                count: 2,
                bytes: 61,
            },
            true,
        )
        .unwrap();
        let (_, error) = measure(&b.into(), true, &mut p, Duration::from_secs(1));
        assert!(error.unwrap().contains("duplicate"));
        assert!(p.samples[0].validated_ns.is_some());
        assert!(p.samples[1].validated_ns.is_none());
    }

    #[test]
    fn failed_native_setup_leaves_only_incomplete_marker_and_cannot_overwrite() {
        let path = std::env::temp_dir().join(format!(
            "slktest-benchmark-test-{}.json",
            std::process::id()
        ));
        // Exclusive creation also tests the path is not silently reused.
        assert!(!path.exists());
        let (a, _b) = UnixDatagram::pair().unwrap();
        let error = run(
            a.into(),
            false,
            Config {
                count: 1,
                bytes: 61,
            },
            &path,
        )
        .unwrap_err();
        assert!(
            format!("{error:#}").contains("ioctl") || format!("{error:#}").contains("os error")
        );
        let original = std::fs::read(&path).unwrap();
        let v: serde_json::Value = serde_json::from_slice(&original).unwrap();
        assert_eq!(v["status"], "INCOMPLETE");
        assert_eq!(v["performance_qualified"], false);
        let (a, _b) = UnixDatagram::pair().unwrap();
        assert!(
            run(
                a.into(),
                false,
                Config {
                    count: 1,
                    bytes: 61
                },
                &path
            )
            .is_err()
        );
        assert_eq!(std::fs::read(&path).unwrap(), original);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn actual_validation_transition_classifies_original_deadline_boundary_as_late() {
        for (now, expired) in [(9, false), (10, true), (11, true)] {
            let mut row = Sample::default();
            assert_eq!(validated(&mut row, now, 10).is_err(), expired);
            assert_eq!(row.validated_ns, Some(now));
            assert_eq!(row.late, expired);
            assert_eq!(row.timed_out, expired);
        }
    }

    #[test]
    fn exact_percentiles_and_empty_small_sample_contract() {
        assert!(distribution(&mut []).is_none());
        let d = distribution(&mut [4, 1, 3, 2]).unwrap();
        assert_eq!(d.min_ns, 1);
        assert_eq!(d.p50_ns, 2);
        assert_eq!(d.p99_ns, 4);
        assert!(d.p999_ns.is_none());
        let mut n: Vec<_> = (1..=10000).rev().collect();
        assert_eq!(distribution(&mut n).unwrap().p999_ns, Some(9990));
        assert!(
            Config {
                count: 0,
                bytes: 61
            }
            .validate()
            .is_err()
        );
        assert!(
            Config {
                count: 1,
                bytes: 28
            }
            .validate()
            .is_err()
        );
    }
}
