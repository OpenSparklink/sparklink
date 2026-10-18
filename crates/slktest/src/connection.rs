use zbus::Connection;
pub(crate) struct DynamicExercise {
    pub(crate) rounds: u32,
    pub(crate) bytes: usize,
    pub(crate) hold: bool,
    pub(crate) start_barrier: bool,
    pub(crate) mode: crate::channel::Mode,
}

pub(crate) struct Client {
    app: tokio::sync::OnceCell<libsparklink::Client>,
    conn: Connection,
    selected: String,
    security: u32,
    message_security: bool,
}
impl Client {
    pub(crate) fn new(conn: Connection, selected: String) -> Self {
        Self {
            app: tokio::sync::OnceCell::new(),
            conn,
            selected,
            security: 0,
            message_security: false,
        }
    }
    pub(crate) fn requiring_security(mut self, security: u32) -> anyhow::Result<Self> {
        anyhow::ensure!(security <= 2, "unsupported security requirement");
        self.security = security;
        Ok(self)
    }
    pub(crate) fn observing_message_security(mut self, enabled: bool) -> Self {
        self.message_security = enabled;
        self
    }
    async fn application(&self) -> anyhow::Result<&libsparklink::Client> {
        Ok(self
            .app
            .get_or_try_init(|| libsparklink::Client::from_connection(self.conn.clone()))
            .await?)
    }
    pub(crate) async fn cmd_dynamic_channel(
        &self,
        path: &str,
        responder: bool,
        route: (u16, u16, u16),
        exercise: DynamicExercise,
    ) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.security == 0,
            "dynamic protected modes are not supported"
        );
        let DynamicExercise {
            rounds,
            bytes,
            hold,
            start_barrier,
            mode,
        } = exercise;
        use std::os::fd::AsRawFd;
        if !(29..=2042).contains(&bytes) || !(1..=20).contains(&rounds) {
            anyhow::bail!("dynamic exercise requires1..20 rounds and29..2042 bytes");
        }
        let connection = self
            .application()
            .await?
            .connection(&self.selected, path)
            .await?;
        let mtu = u16::try_from(bytes.max(249))?;
        let request = (route.0, route.1, route.2, mtu, mtu + 5, 1u8, responder);
        let fd = connection
            .prepare_dynamic_channel(request)
            .await?
            .into_owned_fd();
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
        Ok(self
            .application()
            .await?
            .connection(&self.selected, path)
            .await?
            .open_channel(3, self.security)
            .await?
            .into_owned_fd())
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
        let connection = self
            .application()
            .await?
            .connection(&self.selected, path)
            .await?;
        crate::channel::exercise(
            fd,
            responder,
            rounds,
            bytes,
            mode,
            self.message_security.then_some(self.security),
        )?;
        // Last-close must not silently recreate the connection CMTC session.
        // Basic CUTC has no qualified close/rebind barrier in this lifetime.
        let reopened = connection.open_channel(3, self.security).await;
        match reopened {
            Err(libsparklink::ApplicationError::Bus(zbus::Error::MethodError(name, _, _)))
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
