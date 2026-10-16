use zbus::Connection;
type NativeObjectInfo = (u64, u64, u16, u8, u8, String, bool, bool);
pub(crate) struct DynamicExercise {
    pub(crate) rounds: u32,
    pub(crate) bytes: usize,
    pub(crate) hold: bool,
    pub(crate) start_barrier: bool,
    pub(crate) mode: crate::channel::Mode,
}

pub(crate) struct Client {
    conn: Connection,
    selected: String,
}
impl Client {
    pub(crate) fn new(conn: Connection, selected: String) -> Self {
        Self { conn, selected }
    }
    async fn selected_path(&self) -> anyhow::Result<String> {
        let manager = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            "/org/sparklink",
            "org.sparklink.Manager",
        )
        .await?;
        let paths: Vec<String> = manager.call("ListAdapters", &()).await?;
        if !paths.contains(&self.selected) {
            anyhow::bail!("selected registration removed;select its replacement with slctl");
        }
        Ok(self.selected.clone())
    }
    async fn adapter_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            self.selected_path().await?,
            "org.sparklink.Adapter",
        )
        .await?)
    }
    pub(crate) async fn cmd_dynamic_channel(
        &self,
        path: &str,
        responder: bool,
        route: (u16, u16, u16),
        exercise: DynamicExercise,
    ) -> anyhow::Result<()> {
        let DynamicExercise {
            rounds,
            bytes,
            hold,
            start_barrier,
            mode,
        } = exercise;
        use std::os::fd::AsRawFd;
        let selected = self.selected_path().await?;
        if !path.starts_with(&format!("{selected}/peer_t")) {
            anyhow::bail!("dynamic connection belongs to another adapter");
        }
        if !(29..=2042).contains(&bytes) || !(1..=20).contains(&rounds) {
            anyhow::bail!("dynamic exercise requires1..20 rounds and29..2042 bytes");
        }
        let object = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            path,
            "org.sparklink.Connection",
        )
        .await?;
        let info: NativeObjectInfo = object.call("GetInfo", &()).await?;
        let generation: u64 = self
            .adapter_proxy()
            .await?
            .get_property("Generation")
            .await?;
        let expected = format!(
            "{selected}/peer_t{:02x}_{}/link_{:016x}",
            info.4,
            info.5.replace(':', "").to_lowercase(),
            info.1
        );
        if info.0 != generation || path != expected || !info.6 || !info.7 {
            anyhow::bail!("dynamic immutable connection is not known/live");
        }
        let mtu = u16::try_from(bytes.max(249))?;
        let request = (route.0, route.1, route.2, mtu, mtu + 5, 1u8, responder);
        let fd: zbus::zvariant::OwnedFd = object.call("PrepareDynamicChannel", &(request,)).await?;
        let fd: std::os::fd::OwnedFd = fd.into();
        // An explicit test/coordinated-service hold keeps the final VFS
        // reference alive until both applications have validated their data.
        let retained = if hold {
            // SAFETY: fd is live; success creates a distinct owned reference.
            let raw = unsafe { nix::libc::fcntl(fd.as_raw_fd(), nix::libc::F_DUPFD_CLOEXEC, 0) };
            if raw < 0 {
                return Err(std::io::Error::last_os_error().into());
            }
            use std::os::fd::FromRawFd;
            // SAFETY: unique newly returned descriptor.
            Some(unsafe { std::os::fd::OwnedFd::from_raw_fd(raw) })
        } else {
            None
        };
        println!(
            "NativeDynamicStaged: source={} destination={} aid={} passive={responder}",
            route.0, route.1, route.2
        );
        crate::channel::exercise_dynamic(fd, responder, rounds, bytes, mode, start_barrier)?;
        println!("NativeDynamicBusinessDone: rounds={rounds} held={hold}");
        if hold {
            let mut command = String::new();
            if std::io::stdin().read_line(&mut command)? == 0 || command.trim() != "close" {
                anyhow::bail!("explicit dynamic hold requires close; EOF is author withdrawal");
            }
        }
        drop(retained);
        println!(
            "NativeDynamicLastClose: source={} destination={} aid={}",
            route.0, route.1, route.2
        );
        Ok(())
    }
    // Shared identity/authorization preparation for functional and measured traffic.
    // No D-Bus operation occurs per business datagram.
    pub(crate) async fn open_application_channel(
        &self,
        path: &str,
    ) -> anyhow::Result<std::os::fd::OwnedFd> {
        let selected = self.selected_path().await?;
        if !path.starts_with(&format!("{selected}/peer_t")) {
            anyhow::bail!("connection object belongs to another adapter");
        }
        let object = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            path,
            "org.sparklink.Connection",
        )
        .await?;
        let info: NativeObjectInfo = object.call("GetInfo", &()).await?;
        let adapter = self.adapter_proxy().await?;
        let generation: u64 = adapter.get_property("Generation").await?;
        let expected = format!(
            "{selected}/peer_t{:02x}_{}/link_{:016x}",
            info.4,
            info.5.replace(':', "").to_lowercase(),
            info.1
        );
        if info.0 != generation || path != expected {
            anyhow::bail!("immutable channel connection identity mismatch");
        }
        if !info.6 || !info.7 {
            anyhow::bail!("connection is not known/live");
        }
        let fd: zbus::zvariant::OwnedFd = object.call("OpenChannel", &()).await?;
        Ok(fd.into())
    }
    pub(crate) async fn cmd_channel(
        &self,
        path: &str,
        responder: bool,
        rounds: u32,
        bytes: usize,
        mode: crate::channel::Mode,
    ) -> anyhow::Result<()> {
        let fd = self.open_application_channel(path).await?;
        let object = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            path,
            "org.sparklink.Connection",
        )
        .await?;
        crate::channel::exercise(fd, responder, rounds, bytes, mode)?;
        // Last-close must not silently recreate the connection CMTC session.
        // Basic CUTC has no qualified close/rebind barrier in this lifetime.
        let reopened: zbus::Result<zbus::zvariant::OwnedFd> = object.call("OpenChannel", &()).await;
        match reopened {
            Err(zbus::Error::MethodError(name, _, _))
                if name.as_str() == "org.freedesktop.DBus.Error.NotSupported" =>
            {
                println!("NativeChannelLastClose: same_lifetime_reopen=NotSupported");
                Ok(())
            }
            Err(error) => Err(error.into()),
            Ok(_) => {
                anyhow::bail!("same-lifetime CUTC unexpectedly rebound without a protocol barrier")
            }
        }
    }
}
