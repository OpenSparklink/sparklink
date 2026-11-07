//! Real C/Python WRITE entry and real bus ownership. The broker is explicitly
//! a finite metadata/pending-RPC fixture, not slkd, an Engine or a protocol peer.
use super::*;

struct Pending {
    entered: Arc<tokio::sync::Notify>,
    live_error: bool,
}
#[zbus::interface(name = "org.sparklink.Connection")]
impl Pending {
    fn get_info(&self) -> slk_contract::ConnectionInfo {
        (7, 11, 3, 0, 1, "01:02:03:04:05:06".into(), true, true)
    }
    async fn write_ssap_value(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        stamp: slk_contract::Deadline,
    ) -> zbus::fdo::Result<Vec<u8>> {
        assert_eq!((handle, minimum, value), (17, 0, vec![0x56, 0x12]));
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp)).unwrap();
        self.entered.notify_one();
        if self.live_error {
            Err(zbus::fdo::Error::NoReply(
                "explicit live-owner error".into(),
            ))
        } else {
            std::future::pending().await
        }
    }
}

pub(super) async fn check(
    root: &std::path::Path,
    directory: &std::path::Path,
    library: &std::path::Path,
    probe: &std::path::Path,
) -> anyhow::Result<()> {
    for language in ["c", "python"] {
        for mode in ["release", "disconnect", "live-no-reply"] {
            let bus = support::Bus::start();
            let entered = Arc::new(tokio::sync::Notify::new());
            let server = zbus::connection::Builder::address(bus.address.as_str())?
                .name("org.sparklink")?
                .serve_at("/org/sparklink", Manager)?
                .serve_at(BASE, Adapter)?
                .serve_at(
                    PATH,
                    Pending {
                        entered: entered.clone(),
                        live_error: mode == "live-no-reply",
                    },
                )?
                .build()
                .await?;
            let expected = if mode == "live-no-reply" { 110 } else { 116 };
            let mut command = Command::new("timeout");
            command.arg("15s");
            if language == "c" {
                command.arg(probe);
            } else {
                command
                    .arg("python3")
                    .arg(root.join("tools/testing/application_client/client.py"));
            }
            let child = command
                .args([
                    "ssap-error",
                    "2",
                    "7",
                    PATH,
                    "ssap-write",
                    "17",
                    &expected.to_string(),
                    "5612",
                ])
                .env("DBUS_SYSTEM_BUS_ADDRESS", &bus.address)
                .env("LIBSPARKLINK_PATH", library)
                .env("PYTHONPATH", root.join("bindings/python"))
                .env("LD_LIBRARY_PATH", directory)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?;
            // Reap even when the pending barrier fails; no orphaned fixture.
            let waiting = tokio::task::spawn_blocking(move || child.wait_with_output());
            let observed =
                tokio::time::timeout(std::time::Duration::from_secs(3), entered.notified()).await;
            if observed.is_ok() {
                match mode {
                    "release" => {
                        server.release_name("org.sparklink").await?;
                    }
                    "disconnect" => {
                        server.close().await?;
                    }
                    _ => {}
                }
            }
            let output = waiting.await??;
            let label = format!("sdk-{language}-pending-write-{mode}");
            std::fs::write(directory.join(format!("{label}.stdout")), &output.stdout)?;
            std::fs::write(directory.join(format!("{label}.stderr")), &output.stderr)?;
            observed?;
            anyhow::ensure!(
                output.status.success() && output.stderr.is_empty(),
                "{label}: {output:?}"
            );
            let lines: Vec<serde_json::Value> = std::str::from_utf8(&output.stdout)?
                .lines()
                .map(serde_json::from_str)
                .collect::<Result<_, _>>()?;
            assert_eq!(lines.len(), 2);
            assert_eq!(lines[0]["stage"], "ssap_call");
            assert_eq!(lines[0]["client_closed"], true);
            assert_eq!(lines[1]["stage"], "ssap_error");
            assert_eq!(lines[1]["errno"], expected);
            assert_eq!(lines[1]["operation_success"], false);
            assert_eq!(lines[0]["deadline_ns"], lines[1]["deadline_ns"]);
            assert!(
                lines[1]["returned_ns"].as_u64().unwrap()
                    < lines[0]["deadline_ns"].as_u64().unwrap()
            );
        }
    }
    Ok(())
}
