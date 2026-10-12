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
        if p.revents & (nix::libc::POLLERR | nix::libc::POLLHUP | nix::libc::POLLNVAL) != 0 {
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
            anyhow::bail!("partial seqpacket send");
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
        let mut buffer = [0u8; 249];
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

fn validate(bytes: &[u8], sequence: u32, reply: bool) -> anyhow::Result<()> {
    if bytes.len() != 61
        || &bytes[..8] != b"SLKSOCK1"
        || bytes[24..28] != sequence.to_le_bytes()
        || bytes[28] != u8::from(reply)
    {
        anyhow::bail!("peer application message header/sequence mismatch");
    }
    for i in 0..32 {
        if bytes[29 + i] != bytes[8 + i % 16] ^ (sequence as u8).wrapping_add(i as u8) {
            anyhow::bail!("peer application payload validation failed");
        }
    }
    Ok(())
}

pub(crate) fn exercise(fd: OwnedFd, responder: bool, rounds: u32) -> anyhow::Result<()> {
    if !(1..=20).contains(&rounds) {
        anyhow::bail!("rounds must be 1..20");
    }
    println!(
        "NativeChannelOpened: role={} rounds={rounds}",
        if responder { "peer" } else { "initiator" }
    );
    let mut nonces = std::collections::BTreeSet::new();
    for sequence in 0..rounds {
        let started = Instant::now();
        let deadline = started + Duration::from_secs(10);
        if responder {
            let mut frame = receive(&fd, deadline)?;
            validate(&frame, sequence, false)?;
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
            let mut frame = vec![0u8; 61];
            frame[..8].copy_from_slice(b"SLKSOCK1");
            std::fs::File::open("/dev/urandom")?.read_exact(&mut frame[8..24])?;
            frame[24..28].copy_from_slice(&sequence.to_le_bytes());
            for i in 0..32 {
                frame[29 + i] = frame[8 + i % 16] ^ (sequence as u8).wrapping_add(i as u8);
            }
            println!(
                "NativeChannelSent: sequence={sequence} bytes={}",
                hex(&frame)
            );
            send(&fd, &frame, deadline)?;
            let received = receive(&fd, deadline)?;
            validate(&received, sequence, true)?;
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
    fn application_validates_and_replies_over_real_local_seqpacket_fds() {
        // Local AF_UNIX is application regression support, never WS73 acceptance.
        let mut raw = [-1; 2];
        // SAFETY: writable two-element array; success transfers two owned fds.
        let result = unsafe {
            nix::libc::socketpair(
                nix::libc::AF_UNIX,
                nix::libc::SOCK_SEQPACKET | nix::libc::SOCK_NONBLOCK | nix::libc::SOCK_CLOEXEC,
                0,
                raw.as_mut_ptr(),
            )
        };
        assert_eq!(result, 0, "{}", std::io::Error::last_os_error());
        // SAFETY: distinct descriptors freshly returned by socketpair.
        let (initiator, peer) =
            unsafe { (OwnedFd::from_raw_fd(raw[0]), OwnedFd::from_raw_fd(raw[1])) };
        let task = std::thread::spawn(move || exercise(peer, true, 4));
        exercise(initiator, false, 4).unwrap();
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
        validate(&message, 0, false).unwrap();
        assert!(validate(&message, 1, false).is_err());
        assert!(validate(&message, 0, true).is_err());
        message[40] ^= 1;
        assert!(validate(&message, 0, false).is_err());
        assert!(validate(&message[..60], 0, false).is_err());
    }
}
