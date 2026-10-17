//! Ordinary application socket exercise. Peer validates the actual message and
//! replies; no broadcast payload or daemon-supplied data substitutes for RX.
use std::io::Read;
use std::os::fd::{AsRawFd, OwnedFd};
use std::time::{Duration, Instant};

#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum Mode {
    Regular,
    Boundaries,
    PrefixClose,
    Burst,
}

fn tx_status(
    fd: &OwnedFd,
    stage: &str,
    sequence: usize,
) -> anyhow::Result<slk_protocol::channel::SleChannelTxStatus> {
    let s = slk_protocol::channel::query_tx_status(fd.as_raw_fd())?;
    println!(
        "NativeTxStatus: stage={stage} sequence={sequence} index={} generation={} lifetime={} handle={} maximum={} capacity={} outstanding={} debt={} peak={} queued={} limit={} busy={} bytes={} offset={} flags={} blocks={}",
        s.controller,
        s.generation,
        s.lifetime,
        s.handle,
        s.packet_maximum,
        s.capacity,
        s.outstanding,
        s.connection_debt,
        s.peak_reserved,
        s.queued,
        s.queue_limit,
        s.busy,
        s.active_pdu_bytes,
        s.active_pdu_offset,
        s.flags,
        s.pool_exhaustions
    );
    Ok(s)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

pub(super) fn wait(fd: &OwnedFd, events: i16, deadline: Instant) -> anyhow::Result<()> {
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            anyhow::bail!("channel socket ten-second deadline");
        }
        let mut p = nix::libc::pollfd {
            fd: fd.as_raw_fd(),
            events,
            revents: 0,
        };
        // SAFETY: one writable pollfd live for the bounded call.
        let result = unsafe {
            nix::libc::poll(
                &mut p,
                1,
                remaining.as_millis().min(i32::MAX as u128) as i32,
            )
        };
        if result < 0 {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error.into());
        }
        if p.revents & (nix::libc::POLLERR | nix::libc::POLLNVAL) != 0 {
            anyhow::bail!("channel socket fault/link-down: {}", p.revents);
        }
        // A closed peer may leave a complete readable datagram. Consume it
        // before treating HUP as EOF; a kernel fault remains an error above.
        if events & nix::libc::POLLIN != 0 && p.revents & nix::libc::POLLIN != 0 {
            return Ok(());
        }
        if p.revents & nix::libc::POLLHUP != 0 {
            anyhow::bail!("channel socket fault/link-down: {}", p.revents);
        }
        if p.revents & events != 0 {
            return Ok(());
        }
    }
}

fn send(fd: &OwnedFd, bytes: &[u8], deadline: Instant) -> anyhow::Result<()> {
    loop {
        wait(fd, nix::libc::POLLOUT, deadline)?;
        // SAFETY: immutable bytes are live and owned throughout this call.
        let result = unsafe {
            nix::libc::send(
                fd.as_raw_fd(),
                bytes.as_ptr().cast(),
                bytes.len(),
                nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
            )
        };
        if result == bytes.len() as isize {
            return Ok(());
        }
        if result >= 0 {
            anyhow::bail!("partial datagram send");
        }
        let error = std::io::Error::last_os_error();
        if error.kind() != std::io::ErrorKind::WouldBlock {
            return Err(error.into());
        }
    }
}

