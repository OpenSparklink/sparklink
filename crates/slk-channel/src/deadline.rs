//! Original local Linux CLOCK_MONOTONIC deadlines, not relative RPC budgets.
//! Trusted procfs supplies clock-domain identity; this is not caller attestation.
use slk_protocol::deadline::DeadlineStamp;
use std::{
    fs::File,
    io::{self, Read},
    os::unix::fs::MetadataExt,
    time::{Duration, Instant},
};

pub const MAX_WAIT: Duration = Duration::from_secs(30);
pub const PROTOCOL_WAIT: Duration = Duration::from_secs(5);
/// Local waiting needs no procfs/domain metadata. Cross-process operations
/// separately capture and validate their domain, without burdening local APIs.
pub fn local_instant_from_monotonic_ns(value: u64) -> io::Result<Instant> {
    let start = Instant::now();
    let now = monotonic_ns()?;
    let left = value
        .checked_sub(now)
        .filter(|n| *n != 0)
        .ok_or_else(|| error(nix::libc::ETIMEDOUT))?;
    if Duration::from_nanos(left) > MAX_WAIT {
        return Err(error(nix::libc::EINVAL));
    }
    Ok(start + Duration::from_nanos(left))
}
pub fn remaining(at: Instant) -> io::Result<Duration> {
    at.checked_duration_since(Instant::now())
        .filter(|n| !n.is_zero())
        .ok_or_else(|| error(nix::libc::ETIMEDOUT))
}
fn error(code: i32) -> io::Error {
    io::Error::from_raw_os_error(code)
}
fn bounded_file(path: &str, limit: u64) -> io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    File::open(path)?.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(error(nix::libc::EOVERFLOW));
    }
    Ok(bytes)
}
fn boot_id(bytes: &[u8]) -> io::Result<[u8; 16]> {
    let bytes = bytes.strip_suffix(b"\n").unwrap_or(bytes);
    if bytes.len() != 36 {
        return Err(error(nix::libc::EPROTO));
    }
    let mut id = [0; 16];
    let mut digit = 0;
    for (index, byte) in bytes.iter().copied().enumerate() {
        if [8, 13, 18, 23].contains(&index) {
            if byte != b'-' {
                return Err(error(nix::libc::EPROTO));
            }
            continue;
        }
        let nibble = match byte {
            b'0'..=b'9' => byte - b'0',
            b'a'..=b'f' => byte - b'a' + 10,
            b'A'..=b'F' => byte - b'A' + 10,
            _ => return Err(error(nix::libc::EPROTO)),
        };
        id[digit / 2] |= nibble << (4 * (1 - digit % 2));
        digit += 1;
    }
    if !id.iter().any(|b| *b != 0) {
        return Err(error(nix::libc::EPROTO));
    }
    Ok(id)
}
fn domain() -> io::Result<([u8; 16], u64, u64)> {
    let boot = boot_id(&bounded_file("/proc/sys/kernel/random/boot_id", 64)?)?;
    // Follow the namespace link, rather than identifying the procfs symlink.
    let namespace = std::fs::metadata("/proc/thread-self/ns/time")?;
    Ok((boot, namespace.dev(), namespace.ino()))
}
fn monotonic_ns() -> io::Result<u64> {
    let mut now = nix::libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    if unsafe { nix::libc::clock_gettime(nix::libc::CLOCK_MONOTONIC, &mut now) } != 0 {
        return Err(io::Error::last_os_error());
    }
    if now.tv_sec < 0 || !(0..1_000_000_000).contains(&now.tv_nsec) {
        return Err(error(nix::libc::EPROTO));
    }
    (now.tv_sec as u64)
        .checked_mul(1_000_000_000)
        .and_then(|v| v.checked_add(now.tv_nsec as u64))
        .ok_or_else(|| error(nix::libc::EOVERFLOW))
}
/// Convert a local observation Instant to CLOCK_MONOTONIC nanoseconds.
/// This timestamp grants no admission and imposes no operation budget. Callers
/// must bound their own lifetime; TX continues through kernel_deadline_at.
pub fn monotonic_timestamp_at(at: Instant) -> io::Result<u64> {
    // Sample the clock before the Instant: rounding can only shorten a budget.
    let ns = monotonic_ns()?;
    let sampled = Instant::now();
    if at >= sampled {
        ns.checked_add(
            at.duration_since(sampled)
                .as_nanos()
                .try_into()
                .map_err(|_| error(nix::libc::EOVERFLOW))?,
        )
    } else {
        ns.checked_sub(
            sampled
                .duration_since(at)
                .as_nanos()
                .try_into()
                .map_err(|_| error(nix::libc::EOVERFLOW))?,
        )
    }
    .ok_or_else(|| error(nix::libc::EOVERFLOW))
}

