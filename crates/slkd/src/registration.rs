//! Read-only Core registration objects. These never acquire Managed authority,
//! create protocol state or supply guessed controller capabilities/Host Ready.
use crate::state::{RegistrationDirectory, RegistrationObserver};
use slk_protocol::{RegistrationSnapshotRecord, SleRegistrationSnapshot};

fn record(s: SleRegistrationSnapshot) -> RegistrationSnapshotRecord {
    (
        s.generation,
        s.version,
        s.state,
        s.profile,
        s.phase,
        s.error,
        s.dev_index,
        s.bus,
    )
}
pub(crate) fn path(s: &SleRegistrationSnapshot) -> String {
    format!("/org/sparklink/slk{}_g{}", s.dev_index, s.generation)
}

pub(crate) struct RegistrationIface {
    observer: RegistrationObserver,
}
#[zbus::interface(name = "org.sparklink.Registration")]
impl RegistrationIface {
    #[zbus(signal)]
    async fn snapshot_changed(
        emitter: &zbus::object_server::SignalEmitter<'_>,
        snapshot: RegistrationSnapshotRecord,
    ) -> zbus::Result<()>;
    /// One atomic Core observation. A removed/reused identity is an error, even
    /// if object removal by the background manager has not finished yet.
    async fn get_snapshot(&self) -> zbus::fdo::Result<RegistrationSnapshotRecord> {
        let observer = self.observer.clone();
        tokio::task::spawn_blocking(move || {
            observer
                .adapter
                .registration_snapshot(observer.index, observer.generation)
                .map(record)
                .map_err(|e| match e {
                    libsparklink::Error::Ioctl(nix::errno::Errno::ENODEV) => {
                        zbus::fdo::Error::UnknownObject(
                            "registration removed or generation replaced".into(),
                        )
                    }
                    _ => zbus::fdo::Error::Failed(e.to_string()),
                })
        })
        .await
        .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?
    }
    #[zbus(property)]
    fn generation(&self) -> u64 {
        self.observer.generation
    }
    #[zbus(property)]
    fn index(&self) -> u16 {
        self.observer.index
    }
}

