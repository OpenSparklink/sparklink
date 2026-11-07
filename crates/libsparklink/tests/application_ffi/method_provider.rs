//! Actual external C/Python consumers over the shared SDK and private D-Bus.
//! Broker identity/registration are fixtures; no daemon Engine or wire claim.
use super::*;
use slk_contract::ssap::{MethodProviderReply, MethodProviderRequest};
use std::{path::Path, time::Duration};

pub(super) async fn exercise(
    root: &Path,
    executable: &Path,
    library: &Path,
    directory: &Path,
    address: &str,
    server: &zbus::Connection,
    metadata: &OwnedMetadata,
) -> anyhow::Result<()> {
    for language in ["c", "python"] {
        let mut command = Command::new("timeout");
        command.arg("15s");
        if language == "c" {
            command.arg(executable);
        } else {
            command
                .arg("python3")
                .arg(root.join("crates/libsparklink/tests/fixtures/method_provider.py"));
        }
        // Logs survive failures; COMPLETE is written only by the parent suite.
        let stderr = std::fs::File::create(directory.join(format!("{language}-method.stderr")))?;
        let mut child = command
            .env("DBUS_SYSTEM_BUS_ADDRESS", address)
            .env("LIBSPARKLINK_PATH", library)
            .env("PYTHONPATH", root.join("bindings/python"))
            .env("LD_LIBRARY_PATH", directory)
            .stdout(Stdio::piped())
            .stderr(stderr)
            .spawn()?;
        let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut transcript = String::new();
        let log_path = directory.join(format!("{language}-method.stdout"));
        let mut line =
            |reader: &mut std::io::BufReader<std::process::ChildStdout>| -> anyhow::Result<String> {
                let value = read_provider::line(reader, &mut transcript)?;
                std::fs::write(&log_path, &transcript)?;
                Ok(value)
            };
        assert_eq!(line(&mut reader)?, "METHOD_READY\n");
        let owner = metadata.owner.lock().unwrap().clone();
        let authorizer = metadata.authorizer.lock().unwrap().clone();
        let path = metadata.provider.lock().unwrap().clone();
        let deadline = slk_channel::deadline::Deadline::after(Duration::from_secs(2))?
            .stamp()
            .monotonic_ns;
        // Same handle cannot masquerade as a property authorization request.
        for kind in [0, 3] {
            let prompt: slk_contract::ssap::SsapAuthorizationPrompt = (
                7,
                (2, 7, 13, 1, 41, 0, 10, 10, 0),
                17,
                true,
                deadline,
                vec![0x31; 2043],
                kind,
            );
            let reply = server
                .call_method(
                    Some(owner.as_str()),
                    authorizer.as_str(),
                    Some("org.sparklink.SsapAuthorizer"),
                    "AuthorizeValue",
                    &(prompt,),
                )
                .await?;
            assert_eq!(reply.body().deserialize::<bool>()?, kind == 3);
        }
        assert_eq!(line(&mut reader)?, "AUTH_OK\n");
        for n in 0..4 {
            let request = MethodProviderRequest {
                request_id: 10 + n,
                identity: (2, 7, 13, 1, 41, 0, 10, 10, 0),
                method: 17,
                deadline_ns: slk_channel::deadline::Deadline::after(Duration::from_millis(
                    if n == 2 { 350 } else { 2000 },
                ))?
                .stamp()
                .monotonic_ns,
                operation: if n == 1 { 18 } else { 19 },
                arguments: vec![0x31; 2043],
                maximum_result_bytes: if n == 1 { 0 } else { 2045 },
            };
            let reply = server
                .call_method(
                    Some(owner.as_str()),
                    path.as_str(),
                    Some("org.sparklink.SsapMethodProvider"),
                    "CallMethod",
                    &(request,),
                )
                .await?
                .body()
                .deserialize::<MethodProviderReply>()?;
            assert_eq!(
                reply,
                match n {
                    0 => (0, vec![0xa6; 2045]),
                    1 => (0, vec![]),
                    _ => (0xaf, vec![]),
                }
            );
            assert_eq!(
                line(&mut reader)?,
                if n == 3 {
                    "METHOD_REVOKED\n"
                } else if n == 2 {
                    "METHOD_EXPIRED\n"
                } else {
                    "METHOD_REPLIED\n"
                }
            );
        }
        assert_eq!(line(&mut reader)?, "METHOD_COMPLETE\n");
        anyhow::ensure!(
            child.wait()?.success(),
            "{language} method consumer failed; inspect retained stderr"
        );
    }
    Ok(())
}
