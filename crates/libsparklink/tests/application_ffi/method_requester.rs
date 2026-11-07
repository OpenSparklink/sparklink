//! Real VM requester executables against the existing finite private-bus service.
//! These checks prove tool/API routing and fail-closed results, not peer delivery.
use super::*;
use std::path::Path;

pub(super) fn exercise(
    root: &Path,
    probe: &Path,
    library: &Path,
    directory: &Path,
    address: &str,
    command_calls: &Mutex<Vec<CommandCall>>,
) -> anyhow::Result<()> {
    for language in ["c", "python"] {
        let command = || {
            let mut cmd = Command::new("timeout");
            cmd.arg("12s");
            if language == "c" {
                cmd.arg(probe);
            } else {
                cmd.arg("python3")
                    .arg(root.join("tools/testing/application_client/client.py"));
            }
            cmd.env("DBUS_SYSTEM_BUS_ADDRESS", address)
                .env("LIBSPARKLINK_PATH", library)
                .env("PYTHONPATH", root.join("bindings/python"))
                .env("LD_LIBRARY_PATH", directory)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            cmd
        };
        for (label, handle, arguments, expected) in [
            ("short", "64", "5612".to_owned(), "907834".to_owned()),
            ("empty", "65", String::new(), String::new()),
            ("boundary", "66", "31".repeat(2043), "a6".repeat(2045)),
        ] {
            for correct in [true, false] {
                let mut cmd = command();
                let check = if correct { &expected } else { "0000" };
                cmd.args([
                    "ssap",
                    "2",
                    "7",
                    PATH,
                    "ssap-call-method",
                    handle,
                    check,
                    &arguments,
                ]);
                let mut child = cmd.spawn()?;
                let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
                let mut barrier = String::new();
                stdout.read_line(&mut barrier)?;
                let parsed: serde_json::Value = serde_json::from_str(&barrier)?;
                assert_eq!(
                    parsed,
                    serde_json::json!({"stage":"ssap_start_barrier","api":language,"client_closed":true})
                );
                child.stdin.as_mut().unwrap().write_all(b"start\n")?;
                let mut remaining = String::new();
                stdout.read_to_string(&mut remaining)?;
                let output = child.wait_with_output()?;
                let name = format!("method-requester-{language}-{label}-{correct}");
                std::fs::write(
                    directory.join(format!("{name}.stdout")),
                    barrier + &remaining,
                )?;
                std::fs::write(directory.join(format!("{name}.stderr")), &output.stderr)?;
                assert_eq!(output.status.success(), correct, "{name}");
                if correct {
                    assert!(output.stderr.is_empty());
                    assert_eq!(
                        remaining,
                        format!(
                            "SsapPeerValue: operation=ssap-call-method path={PATH} handle={handle} value={expected}\n"
                        )
                    );
                } else {
                    assert_eq!(output.status.code(), Some(1));
                    assert!(
                        remaining.is_empty(),
                        "mismatched peer result cannot yield success receipt"
                    );
                    assert!(!output.stderr.is_empty());
                }
            }
        }
        for (label, handle, expected_errno, success) in [
            ("unsupported", "67", "95", true),
            ("wrong-errno", "67", "5", false),
            ("immediate-timeout", "68", "110", true),
            ("unexpected-success", "64", "5", false),
        ] {
            let output = command()
                .args([
                    "ssap-error",
                    "2",
                    "7",
                    PATH,
                    "ssap-call-method",
                    handle,
                    expected_errno,
                    "5612",
                ])
                .output()?;
            let name = format!("method-requester-{language}-{label}");
            std::fs::write(directory.join(format!("{name}.stdout")), &output.stdout)?;
            std::fs::write(directory.join(format!("{name}.stderr")), &output.stderr)?;
            assert_eq!(output.status.success(), success, "{name}");
            let rows: Vec<serde_json::Value> = std::str::from_utf8(&output.stdout)?
                .lines()
                .map(serde_json::from_str)
                .collect::<Result<_, _>>()?;
            assert_eq!(rows[0]["stage"], "ssap_call");
            if success {
                assert!(output.stderr.is_empty());
                assert_eq!(rows.len(), 2);
                assert_eq!(rows[1]["errno"], expected_errno.parse::<u32>()?);
                assert_eq!(rows[1]["operation_success"], false);
                assert_eq!(rows[1]["deadline_ns"], rows[0]["deadline_ns"]);
            }
        }
        for (label, arguments, expected) in [
            ("arguments-overflow", "31".repeat(2044), "00".to_owned()),
            ("result-overflow", "5612".to_owned(), "a6".repeat(2046)),
            ("arguments-invalid", "0g".to_owned(), "00".to_owned()),
        ] {
            let output = command()
                .args([
                    "ssap",
                    "2",
                    "7",
                    PATH,
                    "ssap-call-method",
                    "64",
                    &expected,
                    &arguments,
                ])
                .output()?;
            assert!(!output.status.success(), "{language}/{label}");
            assert!(
                output.stdout.is_empty(),
                "invalid inputs must fail before Client acquisition"
            );
            std::fs::write(
                directory.join(format!("method-requester-{language}-{label}.stderr")),
                &output.stderr,
            )?;
        }
        // A missing release is a real original-five-second wait. It must not
        // reach the method RPC, and cannot be mislabeled as successful delivery.
        let mut child = command()
            .args([
                "ssap",
                "2",
                "7",
                PATH,
                "ssap-call-method",
                "64",
                "907834",
                "5612",
            ])
            .spawn()?;
        let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut barrier = String::new();
        stdout.read_line(&mut barrier)?;
        let parsed: serde_json::Value = serde_json::from_str(&barrier)?;
        assert_eq!(parsed["stage"], "ssap_start_barrier");
        let started = std::time::Instant::now();
        // Both wait() and wait_with_output() close Child::stdin. Move the
        // write end out first, so EOF cannot impersonate original expiry.
        let unreleased = child.stdin.take().unwrap();
        let status = child.wait()?;
        let elapsed = started.elapsed();
        drop(unreleased);
        let mut remaining = String::new();
        stdout.read_to_string(&mut remaining)?;
        assert!(remaining.is_empty());
        let output = child.wait_with_output()?;
        std::fs::write(
            directory.join(format!("method-requester-{language}-unreleased.stdout")),
            barrier,
        )?;
        std::fs::write(
            directory.join(format!("method-requester-{language}-unreleased.stderr")),
            &output.stderr,
        )?;
        std::fs::write(
            directory.join(format!(
                "method-requester-{language}-unreleased-timing.json"
            )),
            serde_json::to_vec(
                &serde_json::json!({"elapsed_ns":elapsed.as_nanos(),"exit_code":status.code()}),
            )?,
        )?;
        assert!(elapsed >= std::time::Duration::from_millis(4500));
        assert_eq!(status.code(), Some(1));
        assert!(!output.stderr.is_empty());

        for (label, handle, arguments, success) in [
            ("short", "64", "5612".to_owned(), true),
            ("empty", "65", String::new(), true),
            ("boundary", "66", "31".repeat(2043), true),
            ("unsupported", "67", "5612".to_owned(), false),
            ("timeout-error", "68", "5612".to_owned(), false),
        ] {
            let before = command_calls.lock().unwrap().len();
            let mut child = command()
                .args([
                    "ssap-method-command",
                    "2",
                    "7",
                    PATH,
                    handle,
                    &arguments,
                    "0",
                ])
                .spawn()?;
            let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
            let mut barrier = String::new();
            stdout.read_line(&mut barrier)?;
            let parsed: serde_json::Value = serde_json::from_str(&barrier)?;
            assert_eq!(parsed["stage"], "ssap_command_start_barrier");
            assert_eq!(parsed["api"], language);
            assert_eq!(parsed["client_closed"], true);
            assert_eq!(parsed["mode"], "ssap-method-command");
            assert_eq!(parsed["method"], "CallSsapMethodCommand");
            assert_eq!(parsed["schema_version"], 1);
            child.stdin.as_mut().unwrap().write_all(b"start\n")?;
            let mut remaining = String::new();
            stdout.read_to_string(&mut remaining)?;
            let output = child.wait_with_output()?;
            let name = format!("method-command-{language}-{label}");
            std::fs::write(
                directory.join(format!("{name}.stdout")),
                barrier + &remaining,
            )?;
            std::fs::write(directory.join(format!("{name}.stderr")), &output.stderr)?;
            assert_eq!(output.status.success(), success, "{name}");
            let calls = command_calls.lock().unwrap();
            assert_eq!(
                calls.len(),
                before + 1,
                "request RPC cannot impersonate command RPC"
            );
            let actual = &calls[before];
            assert_eq!(actual.0, handle.parse::<u16>()?);
            assert_eq!(actual.1, 0);
            assert_eq!(
                actual.2,
                (0..arguments.len())
                    .step_by(2)
                    .map(|n| u8::from_str_radix(&arguments[n..n + 2], 16).unwrap())
                    .collect::<Vec<_>>()
            );
            assert_eq!(
                slk_contract::deadline_stamp(actual.3).monotonic_ns,
                parsed["deadline_ns"].as_u64().unwrap()
            );
            if success {
                assert!(output.stderr.is_empty());
                assert_eq!(remaining.lines().count(), 1);
                let receipt: serde_json::Value = serde_json::from_str(
                    remaining
                        .trim_end()
                        .strip_prefix("SSAP_COMMAND_ADMITTED: ")
                        .unwrap(),
                )?;
                assert_eq!(receipt["mode"], "ssap-method-command");
                assert_eq!(receipt["method"], "CallSsapMethodCommand");
                assert_eq!(receipt["schema_version"], 1);
                assert_eq!(receipt["api"], language);
                assert_eq!(receipt["handle"], actual.0);
                assert_eq!(receipt["minimum"], 0);
                assert_eq!(receipt["value"], arguments);
                assert_eq!(receipt["admission_only"], true);
                assert_eq!(receipt["peer_delivery_confirmed"], false);
                assert_eq!(receipt["deadline_ns"], parsed["deadline_ns"]);
                assert!(
                    receipt["call_ns"].as_u64().unwrap() < receipt["returned_ns"].as_u64().unwrap()
                );
                assert!(
                    receipt["returned_ns"].as_u64().unwrap()
                        < parsed["deadline_ns"].as_u64().unwrap()
                );
            } else {
                assert_eq!(output.status.code(), Some(1));
                assert!(!output.stderr.is_empty());
                assert!(remaining.is_empty());
            }
        }
        let before = command_calls.lock().unwrap().len();
        for arguments in ["31".repeat(2044), "0g".to_owned()] {
            let output = command()
                .args(["ssap-method-command", "2", "7", PATH, "64", &arguments, "0"])
                .output()?;
            assert!(!output.status.success());
            assert!(
                output.stdout.is_empty(),
                "invalid arguments fail before Client acquisition"
            );
        }
        let mut child = command()
            .args(["ssap-method-command", "2", "7", PATH, "64", "5612", "0"])
            .spawn()?;
        let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut barrier = String::new();
        stdout.read_line(&mut barrier)?;
        let parsed: serde_json::Value = serde_json::from_str(&barrier)?;
        assert_eq!(parsed["mode"], "ssap-method-command");
        let started = std::time::Instant::now();
        let unreleased = child.stdin.take().unwrap();
        let status = child.wait()?;
        let elapsed = started.elapsed();
        drop(unreleased);
        let mut remaining = String::new();
        stdout.read_to_string(&mut remaining)?;
        let output = child.wait_with_output()?;
        std::fs::write(
            directory.join(format!("method-command-{language}-unreleased.stdout")),
            barrier,
        )?;
        std::fs::write(
            directory.join(format!("method-command-{language}-unreleased.stderr")),
            &output.stderr,
        )?;
        std::fs::write(
            directory.join(format!("method-command-{language}-unreleased-timing.json")),
            serde_json::to_vec(
                &serde_json::json!({"elapsed_ns":elapsed.as_nanos(),"exit_code":status.code()}),
            )?,
        )?;
        assert!(elapsed >= std::time::Duration::from_millis(4500));
        assert_eq!(status.code(), Some(1));
        assert!(remaining.is_empty());
        assert!(!output.stderr.is_empty());
        assert_eq!(
            command_calls.lock().unwrap().len(),
            before,
            "invalid/unreleased commands never submit"
        );
    }
    Ok(())
}