/// An immutable original deadline. It may expire while held or already be past.
/// Methods which perform work must call remaining before any side effect.
/// cbindgen:ignore
#[derive(Clone, Copy, Debug)]
pub struct Deadline {
    at: Instant,
    stamp: DeadlineStamp,
}
impl Deadline {
    pub fn after(duration: Duration) -> io::Result<Self> {
        if duration > MAX_WAIT {
            return Err(error(nix::libc::EINVAL));
        }
        Self::at(Instant::now() + duration)
    }
    pub fn at(at: Instant) -> io::Result<Self> {
        if at.saturating_duration_since(Instant::now()) > MAX_WAIT {
            return Err(error(nix::libc::EINVAL));
        }
        let (boot_id, time_namespace_device, time_namespace_inode) = domain()?;
        let monotonic_ns = monotonic_timestamp_at(at)?;
        if domain()? != (boot_id, time_namespace_device, time_namespace_inode) {
            return Err(error(nix::libc::EOPNOTSUPP));
        }
        Ok(Self {
            at,
            stamp: DeadlineStamp {
                monotonic_ns,
                boot_id,
                time_namespace_device,
                time_namespace_inode,
            },
        })
    }
    pub fn from_monotonic_ns(value: u64) -> io::Result<Self> {
        let before = domain()?;
        let at = local_instant_from_monotonic_ns(value)?;
        if domain()? != before {
            return Err(error(nix::libc::EOPNOTSUPP));
        }
        Ok(Self {
            at,
            stamp: DeadlineStamp {
                monotonic_ns: value,
                boot_id: before.0,
                time_namespace_device: before.1,
                time_namespace_inode: before.2,
            },
        })
    }
    pub fn from_stamp(stamp: DeadlineStamp) -> io::Result<Self> {
        if !stamp.valid() {
            return Err(error(nix::libc::EINVAL));
        }
        // A foreign clock value has no local expiry meaning. Reject its domain
        // before interpreting the number, then recheck while sampling locally.
        if domain()?
            != (
                stamp.boot_id,
                stamp.time_namespace_device,
                stamp.time_namespace_inode,
            )
        {
            return Err(error(nix::libc::EOPNOTSUPP));
        }
        let value = Self::from_monotonic_ns(stamp.monotonic_ns)?;
        if value.stamp != stamp {
            return Err(error(nix::libc::EOPNOTSUPP));
        }
        Ok(value)
    }
    pub fn instant(self) -> Instant {
        self.at
    }
    pub fn stamp(self) -> DeadlineStamp {
        self.stamp
    }
    pub fn remaining(self) -> io::Result<Duration> {
        remaining(self.at)
    }
    /// A stricter upper bound is allowed; queueing never starts a fresh budget.
    pub fn capped(self, maximum: Duration) -> io::Result<Self> {
        self.remaining()?;
        let bound = Instant::now() + maximum.min(MAX_WAIT);
        if self.at <= bound {
            Ok(self)
        } else {
            Self::at(bound)
        }
    }
}

