//! Actual external C/Python -> compiled SDK -> original typed D-Bus endpoint.
//! The parent is finite broker metadata, not a daemon Engine/kernel/RF peer.
use super::*;
use slk_contract::ssap::{WriteProviderReply, WriteProviderRequest};
use std::time::Duration;

pub(super) async fn exercise(
    root: &std::path::Path,
    executable: &std::path::Path,
    library: &std::path::Path,
    directory: &std::path::Path,
    address: &str,
    server: &zbus::Connection,
    metadata: &OwnedMetadata,
) -> anyhow::Result<()> {
    for language in ["c", "python"] {
        let mut command = Command::new("timeout");
        command.arg("20s");
        if language == "c" {
            command.arg(executable);
        } else {
            command
                .arg("python3")
                .arg(root.join("tools/testing/application_client/write_provider.py"));
        }
        let mut child = command
            .env("DBUS_SYSTEM_BUS_ADDRESS", address)
            .env("LIBSPARKLINK_PATH", library)
            .env("PYTHONPATH", root.join("bindings/python"))
            .env("LD_LIBRARY_PATH", directory)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut transcript = String::new();
        let mut line = read_provider::line(&mut reader, &mut transcript)?;
        assert_eq!(line, "READY\n");
        for n in 1..=4 {
            let mut value = vec![0; if n == 2 { 0 } else { 31 }];
            std::fs::File::open("/dev/urandom")?.read_exact(&mut value)?;
            let original =
                slk_channel::deadline::Deadline::after(Duration::from_millis(if n == 4 {
                    250
                } else {
                    2000
                }))?;
            let request = WriteProviderRequest {
                request_id: n,
                identity: (2, 7, 13, 1, 41, 0, 10, 10, 0),
                property: 17,
                deadline_ns: original.stamp().monotonic_ns,
                operation: if n == 2 { 12 } else { 13 },
                data_type: 0,
                offset: 0,
                value: value.clone(),
                verify: n == 1,
            };
            let owner = metadata.owner.lock().unwrap().clone();
            let path = metadata.provider.lock().unwrap().clone();
            let bus = server.clone();
            let task = tokio::spawn(async move {
                bus.call_method(
                    Some(owner.as_str()),
                    path.as_str(),
                    Some("org.sparklink.SsapWriteProvider"),
                    "WriteValue",
                    &(request,),
                )
                .await?
                .body()
                .deserialize::<WriteProviderReply>()
            });
            line = read_provider::line(&mut reader, &mut transcript)?;
            let hex = value.iter().map(|b| format!("{b:02x}")).collect::<String>();
            assert_eq!(line, format!("VALUE {n} {hex}\n"));
            line = read_provider::line(&mut reader, &mut transcript)?;
            assert_eq!(
                line,
                format!(
                    "RESULT {n} {}\n",
                    if n == 4 { -nix::libc::ETIMEDOUT } else { 0 }
                )
            );
            let reply = task.await??;
            assert_eq!(
                reply,
                if n >= 3 {
                    (0xaf, vec![])
                } else {
                    (0, if n == 1 { value } else { vec![] })
                }
            );
            child.stdin.as_mut().unwrap().write_all(b"CONTINUE\n")?;
            child.stdin.as_mut().unwrap().flush()?;
        }
        line = read_provider::line(&mut reader, &mut transcript)?;
        assert_eq!(line, "DONE\n");
        let output = child.wait_with_output()?;
        std::fs::write(
            directory.join(format!("{language}-write-provider.stdout")),
            transcript,
        )?;
        std::fs::write(
            directory.join(format!("{language}-write-provider.stderr")),
            &output.stderr,
        )?;
        anyhow::ensure!(
            output.status.success(),
            "{language} actual WRITE consumer failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
    Ok(())
}