#[derive(Clone, Copy)]
struct ReceiptExpectation {
    channel: slk_protocol::SleChannelInfo,
    minimum: u32,
}
impl ReceiptExpectation {
    fn verify(self, m: slk_protocol::SleMessageSecurity) -> anyhow::Result<()> {
        m.validate()?;
        let c = self.channel;
        anyhow::ensure!(
            m.controller == c.controller
                && m.generation == c.generation
                && m.lifetime == c.lifetime
                && m.handle == c.handle
                && m.local_tcid == c.local_tcid
                && m.remote_tcid == c.remote_tcid
                && m.pi == c.pi
                && m.flags == 3
                && m.security >= self.minimum,
            "receipt identity/current mechanism differs from authorized fd"
        );
        Ok(())
    }
}
fn receive(fd: &OwnedFd, deadline: Instant) -> anyhow::Result<Vec<u8>> {
    receive_checked(fd, deadline, None, 0).map(|v| v.0)
}
fn receive_checked(
    fd: &OwnedFd,
    deadline: Instant,
    receipt: Option<ReceiptExpectation>,
    sequence: u32,
) -> anyhow::Result<(Vec<u8>, Option<slk_protocol::SleMessageSecurity>)> {
    loop {
        wait(fd, nix::libc::POLLIN, deadline)?;
        let mut buffer = [0u8; 2042];
        if let Some(expected) = receipt {
            match slk_protocol::message_security::recv(
                fd.as_raw_fd(),
                &mut buffer,
                nix::libc::MSG_DONTWAIT | nix::libc::MSG_TRUNC,
            ) {
                Ok((count, context, flags)) => {
                    expected.verify(context)?;
                    anyhow::ensure!(
                        count > 0 && count <= buffer.len() && flags & nix::libc::MSG_TRUNC == 0,
                        "truncated/empty application receipt"
                    );
                    println!(
                        "NativeMessageSecurity: sequence={sequence} index={} generation={} lifetime={} handle={} local={} remote={} pi={} security={} epoch={} flags={}",
                        context.controller,
                        context.generation,
                        context.lifetime,
                        context.handle,
                        context.local_tcid,
                        context.remote_tcid,
                        context.pi,
                        context.security,
                        context.security_epoch,
                        context.flags
                    );
                    return Ok((buffer[..count].to_vec(), Some(context)));
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => continue,
                Err(error) => return Err(error.into()),
            }
        }
        // SAFETY: writable stack buffer and valid owned socket; MSG_TRUNC reveals oversized messages.
        let result = unsafe {
            nix::libc::recv(
                fd.as_raw_fd(),
                buffer.as_mut_ptr().cast(),
                buffer.len(),
                nix::libc::MSG_DONTWAIT | nix::libc::MSG_TRUNC,
            )
        };
        if result > buffer.len() as isize {
            anyhow::bail!("oversized socket message");
        }
        if result > 0 {
            return Ok((buffer[..result as usize].to_vec(), None));
        }
        if result == 0 {
            anyhow::bail!("channel socket EOF");
        }
        let error = std::io::Error::last_os_error();
        if error.kind() != std::io::ErrorKind::WouldBlock {
            return Err(error.into());
        }
    }
}

pub(super) fn validate(
    bytes: &[u8],
    sequence: u32,
    reply: bool,
    message_bytes: usize,
) -> anyhow::Result<()> {
    if bytes.len() != message_bytes
        || &bytes[..8] != b"SLKSOCK1"
        || bytes[24..28] != sequence.to_le_bytes()
        || bytes[28] != u8::from(reply)
    {
        anyhow::bail!("peer application message header/sequence mismatch");
    }
    for i in 0..message_bytes - 29 {
        if bytes[29 + i] != bytes[8 + i % 16] ^ (sequence as u8).wrapping_add(i as u8) {
            anyhow::bail!("peer application payload validation failed");
        }
    }
    Ok(())
}

fn reject_boundaries(fd: &OwnedFd) -> anyhow::Result<()> {
    wait(
        fd,
        nix::libc::POLLOUT,
        Instant::now() + Duration::from_secs(10),
    )?;
    let mtu = usize::from(slk_protocol::channel::query(fd.as_raw_fd())?.mtu);
    for length in [mtu + 1, mtu + 4, mtu + 5, mtu + 6] {
        let mut bytes = vec![0u8; length];
        std::fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
        bytes[..8].copy_from_slice(b"SLKBOUND");
        // SAFETY: the complete immutable buffer and socket live for this call.
        let result = unsafe {
            nix::libc::send(
                fd.as_raw_fd(),
                bytes.as_ptr().cast(),
                bytes.len(),
                nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
            )
        };
        let error = std::io::Error::last_os_error();
        if result != -1 || error.raw_os_error() != Some(nix::libc::EMSGSIZE) {
            anyhow::bail!(
                "oversized basic-channel message was not rejected with EMSGSIZE: result={result} error={error}"
            );
        }
        println!(
            "NativeChannelRejected: length={length} errno={} bytes={}",
            nix::libc::EMSGSIZE,
            hex(&bytes)
        );
    }
    Ok(())
}

// This tests refusal before software admission, never a security downgrade.
fn reject_send_control(fd: &OwnedFd) -> anyhow::Result<()> {
    let mut payload = [0u8; 61];
    payload[..8].copy_from_slice(b"SLKCMREJ");
    std::fs::File::open("/dev/urandom")?.read_exact(&mut payload[8..])?;
    let mut control = [0u64; 8];
    // SAFETY: aligned owned buffer covers header plus the complete 40-byte record.
    unsafe {
        control
            .as_mut_ptr()
            .cast::<nix::libc::cmsghdr>()
            .write(nix::libc::cmsghdr {
                cmsg_len: nix::libc::CMSG_LEN(40) as _,
                cmsg_level: slk_protocol::message_security::SOL_SPARKLINK,
                cmsg_type: slk_protocol::message_security::SCM_RX_SECURITY,
            });
    }
    let mut io_vec = nix::libc::iovec {
        iov_base: payload.as_mut_ptr().cast(),
        iov_len: payload.len(),
    };
    let mut message: nix::libc::msghdr = unsafe { std::mem::zeroed() };
    message.msg_iov = &mut io_vec;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = unsafe { nix::libc::CMSG_SPACE(40) } as _;
    // SAFETY: all complete buffers and owned fd remain live through sendmsg.
    let result = unsafe {
        nix::libc::sendmsg(
            fd.as_raw_fd(),
            &message,
            nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
        )
    };
    let error = std::io::Error::last_os_error();
    anyhow::ensure!(
        result == -1 && error.raw_os_error() == Some(nix::libc::EOPNOTSUPP),
        "unsupported send control was not rejected: {result} {error}"
    );
    println!(
        "NativeControlRejected: errno={} bytes={}",
        nix::libc::EOPNOTSUPP,
        hex(&payload)
    );
    Ok(())
}

fn reject_stale_intents(
    fd: &OwnedFd,
    good: slk_protocol::SleSendConstraint,
    sequence: u32,
) -> anyhow::Result<()> {
    for kind in ["epoch", "lifetime", "deadline"] {
        let mut bad = good;
        if kind == "epoch" {
            bad.security_epoch = good.security_epoch.checked_add(1).unwrap_or(1);
        } else if kind == "lifetime" {
            bad.lifetime = good.lifetime.checked_add(1).unwrap_or(1);
        } else {
            bad.deadline_monotonic_ns = 1;
        }
        let mut payload = [0u8; 61];
        payload[..8].copy_from_slice(b"SLKINTRE");
        std::fs::File::open("/dev/urandom")?.read_exact(&mut payload[8..])?;
        let expected = if kind == "deadline" {
            nix::libc::ETIMEDOUT
        } else {
            nix::libc::EACCES
        };
        let result = slk_protocol::message_security::send(
            fd.as_raw_fd(),
            &payload,
            nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
            &bad,
        );
        anyhow::ensure!(
            result.as_ref().err().and_then(|e| e.raw_os_error()) == Some(expected),
            "invalid intent unexpectedly admitted: {kind} {result:?}"
        );
        println!(
            "NativeConstraintRejected: sequence={sequence} kind={kind} errno={expected} bytes={}",
            hex(&payload)
        );
    }
    Ok(())
}

fn info_copy_retry(fd: &OwnedFd, expected: slk_protocol::SleChannelInfo) -> anyhow::Result<()> {
    let page = unsafe { nix::libc::sysconf(nix::libc::_SC_PAGESIZE) };
    if !(4096..=1048576).contains(&page) {
        anyhow::bail!("unsupported guard page size");
    }
    struct Mapping(*mut nix::libc::c_void, usize);
    impl Drop for Mapping {
        fn drop(&mut self) {
            unsafe {
                nix::libc::munmap(self.0, self.1);
            }
        }
    }
    // SAFETY: fresh private mapping, no hardware/service operation.
    let raw = unsafe {
        nix::libc::mmap(
            std::ptr::null_mut(),
            page as usize * 2,
            nix::libc::PROT_READ | nix::libc::PROT_WRITE,
            nix::libc::MAP_PRIVATE | nix::libc::MAP_ANONYMOUS,
            -1,
            0,
        )
    };
    if raw == nix::libc::MAP_FAILED {
        return Err(std::io::Error::last_os_error().into());
    }
    let mapping = Mapping(raw, page as usize * 2);
    let protected = unsafe { raw.cast::<u8>().add(page as usize) };
    if unsafe { nix::libc::mprotect(protected.cast(), page as usize, nix::libc::PROT_NONE) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let target = unsafe { protected.sub(16) };
    unsafe {
        target.write_bytes(0xa5, 16);
    }
    // No Rust reference is created across the guard; the kernel must EFAULT.
    let result = unsafe { slk_protocol::channel::sl_channel_info(fd.as_raw_fd(), target.cast()) };
    if result != Err(nix::errno::Errno::EFAULT) {
        anyhow::bail!("channel snapshot guard did not EFAULT: {result:?}");
    }
    let prefix = unsafe { std::slice::from_raw_parts(target, 16) };
    let changed = prefix.iter().filter(|&&byte| byte != 0xa5).count();
    if changed == 0 {
        anyhow::bail!("no partial channel snapshot copy observed");
    }
    if slk_protocol::channel::query(fd.as_raw_fd())? != expected {
        anyhow::bail!("channel snapshot changed after copy fault");
    }
    println!("NativeChannelInfoCopy: partial={changed} retry=1 unchanged=1");
    drop(mapping);
    Ok(())
}

fn validate_exercise(rounds: u32, message_bytes: usize) -> anyhow::Result<()> {
    if !(1..=20).contains(&rounds) {
        anyhow::bail!("rounds must be 1..20");
    }
    if !(29..=2042).contains(&message_bytes) {
        anyhow::bail!("message size must be 29..2042 within the negotiated basic channel");
    }
    Ok(())
}
pub(super) fn prepare_application_fd(fd: OwnedFd) -> anyhow::Result<OwnedFd> {
    // Exercise the shared open-file description: dropping one descriptor
    // must not retire the Binding while its duplicate is still used.
    let duplicate = fd.try_clone()?;
    drop(fd);
    let fd = duplicate;
    println!("NativeChannelDup: original_closed=1 duplicate_live=1");
    let linger = nix::libc::linger {
        l_onoff: 1,
        l_linger: 2,
    };
    // SAFETY: complete initialized option and live owned socket. This finite
    // close wait drains queued TX; only actual opposite RX proves delivery.
    if unsafe {
        nix::libc::setsockopt(
            fd.as_raw_fd(),
            nix::libc::SOL_SOCKET,
            nix::libc::SO_LINGER,
            (&linger as *const nix::libc::linger).cast(),
            std::mem::size_of_val(&linger) as nix::libc::socklen_t,
        )
    } != 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(fd)
}

pub(crate) fn exercise(
    fd: OwnedFd,
    responder: bool,
    rounds: u32,
    message_bytes: usize,
    mode: Mode,
    receipt_security: Option<u32>,
) -> anyhow::Result<()> {
    exercise_channel(
        fd,
        responder,
        rounds,
        message_bytes,
        mode,
        ExerciseSettings {
            dynamic: false,
            start_barrier: false,
            receipt_security,
        },
    )
}
pub(crate) fn exercise_dynamic(
    fd: OwnedFd,
    responder: bool,
    rounds: u32,
    message_bytes: usize,
    mode: Mode,
    start_barrier: bool,
) -> anyhow::Result<()> {
    if mode == Mode::Burst && (responder || rounds != 16 || message_bytes != 2042) {
        anyhow::bail!("dynamic burst requires an initiator with16 messages of2042 bytes");
    }
    exercise_channel(
        fd,
        responder,
        rounds,
        message_bytes,
        mode,
        ExerciseSettings {
            dynamic: true,
            start_barrier,
            receipt_security: None,
        },
    )
}
struct ExerciseSettings {
    dynamic: bool,
    start_barrier: bool,
    receipt_security: Option<u32>,
}
fn exercise_channel(
    fd: OwnedFd,
    responder: bool,
    rounds: u32,
    message_bytes: usize,
    mode: Mode,
    settings: ExerciseSettings,
) -> anyhow::Result<()> {
    let ExerciseSettings {
        dynamic,
        start_barrier,
        receipt_security,
    } = settings;
    anyhow::ensure!(
        receipt_security.is_none()
            || (!dynamic && matches!(mode, Mode::Regular | Mode::Boundaries)),
        "receipt check requires fixed regular/boundaries mode"
    );
    validate_exercise(rounds, message_bytes)?;
    let fd = prepare_application_fd(fd)?;
    wait(
        &fd,
        nix::libc::POLLOUT,
        Instant::now() + Duration::from_secs(10),
    )?;
    let info = slk_protocol::channel::query(fd.as_raw_fd())?;
    let valid_pair = if dynamic {
        (0x80..=0xdf).contains(&info.local_tcid) && (0x80..=0xdf).contains(&info.remote_tcid)
    } else {
        info.local_tcid == 31 && info.remote_tcid == 31
    };
    if !valid_pair
        || info.pi != 241
        || info.directions != 3
        || usize::from(info.mtu) < message_bytes
        || info.mode != 0
        || usize::from(info.mps) < message_bytes + 5
    {
        anyhow::bail!("actual channel capabilities do not permit this business exercise");
    }
    println!(
        "NativeChannelInfo: index={} generation={} lifetime={} handle={} local={} remote={} pi={} mtu={} mps={} mode={} directions={}",
        info.controller,
        info.generation,
        info.lifetime,
        info.handle,
        info.local_tcid,
        info.remote_tcid,
        info.pi,
        info.mtu,
        info.mps,
        info.mode,
        info.directions
    );
    info_copy_retry(&fd, info)?;
    if receipt_security.is_some() {
        reject_send_control(&fd)?;
    }
    tx_status(&fd, "ready", 0)?;
    if start_barrier {
        // Channel capability/authority checks above are real; this controls only
        // application scheduling and never extends negotiation or PDU deadlines.
        println!("NativeDynamicArmed: count={rounds} bytes={message_bytes}");
        crate::benchmark::read_start(nix::libc::STDIN_FILENO, Duration::from_secs(30))?;
    }
    if mode == Mode::PrefixClose {
        exercise_prefix_close(fd, message_bytes)
    } else {
        if mode == Mode::Burst {
            exercise_burst(fd, rounds, message_bytes, true)
        } else {
            exercise_messages(
                fd,
                responder,
                rounds,
                message_bytes,
                mode == Mode::Boundaries,
                receipt_security.map(|minimum| ReceiptExpectation {
                    channel: info,
                    minimum,
                }),
            )
        }
    }
}

// Burst is application software-admission pressure, not a claim that the
// controller packet-credit pool ran out. Only opposite receipts prove delivery.
fn exercise_burst(
    fd: OwnedFd,
    rounds: u32,
    message_bytes: usize,
    observe_native: bool,
) -> anyhow::Result<()> {
    if rounds != 16 || message_bytes != 2042 {
        anyhow::bail!("burst requires16 messages of2042 bytes");
    }
    println!("NativeChannelOpened: role=initiator rounds={rounds}");
    println!("NativeChannelMessageSize: bytes={message_bytes}");
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut frames = Vec::new();
    let mut nonces = std::collections::BTreeSet::new();
    let mut sequences = std::collections::BTreeSet::new();
    for _ in 0..rounds {
        let mut frame = vec![0u8; message_bytes];
        frame[..8].copy_from_slice(b"SLKSOCK1");
        std::fs::File::open("/dev/urandom")?.read_exact(&mut frame[8..28])?;
        let sequence = u32::from_le_bytes(frame[24..28].try_into()?);
        if !nonces.insert(frame[8..24].to_vec()) || !sequences.insert(sequence) {
            anyhow::bail!("burst random identity repeated");
        }
        for i in 0..message_bytes - 29 {
            frame[29 + i] = frame[8 + i % 16] ^ (sequence as u8).wrapping_add(i as u8);
        }
        frames.push(frame);
    }
    let started = Instant::now();
    let mut blocked = 0;
    let mut not_writable = 0;
    for (index, frame) in frames.iter().enumerate() {
        let mut stalled = false;
        loop {
            // SAFETY: immutable full datagram and valid owned fd.
            let result = unsafe {
                nix::libc::send(
                    fd.as_raw_fd(),
                    frame.as_ptr().cast(),
                    frame.len(),
                    nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
                )
            };
            if result == frame.len() as isize {
                if stalled {
                    println!("NativeBurstResumed: sequence={index}");
                }
                println!("NativeChannelSent: sequence={index} bytes={}", hex(frame));
                break;
            }
            if result >= 0 {
                anyhow::bail!("partial burst datagram");
            }
            let error = std::io::Error::last_os_error();
            if error.kind() != std::io::ErrorKind::WouldBlock {
                return Err(error.into());
            }
            blocked += 1;
            stalled = true;
            let mut poll = nix::libc::pollfd {
                fd: fd.as_raw_fd(),
                events: nix::libc::POLLOUT,
                revents: 0,
            };
            // SAFETY: one live pollfd; zero timeout only observes current state.
            let result = unsafe { nix::libc::poll(&mut poll, 1, 0) };
            if result < 0 {
                return Err(std::io::Error::last_os_error().into());
            }
            if poll.revents & (nix::libc::POLLERR | nix::libc::POLLHUP | nix::libc::POLLNVAL) != 0 {
                anyhow::bail!("burst pressure returned socket failure");
            }
            let writable = poll.revents & nix::libc::POLLOUT != 0;
            not_writable += u32::from(!writable);
            println!(
                "NativeBurstBlocked: sequence={index} poll_writable={}",
                u8::from(writable)
            );
            if observe_native {
                tx_status(&fd, "blocked", index)?;
            }
            wait(&fd, nix::libc::POLLOUT, deadline)?;
        }
    }
    if blocked == 0 || not_writable == 0 {
        anyhow::bail!("no actual bounded-queue backpressure observed");
    }
    for (index, frame) in frames.iter().enumerate() {
        let received = receive(&fd, deadline)?;
        let wire = u32::from_le_bytes(frame[24..28].try_into()?);
        validate(&received, wire, true, message_bytes)?;
        let mut expected = frame.clone();
        expected[28] = 1;
        if received != expected {
            anyhow::bail!("burst opposite application reply mismatch");
        }
        println!(
            "NativeChannelRoundTrip: sequence={index} elapsed_ms={} bytes={}",
            started.elapsed().as_millis(),
            hex(&received)
        );
    }
    if observe_native {
        tx_status(&fd, "replied", rounds as usize)?;
    }
    println!("NativeBurstPressure: eagain={blocked} not_writable={not_writable} replies={rounds}");
    Ok(())
}

// Dedicated application lifecycle gate. Delay is only scheduling support;
// the USB evidence verifier must prove first submit < close < final submit.
fn exercise_prefix_close(fd: OwnedFd, message_bytes: usize) -> anyhow::Result<()> {
    if message_bytes != 2042 {
        anyhow::bail!("prefix-close requires a 2042-byte operation");
    }
    let linger = nix::libc::linger {
        l_onoff: 0,
        l_linger: 0,
    };
    // SAFETY: initialized finite socket option; disable the earlier drain wait.
    if unsafe {
        nix::libc::setsockopt(
            fd.as_raw_fd(),
            nix::libc::SOL_SOCKET,
            nix::libc::SO_LINGER,
            (&linger as *const nix::libc::linger).cast(),
            std::mem::size_of_val(&linger) as nix::libc::socklen_t,
        )
    } != 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    let wall = || {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|v| v.as_nanos())
            .map_err(anyhow::Error::from)
    };
    let mut frame = vec![0u8; message_bytes];
    frame[..8].copy_from_slice(b"SLKSOCK1");
    std::fs::File::open("/dev/urandom")?.read_exact(&mut frame[8..28])?;
    let wire_sequence = u32::from_le_bytes(frame[24..28].try_into()?);
    for i in 0..message_bytes - 29 {
        frame[29 + i] = frame[8 + i % 16] ^ (wire_sequence as u8).wrapping_add(i as u8);
    }
    let deadline = Instant::now() + Duration::from_secs(10);
    send(&fd, &frame, deadline)?;
    let mut dropped = [0u8; 61];
    dropped[..8].copy_from_slice(b"SLKDROP1");
    std::fs::File::open("/dev/urandom")?.read_exact(&mut dropped[8..])?;
    send(&fd, &dropped, deadline)?;
    println!("NativePrefixSent: bytes={}", hex(&frame));
    println!("NativePrefixQueued: bytes={}", hex(&dropped));
    std::thread::sleep(Duration::from_millis(25));
    let before = wall()?;
    drop(fd); // actual final open-file reference, no linger or simulated reply
    let after = wall()?;
    println!("NativePrefixClosed: start_wall_ns={before} end_wall_ns={after}");
    Ok(())
}

// Application algorithm reused by a dedicated AF_UNIX regression. It does not
// claim Native admission/capabilities; the production entry always checks them.
fn exercise_messages(
    fd: OwnedFd,
    responder: bool,
    rounds: u32,
    message_bytes: usize,
    boundaries: bool,
    receipt: Option<ReceiptExpectation>,
) -> anyhow::Result<()> {
    validate_exercise(rounds, message_bytes)?;
    println!(
        "NativeChannelOpened: role={} rounds={rounds}",
        if responder { "peer" } else { "initiator" }
    );
    println!("NativeChannelMessageSize: bytes={message_bytes}");
    if boundaries {
        reject_boundaries(&fd)?;
    }
    let mut nonces = std::collections::BTreeSet::new();
    let mut wire_sequences = std::collections::BTreeSet::new();
    for sequence in 0..rounds {
        let started = Instant::now();
        let deadline = started + Duration::from_secs(10);
        if responder {
            let (mut frame, context) = receive_checked(&fd, deadline, receipt, sequence)?;
            if frame.len() != message_bytes {
                anyhow::bail!("peer application message length mismatch");
            }
            let wire_sequence = u32::from_le_bytes(frame[24..28].try_into()?);
            validate(&frame, wire_sequence, false, message_bytes)?;
            if !wire_sequences.insert(wire_sequence) {
                anyhow::bail!("duplicate wire sequence");
            }
            if !nonces.insert(frame[8..24].to_vec()) {
                anyhow::bail!("duplicate nonce");
            }
            println!(
                "NativeChannelReceived: sequence={sequence} bytes={}",
                hex(&frame)
            );
            frame[28] = 1;
            if let Some(context) = context {
                let absolute = slk_protocol::message_security::deadline_at(
                    deadline.min(Instant::now() + Duration::from_secs(5)),
                )?;
                let intent = slk_protocol::SleSendConstraint::from_receipt(
                    context,
                    context.security,
                    absolute,
                )?;
                reject_stale_intents(&fd, intent, sequence)?;
                loop {
                    wait(&fd, nix::libc::POLLOUT, deadline)?;
                    match slk_protocol::message_security::send(
                        fd.as_raw_fd(),
                        &frame,
                        nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
                        &intent,
                    ) {
                        Ok(n) if n == frame.len() => break,
                        Ok(_) => anyhow::bail!("partial constrained datagram"),
                        Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => continue,
                        Err(e) => return Err(e.into()),
                    }
                }
                println!(
                    "NativeConstrainedReply: sequence={sequence} epoch={} minimum={} deadline_ns={}",
                    intent.security_epoch, intent.minimum, intent.deadline_monotonic_ns
                );
            } else {
                send(&fd, &frame, deadline)?;
            }
            println!(
                "NativeChannelReply: sequence={sequence} bytes={}",
                hex(&frame)
            );
        } else {
            let mut frame = vec![0u8; message_bytes];
            frame[..8].copy_from_slice(b"SLKSOCK1");
            std::fs::File::open("/dev/urandom")?.read_exact(&mut frame[8..28])?;
            let wire_sequence = u32::from_le_bytes(frame[24..28].try_into()?);
            if !wire_sequences.insert(wire_sequence) || !nonces.insert(frame[8..24].to_vec()) {
                anyhow::bail!("random source repeated nonce or sequence");
            }
            for i in 0..message_bytes - 29 {
                frame[29 + i] = frame[8 + i % 16] ^ (wire_sequence as u8).wrapping_add(i as u8);
            }
            println!(
                "NativeChannelSent: sequence={sequence} bytes={}",
                hex(&frame)
            );
            send(&fd, &frame, deadline)?;
            let (received, _) = receive_checked(&fd, deadline, receipt, sequence)?;
            validate(&received, wire_sequence, true, message_bytes)?;
            frame[28] = 1;
            if received != frame {
                anyhow::bail!("actual peer reply differs from original random payload");
            }
            println!(
                "NativeChannelRoundTrip: sequence={sequence} elapsed_ms={} bytes={}",
                started.elapsed().as_millis(),
                hex(&received)
            );
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::fd::FromRawFd;

    #[test]
    fn receipt_validator_rejects_old_unknown_wrong_scope_and_insufficient_mechanism() {
        let channel = slk_protocol::SleChannelInfo {
            controller: 1,
            generation: 7,
            lifetime: 9,
            handle: 3,
            local_tcid: 31,
            remote_tcid: 31,
            pi: 241,
            ..Default::default()
        };
        let check = ReceiptExpectation {
            channel,
            minimum: 1,
        };
        let valid = slk_protocol::SleMessageSecurity {
            version: 1,
            size: 40,
            controller: 1,
            generation: 7,
            lifetime: 9,
            handle: 3,
            local_tcid: 31,
            remote_tcid: 31,
            pi: 241,
            security: 1,
            security_epoch: 2,
            flags: 3,
        };
        check.verify(valid).unwrap();
        for bad in [
            slk_protocol::SleMessageSecurity {
                generation: 8,
                ..valid
            },
            slk_protocol::SleMessageSecurity {
                lifetime: 10,
                ..valid
            },
            slk_protocol::SleMessageSecurity { handle: 4, ..valid },
            slk_protocol::SleMessageSecurity {
                remote_tcid: 10,
                ..valid
            },
            slk_protocol::SleMessageSecurity { flags: 1, ..valid },
            slk_protocol::SleMessageSecurity {
                flags: 0,
                security: 0,
                ..valid
            },
            slk_protocol::SleMessageSecurity {
                security: 0,
                ..valid
            },
        ] {
            assert!(check.verify(bad).is_err());
        }
    }
    #[test]
    fn application_validates_and_replies_over_real_local_datagram_fds() {
        for message_bytes in [61, 249, 250, 253, 254, 255, 1024, 2042] {
            // Local AF_UNIX is application regression support, never WS73 acceptance.
            let mut raw = [-1; 2];
            // SAFETY: writable two-element array; success transfers two owned fds.
            let result = unsafe {
                nix::libc::socketpair(
                    nix::libc::AF_UNIX,
                    nix::libc::SOCK_DGRAM | nix::libc::SOCK_NONBLOCK | nix::libc::SOCK_CLOEXEC,
                    0,
                    raw.as_mut_ptr(),
                )
            };
            assert_eq!(result, 0, "{}", std::io::Error::last_os_error());
            // SAFETY: distinct descriptors freshly returned by socketpair.
            let (initiator, peer) =
                unsafe { (OwnedFd::from_raw_fd(raw[0]), OwnedFd::from_raw_fd(raw[1])) };
            let task = std::thread::spawn(move || {
                exercise_messages(
                    prepare_application_fd(peer)?,
                    true,
                    4,
                    message_bytes,
                    false,
                    None,
                )
            });
            exercise_messages(
                prepare_application_fd(initiator).unwrap(),
                false,
                4,
                message_bytes,
                false,
                None,
            )
            .unwrap();
            task.join().unwrap().unwrap();
        }
    }

    #[test]
    fn burst_recovers_from_real_local_datagram_backpressure_and_peer_replies() {
        // AF_UNIX verifies application control flow only, never WS73 credit/RF.
        let mut raw = [-1; 2];
        // SAFETY: two writable slots become distinct owned descriptors.
        assert_eq!(
            unsafe {
                nix::libc::socketpair(
                    nix::libc::AF_UNIX,
                    nix::libc::SOCK_DGRAM | nix::libc::SOCK_NONBLOCK | nix::libc::SOCK_CLOEXEC,
                    0,
                    raw.as_mut_ptr(),
                )
            },
            0
        );
        // SAFETY: successful socketpair transferred these fresh descriptors.
        let (source, peer) =
            unsafe { (OwnedFd::from_raw_fd(raw[0]), OwnedFd::from_raw_fd(raw[1])) };
        let budget: nix::libc::c_int = 4096;
        // SAFETY: initialized integer option on this test-owned local fd.
        assert_eq!(
            unsafe {
                nix::libc::setsockopt(
                    source.as_raw_fd(),
                    nix::libc::SOL_SOCKET,
                    nix::libc::SO_SNDBUF,
                    (&budget as *const nix::libc::c_int).cast(),
                    std::mem::size_of_val(&budget) as nix::libc::socklen_t,
                )
            },
            0
        );
        // This send-first exercise retains all16 replies until admission is
        // finished. Bound the reverse-direction local budget explicitly: a
        // smaller host default can otherwise deadlock the two finite queues.
        // Source remains4096 bytes so genuine forward EAGAIN is still required.
        let reply_budget: nix::libc::c_int = 128 * 1024;
        // SAFETY: initialized option and this test's live peer descriptor.
        assert_eq!(
            unsafe {
                nix::libc::setsockopt(
                    peer.as_raw_fd(),
                    nix::libc::SOL_SOCKET,
                    nix::libc::SO_SNDBUF,
                    (&reply_budget as *const nix::libc::c_int).cast(),
                    std::mem::size_of_val(&reply_budget) as nix::libc::socklen_t,
                )
            },
            0
        );
        let task = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(100));
            exercise_messages(peer, true, 16, 2042, false, None)
        });
        exercise_burst(source, 16, 2042, false).unwrap();
        task.join().unwrap().unwrap();
    }

    #[test]
    fn peer_rejects_corrupt_payload_wrong_sequence_and_reply_direction() {
        let mut message = vec![0u8; 61];
        message[..8].copy_from_slice(b"SLKSOCK1");
        message[8..24].fill(7);
        for i in 0..32 {
            message[29 + i] = 7 ^ i as u8;
        }
        validate(&message, 0, false, 61).unwrap();
        assert!(validate(&message, 1, false, 61).is_err());
        assert!(validate(&message, 0, true, 61).is_err());
        message[40] ^= 1;
        assert!(validate(&message, 0, false, 61).is_err());
        assert!(validate(&message[..60], 0, false, 61).is_err());
    }
}