fn zero_offsets(bytes: &[u8]) -> io::Result<()> {
    let text = std::str::from_utf8(bytes).map_err(|_| error(nix::libc::EPROTO))?;
    let mut seen = 0;
    for line in text.lines() {
        let fields: Vec<_> = line.split_whitespace().collect();
        if fields.len() != 3 {
            return Err(error(nix::libc::EPROTO));
        }
        let bit = match fields[0] {
            "monotonic" => 1,
            "boottime" => 2,
            _ => return Err(error(nix::libc::EPROTO)),
        };
        if seen & bit != 0 {
            return Err(error(nix::libc::EPROTO));
        }
        seen |= bit;
        let seconds: i64 = fields[1].parse().map_err(|_| error(nix::libc::EPROTO))?;
        let nanos: i64 = fields[2].parse().map_err(|_| error(nix::libc::EPROTO))?;
        if seconds != 0 || nanos != 0 {
            return Err(error(nix::libc::EOPNOTSUPP));
        }
    }
    if seen != 3 {
        return Err(error(nix::libc::EPROTO));
    }
    Ok(())
}
/// Current kernel UAPI uses ktime_get_ns, not a task time-namespace offset.
/// No guessed subtraction or fallback if procfs/domain support is unavailable.
pub(crate) fn kernel_deadline_at(at: Instant) -> io::Result<u64> {
    let left = at.saturating_duration_since(Instant::now());
    if left.is_zero() {
        return Err(error(nix::libc::ETIMEDOUT));
    }
    if left > PROTOCOL_WAIT {
        return Err(error(nix::libc::EINVAL));
    }
    let thread = std::fs::metadata("/proc/thread-self/ns/time")?;
    let process = std::fs::metadata("/proc/self/ns/time")?;
    if (thread.dev(), thread.ino()) != (process.dev(), process.ino()) {
        return Err(error(nix::libc::EOPNOTSUPP));
    }
    // Linux exposes this file in the TGID proc table, not the TID table.
    zero_offsets(&bounded_file("/proc/self/timens_offsets", 256)?)?;
    if at <= Instant::now() {
        return Err(error(nix::libc::ETIMEDOUT));
    }
    monotonic_timestamp_at(at)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_clock_roundtrip_preserves_the_absolute_stamp_and_never_extends() {
        let d = Deadline::after(Duration::from_secs(2)).unwrap();
        let decoded = Deadline::from_stamp(d.stamp()).unwrap();
        assert_eq!(d.stamp(), decoded.stamp());
        assert!(decoded.instant() <= d.instant());
        assert!(d.capped(PROTOCOL_WAIT).unwrap().instant() == d.instant());
        assert!(d.capped(Duration::from_millis(30)).unwrap().instant() < d.instant());
        assert!(Deadline::at(Instant::now()).unwrap().remaining().is_err());
    }
    #[test]
    fn foreign_clock_and_bad_input_never_get_a_fresh_budget() {
        let d = Deadline::after(Duration::from_secs(2)).unwrap().stamp();
        for v in [
            DeadlineStamp {
                boot_id: [1; 16],
                ..d
            },
            DeadlineStamp {
                time_namespace_inode: d.time_namespace_inode + 1,
                ..d
            },
            DeadlineStamp {
                time_namespace_device: d.time_namespace_device + 1,
                ..d
            },
            DeadlineStamp {
                monotonic_ns: 1,
                boot_id: [1; 16],
                ..d
            },
        ] {
            assert_eq!(
                Deadline::from_stamp(v).unwrap_err().raw_os_error(),
                Some(nix::libc::EOPNOTSUPP)
            );
        }
        assert_eq!(
            Deadline::from_monotonic_ns(0).unwrap_err().raw_os_error(),
            Some(nix::libc::ETIMEDOUT)
        );
        assert_eq!(
            Deadline::from_monotonic_ns(u64::MAX)
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::EINVAL)
        );
        assert!(Deadline::after(MAX_WAIT + Duration::from_secs(1)).is_err());
        for bad in [
            b"".as_slice(),
            b"00000000-0000-0000-0000-000000000000\n",
            b"11000000x0000-0000-0000-000000000000",
            b"z1000000-0000-0000-0000-000000000000",
        ] {
            assert!(boot_id(bad).is_err());
        }
    }
    #[test]
    fn kernel_projection_refuses_missing_duplicate_and_shifted_offsets() {
        zero_offsets(b"monotonic 0 0\nboottime 0 0\n").unwrap();
        for bad in [
            b"".as_slice(),
            b"monotonic 0 0",
            b"monotonic 0 0\nmonotonic 0 0\nboottime 0 0",
            b"monotonic 1 0\nboottime 0 0",
            b"monotonic 0 1\nboottime 0 0",
            b"other 0 0\nboottime 0 0",
            b"monotonic 18446744073709551616 0\nboottime 0 0",
        ] {
            assert!(zero_offsets(bad).is_err());
        }
        kernel_deadline_at(Instant::now() + Duration::from_secs(1)).unwrap();
        assert_eq!(
            kernel_deadline_at(Instant::now())
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::ETIMEDOUT)
        );
    }
}
