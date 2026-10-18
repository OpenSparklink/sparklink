//! Actual cdylib/header and Python public entry against a real private bus.
//! Fixture replies are explicit denials/AF_UNIX fds, never a successful channel.
mod support;
use std::{
    io::{BufRead, Read, Write},
    path::PathBuf,
    process::{Command, Stdio},
    sync::{
        Arc,
        atomic::{AtomicU64, AtomicUsize, Ordering},
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
struct Link(Arc<AtomicUsize>, Arc<AtomicUsize>, Arc<AtomicU64>);
#[zbus::interface(name = "org.sparklink.Connection")]
impl Link {
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
    async fn read_ssap_value(&self, handle: u16, minimum: u32) -> zbus::fdo::Result<Vec<u8>> {
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
            _ => Err(zbus::fdo::Error::NotSupported(
                "unmatched fixture read".into(),
            )),
        }
    }
    fn write_ssap_value(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
    ) -> zbus::fdo::Result<Vec<u8>> {
        self.1.fetch_add(1, Ordering::SeqCst);
        match (handle, minimum, value.as_slice()) {
            (17, 1, [0x56, 0x12]) => Ok(vec![0x90]),
            (17, 0, []) => Ok(vec![0x91]),
            _ => Err(zbus::fdo::Error::InvalidArgs(
                "unmatched fixture write".into(),
            )),
        }
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
            }
        }
    }
    let _cleanup = Cleanup(directory.clone(), retained.is_none());
    // The compiled file has its real installed ABI SONAME. Supply only that
    // runtime name in this private directory, with the exact compiled bytes.
    let runtime_library = directory.join("libsparklink.so.0");
    std::fs::copy(&library, &runtime_library)?;
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
    let sdk_probe = directory.join("sdk-ssap-probe");
    let compiled = Command::new(std::env::var("CC").unwrap_or("cc".into()))
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
        .arg(root.join("crates/libsparklink/include/sparklink.h"))
        .arg(root.join("crates/libsparklink/tests/fixtures/application_client.c"))
        .arg(root.join("crates/libsparklink/tests/fixtures/application_client.py"))
        .arg(root.join("tools/testing/application_client/client.c"))
        .arg(root.join("tools/testing/application_client/client.py"))
        .output()?;
    anyhow::ensure!(
        identities.status.success() && identities.stderr.is_empty(),
        "artifact hash command failed"
    );
    std::fs::write(directory.join("materials.sha256"), &identities.stdout)?;
    let bus = support::Bus::start();
    let calls = Arc::new(AtomicUsize::new(0));
    let ssap_calls = Arc::new(AtomicUsize::new(0));
    let lifetime = Arc::new(AtomicU64::new(11));
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter)?
        .serve_at(
            PATH,
            Link(calls.clone(), ssap_calls.clone(), lifetime.clone()),
        )?
        .build()
        .await?;
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
            anyhow::ensure!(output.stderr.is_empty(), "unexpected C consumer diagnostic");
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
    }
    assert_eq!(
        calls.load(Ordering::SeqCst),
        22,
        "no retry or weaker fallback, invalid inputs never reach OpenChannel"
    );
    assert_eq!(
        ssap_calls.load(Ordering::SeqCst),
        14,
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
    assert_eq!(ssap_calls.load(Ordering::SeqCst), 18);
    let unchanged = Command::new("sha256sum")
        .arg("--check")
        .arg(directory.join("materials.sha256"))
        .output()?;
    anyhow::ensure!(
        unchanged.status.success(),
        "executed artifact changed during test"
    );
    std::fs::write(
        directory.join("COMPLETE"),
        b"CURRENT_APPLICATION_CLIENT_NEGATIVE_BUS_PASS\n",
    )?;
    Ok(())
}
