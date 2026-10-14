//! Ordinary application socket exercise. Peer validates the actual message and
//! replies; no broadcast payload or daemon-supplied data substitutes for RX.
use std::io::Read;
use std::os::fd::{AsRawFd, OwnedFd};
use std::time::{Duration, Instant};

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn wait(fd: &OwnedFd, events: i16, deadline: Instant) -> anyhow::Result<()> {
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

fn receive(fd: &OwnedFd, deadline: Instant) -> anyhow::Result<Vec<u8>> {
    loop {
        wait(fd, nix::libc::POLLIN, deadline)?;
        let mut buffer = [0u8; 2042];
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
            return Ok(buffer[..result as usize].to_vec());
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

fn validate(bytes: &[u8], sequence: u32, reply: bool, message_bytes: usize) -> anyhow::Result<()> {
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
fn prepare_application_fd(fd: OwnedFd) -> anyhow::Result<OwnedFd> {
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
    boundaries: bool,
    close_prefix: bool,
) -> anyhow::Result<()> {
    validate_exercise(rounds, message_bytes)?;
    let fd = prepare_application_fd(fd)?;
    wait(
        &fd,
        nix::libc::POLLOUT,
        Instant::now() + Duration::from_secs(10),
    )?;
    let info = slk_protocol::channel::query(fd.as_raw_fd())?;
    if info.local_tcid != 31
        || info.remote_tcid != 31
        || info.pi != 241
        || info.directions != 3
        || usize::from(info.mtu) < message_bytes
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
    if close_prefix {
        exercise_prefix_close(fd, message_bytes)
    } else {
        exercise_messages(fd, responder, rounds, message_bytes, boundaries)
    }
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
            let mut frame = receive(&fd, deadline)?;
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
            send(&fd, &frame, deadline)?;
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
            let received = receive(&fd, deadline)?;
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
                exercise_messages(prepare_application_fd(peer)?, true, 4, message_bytes, false)
            });
            exercise_messages(
                prepare_application_fd(initiator).unwrap(),
                false,
                4,
                message_bytes,
                false,
            )
            .unwrap();
            task.join().unwrap().unwrap();
        }
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
