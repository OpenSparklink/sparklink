//! Actual cdylib/header and Python public entry against a real private bus.
//! Finite metadata, explicit denials/AF_UNIX fds and actual SDK callbacks; no
//! successful Native channel, daemon SSAP Engine, wire or hardware qualification.
#[path = "application_ffi/authorization.rs"]
mod authorization;
#[path = "application_ffi/pending_owner.rs"]
mod pending_owner;
#[path = "application_ffi/read_provider.rs"]
mod read_provider;
#[path = "application_ffi/subscription.rs"]
mod subscription;
mod support;
#[path = "application_ffi/value_update.rs"]
mod value_update;
#[path = "application_ffi/write_provider.rs"]
mod write_provider;
use std::{
    io::{BufRead, Read, Write},
    path::PathBuf,
    process::{Command, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, AtomicUsize, Ordering},
    },
};
const BASE: &str = "/org/sparklink/slk2_g7";
const PATH: &str = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b";
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    async fn get_controller_changes(
        &self,
        after: u64,
        wait: bool,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<slk_contract::controller_events::Batch> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        match (after, wait) {
            (0, false) => Ok((1, 0, 0, false, vec![])),
            (0, true) => Ok((1, 1, 2, false, vec![(1, 2, 7, 1), (2, 2, 7, 2)])),
            _ => Err(zbus::fdo::Error::InvalidArgs(
                "finite directory metadata fixture only".into(),
            )),
        }
    }
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into(), "/org/sparklink/slk3_g9".into()]
    }
}
struct Adapter;
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    // Finite language serialization fixture, not scan scheduling or RF success.
    fn acquire_discovery(
        &self,
        prefix: Vec<u8>,
        rssi: i16,
        duration: u32,
        stamp: slk_contract::Deadline,
    ) -> zbus::fdo::Result<u64> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp)).unwrap();
        if (prefix, rssi, duration) != (vec![0xab], -128, 20000) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "finite discovery fixture".into(),
            ));
        }
        Ok(9)
    }
    fn read_discovery(
        &self,
        session: u64,
        _wait: bool,
        stamp: slk_contract::Deadline,
    ) -> zbus::fdo::Result<slk_contract::discovery::Batch> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp)).unwrap();
        if session != 9 {
            return Err(zbus::fdo::Error::UnknownObject(
                "finite discovery fixture".into(),
            ));
        }
        let mut header = vec![0; 23];
        header[2..8].copy_from_slice(&[1, 2, 3, 4, 5, 6]);
        Ok(slk_contract::discovery::Batch {
            version: 1,
            session,
            generation: 7,
            dropped: 0,
            kernel_lost: 0,
            reports: vec![slk_contract::discovery::Report {
                sequence: 1,
                kernel_boottime_ns: 1,
                address_type: 0,
                address: vec![1, 2, 3, 4, 5, 6],
                rssi: -42,
                rssi_known: true,
                header,
                data: vec![0xab, 0xff],
            }],
        })
    }
    fn release_discovery(
        &self,
        session: u64,
        _stamp: slk_contract::Deadline,
    ) -> zbus::fdo::Result<bool> {
        if session != 9 {
            return Err(zbus::fdo::Error::UnknownObject(
                "finite discovery fixture".into(),
            ));
        }
        Ok(true)
    }
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        7
    }
}
type CommandCall = (u16, u32, Vec<u8>, slk_contract::Deadline);
struct Link(
    Arc<AtomicUsize>,
    Arc<AtomicUsize>,
    Arc<AtomicU64>,
    Arc<subscription::Metadata>,
    Arc<Mutex<Vec<CommandCall>>>,
    Arc<AtomicUsize>,
);
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
    fn subscribe_ssap_updates(
        &self,
        handles: Vec<u16>,
        modes: u8,
        duration_ms: u32,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::ssap::subscription::Info> {
        self.3.subscribe(
            handles,
            modes,
            duration_ms,
            deadline,
            h.sender().unwrap().to_string(),
            self.2.load(Ordering::SeqCst),
        )
    }
    fn read_ssap_updates(
        &self,
        token: u64,
        _wait: bool,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::ssap::subscription::Batch> {
        self.3.read(token, deadline, h.sender().unwrap().as_str())
    }
    fn renew_ssap_subscription(
        &self,
        token: u64,
        duration_ms: u32,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::ssap::subscription::Info> {
        self.3
            .renew(token, duration_ms, deadline, h.sender().unwrap().as_str())
    }
    fn close_ssap_subscription(
        &self,
        token: u64,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::ssap::subscription::Batch> {
        self.3.close(token, deadline, h.sender().unwrap().as_str())
    }
    fn get_info(&self) -> slk_contract::ConnectionInfo {
        (
            7,
            self.2.load(Ordering::SeqCst),
            3,
            0,
            1,
            "01:02:03:04:05:06".into(),
            true,
            true,
        )
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
    // Finite broker serialization/identity fixture, not a protocol peer or
    // successful dependency stub. Wrong requests fail and result != input.
    async fn read_ssap_value(
        &self,
        handle: u16,
        minimum: u32,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<Vec<u8>> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        self.1.fetch_add(1, Ordering::SeqCst);
        match (handle, minimum) {
            (17, 0 | 2) => Ok(vec![0x34, 0x78]),
            (18, 0) => Ok(vec![0; 65536]), // Over the C output budget, not RF/MTU.
            (19, 0) => {
                self.2.store(12, Ordering::SeqCst);
                Ok(vec![0xff])
            }
            (20, 0) => {
                tokio::time::sleep(std::time::Duration::from_millis(500)).await;
                Ok(vec![0xfe])
            }
            (21, 0) => Err(zbus::fdo::Error::Timeout(
                "explicit immediate error fixture; not an elapsed deadline".into(),
            )),
            _ => Err(zbus::fdo::Error::NotSupported(
                "unmatched fixture read".into(),
            )),
        }
    }
    fn read_ssap_description(
        &self,
        handle: u16,
        minimum: u32,
        original: slk_contract::Deadline,
    ) -> zbus::fdo::Result<Vec<u8>> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(original))
            .unwrap();
        self.5.fetch_add(1, Ordering::SeqCst);
        match (handle, minimum) {
            (17, 0 | 2) => Ok("描述".as_bytes().to_vec()),
            _ => Err(zbus::fdo::Error::NotSupported(
                "finite description fixture".into(),
            )),
        }
    }
    fn write_ssap_value(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<Vec<u8>> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        self.1.fetch_add(1, Ordering::SeqCst);
        match (handle, minimum, value.as_slice()) {
            (17, 1, [0x56, 0x12]) => Ok(vec![0x90]),
            (17, 0, []) => Ok(vec![0x91]),
            (21, 0, [0x56, 0x12]) => Err(zbus::fdo::Error::Timeout(
                "explicit immediate error fixture; not an elapsed deadline".into(),
            )),
            _ => Err(zbus::fdo::Error::InvalidArgs(
                "unmatched fixture write".into(),
            )),
        }
    }
    fn write_ssap_command(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<()> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
            .unwrap();
        self.1.fetch_add(1, Ordering::SeqCst);
        self.4
            .lock()
            .unwrap()
            .push((handle, minimum, value.clone(), deadline));
        match (handle, minimum, value.as_slice()) {
            (17, 1, [0x56, 0x12]) | (17, 0, []) => Ok(()),
            (17, 0, bytes) if bytes.len() == 2042 && bytes.iter().all(|v| *v == 0xa5) => Ok(()),
            // An explicit finite daemon fixture, not a negotiated MTU or RF result.
            (17, 0, bytes) if bytes.len() == 2043 => Err(zbus::fdo::Error::InvalidArgs(
                "fixture-only 2043 command rejection; not negotiated MTU or hardware".into(),
            )),
            (21, 0, bytes) if bytes.len() == 2043 => Err(zbus::fdo::Error::Timeout(
                "wrong-error negative control for command rejection helper".into(),
            )),
            (22, 0, bytes) if bytes.len() == 2043 => Ok(()), // Unexpected-success negative control.
            (21, 0, [0x56, 0x12]) => Err(zbus::fdo::Error::Timeout(
                "explicit immediate command error fixture; not elapsed deadline".into(),
            )),
            _ => Err(zbus::fdo::Error::InvalidArgs(
                "unmatched command fixture".into(),
            )),
        }
    }
}

// Finite metadata and callback sender fixture,not a DB,wire or Native Engine.
#[derive(Default)]
struct OwnedMetadata {
    owner: Mutex<String>,
    authorizer: Mutex<String>,
    provider: Mutex<String>,
    provider_binds: AtomicUsize,
    operations: AtomicUsize,
    registered: AtomicUsize,
    read: AtomicUsize,
    removed: AtomicUsize,
    value: Mutex<Vec<u8>>,
    replacements: AtomicUsize,
    descriptions: Mutex<Vec<(u16, String, slk_contract::Deadline)>>,
}
struct OwnedServices(Arc<OwnedMetadata>);
#[zbus::interface(name = "org.sparklink.ServiceManager")]
impl OwnedServices {
    fn register_owned_local_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<slk_contract::ssap::local::PropertyDefinition>,
        authorizer: zbus::zvariant::OwnedObjectPath,
        stamp: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> (u16, u16, Vec<u16>) {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp)).unwrap();
        assert_eq!(uuid, [1, 0]);
        let access = properties[0].2;
        assert!(matches!(access, 0 | 36));
        assert!(matches!(properties[0].1, 1 | 5 | 6));
        assert_eq!(
            properties,
            [(vec![2, 0], properties[0].1, access, vec![7, 8, 9])]
        );
        *self.0.value.lock().unwrap() = vec![7, 8, 9];
        assert_eq!(
            authorizer.as_str(),
            if access == 0 {
                "/"
            } else {
                "/org/sparklink/sdk/ssap_authorizer"
            }
        );
        *self.0.authorizer.lock().unwrap() = authorizer.to_string();
        self.0.provider.lock().unwrap().clear();
        self.0
            .operations
            .store(properties[0].1 as usize, Ordering::SeqCst);
        *self.0.owner.lock().unwrap() = h.sender().unwrap().to_string();
        self.0.registered.fetch_add(1, Ordering::SeqCst);
        (16, 17, vec![17])
    }
    fn bind_owned_read_provider(
        &self,
        handle: u16,
        provider: zbus::zvariant::OwnedObjectPath,
        original: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(original))
            .unwrap();
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        assert_eq!(self.0.operations.load(Ordering::SeqCst), 1);
        assert_eq!(handle, 17);
        assert_eq!(provider.as_str(), "/org/sparklink/sdk/ssap_read_provider");
        let mut current = self.0.provider.lock().unwrap();
        assert!(current.is_empty(), "one bind per original registration");
        *current = provider.to_string();
        self.0.provider_binds.fetch_add(1, Ordering::SeqCst);
    }
    fn bind_owned_write_provider(
        &self,
        handle: u16,
        provider: zbus::zvariant::OwnedObjectPath,
        original: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(original))
            .unwrap();
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        assert_eq!(self.0.operations.load(Ordering::SeqCst), 6);
        assert_eq!(handle, 17);
        assert_eq!(provider.as_str(), "/org/sparklink/sdk/ssap_read_provider");
        let mut current = self.0.provider.lock().unwrap();
        assert!(current.is_empty(), "one bind per original registration");
        *current = provider.to_string();
        self.0.provider_binds.fetch_add(1, Ordering::SeqCst);
    }
    fn read_owned_local_value(
        &self,
        handle: u16,
        stamp: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> Vec<u8> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp)).unwrap();
        assert_eq!(handle, 17);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        self.0.read.fetch_add(1, Ordering::SeqCst);
        self.0.value.lock().unwrap().clone()
    }
    fn replace_owned_local_value(
        &self,
        handle: u16,
        value: Vec<u8>,
        stamp: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp)).unwrap();
        assert_eq!(handle, 17);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        assert!(value.len() <= 2042);
        *self.0.value.lock().unwrap() = value;
        self.0.replacements.fetch_add(1, Ordering::SeqCst);
    }
    fn set_owned_local_description(
        &self,
        handle: u16,
        text: String,
        original: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(original))
            .unwrap();
        assert_eq!(handle, 17);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        assert!((1..=244).contains(&text.len()) && !text.contains('\0'));
        self.0
            .descriptions
            .lock()
            .unwrap()
            .push((handle, text, original));
    }
    fn unregister_owned_local_service(
        &self,
        start: u16,
        stamp: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp)).unwrap();
        assert_eq!(start, 16);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        self.0.removed.fetch_add(1, Ordering::SeqCst);
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
    let retained = std::env::var_os("SPARKLINK_APPLICATION_FFI_ARTIFACT_DIR");
    let directory = retained.as_ref().map(PathBuf::from).unwrap_or_else(|| {
        std::env::temp_dir().join(format!("slk-client-ffi-{}", std::process::id()))
    });
    std::fs::create_dir(&directory)?;
    struct Cleanup(PathBuf, bool);
    impl Drop for Cleanup {
        fn drop(&mut self) {
            if self.1 {
                let _ = std::fs::remove_dir_all(&self.0);
            } else if !self.0.join("COMPLETE").exists() {
                let _ = std::fs::write(
                    self.0.join("INCOMPLETE"),
                    b"Failed or incomplete fixture; not qualification.\n",
                );
            }
        }
    }
    // Failure diagnostics and the actual executed ELF must survive even when
    // the caller omitted explicit artifact retention. COMPLETE is written last.
    let mut cleanup = Cleanup(directory.clone(), false);
    // The compiled file has its real installed ABI SONAME. Supply only that
    // runtime name in this private directory, with the exact compiled bytes.
    let runtime_library = directory.join("libsparklink.so.0");
    std::fs::copy(&library, &runtime_library)?;
    let compiler = std::env::var("CC").unwrap_or("cc".into());
    let compiler_version = Command::new(&compiler).arg("--version").output()?;
    anyhow::ensure!(
        compiler_version.status.success(),
        "C compiler version failed"
    );
    std::fs::write(
        directory.join("build-environment.txt"),
        format!(
            "compiler={compiler:?}\nversion_stdout={}\nversion_stderr={}\ntoolchain={:?}\nrust_test={:?}\nloaded_library={:?}\nscope=Actual test-profile fixture;not device/Engine/RF\n",
            String::from_utf8_lossy(&compiler_version.stdout),
            String::from_utf8_lossy(&compiler_version.stderr),
            std::env::var("RUSTUP_TOOLCHAIN").ok(),
            std::env::current_exe()?,
            runtime_library
        ),
    )?;
    let c = directory.join("client");
    let compile = Command::new(&compiler)
        .args(["-std=c11", "-Wall", "-Wextra", "-Werror", "-pthread"])
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
    let sdk_probe = directory.join("sdk-ssap-probe");
    let compiled = Command::new(&compiler)
        .args(["-std=c11", "-Wall", "-Wextra", "-Werror"])
        .arg(root.join("tools/testing/application_client/client.c"))
        .arg("-I")
        .arg(root.join("crates/libsparklink/include"))
        .arg(&library)
        .arg("-o")
        .arg(&sdk_probe)
        .output()?;
    anyhow::ensure!(
        compiled.status.success(),
        "actual SDK consumer compile: {}",
        String::from_utf8_lossy(&compiled.stderr)
    );
    // Explicit qualification retention keeps the actual executable and outputs;
    // recompiling a consumer later cannot reconstruct its execution identity.
    let identities = Command::new("sha256sum")
        .arg(&library)
        .arg(&runtime_library)
        .arg(&c)
        .arg(&sdk_probe)
        .arg(root.join("crates/libsparklink/tests/application_ffi/write_provider.rs"))
        .arg(root.join("crates/libsparklink/src/ffi_service_write_provider.rs"))
        .arg(root.join("crates/libsparklink/src/ssap/provider/request.rs"))
        .arg(root.join("crates/libsparklink/include/sparklink.h"))
        .arg(root.join("crates/libsparklink/tests/fixtures/application_client.c"))
        .arg(root.join("crates/libsparklink/tests/fixtures/application_client.py"))
        .arg(root.join("tools/testing/application_client/client.c"))
        .arg(root.join("tools/testing/application_client/client.py"))
        .arg(root.join("bindings/python/sparklink/local_services.py"))
        .arg(root.join("bindings/python/sparklink/service_authorization.py"))
        .arg(root.join("bindings/python/sparklink/service_provider.py"))
        .arg(root.join("crates/libsparklink/tests/application_ffi/authorization.rs"))
        .arg(root.join("crates/libsparklink/tests/application_ffi/read_provider.rs"))
        .arg(root.join("crates/libsparklink/src/ffi_service_provider.rs"))
        .arg(root.join("crates/libsparklink/src/ssap/provider.rs"))
        .arg(root.join("crates/libsparklink/src/ssap/provider/frontend.rs"))
        .arg(root.join("crates/libsparklink/tests/application_ffi/value_update.rs"))
        .arg(root.join("crates/libsparklink/tests/application_ffi/subscription.rs"))
        .arg(root.join("bindings/python/sparklink/ssap_subscription.py"))
        .arg(root.join("crates/libsparklink/src/ssap/subscription.rs"))
        .arg(root.join("crates/libsparklink/src/ffi_ssap_subscription.rs"))
        .output()?;
    anyhow::ensure!(
        identities.status.success() && identities.stderr.is_empty(),
        "artifact hash command failed"
    );
    std::fs::write(directory.join("materials.sha256"), &identities.stdout)?;
    let bus = support::Bus::start();
    let calls = Arc::new(AtomicUsize::new(0));
    let ssap_calls = Arc::new(AtomicUsize::new(0));
    let description_reads = Arc::new(AtomicUsize::new(0));
    let command_calls = Arc::new(Mutex::new(Vec::new()));
    let lifetime = Arc::new(AtomicU64::new(11));
    let subscriptions = Arc::new(subscription::Metadata::default());
    let owned = Arc::new(OwnedMetadata::default());
    let server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter)?
        .serve_at(format!("{BASE}/services"), OwnedServices(owned.clone()))?
        .serve_at(
            PATH,
            Link(
                calls.clone(),
                ssap_calls.clone(),
                lifetime.clone(),
                subscriptions.clone(),
                command_calls.clone(),
                description_reads.clone(),
            ),
        )?
        .build()
        .await?;
    for language in ["c", "python"] {
        let mut cmd = Command::new("timeout");
        cmd.arg("10s");
        if language == "c" {
            cmd.arg(&sdk_probe);
        } else {
            cmd.arg("python3")
                .arg(root.join("tools/testing/application_client/client.py"));
        }
        let mut process = cmd
            .args(["owned", "2", "7", "0100", "0200", "070809"])
            .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
            .env("LIBSPARKLINK_PATH", &runtime_library)
            .env("PYTHONPATH", root.join("bindings/python"))
            .env("LD_LIBRARY_PATH", &directory)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let mut stdout = std::io::BufReader::new(process.stdout.take().unwrap());
        let mut transcript = String::new();
        for expected in [
            format!("SdkOwnedAPI: api={language} client_closed=true\n"),
            "SsapOwnedService: start=16 end=17 property=17; local registration only\n".into(),
        ] {
            let mut line = String::new();
            stdout.read_line(&mut line)?;
            assert_eq!(line, expected);
            transcript.push_str(&line);
        }
        process.stdin.as_mut().unwrap().write_all(b"value\n")?;
        let mut line = String::new();
        stdout.read_line(&mut line)?;
        assert_eq!(line, "SsapOwnedValue: handle=17 value=070809\n");
        transcript.push_str(&line);
        process.stdin.as_mut().unwrap().write_all(b"quit\n")?;
        let mut rest = String::new();
        stdout.read_to_string(&mut rest)?;
        assert_eq!(rest, format!("SdkOwnedRemoved: api={language} start=16\n"));
        transcript.push_str(&rest);
        let output = process.wait_with_output()?;
        std::fs::write(
            directory.join(format!("{language}-owned.stdout")),
            transcript,
        )?;
        std::fs::write(
            directory.join(format!("{language}-owned.stderr")),
            &output.stderr,
        )?;
        assert!(
            output.status.success() && output.stderr.is_empty(),
            "{language} Owned consumer failed: {output:?}"
        );
    }
    // Actual installed language frontends consume requests while their original
    // Client has closed. This tests real RPC/eventfd/FFI policy delivery, not RF.
    for language in ["c", "python"] {
        for policy in ["allow", "deny"] {
            let mut command = Command::new("timeout");
            command.arg("10s");
            if language == "c" {
                command.arg(&sdk_probe);
            } else {
                command
                    .arg("python3")
                    .arg(root.join("tools/testing/application_client/client.py"));
            }
            let mut process = command
                .args(["owned", "2", "7", "0100", "0200", "070809", policy])
                .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
                .env("LIBSPARKLINK_PATH", &runtime_library)
                .env("PYTHONPATH", root.join("bindings/python"))
                .env("LD_LIBRARY_PATH", &directory)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?;
            let mut stdout = std::io::BufReader::new(process.stdout.take().unwrap());
            let mut transcript = String::new();
            for expected in [
                format!("SdkOwnedAPI: api={language} client_closed=true\n"),
                "SsapOwnedService: start=16 end=17 property=17; local registration only\n".into(),
            ] {
                let mut line = String::new();
                stdout.read_line(&mut line)?;
                assert_eq!(line, expected);
                transcript.push_str(&line);
            }
            let owner = owned.owner.lock().unwrap().clone();
            let path = owned.authorizer.lock().unwrap().clone();
            let mut last_token = 0;
            for (request_id, write) in [(1u64, false), (2, true)] {
                let deadline =
                    slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(2))?
                        .stamp()
                        .monotonic_ns;
                let value = if write { vec![4u8, 5, 6] } else { vec![] };
                let prompt: slk_contract::ssap::SsapAuthorizationPrompt = (
                    request_id,
                    (2, 7, 13, 3, 41, 0, 10, 10, 0),
                    17,
                    write,
                    deadline,
                    value.clone(),
                    0,
                );
                let wall_start = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_nanos() as u64;
                let message = server
                    .call_method(
                        Some(owner.as_str()),
                        path.as_str(),
                        Some("org.sparklink.SsapAuthorizer"),
                        "AuthorizeValue",
                        &(prompt,),
                    )
                    .await?;
                let wall_end = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_nanos() as u64;
                assert_eq!(message.body().deserialize::<bool>()?, policy == "allow");
                let mut line = String::new();
                stdout.read_line(&mut line)?;
                let decision: serde_json::Value =
                    serde_json::from_str(line.strip_prefix("SdkAuthorizationDecision: ").unwrap())?;
                assert_eq!(decision["api"], language);
                for (name, expected) in [
                    ("index", 2),
                    ("generation", 7),
                    ("request_id", request_id),
                    ("lifetime", 13),
                    ("handle", 3),
                    ("epoch", 41),
                    ("level", 0),
                    ("property", 17),
                    ("local_tcid", 10),
                    ("remote_tcid", 10),
                    ("pi", 0),
                    ("deadline_ns", deadline),
                ] {
                    assert_eq!(decision[name].as_u64(), Some(expected), "{name}");
                }
                assert_eq!(decision["write"], write);
                assert_eq!(decision["allow"], policy == "allow");
                assert_eq!(decision["value"], if write { "040506" } else { "" });
                let token = decision["token"].as_u64().unwrap();
                assert!(token > last_token);
                last_token = token;
                assert!(decision["decision_ns"].as_u64().unwrap() < deadline);
                assert!(
                    (wall_start..=wall_end)
                        .contains(&decision["decision_wall_ns"].as_u64().unwrap())
                );
                transcript.push_str(&line);
            }
            process
                .stdin
                .as_mut()
                .unwrap()
                .write_all(b"value\nquit\n")?;
            let mut rest = String::new();
            stdout.read_to_string(&mut rest)?;
            assert_eq!(
                rest,
                format!(
                    "SsapOwnedValue: handle=17 value=070809\nSdkOwnedRemoved: api={language} start=16\n"
                )
            );
            transcript.push_str(&rest);
            let output = process.wait_with_output()?;
            std::fs::write(
                directory.join(format!("{language}-authorization-{policy}.stdout")),
                transcript,
            )?;
            std::fs::write(
                directory.join(format!("{language}-authorization-{policy}.stderr")),
                &output.stderr,
            )?;
            assert!(
                output.status.success() && output.stderr.is_empty(),
                "actual {language}/{policy}: {output:?}"
            );
        }
    }
    assert_eq!(
        (
            owned.registered.load(Ordering::SeqCst),
            owned.read.load(Ordering::SeqCst),
            owned.removed.load(Ordering::SeqCst)
        ),
        (6, 6, 6)
    );
    authorization::exercise(
        &root,
        &sdk_probe,
        &runtime_library,
        &directory,
        &bus.address,
        &server,
        &owned,
    )
    .await?;
    assert_eq!(
        (
            owned.registered.load(Ordering::SeqCst),
            owned.read.load(Ordering::SeqCst),
            owned.removed.load(Ordering::SeqCst)
        ),
        (8, 8, 6)
    );
    value_update::exercise(
        &root,
        &sdk_probe,
        &runtime_library,
        &directory,
        &bus.address,
    )
    .await?;
    subscription::exercise(
        &root,
        &sdk_probe,
        &runtime_library,
        &directory,
        &bus.address,
        &subscriptions,
    )
    .await?;
    assert_eq!(
        (
            owned.registered.load(Ordering::SeqCst),
            owned.read.load(Ordering::SeqCst),
            owned.removed.load(Ordering::SeqCst),
            owned.replacements.load(Ordering::SeqCst)
        ),
        (10, 14, 8, 6)
    );
    for language in ["c", "python"] {
        let mut command = Command::new("timeout");
        command.arg("10s");
        if language == "c" {
            command.arg(&sdk_probe);
        } else {
            command
                .arg("python3")
                .arg(root.join("tools/testing/application_client/client.py"));
        }
        let output = command
            .args(["discovery", "2", "7", "ab", "1", "010203040506"])
            .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
            .env("LIBSPARKLINK_PATH", &runtime_library)
            .env("PYTHONPATH", root.join("bindings/python"))
            .env("LD_LIBRARY_PATH", &directory)
            .output()?;
        std::fs::write(
            directory.join(format!("{language}-discovery.stdout")),
            &output.stdout,
        )?;
        std::fs::write(
            directory.join(format!("{language}-discovery.stderr")),
            &output.stderr,
        )?;
        anyhow::ensure!(
            output.status.success() && output.stderr.is_empty(),
            "external discovery {language}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let text = std::str::from_utf8(&output.stdout)?;
        anyhow::ensure!(
            text == "Selected /org/sparklink/slk2_g7\nDiscoverySession: id=9 path=/org/sparklink/slk2_g7 state=active source=broker\nDiscoveryReport: session=9 generation=7 sequence=1 address_type=0 address=010203040506 rssi=-42 data=abff\nDiscoveryReleased: session=9 last_physical_stop_confirmed=true\n",
            "exact external discovery delivery {language}"
        );
    }
    for language in ["c", "python"] {
        lifetime.store(11, Ordering::SeqCst);
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
            .env("LIBSPARKLINK_PATH", &runtime_library)
            .env("PYTHONPATH", root.join("bindings/python"))
            .env("LD_LIBRARY_PATH", &directory)
            .output()?;
        std::fs::write(directory.join(format!("{language}.stdout")), &output.stdout)?;
        std::fs::write(directory.join(format!("{language}.stderr")), &output.stderr)?;
        // The deliberate fork-negative on Python>=3.12 warns about inheriting
        // a multithreaded process. Preserve and recognize only that warning;
        // it is not evidence that opening/using a client after fork is safe.
        if language == "python" && !output.stderr.is_empty() {
            let warning = std::str::from_utf8(&output.stderr)?;
            let lines: Vec<_> = warning.lines().collect();
            anyhow::ensure!(
                lines.len() == 2
                    && lines[0].contains("application_client.py:")
                    && lines[0].contains(": DeprecationWarning: This process (pid=")
                    && lines[0].ends_with(
                        "is multi-threaded, use of fork() may lead to deadlocks in the child."
                    )
                    && lines[1].trim() == "child = os.fork()",
                "unexpected Python consumer diagnostic: {warning}"
            );
        } else {
            anyhow::ensure!(
                output.stderr.is_empty(),
                "unexpected C consumer diagnostic (retained {}): {}",
                directory.display(),
                String::from_utf8_lossy(&output.stderr)
            );
        }
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
        assert!(
            String::from_utf8_lossy(&output.stdout)
                .contains("CURRENT_CONTROLLER_DIRECTORY_LANGUAGE_FIXTURE_PASS_NOT_RF")
        );
    }
    assert_eq!(
        description_reads.load(Ordering::SeqCst),
        5,
        "new description method only; expired/invalid/stale calls cannot fall back to value"
    );
    {
        let descriptions = owned.descriptions.lock().unwrap();
        assert_eq!(descriptions.len(), 4);
        assert_eq!(
            descriptions.iter().map(|v| v.1.len()).collect::<Vec<_>>(),
            [6, 244, 6, 244]
        );
    }
    assert_eq!(
        calls.load(Ordering::SeqCst),
        22,
        "no retry or weaker fallback, invalid inputs never reach OpenChannel"
    );
    assert_eq!(
        ssap_calls.load(Ordering::SeqCst),
        24,
        "exact finite RPC count; invalid, expired and retired inputs never retry"
    );
    lifetime.store(11, Ordering::SeqCst);
    // Exercise the actual VM consumer binaries/modes, not an internal wrapper.
    // They retain the original5s deadline and wait for this explicit start.
    for language in ["c", "python"] {
        for correct in [true, false] {
            let mut command = Command::new("timeout");
            command.arg("20s");
            if language == "c" {
                command.arg(&sdk_probe);
            } else {
                command
                    .arg("python3")
                    .arg(root.join("tools/testing/application_client/client.py"));
            }
            let mut process = command
                .args([
                    "ssap",
                    "2",
                    "7",
                    PATH,
                    "ssap-read",
                    "17",
                    if correct { "3478" } else { "0000" },
                ])
                .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
                .env("LIBSPARKLINK_PATH", &runtime_library)
                .env("PYTHONPATH", root.join("bindings/python"))
                .env("LD_LIBRARY_PATH", &directory)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?;
            let mut stdout = std::io::BufReader::new(process.stdout.take().unwrap());
            let mut barrier = String::new();
            stdout.read_line(&mut barrier)?;
            let expected = if language == "c" {
                r#"{"stage":"ssap_start_barrier","api":"c","client_closed":true}"#
            } else {
                r#"{"stage": "ssap_start_barrier", "api": "python", "client_closed": true}"#
            };
            assert_eq!(barrier.trim_end(), expected);
            process.stdin.as_mut().unwrap().write_all(b"start\n")?;
            let mut remaining = String::new();
            stdout.read_to_string(&mut remaining)?;
            let result = process.wait_with_output()?;
            let label = format!(
                "sdk-{language}-{}",
                if correct { "positive" } else { "negative" }
            );
            std::fs::write(
                directory.join(format!("{label}.stdout")),
                barrier + &remaining,
            )?;
            std::fs::write(directory.join(format!("{label}.stderr")), &result.stderr)?;
            if correct {
                assert!(result.status.success());
                assert!(result.stderr.is_empty());
                assert_eq!(
                    remaining,
                    format!(
                        "SsapPeerValue: operation=ssap-read path={PATH} handle=17 value=3478\n"
                    )
                );
            } else {
                assert_eq!(result.status.code(), Some(1));
                assert!(remaining.is_empty());
                if language == "c" {
                    assert_eq!(
                        result.stderr,
                        b"application-client-c-ssap: Protocol error\n"
                    );
                } else {
                    assert!(String::from_utf8_lossy(&result.stderr).ends_with(
                        "ValueError: actual peer SSAP result differs from expected random value\n"
                    ));
                }
            }
        }
    }
    assert_eq!(ssap_calls.load(Ordering::SeqCst), 28);
    // Actual C/Python VM consumers, including their new negative-result mode.
    // An immediate FDO Timeout tests errno mapping only: it must never qualify
    // the hardware gate's original five-second elapsed-time requirement.
    for language in ["c", "python"] {
        for (label, operation, handle, expected, success) in [
            ("timeout-read", "ssap-read", "21", "110", true),
            ("timeout-write", "ssap-write", "21", "110", true),
            ("wrong-errno", "ssap-read", "21", "5", false),
            ("unexpected-success", "ssap-read", "17", "110", false),
            ("invalid-errno", "ssap-read", "21", "0", false),
        ] {
            let mut command = Command::new("timeout");
            command.arg("20s");
            if language == "c" {
                command.arg(&sdk_probe);
            } else {
                command
                    .arg("python3")
                    .arg(root.join("tools/testing/application_client/client.py"));
            }
            command.args(["ssap-error", "2", "7", PATH, operation, handle, expected]);
            if operation == "ssap-write" {
                command.arg("5612");
            }
            let output = command
                .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
                .env("LIBSPARKLINK_PATH", &runtime_library)
                .env("PYTHONPATH", root.join("bindings/python"))
                .env("LD_LIBRARY_PATH", &directory)
                .output()?;
            std::fs::write(
                directory.join(format!("sdk-{language}-{label}.stdout")),
                &output.stdout,
            )?;
            std::fs::write(
                directory.join(format!("sdk-{language}-{label}.stderr")),
                &output.stderr,
            )?;
            assert_eq!(output.status.success(), success, "{language}/{label}");
            let text = std::str::from_utf8(&output.stdout)?.replace(' ', "");
            if success || label == "wrong-errno" {
                assert_eq!(text.lines().count(), 2);
                assert!(text.contains(r#""stage":"ssap_error""#));
                assert!(text.contains(r#""errno":110,"operation_success":false"#));
                if success {
                    assert!(output.stderr.is_empty());
                }
            } else if label == "unexpected-success" {
                if language == "c" {
                    assert!(text.contains(r#""errno":0,"operation_success":true"#));
                } else {
                    assert!(!text.contains(r#""stage":"ssap_error""#));
                }
            } else {
                assert!(text.is_empty(), "invalid expectation cannot reach the API");
            }
        }
    }
    assert_eq!(
        ssap_calls.load(Ordering::SeqCst),
        36,
        "eight added actual value calls; invalid expectations rejected before RPC"
    );
    // Actual new command helper entry points, with their own admission-only
    // output schema. The service remains a finite RPC fixture, never peer RF.
    for language in ["c", "python"] {
        for scenario in [
            "admitted",
            "empty",
            "boundary2042",
            "rejected",
            "eof",
            "stale",
            "invalid",
            "oversized2043",
        ] {
            lifetime.store(11, Ordering::SeqCst);
            let payload = match scenario {
                "empty" => String::new(),
                "boundary2042" => "a5".repeat(2042),
                "oversized2043" => "a5".repeat(2043),
                _ => "5612".to_owned(),
            };
            let minimum = match scenario {
                "invalid" => 3,
                "empty" | "boundary2042" | "oversized2043" => 0,
                _ => 1,
            };
            let minimum_arg = minimum.to_string();
            let admitted = matches!(scenario, "admitted" | "empty" | "boundary2042");
            let invalid_input = matches!(scenario, "invalid" | "oversized2043");
            let mut command = Command::new("timeout");
            command.arg("20s");
            if language == "c" {
                command.arg(&sdk_probe);
            } else {
                command
                    .arg("python3")
                    .arg(root.join("tools/testing/application_client/client.py"));
            }
            let mut process = command
                .args([
                    "ssap-command",
                    "2",
                    "7",
                    PATH,
                    if scenario == "rejected" { "18" } else { "17" },
                    &payload,
                    &minimum_arg,
                ])
                .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
                .env("LIBSPARKLINK_PATH", &runtime_library)
                .env("PYTHONPATH", root.join("bindings/python"))
                .env("LD_LIBRARY_PATH", &directory)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?;
            let mut stdout = std::io::BufReader::new(process.stdout.take().unwrap());
            let mut barrier = String::new();
            stdout.read_line(&mut barrier)?;
            let barrier_value: Option<serde_json::Value> = if invalid_input {
                assert!(barrier.is_empty(), "invalid input must not open the caller");
                None
            } else {
                let value: serde_json::Value = serde_json::from_str(&barrier)?;
                assert_eq!(value["stage"], "ssap_command_start_barrier");
                assert_eq!(value["api"], language);
                assert_eq!(value["client_closed"], true);
                assert!(value["deadline_ns"].as_u64().is_some());
                if scenario == "stale" {
                    lifetime.store(12, Ordering::SeqCst);
                }
                if scenario == "eof" {
                    drop(process.stdin.take());
                } else {
                    process.stdin.as_mut().unwrap().write_all(b"start\n")?;
                }
                Some(value)
            };
            let mut remaining = String::new();
            stdout.read_to_string(&mut remaining)?;
            let output = process.wait_with_output()?;
            std::fs::write(
                directory.join(format!("sdk-{language}-command-{scenario}.stdout")),
                barrier + &remaining,
            )?;
            std::fs::write(
                directory.join(format!("sdk-{language}-command-{scenario}.stderr")),
                &output.stderr,
            )?;
            assert_eq!(output.status.success(), admitted, "{language}/{scenario}");
            assert!(!remaining.contains("SsapPeerValue:"));
            if admitted {
                assert!(output.stderr.is_empty());
                let line = remaining
                    .strip_prefix("SSAP_COMMAND_ADMITTED: ")
                    .expect("explicit admission receipt");
                let receipt: serde_json::Value = serde_json::from_str(line)?;
                assert_eq!(receipt["api"], language);
                assert_eq!(receipt["handle"], 17);
                assert_eq!(receipt["value"], payload);
                assert_eq!(receipt["minimum"], minimum);
                assert_eq!(receipt["admission_only"], true);
                assert_eq!(receipt["peer_delivery_confirmed"], false);
                assert_eq!(
                    receipt["deadline_ns"],
                    barrier_value.unwrap()["deadline_ns"]
                );
                let (called, returned, end) = (
                    receipt["call_ns"].as_u64().unwrap(),
                    receipt["returned_ns"].as_u64().unwrap(),
                    receipt["deadline_ns"].as_u64().unwrap(),
                );
                assert!(called < returned && returned <= end);
            } else {
                assert!(
                    remaining.is_empty(),
                    "failure cannot emit an admission receipt"
                );
                if language == "c" && invalid_input {
                    assert_eq!(output.status.code(), Some(2));
                    assert!(output.stderr.is_empty(), "C syntax rejection is exit 2");
                } else {
                    assert!(!output.stderr.is_empty());
                }
            }
        }
    }
    lifetime.store(11, Ordering::SeqCst);
    assert_eq!(
        ssap_calls.load(Ordering::SeqCst),
        44,
        "eight command RPCs including empty/2042; EOF/invalid/oversized/retired helper cases never enter the method"
    );
    // Both actual external SDKs must enter the daemon fixture for the new
    // 2043 negative mode. This verifies ABI/serialization, not Native/RF.
    for language in ["c", "python"] {
        for scenario in [
            "rejected",
            "wrong-error",
            "unexpected-success",
            "eof",
            "bad-start",
            "stale",
            "invalid-minimum",
            "undersized",
            "oversized",
            "empty",
            "invalid-hex",
        ] {
            lifetime.store(11, Ordering::SeqCst);
            let payload = match scenario {
                "undersized" => "a5".repeat(2042),
                "oversized" => "a5".repeat(2044),
                "empty" => String::new(),
                "invalid-hex" => "gg".repeat(2043),
                _ => "a5".repeat(2043),
            };
            let handle = match scenario {
                "wrong-error" => 21,
                "unexpected-success" => 22,
                _ => 17,
            };
            let invalid = matches!(
                scenario,
                "invalid-minimum" | "undersized" | "oversized" | "empty" | "invalid-hex"
            );
            let enters = matches!(scenario, "rejected" | "wrong-error" | "unexpected-success");
            let before = command_calls.lock().unwrap().len();
            let mut command = Command::new("timeout");
            command.arg("20s");
            if language == "c" {
                command.arg(&sdk_probe);
            } else {
                command
                    .arg("python3")
                    .arg(root.join("tools/testing/application_client/client.py"));
            }
            let mut process = command
                .args([
                    "ssap-command-reject",
                    "2",
                    "7",
                    PATH,
                    &handle.to_string(),
                    &payload,
                    if scenario == "invalid-minimum" {
                        "1"
                    } else {
                        "0"
                    },
                ])
                .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
                .env("LIBSPARKLINK_PATH", &runtime_library)
                .env("PYTHONPATH", root.join("bindings/python"))
                .env("LD_LIBRARY_PATH", &directory)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?;
            let mut stdout = std::io::BufReader::new(process.stdout.take().unwrap());
            let mut barrier = String::new();
            stdout.read_line(&mut barrier)?;
            let barrier_value: Option<serde_json::Value> = if invalid {
                assert!(barrier.is_empty(), "syntax rejection cannot enter the SDK");
                None
            } else {
                let value: serde_json::Value = serde_json::from_str(&barrier)?;
                assert_eq!(value["stage"], "ssap_command_start_barrier");
                assert_eq!(value["mode"], "ssap-command-reject");
                assert_eq!(value["schema_version"], 1);
                assert_eq!(value["api"], language);
                assert_eq!(value["client_closed"], true);
                if scenario == "stale" {
                    lifetime.store(12, Ordering::SeqCst);
                }
                if scenario == "eof" {
                    drop(process.stdin.take());
                } else {
                    process
                        .stdin
                        .as_mut()
                        .unwrap()
                        .write_all(if scenario == "bad-start" {
                            b"wrong\n"
                        } else {
                            b"start\n"
                        })?;
                }
                Some(value)
            };
            let mut remaining = String::new();
            stdout.read_to_string(&mut remaining)?;
            let output = process.wait_with_output()?;
            std::fs::write(
                directory.join(format!("sdk-{language}-command-reject-{scenario}.stdout")),
                barrier + &remaining,
            )?;
            std::fs::write(
                directory.join(format!("sdk-{language}-command-reject-{scenario}.stderr")),
                &output.stderr,
            )?;
            assert_eq!(
                output.status.success(),
                scenario == "rejected",
                "{language}/{scenario}"
            );
            let calls = command_calls.lock().unwrap();
            assert_eq!(
                calls.len(),
                before + usize::from(enters),
                "actual daemon entry {language}/{scenario}"
            );
            if enters {
                let (actual_handle, minimum, actual_value, original) = &calls[before];
                assert_eq!((*actual_handle, *minimum), (handle, 0));
                assert_eq!(actual_value.as_slice(), vec![0xa5; 2043]);
                assert_eq!(
                    Some(original.0),
                    barrier_value.as_ref().unwrap()["deadline_ns"].as_u64()
                );
            }
            if scenario == "rejected" {
                assert!(output.stderr.is_empty());
                assert_eq!(remaining.lines().count(), 1);
                let receipt: serde_json::Value = serde_json::from_str(
                    remaining
                        .strip_prefix("SSAP_COMMAND_REJECTED: ")
                        .expect("actual SDK rejection receipt"),
                )?;
                assert_eq!(receipt["schema_version"], 1);
                assert_eq!(receipt["mode"], "ssap-command-reject");
                assert_eq!(receipt["api"], language);
                assert_eq!(receipt["method"], "WriteSsapCommand");
                assert_eq!(receipt["index"], 2);
                assert_eq!(receipt["generation"], 7);
                assert_eq!(receipt["path"], PATH);
                assert_eq!(receipt["handle"], 17);
                assert_eq!(receipt["value"], payload);
                assert_eq!(receipt["application_bytes"], 2043);
                assert_eq!(receipt["minimum"], 0);
                assert_eq!(receipt["sdk_entered"], true);
                assert_eq!(receipt["errno"], nix::libc::EINVAL);
                assert_eq!(receipt["operation_success"], false);
                assert_eq!(receipt["peer_delivery_confirmed"], false);
                assert_eq!(
                    receipt["deadline_ns"],
                    barrier_value.as_ref().unwrap()["deadline_ns"]
                );
                let (called, returned, end) = (
                    receipt["call_ns"].as_u64().unwrap(),
                    receipt["returned_ns"].as_u64().unwrap(),
                    receipt["deadline_ns"].as_u64().unwrap(),
                );
                assert!(called < returned && returned < end);
            } else {
                assert!(
                    remaining.is_empty(),
                    "wrong/error/invalid cases cannot report expected rejection"
                );
            }
        }
    }
    lifetime.store(11, Ordering::SeqCst);
    assert_eq!(
        ssap_calls.load(Ordering::SeqCst),
        50,
        "six actual new command RPCs; all other negative modes stop before the method"
    );
    authorization::lifecycle(
        &root,
        &sdk_probe,
        &runtime_library,
        &directory,
        &bus.address,
        &server,
        &owned,
    )
    .await?;
    read_provider::exercise(
        &root,
        &sdk_probe,
        &runtime_library,
        &directory,
        &bus.address,
        &server,
        &owned,
    )
    .await?;
    write_provider::exercise(
        &root,
        &sdk_probe,
        &runtime_library,
        &directory,
        &bus.address,
        &server,
        &owned,
    )
    .await?;
    let unchanged = Command::new("sha256sum")
        .arg("--check")
        .arg(directory.join("materials.sha256"))
        .output()?;
    anyhow::ensure!(
        unchanged.status.success(),
        "executed artifact changed during test"
    );
    pending_owner::check(&root, &directory, &runtime_library, &sdk_probe).await?;
    std::fs::write(
        directory.join("COMPLETE"),
        b"CURRENT_APPLICATION_CLIENT_NEGATIVE_BUS_PASS\n",
    )?;
    cleanup.1 = retained.is_none();
    Ok(())
}
