// SPDX-License-Identifier: GPL-2.0-only
//! VM test client: obtain a real daemon-authorized channel and pass its fd.
//! Does not bind a native socket, issue management ioctls or synthesize data.
use anyhow::{Context, ensure};
use nix::sys::socket::{ControlMessage, MsgFlags, sendmsg};
use std::io::IoSlice;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

fn ordinary() -> anyhow::Result<String> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    for key in ["Uid:", "Gid:"] {
        let expected = if key == "Uid:" { "1000" } else { "1002" };
        let row = status
            .lines()
            .find(|line| line.starts_with(key))
            .context(key)?;
        ensure!(
            row.split_whitespace().skip(1).collect::<Vec<_>>() == [expected; 4],
            "ordinary identity required"
        );
    }
    for key in ["CapEff:", "CapPrm:", "CapAmb:", "CapInh:"] {
        let value = status
            .lines()
            .find(|line| line.starts_with(key))
            .context(key)?
            .split_whitespace()
            .nth(1)
            .context("missing capability value")?;
        ensure!(
            u64::from_str_radix(value, 16)? == 0,
            "capability-free client required"
        );
    }
    Ok(status)
}

async fn transfer(path: &str, destination: &str, token: &str) -> anyhow::Result<()> {
    ensure!(
        token.len() == 32 && token.bytes().all(|b| b.is_ascii_hexdigit()),
        "explicit transfer token required"
    );
    let process_status = ordinary()?;
    ensure!(
        std::fs::read_to_string("/sys/class/dmi/id/sys_vendor")?.trim() == "QEMU"
            && std::path::Path::new("/scratch-root-uuid").is_file()
            && std::fs::read_to_string("/proc/cmdline")?
                .split_whitespace()
                .any(|v| v == "ws73.channel_daemon_crash=1"),
        "explicit scratch VM only"
    );
    let bus = zbus::Connection::session().await?;
    let proxy = zbus::Proxy::new(&bus, "org.sparklink", path, "org.sparklink.Connection").await?;
    let dbus = zbus::fdo::DBusProxy::new(&bus).await?;
    let owner = dbus.get_name_owner("org.sparklink".try_into()?).await?;
    let daemon_pid = dbus
        .get_connection_unix_process_id(owner.as_str().try_into()?)
        .await?;
    let fd: zbus::zvariant::OwnedFd = proxy.call("OpenChannel", &()).await?;
    // Keeping the full D-Bus owner identity prevents treating a replacement
    // daemon as the original grantor in the independent supervisor receipt.
    ensure!(
        dbus.get_name_owner("org.sparklink".try_into()?).await? == owner,
        "grantor changed during fd delivery"
    );
    let inode = nix::sys::stat::fstat(&fd)?.st_ino;
    let bytes = serde_json::to_vec(&serde_json::json!({
        "stage": "daemon_channel_fd", "token": token, "path": path,
        "pid": std::process::id(), "daemon_pid": daemon_pid, "daemon_owner": owner.as_str(),
        "inode": inode, "process_status": process_status,
        "wall_ns": SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos().to_string(),
    }))?;
    let ipc = UnixDatagram::unbound()?;
    ipc.connect(destination)?;
    let descriptors = [fd.as_raw_fd()];
    ensure!(
        sendmsg::<()>(
            ipc.as_raw_fd(),
            &[IoSlice::new(&bytes)],
            &[ControlMessage::ScmRights(&descriptors)],
            MsgFlags::empty(),
            None
        )? == bytes.len(),
        "partial fd delivery"
    );
    // All local fd references close when this bounded client exits. The
    // receiver owns the queued SCM_RIGHTS reference independently.
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    let args = std::env::args().collect::<Vec<_>>();
    ensure!(
        args.len() == 4,
        "usage: ws73-channel-fd-probe CONNECTION_PATH UNIX_DATAGRAM TOKEN"
    );
    tokio::time::timeout(
        Duration::from_secs(10),
        transfer(&args[1], &args[2], &args[3]),
    )
    .await??;
    Ok(())
}
