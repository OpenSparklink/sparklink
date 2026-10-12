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

The receiver primitive is `tools/ws73_daemon_channel_fd.py`; it checks kernel
SCM_CREDENTIALS, exact metadata, fd identity, CLOEXEC and actual socket family/type.
Local ancillary/truncation rejection tests exercise real Unix fd passing without
claiming Sparklink behavior.

Current scope: client strict build and receiver local regression only. VM staging,
actual slkd death, retained application fd, successor and USB/RF qualification
are not yet connected. This tool cannot count as a passed daemon-death gate.
