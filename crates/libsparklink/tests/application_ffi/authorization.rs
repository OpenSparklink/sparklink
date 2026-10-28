//! Actual language frontends/compiled ABI/private bus. Metadata sender only;
//! not daemon DB removal, Kernel, wire or RF qualification.
use super::*;

fn line(reader: &mut impl BufRead, transcript: &mut String) -> anyhow::Result<String> {
    let mut value = String::new();
    anyhow::ensure!(reader.read_line(&mut value)? != 0, "consumer stream ended");
    transcript.push_str(&value);
    Ok(value)
}
fn json_line(
    reader: &mut impl BufRead,
    transcript: &mut String,
    prefix: &str,
) -> anyhow::Result<serde_json::Value> {
    let value = line(reader, transcript)?;
    Ok(serde_json::from_str(
        value
            .strip_prefix(prefix)
            .ok_or_else(|| anyhow::anyhow!("missing {prefix}: {value}"))?,
    )?)
}

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
        command.arg("10s");
        if language == "c" {
            command.arg(executable);
        } else {
            command
                .arg("python3")
                .arg(root.join("tools/testing/application_client/client.py"));
        }
        let mut child = command
            .args(["owned", "2", "7", "0100", "0200", "070809", "ask"])
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
        assert_eq!(
            line(&mut reader, &mut transcript)?,
            format!("SdkOwnedAPI: api={language} client_closed=true\n")
        );
        assert_eq!(
            line(&mut reader, &mut transcript)?,
            "SsapOwnedService: start=16 end=17 property=17; local registration only\n"
        );
        let owner = metadata.owner.lock().unwrap().clone();
        let path = metadata.authorizer.lock().unwrap().clone();
        let mut first_token = 0;
        for (ordinal, operation) in ["deny", "expire", "close"].into_iter().enumerate() {
            let deadline =
                slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(2))?
                    .stamp()
                    .monotonic_ns;
            let prompt: slk_contract::ssap::SsapAuthorizationPrompt = (
                100 + ordinal as u64,
                (2, 7, 13, 3, 41, 0, 10, 10, 0),
                17,
                true,
                deadline,
                vec![4, 5, 6],
                0,
            );
            let connection = server.clone();
            let destination = owner.clone();
            let endpoint = path.clone();
            let pending = tokio::spawn(async move {
                connection
                    .call_method(
                        Some(destination.as_str()),
                        endpoint.as_str(),
                        Some("org.sparklink.SsapAuthorizer"),
                        "AuthorizeValue",
                        &(prompt,),
                    )
                    .await
            });
            let context = json_line(&mut reader, &mut transcript, "SdkAuthorizationRequest: ")?;
            assert_eq!(context["api"], language);
            assert_eq!(context["request_id"], 100 + ordinal as u64);
            assert_eq!(context["deadline_ns"], deadline);
            assert_eq!(context["value"], "040506");
            let token = context["token"].as_u64().unwrap();
            let text = line(&mut reader, &mut transcript)?;
            assert!(text.starts_with(&format!(
                "SsapAuthorizationPrompt: token={token} request={}",
                100 + ordinal
            )));
            if operation == "close" {
                child.stdin.as_mut().unwrap().write_all(b"close\n")?;
                let closed = json_line(&mut reader, &mut transcript, "SdkServiceClosed: ")?;
                assert_eq!(closed["token"], token);
                assert_eq!(closed["info_preserved"], true);
                assert_eq!(closed["notification_fd_alive"], true);
                assert_eq!(closed["reply_result"], -libc_errno::ESTALE);
                assert!(
                    child.try_wait()?.is_none(),
                    "process must outlive original caller"
                );
                let bus = zbus::fdo::DBusProxy::new(server).await?;
                assert!(!bus.name_has_owner(owner.as_str().try_into()?).await?);
                // Scope cancellation may close RPC before a false return is
                // delivered. Never require a fabricated successful reply.
                if let Ok(message) = pending.await? {
                    assert!(!message.body().deserialize::<bool>()?);
                }
                child.stdin.as_mut().unwrap().write_all(b"quit\n")?;
                assert_eq!(
                    line(&mut reader, &mut transcript)?,
                    format!("SdkOwnedClosedExit: api={language} start=16\n")
                );
            } else {
                let allow = operation == "expire";
                let supplied = if allow { first_token } else { token };
                child.stdin.as_mut().unwrap().write_all(
                    format!("{} {supplied}\n", if allow { "yes" } else { "no" }).as_bytes(),
                )?;
                let decision = json_line(&mut reader, &mut transcript, "SdkAuthorizationReply: ")?;
                assert_eq!(decision["token"], supplied);
                assert_eq!(decision["current_token"], token);
                assert_eq!(decision["api_called"], !allow);
                assert_eq!(
                    decision["result"],
                    if allow { -libc_errno::ESTALE } else { 0 }
                );
                if allow {
                    assert!(
                        !pending.is_finished(),
                        "stale UI token completed a new request"
                    );
                }
                assert!(!pending.await??.body().deserialize::<bool>()?);
                if allow {
                    child
                        .stdin
                        .as_mut()
                        .unwrap()
                        .write_all(format!("yes {token}\n").as_bytes())?;
                    let late = json_line(&mut reader, &mut transcript, "SdkAuthorizationReply: ")?;
                    assert_eq!(late["api_called"], true);
                    assert_eq!(late["result"], -libc_errno::ETIMEDOUT);
                    assert!(late["returned_ns"].as_u64().unwrap() >= deadline);
                    child.stdin.as_mut().unwrap().write_all(b"value\n")?;
                    assert_eq!(
                        line(&mut reader, &mut transcript)?,
                        "SsapOwnedValue: handle=17 value=070809\n"
                    );
                }
                first_token = token;
            }
        }
        let mut rest = String::new();
        reader.read_to_string(&mut rest)?;
        assert!(rest.is_empty());
        let output = child.wait_with_output()?;
        std::fs::write(
            directory.join(format!("{language}-authorization-ask.stdout")),
            transcript,
        )?;
        std::fs::write(
            directory.join(format!("{language}-authorization-ask.stderr")),
            &output.stderr,
        )?;
        assert!(
            output.status.success() && output.stderr.is_empty(),
            "{language} ask: {output:?}"
        );
    }
    Ok(())
}