pub(crate) struct RegistrationNode {
    snapshot: SleRegistrationSnapshot,
    pub(crate) path: String,
}
impl RegistrationNode {
    pub(crate) fn generation(&self) -> u64 {
        self.snapshot.generation
    }
    pub(crate) async fn create(
        connection: &zbus::Connection,
        directory: &RegistrationDirectory,
        adapter: std::sync::Arc<libsparklink::Adapter>,
        snapshot: SleRegistrationSnapshot,
    ) -> anyhow::Result<Self> {
        let path = path(&snapshot);
        let observer = RegistrationObserver {
            adapter,
            index: snapshot.dev_index,
            generation: snapshot.generation,
        };
        anyhow::ensure!(
            connection
                .object_server()
                .at(
                    path.as_str(),
                    RegistrationIface {
                        observer: observer.clone()
                    }
                )
                .await?,
            "registration interface already published"
        );
        directory.lock().await.insert(path.clone(), observer);
        Ok(Self { snapshot, path })
    }
    pub(crate) async fn update(
        &mut self,
        connection: &zbus::Connection,
        snapshot: SleRegistrationSnapshot,
    ) -> anyhow::Result<()> {
        anyhow::ensure!(
            snapshot.dev_index == self.snapshot.dev_index
                && snapshot.generation == self.snapshot.generation,
            "registration node identity changed"
        );
        if snapshot != self.snapshot {
            self.snapshot = snapshot;
            // Notification only. Readers requery the atomic Core snapshot; a
            // delayed signal never renews authority or revives a removed node.
            connection
                .emit_signal(
                    None::<&str>,
                    self.path.as_str(),
                    "org.sparklink.Registration",
                    "SnapshotChanged",
                    &(record(snapshot),),
                )
                .await?;
        }
        Ok(())
    }
    pub(crate) async fn remove(
        self,
        connection: &zbus::Connection,
        directory: &RegistrationDirectory,
    ) {
        directory.lock().await.remove(&self.path);
        let _ = connection
            .object_server()
            .remove::<RegistrationIface, _>(self.path.as_str())
            .await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{BufRead, BufReader},
        process::{Child, Command, Stdio},
        sync::Arc,
    };
    use tokio::sync::Mutex;
    struct Bus {
        child: Child,
        address: String,
    }
    impl Bus {
        fn start() -> Self {
            let executable = std::env::var_os("SPARKLINK_TEST_DBUS_DAEMON")
                .unwrap_or_else(|| "dbus-daemon".into());
            let mut child = Command::new(executable)
                .args(["--session", "--nofork", "--print-address=1"])
                .stdout(Stdio::piped())
                .spawn()
                .unwrap();
            let mut address = String::new();
            BufReader::new(child.stdout.take().unwrap())
                .read_line(&mut address)
                .unwrap();
            Self {
                child,
                address: address.trim().into(),
            }
        }
    }
    impl Drop for Bus {
        fn drop(&mut self) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
    #[tokio::test]
    async fn real_dbus_objects_never_replace_core_errors_with_cached_success() {
        let bus = Bus::start();
        let adapters = Arc::new(Mutex::new(Default::default()));
        let directory: RegistrationDirectory = Arc::new(Mutex::new(Default::default()));
        let server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .name("org.sparklink")
            .unwrap()
            .serve_at(
                "/org/sparklink",
                crate::dbus_iface::Root::new(adapters, directory.clone()),
            )
            .unwrap()
            .build()
            .await
            .unwrap();
        let client = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let fd = Arc::new(libsparklink::Adapter::open("/dev/null").unwrap());
        let fixture = SleRegistrationSnapshot {
            version: 1,
            generation: 7,
            state: 2,
            profile: 1,
            phase: 3,
            error: -2,
            dev_index: 2,
            bus: 4,
            ..Default::default()
        };
        let node = RegistrationNode::create(&server, &directory, fd.clone(), fixture)
            .await
            .unwrap();
        let original_path = node.path.clone();
        let proxy = zbus::Proxy::new(
            &client,
            "org.sparklink",
            original_path.as_str(),
            "org.sparklink.Registration",
        )
        .await
        .unwrap();
        let result: zbus::Result<RegistrationSnapshotRecord> = proxy.call("GetSnapshot", &()).await;
        assert!(
            result.is_err(),
            "/dev/null ENOTTY must not become cached Fault/Ready"
        );
        let manager = zbus::Proxy::new(
            &client,
            "org.sparklink",
            "/org/sparklink",
            "org.sparklink.Manager",
        )
        .await
        .unwrap();
        let result: zbus::Result<Vec<String>> = manager.call("ListRegistrations", &()).await;
        assert!(result.is_err());
        let xml = zbus::fdo::IntrospectableProxy::builder(&client)
            .destination("org.sparklink")
            .unwrap()
            .path(node.path.as_str())
            .unwrap()
            .build()
            .await
            .unwrap()
            .introspect()
            .await
            .unwrap();
        assert!(xml.contains("org.sparklink.Registration"));
        assert!(!xml.contains("name=\"Ready\""));
        assert!(!xml.contains("AcquireManagement"));
        node.remove(&server, &directory).await;
        assert!(directory.lock().await.is_empty());
        let paths: Vec<String> = manager.call("ListRegistrations", &()).await.unwrap();
        assert!(paths.is_empty());
        let replacement = RegistrationNode::create(
            &server,
            &directory,
            fd,
            SleRegistrationSnapshot {
                generation: 8,
                ..fixture
            },
        )
        .await
        .unwrap();
        assert_eq!(replacement.path, "/org/sparklink/slk2_g8");
        let result: zbus::Result<RegistrationSnapshotRecord> = proxy.call("GetSnapshot", &()).await;
        assert!(result.is_err(), "old object cannot route to replacement");
        replacement.remove(&server, &directory).await;
    }
}
