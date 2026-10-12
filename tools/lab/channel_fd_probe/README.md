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

Current scope: tools82aa65a with Kbf8663/compiled serviceU86bfbc8 completed two
VM real-device cases, exchanged connection roles and retained ordinary business
fds across actual slkd SIGKILL/reap and successor. See canonical capabilities
and `docs/evidence/ws73-daemon-channel-death-20261013.json`. Both controllers
share the same daemon; both leases must withdraw. This does not qualify
independent-owner business isolation, security or natural hardware recovery.

The supervisor is `tools/ws73_channel_daemon_crash.py`. Prepare a signed native
VM with `--native-channel-fd-probe PATH_TO_THIS_BUILT_BINARY`; run it with
`--channel-daemon-crash --channel-daemon-index 0` and a separate new output for
index1. The init shell alone kills/reaps its original daemon after kernel
blocking witnesses, observes actual Free, starts the successor and seals USB.
A first ESTALE wake requires captured matching physical Down before that wake;
after Free and successor, every old fd must give EACCES and poll ERR/HUP.