// One existing errno source,not another protocol/authorization implementation.
use nix::libc as libc_errno;

// Actual frontend timer and API boundaries;the metadata producer is still a
// fixture,not a daemon database,Native Host or physical cleanup implementation.
pub(super) async fn lifecycle(
    root: &std::path::Path,
    executable: &std::path::Path,
    library: &std::path::Path,
    directory: &std::path::Path,
    address: &str,
    server: &zbus::Connection,
    metadata: &OwnedMetadata,
) -> anyhow::Result<()> {
    let spawn = |language: &str| -> anyhow::Result<std::process::Child> {
        let mut command = Command::new("timeout");
        command.arg("40s"); // Outer supervision,not a replacement for Owned30.
        if language == "c" {
            command.arg(executable);
        } else {
            command
                .arg("python3")
                .arg(root.join("tools/testing/application_client/client.py"));
        }
        Ok(command
            .args(["owned", "2", "7", "0100", "0200", "070809", "allow"])
            .env("DBUS_SYSTEM_BUS_ADDRESS", address)
            .env("LIBSPARKLINK_PATH", library)
            .env("PYTHONPATH", root.join("bindings/python"))
            .env("LD_LIBRARY_PATH", directory)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?)
    };
    fn sample(reader: &mut impl BufRead, text: &mut String) -> anyhow::Result<serde_json::Value> {
        let value = json_line(reader, text, "SdkOwnedLifecycle: ")?;
        assert_eq!(value["version"], 1);
        assert_eq!(value["index"], 2);
        assert_eq!(value["generation"], 7);
        assert_eq!(value["start"], 16);
        assert_eq!(value["property"], 17);
        let created = value["created_ns"].as_u64().unwrap();
        let end = value["deadline_ns"].as_u64().unwrap();
        assert!(created > 0);
        assert_eq!(end - created, 30_000_000_000);
        assert!(value["sampled_ns"].as_u64().unwrap() >= created);
        Ok(value)
    }
    fn ready(
        child: &mut std::process::Child,
        language: &str,
    ) -> anyhow::Result<(
        std::io::BufReader<std::process::ChildStdout>,
        String,
        serde_json::Value,
    )> {
        let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut text = String::new();
        assert_eq!(
            line(&mut reader, &mut text)?,
            format!("SdkOwnedAPI: api={language} client_closed=true\n")
        );
        assert_eq!(
            line(&mut reader, &mut text)?,
            "SsapOwnedService: start=16 end=17 property=17; local registration only\n"
        );
        child.stdin.as_mut().unwrap().write_all(b"lifecycle\n")?;
        let value = sample(&mut reader, &mut text)?;
        assert_eq!(value["stage"], "observed");
        assert_eq!(value["error"], 0);
        assert_eq!(value["api"], language);
        assert!(value["sampled_ns"].as_u64().unwrap() < value["deadline_ns"].as_u64().unwrap());
        Ok((reader, text, value))
    }
    fn same_budget(first: &serde_json::Value, later: &serde_json::Value) {
        for field in [
            "api",
            "pid",
            "index",
            "generation",
            "start",
            "property",
            "created_ns",
            "deadline_ns",
        ] {
            assert_eq!(first[field], later[field], "original {field}");
        }
    }
    for language in ["c", "python"] {
        let mut child = spawn(language)?;
        let (mut reader, mut text, first) = ready(&mut child, language)?;
        let deadline = slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(2))?
            .stamp()
            .monotonic_ns;
        let prompt: slk_contract::ssap::SsapAuthorizationPrompt = (
            999,
            (2, 7, 13, 3, 41, 0, 10, 10, 0),
            17,
            false,
            deadline,
            vec![],
            0,
        );
        let destination = metadata.owner.lock().unwrap().clone();
        let path = metadata.authorizer.lock().unwrap().clone();
        let connection = server.clone();
        let pending = tokio::spawn(async move {
            connection
                .call_method(
                    Some(destination.as_str()),
                    path.as_str(),
                    Some("org.sparklink.SsapAuthorizer"),
                    "AuthorizeValue",
                    &(prompt,),
                )
                .await
        });
        let returned = sample(&mut reader, &mut text)?;
        same_budget(&first, &returned);
        assert_eq!(returned["stage"], "approval_return");
        assert_eq!(returned["error"], 0);
        assert_eq!(returned["request_id"], 999);
        assert!(
            returned["call_returned_ns"].as_u64().unwrap()
                >= returned["call_started_ns"].as_u64().unwrap()
        );
        let decision = json_line(&mut reader, &mut text, "SdkAuthorizationDecision: ")?;
        assert_eq!(decision["token"], returned["token"]);
        assert_eq!(decision["decision_ns"], returned["call_started_ns"]);
        assert!(pending.await??.body().deserialize::<bool>()?);
        child.stdin.as_mut().unwrap().write_all(b"quit\n")?;
        assert_eq!(
            line(&mut reader, &mut text)?,
            format!("SdkOwnedRemoved: api={language} start=16\n")
        );
        for stage in ["cleanup_begin", "cleanup_end"] {
            let value = sample(&mut reader, &mut text)?;
            same_budget(&first, &value);
            assert_eq!(value["stage"], stage);
            assert_eq!(value["error"], 0);
        }
        let output = child.wait_with_output()?;
        assert!(output.status.success() && output.stderr.is_empty());
        assert!(line_eof(&mut reader)?);
        std::fs::write(
            directory.join(format!("{language}-publisher-lifecycle-normal.stdout")),
            text,
        )?;
    }
    // Both real frontend budgets expire concurrently. Do not substitute a
    // shortened timer or a fake clock for the original thirty seconds.
    let mut expired = Vec::new();
    for language in ["c", "python"] {
        let mut child = spawn(language)?;
        let (reader, text, first) = ready(&mut child, language)?;
        expired.push((language, child, reader, text, first));
    }
    for (language, child, mut reader, mut text, first) in expired {
        for (stage, error) in [
            ("cleanup_begin", -(libc_errno::ETIMEDOUT as i64)),
            ("cleanup_end", 0),
        ] {
            let value = sample(&mut reader, &mut text)?;
            same_budget(&first, &value);
            assert_eq!(value["stage"], stage);
            // Python preserves the exception through context-manager exit;
            // C's void free only reports returning,not cleanup success.
            if stage == "cleanup_begin" || language == "c" {
                assert_eq!(value["error"], error);
            } else {
                assert_eq!(value["error"], -(libc_errno::ETIMEDOUT as i64));
            }
            assert!(
                value["sampled_ns"].as_u64().unwrap() >= value["deadline_ns"].as_u64().unwrap()
            );
        }
        let output = child.wait_with_output()?;
        assert!(!output.status.success() && !output.stderr.is_empty());
        assert!(line_eof(&mut reader)?);
        std::fs::write(
            directory.join(format!("{language}-publisher-lifecycle-expired.stdout")),
            text,
        )?;
        std::fs::write(
            directory.join(format!("{language}-publisher-lifecycle-expired.stderr")),
            output.stderr,
        )?;
    }
    Ok(())
}

fn line_eof(reader: &mut impl BufRead) -> anyhow::Result<bool> {
    let mut text = String::new();
    Ok(reader.read_line(&mut text)? == 0)
}
