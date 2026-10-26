//! Same parameterized Owned consumers used by VM callers, through actual SDK.
//! Only broker metadata/transport are fixtures; no daemon Engine or RF claim.
use super::*;
use slk_contract::ssap::{WriteProviderReply, WriteProviderRequest};
use std::time::Duration;

fn send(child: &mut std::process::Child, input: &str) -> anyhow::Result<()> {
    child.stdin.as_mut().unwrap().write_all(input.as_bytes())?;
    child.stdin.as_mut().unwrap().flush()?;
    Ok(())
}
fn json_line(
    reader: &mut impl BufRead,
    log: &mut String,
    prefix: &str,
) -> anyhow::Result<serde_json::Value> {
    let text = read_provider::line(reader, log)?;
    Ok(serde_json::from_str(
        text.strip_prefix(prefix)
            .ok_or_else(|| anyhow::anyhow!("expected {prefix}: {text}"))?,
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
        command.arg("20s");
        if language == "c" {
            command.arg(executable);
        } else {
            command
                .arg("python3")
                .arg(root.join("tools/testing/application_client/client.py"));
        }
        let mut child = command
            .args([
                "owned-writeonly",
                "2",
                "7",
                "0100",
                "0200",
                "070809",
                "allow",
            ])
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
            read_provider::line(&mut reader, &mut transcript)?,
            format!("SdkOwnedAPI: api={language} client_closed=true\n")
        );
        assert_eq!(
            read_provider::line(&mut reader, &mut transcript)?,
            "SsapOwnedService: start=16 end=17 property=17; local registration only\n"
        );
        send(&mut child, "provider\n")?;
        let bound = json_line(&mut reader, &mut transcript, "SdkWriteProviderBound: ")?;
        assert_eq!(bound["api"], language);
        assert_eq!(bound["result"], 0);
        assert_eq!(bound["notification_result"], 0);
        assert_eq!(bound["notification_ready"], true);
        let mut applied: Option<String> = None;
        let mut previous_token = 0;
        for n in 1..=7 {
            let mut value = vec![
                0;
                match n {
                    2 => 0,
                    5 => 2042,
                    _ => 31,
                }
            ];
            std::fs::File::open("/dev/urandom")?.read_exact(&mut value)?;
            let hex = value.iter().map(|b| format!("{b:02x}")).collect::<String>();
            let original = slk_channel::deadline::Deadline::after(Duration::from_millis(
                if n == 4 || n == 6 { 350 } else { 3000 },
            ))?;
            let deadline = original.stamp().monotonic_ns;
            // Independent authorization callback is actually answered first;
            // that policy result is not a WRITE result or application effect.
            let owner = metadata.owner.lock().unwrap().clone();
            let authorizer = metadata.authorizer.lock().unwrap().clone();
            let prompt: slk_contract::ssap::SsapAuthorizationPrompt = (
                n,
                (2, 7, 13, 1, 41, 0, 10, 10, 0),
                17,
                true,
                deadline,
                value.clone(),
                0,
            );
            let approval = server
                .call_method(
                    Some(owner.as_str()),
                    authorizer.as_str(),
                    Some("org.sparklink.SsapAuthorizer"),
                    "AuthorizeValue",
                    &(prompt,),
                )
                .await?;
            assert!(approval.body().deserialize::<bool>()?);
            let approved = json_line(&mut reader, &mut transcript, "SdkAuthorizationDecision: ")?;
            assert_eq!(approved["value"], hex);
            assert_eq!(approved["allow"], true);
            assert_eq!(approved["request_id"], n);
            let request = WriteProviderRequest {
                request_id: n,
                identity: (2, 7, 13, 1, 41, 0, 10, 10, 0),
                property: 17,
                deadline_ns: deadline,
                operation: if n == 2 { 12 } else { 13 },
                data_type: 0,
                offset: 0,
                value: value.clone(),
                verify: matches!(n, 1 | 5 | 6 | 7),
            };
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
            let observed = json_line(&mut reader, &mut transcript, "SdkWriteProviderRequest: ")?;
            assert_eq!(observed.as_object().unwrap().len(), 22);
            assert_eq!(observed["api"], language);
            assert_eq!(observed["value"], hex);
            for (field, expected) in [
                ("index", 2),
                ("generation", 7),
                ("request_id", n),
                ("lifetime", 13),
                ("handle", 1),
                ("epoch", 41),
                ("level", 0),
                ("deadline_ns", deadline),
                ("property", 17),
                ("local_tcid", 10),
                ("remote_tcid", 10),
                ("pi", 0),
                ("operation", if n == 2 { 12 } else { 13 }),
                ("data_type", 0),
                ("offset", 0),
                ("value_length", value.len() as u64),
            ] {
                assert_eq!(observed[field].as_u64(), Some(expected), "{field}");
            }
            assert_eq!(observed["verify"], matches!(n, 1 | 5 | 6 | 7));
            let token = observed["token"].as_u64().unwrap();
            assert!(token > previous_token);
            previous_token = token;
            if n == 7 {
                // Same live consumer and actual SDK request, after successful
                // writes. Withdrawal must not overwrite the previous app value.
                assert!(!task.is_finished(), "withdraw an actually pending callback");
                let removals = metadata.removed.load(Ordering::SeqCst);
                send(&mut child, "provider-unregister\n")?;
                let removed = json_line(
                    &mut reader,
                    &mut transcript,
                    "SdkWriteProviderUnregistered: ",
                )?;
                let fields = [
                    "api",
                    "token",
                    "property",
                    "original_deadline_ns",
                    "deadline_ns",
                    "started_ns",
                    "returned_ns",
                    "result",
                    "info_preserved",
                    "notification_fd_alive",
                    "reply_started_ns",
                    "reply_returned_ns",
                    "reply_result",
                    "local_observation_only",
                    "value_preserved",
                ];
                assert_eq!(removed.as_object().unwrap().len(), fields.len());
                assert!(fields.iter().all(|key| removed.get(*key).is_some()));
                assert_eq!(removed["api"], language);
                assert_eq!(removed["token"], token);
                assert_eq!(removed["property"], 17);
                assert_eq!(removed["original_deadline_ns"], deadline);
                assert_eq!(removed["deadline_ns"], deadline);
                assert_eq!(removed["result"], 0);
                assert_eq!(removed["reply_result"], -nix::libc::ESHUTDOWN);
                for key in [
                    "info_preserved",
                    "notification_fd_alive",
                    "value_preserved",
                    "local_observation_only",
                ] {
                    assert_eq!(removed[key], true, "{key}");
                }
                let times = [
                    observed["observed_ns"].as_u64().unwrap(),
                    removed["started_ns"].as_u64().unwrap(),
                    removed["returned_ns"].as_u64().unwrap(),
                    removed["reply_started_ns"].as_u64().unwrap(),
                    removed["reply_returned_ns"].as_u64().unwrap(),
                ];
                assert!(times.windows(2).all(|pair| pair[0] <= pair[1]));
                assert!(
                    times[4] < deadline,
                    "withdrawal does not renew the original deadline"
                );
                let reply = tokio::time::timeout(original.remaining()?, task).await???;
                assert_eq!(
                    reply,
                    (0xaf, vec![]),
                    "actual SDK callback stop; not a wire outcome"
                );
                assert_eq!(metadata.removed.load(Ordering::SeqCst), removals + 1);
                assert!(
                    child.try_wait()?.is_none(),
                    "retired views do not kill their owner"
                );
                send(&mut child, "value\n")?;
                let actual = json_line(&mut reader, &mut transcript, "SdkWriteProviderValue: ")?;
                assert_eq!(
                    actual,
                    serde_json::json!({"api":language,"property":17,"value":applied,"application_memory_only":true})
                );
                continue;
            }
            if n == 1 {
                send(&mut child, &format!("provide p{} {hex}\n", token + 100))?;
                let wrong = json_line(&mut reader, &mut transcript, "SdkWriteProviderReply: ")?;
                assert_eq!(wrong["result"], -nix::libc::ESTALE);
                assert_eq!(wrong["api_called"], false);
                let mut wrong = value.clone();
                wrong[0] ^= 1;
                let bad = wrong.iter().map(|b| format!("{b:02x}")).collect::<String>();
                send(&mut child, &format!("provide p{token} {bad}\n"))?;
                let wrong = json_line(&mut reader, &mut transcript, "SdkWriteProviderReply: ")?;
                assert_eq!(wrong["result"], -nix::libc::EINVAL);
                assert_eq!(wrong["api_called"], false);
                assert_eq!(wrong["matched_value"], false);
                assert!(wrong["accepted_value"].is_null());
                assert!(
                    !task.is_finished(),
                    "bad UI input cannot answer the actual callback"
                );
            }
            // Both ordinary WriteReq and verified WriteReq retain the original
            // callback deadline; late matching bytes cannot alter app memory.
            if n == 4 || n == 6 {
                while let Ok(left) = original.remaining() {
                    tokio::time::sleep(left).await;
                }
            }
            send(
                &mut child,
                &if n == 3 {
                    format!("provider-error p{token} AF\n")
                } else {
                    format!(
                        "provide p{token} {}\n",
                        if hex.is_empty() { "-" } else { &hex }
                    )
                },
            )?;
            let result = json_line(&mut reader, &mut transcript, "SdkWriteProviderReply: ")?;
            let fields = [
                "api",
                "token",
                "current_token",
                "api_called",
                "status",
                "value",
                "deadline_ns",
                "started_ns",
                "returned_ns",
                "result",
                "local_acceptance_only",
                "matched_value",
                "accepted_value",
            ];
            assert_eq!(result.as_object().unwrap().len(), fields.len());
            assert!(fields.iter().all(|field| result.get(*field).is_some()));
            assert_eq!(result["api_called"], true);
            assert_eq!(result["matched_value"], true);
            assert_eq!(result["local_acceptance_only"], true);
            assert_eq!(result["token"], token);
            assert_eq!(result["current_token"], token);
            assert_eq!(result["deadline_ns"], deadline);
            assert_eq!(result["status"], if n == 3 { 0xaf } else { 0 });
            assert_eq!(
                result["result"],
                if n == 4 || n == 6 {
                    -nix::libc::ETIMEDOUT
                } else {
                    0
                }
            );
            if n == 4 || n == 6 {
                assert!(result["started_ns"].as_u64().unwrap() >= deadline);
                assert!(
                    result["returned_ns"].as_u64().unwrap()
                        >= result["started_ns"].as_u64().unwrap()
                );
            }
            if n == 1 || n == 2 || n == 5 {
                assert_eq!(result["accepted_value"], hex);
                applied = Some(hex.clone());
            } else {
                assert!(result["accepted_value"].is_null());
            }
            assert_eq!(
                result["value"],
                if n == 1 || n == 5 || n == 6 { &hex } else { "" }
            );
            // Drain the real callback BEFORE close/next operation; no sleep or
            // local success is substituted for receipt by the original caller.
            let reply = task.await??;
            assert_eq!(
                reply,
                if n == 3 || n == 4 || n == 6 {
                    (0xaf, vec![])
                } else {
                    (0, if n == 1 || n == 5 { value } else { vec![] })
                }
            );
            send(&mut child, "value\n")?;
            let actual = json_line(&mut reader, &mut transcript, "SdkWriteProviderValue: ")?;
            assert_eq!(
                actual,
                serde_json::json!({"api":language,"property":17,"value":applied,"application_memory_only":true})
            );
        }
        send(&mut child, "quit\n")?;
        assert_eq!(
            read_provider::line(&mut reader, &mut transcript)?,
            format!("SdkOwnedClosedExit: api={language} start=16\n")
        );
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
