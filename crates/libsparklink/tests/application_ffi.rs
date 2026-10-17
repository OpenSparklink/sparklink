//! Actual cdylib/header and Python public entry against a real private bus.
//! Fixture replies are explicit denials/AF_UNIX fds, never a successful channel.
mod support;
use std::{
    path::PathBuf,
    process::Command,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};
const BASE: &str = "/org/sparklink/slk2_g7";
const PATH: &str = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b";
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into(), "/org/sparklink/slk3_g9".into()]
    }
}
struct Adapter;
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        7
    }
}
struct Link(Arc<AtomicUsize>);
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
    fn get_info(&self) -> slk_contract::ConnectionInfo {
        (7, 11, 3, 0, 1, "01:02:03:04:05:06".into(), true, true)
    }
    fn open_channel(&self) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(zbus::fdo::Error::AccessDenied(
            "explicit fixture denial".into(),
        ))
    }
    fn open_channel_scoped(
        &self,
        directions: u32,
        minimum: u32,
    ) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
        assert_eq!((directions, minimum), (3, 2));
        self.0.fetch_add(10, Ordering::SeqCst);
        let fd: std::os::fd::OwnedFd = std::os::unix::net::UnixDatagram::unbound()
            .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?
            .into();
        Ok(fd.into())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_c_and_python_application_clients_share_broker_and_fd_rejection()
-> anyhow::Result<()> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()?;
    // Cargo builds the actual cdylib alongside this test under deps. Do not use
    // an arbitrary pre-existing target/debug library or a mock exported ABI.
    let library = std::env::current_exe()?
        .parent()
        .unwrap()
        .join("liblibsparklink.so");
    anyhow::ensure!(
        library.is_file(),
        "actual test-profile application cdylib missing: {}",
        library.display()
    );
    let directory = std::env::temp_dir().join(format!("slk-client-ffi-{}", std::process::id()));
    std::fs::create_dir(&directory)?;
    struct Cleanup(PathBuf);
    impl Drop for Cleanup {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    let _cleanup = Cleanup(directory.clone());
    // The compiled file has its real installed ABI SONAME. Supply only that
    // runtime link in this private test directory, as the installer does.
    std::os::unix::fs::symlink(&library, directory.join("libsparklink.so.0"))?;
    let c = directory.join("client");
    let compile = Command::new(std::env::var("CC").unwrap_or("cc".into()))
        .args(["-std=c11", "-Wall", "-Wextra", "-Werror"])
        .arg(root.join("crates/libsparklink/tests/fixtures/application_client.c"))
        .arg("-I")
        .arg(root.join("crates/libsparklink/include"))
        .arg(&library)
        .arg("-o")
        .arg(&c)
        .output()?;
    anyhow::ensure!(
        compile.status.success(),
        "C header/compile failed: {}",
        String::from_utf8_lossy(&compile.stderr)
    );
    let bus = support::Bus::start();
    let calls = Arc::new(AtomicUsize::new(0));
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter)?
        .serve_at(PATH, Link(calls.clone()))?
        .build()
        .await?;
    for language in ["c", "python"] {
        let mut command = Command::new("timeout");
        command.arg("20s");
        if language == "c" {
            command.arg(&c);
        } else {
            command
                .arg("python3")
                .arg(root.join("crates/libsparklink/tests/fixtures/application_client.py"));
        }
        let output = command
            .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
            .env("LIBSPARKLINK_PATH", &library)
            .env("PYTHONPATH", root.join("bindings/python"))
            .env("LD_LIBRARY_PATH", &directory)
            .output()?;
        anyhow::ensure!(
            output.status.success(),
            "{language} client failed {:?}: {} {}",
            output.status.code(),
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(
            String::from_utf8_lossy(&output.stdout)
                .contains("CURRENT_APPLICATION_CLIENT_NEGATIVE_BUS_PASS")
        );
    }
    assert_eq!(
        calls.load(Ordering::SeqCst),
        22,
        "no retry or weaker fallback, invalid inputs never reach OpenChannel"
    );
    Ok(())
}
