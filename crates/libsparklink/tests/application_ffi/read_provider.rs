//! Actual compiled C/Python consumer -> sole SDK queue -> real private D-Bus
//! callback. Metadata is a fixture, not a daemon DB/Engine or an RF peer. A local
//! reply receipt and the independently awaited callback body are separate checks.
use super::*;
use slk_channel::deadline::Deadline;
use std::time::Duration;

pub(super) fn line(reader: &mut impl BufRead, transcript: &mut String) -> anyhow::Result<String> {
    let mut text = String::new();
    anyhow::ensure!(
        reader.read_line(&mut text)? != 0,
        "Provider consumer stream ended"
    );
    // Rust test capture retains these lines if a later assertion fails; do not
    // discard the original child observations just because the test cannot seal.
    eprint!("{text}");
    transcript.push_str(&text);
    Ok(text)
}
pub(super) fn receipt(
    reader: &mut impl BufRead,
    transcript: &mut String,
    prefix: &str,
    fields: &[&str],
) -> anyhow::Result<serde_json::Value> {
    let text = line(reader, transcript)?;
    let value: serde_json::Value = serde_json::from_str(
        text.strip_prefix(prefix)
            .ok_or_else(|| anyhow::anyhow!("missing {prefix}: {text}"))?,
    )?;
    let object = value
        .as_object()
        .ok_or_else(|| anyhow::anyhow!("receipt is not object"))?;
    assert_eq!(object.len(), fields.len(), "exact frozen consumer fields");
    assert!(fields.iter().all(|name| object.contains_key(*name)));
    Ok(value)
}
const REPLY_FIELDS: &[&str] = &[
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
];
fn check_reply(
    value: &serde_json::Value,
    language: &str,
    tokens: (u64, u64),
    original: u64,
    status: u16,
    bytes: &str,
    result: i32,
) {
    assert_eq!(value["api"], language);
    assert_eq!(value["token"], tokens.0);
    assert_eq!(value["current_token"], tokens.1);
    assert_eq!(value["api_called"], tokens.0 == tokens.1 && tokens.1 != 0);
    assert_eq!(value["status"], status);
    assert_eq!(value["value"], bytes);
    assert_eq!(value["deadline_ns"], original);
    assert_eq!(value["result"], result);
    assert_eq!(value["local_acceptance_only"], true);
    assert!(value["started_ns"].as_u64().unwrap() <= value["returned_ns"].as_u64().unwrap());
}
fn send(child: &mut std::process::Child, text: &str) -> anyhow::Result<()> {
    child.stdin.as_mut().unwrap().write_all(text.as_bytes())?;
    child.stdin.as_mut().unwrap().flush()?;
    Ok(())
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
    for (language, withdrawal) in [
        ("c", false),
        ("c", true),
        ("python", false),
        ("python", true),
    ] {
        // Keep the original normal quit coverage and its artifact names. The
        // pending withdrawal owns a fresh registration and separate receipts.
        let suffix = if withdrawal { "-withdrawal" } else { "" };
        let registrations = metadata.registered.load(Ordering::SeqCst);
        let removals = metadata.removed.load(Ordering::SeqCst);
        let binds = metadata.provider_binds.load(Ordering::SeqCst);
        let mut command = Command::new("timeout");
        command.arg("35s"); // Supervisor only; the actual Owned30 budget remains.
        if language == "c" {
            command.arg(executable);
        } else {
            command
                .arg("python3")
                .arg(root.join("tools/testing/application_client/client.py"));
        }
        let mut child = command
            .args([
                "owned-readonly",
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
            line(&mut reader, &mut transcript)?,
            format!("SdkOwnedAPI: api={language} client_closed=true\n")
        );
        assert_eq!(
            line(&mut reader, &mut transcript)?,
            "SsapOwnedService: start=16 end=17 property=17; local registration only\n"
        );
        send(&mut child, "provider\n")?;
        let bound = receipt(
            &mut reader,
            &mut transcript,
            "SdkReadProviderBound: ",
            &[
                "api",
                "index",
                "generation",
                "property",
                "started_ns",
                "deadline_ns",
                "returned_ns",
                "result",
                "notification_result",
                "notification_ready",
                "local_binding_only",
            ],
        )?;
        assert_eq!(bound["api"], language);
        assert_eq!(bound["index"], 2);
        assert_eq!(bound["generation"], 7);
        assert_eq!(bound["property"], 17);
        assert_eq!(bound["result"], 0);
        assert_eq!(bound["notification_result"], 0);
        assert_eq!(bound["notification_ready"], true);
        assert_eq!(bound["local_binding_only"], true);
        let started = bound["started_ns"].as_u64().unwrap();
        let returned = bound["returned_ns"].as_u64().unwrap();
        let deadline = bound["deadline_ns"].as_u64().unwrap();
        assert!(started <= returned && returned < deadline && deadline - started <= 5_000_000_000);
        assert_eq!(metadata.provider_binds.load(Ordering::SeqCst), binds + 1);
        let owner = metadata.owner.lock().unwrap().clone();
        let provider = metadata.provider.lock().unwrap().clone();
        let authorizer = metadata.authorizer.lock().unwrap().clone();
        let mut random = [0u8; 32];
        std::fs::File::open("/dev/urandom")?.read_exact(&mut random)?;
        let hex: String = random.iter().map(|b| format!("{b:02x}")).collect();
        std::fs::write(
            directory.join(format!("{language}-provider{suffix}-random32.bin")),
            random,
        )?;
        let mut prior_token = 0;
        let mut callback_results = Vec::new();
        let cases: &[&str] = if withdrawal {
            &["unregister"]
        } else {
            &["empty", "value", "error", "expire"]
        };
        for (ordinal, &case) in cases.iter().enumerate() {
            let original = Deadline::after(Duration::from_secs(2))?
                .stamp()
                .monotonic_ns;
            let request_id = 600 + ordinal as u64;
            // Real authorization endpoint and independent pending value queue.
            // The fixture deliberately drives these calls; this is not a daemon
            // authorization-to-wire ordering or trusted-peer qualification.
            let approval: slk_contract::ssap::SsapAuthorizationPrompt = (
                request_id,
                (2, 7, 13, 3, 41, 0, 10, 10, 0),
                17,
                false,
                original,
                vec![],
                0,
            );
            let accepted = server
                .call_method(
                    Some(owner.as_str()),
                    authorizer.as_str(),
                    Some("org.sparklink.SsapAuthorizer"),
                    "AuthorizeValue",
                    &(approval,),
                )
                .await?;
            assert!(accepted.body().deserialize::<bool>()?);
            let approval_line = line(&mut reader, &mut transcript)?;
            let decision: serde_json::Value = serde_json::from_str(
                approval_line
                    .strip_prefix("SdkAuthorizationDecision: ")
                    .unwrap(),
            )?;
            assert_eq!(decision["api"], language);
            assert_eq!(decision["request_id"], request_id);
            assert_eq!(decision["allow"], true);
            let request = slk_contract::ssap::ReadProviderRequest {
                request_id,
                identity: (2, 7, 13, 3, 41, 0, 10, 10, 0),
                property: 17,
                deadline_ns: original,
                maximum_bytes: 32,
            };
            let connection = server.clone();
            let destination = owner.clone();
            let endpoint = provider.clone();
            let pending = tokio::spawn(async move {
                connection
                    .call_method(
                        Some(destination.as_str()),
                        endpoint.as_str(),
                        Some("org.sparklink.SsapReadProvider"),
                        "ReadValue",
                        &(request,),
                    )
                    .await
            });
            let context = receipt(
                &mut reader,
                &mut transcript,
                "SdkReadProviderRequest: ",
                &[
                    "api",
                    "index",
                    "generation",
                    "token",
                    "request_id",
                    "lifetime",
                    "handle",
                    "epoch",
                    "level",
                    "deadline_ns",
                    "property",
                    "maximum_bytes",
                    "local_tcid",
                    "remote_tcid",
                    "pi",
                    "observed_ns",
                    "observed_wall_ns",
                ],
            )?;
            let token = context["token"].as_u64().unwrap();
            assert!(token > prior_token);
            prior_token = token;
            for (name, expected) in [
                ("index", 2),
                ("generation", 7),
                ("request_id", request_id),
                ("lifetime", 13),
                ("handle", 3),
                ("epoch", 41),
                ("level", 0),
                ("deadline_ns", original),
                ("property", 17),
                ("maximum_bytes", 32),
                ("local_tcid", 10),
                ("remote_tcid", 10),
                ("pi", 0),
            ] {
                assert_eq!(context[name], expected, "{language} {name}");
            }
            assert_eq!(context["api"], language);
            assert!(context["observed_ns"].as_u64().unwrap() < original);
            assert!(context["observed_wall_ns"].as_u64().unwrap() > 0);
            if case == "value" {
                let wrong = token.checked_add(1).unwrap();
                send(&mut child, &format!("provide p{wrong} {hex}\n"))?;
                let answer = receipt(
                    &mut reader,
                    &mut transcript,
                    "SdkReadProviderReply: ",
                    REPLY_FIELDS,
                )?;
                check_reply(
                    &answer,
                    language,
                    (wrong, token),
                    original,
                    0,
                    &hex,
                    -nix::libc::ESTALE,
                );
                assert!(
                    !pending.is_finished(),
                    "wrong UI token completed the real callback"
                );
                let large = "ab".repeat(33);
                send(&mut child, &format!("provide p{token} {large}\n"))?;
                let answer = receipt(
                    &mut reader,
                    &mut transcript,
                    "SdkReadProviderReply: ",
                    REPLY_FIELDS,
                )?;
                check_reply(
                    &answer,
                    language,
                    (token, token),
                    original,
                    0,
                    &large,
                    -nix::libc::EMSGSIZE,
                );
                assert!(
                    !pending.is_finished(),
                    "oversize consumed the original callback"
                );
            }
            if case == "unregister" {
                assert!(
                    !pending.is_finished(),
                    "actual callback must still be pending"
                );
                send(&mut child, "provider-unregister\n")?;
                let removed = receipt(
                    &mut reader,
                    &mut transcript,
                    "SdkReadProviderUnregistered: ",
                    &[
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
                    ],
                )?;
                assert_eq!(removed["api"], language);
                assert_eq!(removed["token"], token);
                assert_eq!(removed["property"], 17);
                assert_eq!(removed["original_deadline_ns"], original);
                assert_eq!(removed["deadline_ns"], original);
                assert_eq!(removed["result"], 0);
                assert_eq!(removed["info_preserved"], true);
                assert_eq!(removed["notification_fd_alive"], true);
                assert_eq!(removed["reply_result"], -nix::libc::ESHUTDOWN);
                assert_eq!(removed["local_observation_only"], true);
                let started = removed["started_ns"].as_u64().unwrap();
                let returned = removed["returned_ns"].as_u64().unwrap();
                let reply_started = removed["reply_started_ns"].as_u64().unwrap();
                let reply_returned = removed["reply_returned_ns"].as_u64().unwrap();
                assert!(context["observed_ns"].as_u64().unwrap() <= started);
                assert!(started <= returned && returned <= reply_started);
                assert!(reply_started <= reply_returned && reply_returned < original);
                let body = tokio::time::timeout(Duration::from_secs(3), pending)
                    .await???
                    .body()
                    .deserialize::<slk_contract::ssap::ReadProviderReply>()?;
                assert_eq!(
                    body,
                    (0xaf, vec![]),
                    "actual SDK callback stop, not a wire outcome"
                );
                callback_results.push(serde_json::json!({"case":case,"request_id":request_id,
                    "original_deadline_ns":original,"actual_status":body.0,"actual_value":"",
                    "withdrawal":removed,"scope":"real-private-D-Bus-SDK-callback-not-wire"}));
                assert_eq!(metadata.removed.load(Ordering::SeqCst), removals + 1);
                assert!(
                    child.try_wait()?.is_none(),
                    "retired views must not kill the caller"
                );
            } else if case == "expire" {
                let expired = tokio::time::timeout(Duration::from_secs(3), pending)
                    .await???
                    .body()
                    .deserialize::<slk_contract::ssap::ReadProviderReply>()?;
                assert_eq!(
                    expired,
                    (0xaf, vec![]),
                    "actual endpoint expiry, not a wire AF claim"
                );
                callback_results.push(serde_json::json!({"case":case,"request_id":request_id,
                    "original_deadline_ns":original,"actual_status":expired.0,"actual_value":"",
                    "scope":"real-private-D-Bus-SDK-callback-not-wire"}));
                send(&mut child, &format!("provide p{token} -\n"))?;
                let answer = receipt(
                    &mut reader,
                    &mut transcript,
                    "SdkReadProviderReply: ",
                    REPLY_FIELDS,
                )?;
                check_reply(
                    &answer,
                    language,
                    (token, token),
                    original,
                    0,
                    "",
                    -nix::libc::ETIMEDOUT,
                );
                assert!(answer["started_ns"].as_u64().unwrap() >= original);
                assert!(
                    child.try_wait()?.is_none(),
                    "late input must not kill the owner"
                );
            } else {
                let (status, value, input) = match case {
                    "empty" => (0, "", format!("provide p{token} -\n")),
                    "value" => (
                        0,
                        hex.as_str(),
                        format!("provide p{token} {}\n", hex.to_uppercase()),
                    ),
                    "error" => (0xff, "", format!("provider-error p{token} FF\n")),
                    _ => unreachable!(),
                };
                send(&mut child, &input)?;
                let answer = receipt(
                    &mut reader,
                    &mut transcript,
                    "SdkReadProviderReply: ",
                    REPLY_FIELDS,
                )?;
                check_reply(
                    &answer,
                    language,
                    (token, token),
                    original,
                    status,
                    value,
                    0,
                );
                assert!(answer["returned_ns"].as_u64().unwrap() < original);
                let body = tokio::time::timeout(Duration::from_secs(3), pending)
                    .await???
                    .body()
                    .deserialize::<slk_contract::ssap::ReadProviderReply>()?;
                assert_eq!(
                    body,
                    (
                        status,
                        if case == "value" {
                            random.to_vec()
                        } else {
                            vec![]
                        }
                    )
                );
                callback_results.push(serde_json::json!({"case":case,"request_id":request_id,
                    "original_deadline_ns":original,"actual_status":body.0,
                    "actual_value":body.1.iter().map(|b|format!("{b:02x}")).collect::<String>(),
                    "scope":"real-private-D-Bus-SDK-callback-not-wire"}));
                // Reusing a consumed opaque token is a selector rejection, not
                // another callback and not an invented successful response.
                send(&mut child, &format!("provide p{token} -\n"))?;
                let duplicate = receipt(
                    &mut reader,
                    &mut transcript,
                    "SdkReadProviderReply: ",
                    REPLY_FIELDS,
                )?;
                check_reply(
                    &duplicate,
                    language,
                    (token, 0),
                    0,
                    0,
                    "",
                    -nix::libc::ESTALE,
                );
            }
        }
        send(&mut child, "quit\n")?;
        assert_eq!(
            line(&mut reader, &mut transcript)?,
            if withdrawal {
                format!("SdkOwnedClosedExit: api={language} start=16\n")
            } else {
                format!("SdkOwnedRemoved: api={language} start=16\n")
            }
        );
        let mut remainder = String::new();
        reader.read_to_string(&mut remainder)?;
        assert!(remainder.is_empty());
        let output = child.wait_with_output()?;
        std::fs::write(
            directory.join(format!("{language}-provider{suffix}.stdout")),
            transcript,
        )?;
        std::fs::write(
            directory.join(format!("{language}-provider{suffix}.stderr")),
            &output.stderr,
        )?;
        std::fs::write(
            directory.join(format!("{language}-provider{suffix}-callback-results.json")),
            serde_json::to_vec_pretty(&callback_results)?,
        )?;
        assert!(
            output.status.success() && output.stderr.is_empty(),
            "{language} Provider child: {output:?}"
        );
        assert_eq!(
            metadata.registered.load(Ordering::SeqCst),
            registrations + 1
        );
        assert_eq!(metadata.removed.load(Ordering::SeqCst), removals + 1);
        assert_eq!(metadata.provider_binds.load(Ordering::SeqCst), binds + 1);
        assert!(
            !zbus::fdo::DBusProxy::new(server)
                .await?
                .name_has_owner(owner.as_str().try_into()?)
                .await?,
            "local views/fds must not keep the exited original bus owner alive"
        );
    }
    Ok(())
}
