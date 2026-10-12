# VM-only channel fd client

This isolated, unpublished Cargo package is not a production workspace member.
It obtains an existing Connection object's fd from the actual slkd D-Bus
`OpenChannel` method as UID1000/GID1002 with no capabilities, verifies the bus
owner did not change, and delivers that fd via SCM_RIGHTS. It never binds a
native socket or controls radio/management state.

Build with `cargo build --locked --offline --manifest-path tools/lab/channel_fd_probe/Cargo.toml`.
Execution requires QEMU, a scratch-root marker and the explicit
`ws73.channel_daemon_crash=1` boot mode. Its ten-second deadline bounds all
D-Bus steps. Invocation is `ws73-channel-fd-probe CONNECTION_PATH UNIX_DATAGRAM TOKEN`.
The receiver must check token, path, actual daemon pid/unique owner, exactly one
fd, CLOEXEC and inode; reject truncated ancillary data and close rejected fds.
The supervisor must reap this client before interpreting a daemon last-File
close, so no helper-held references contaminate the result.

Current scope: source and strict offline build only. VM staging, receiver,
actual slkd death, retained application fd, successor and USB/RF qualification
are not yet connected. This tool cannot count as a passed daemon-death gate.
