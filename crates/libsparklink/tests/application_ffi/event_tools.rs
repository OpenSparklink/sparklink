//! Real installed-language helper processes,actual SDK/cdylib/private bus.
//! Native/peer/Owned wire behavior is finite metadata,not a replacement Engine.
use super::*;
fn child(
    root: &std::path::Path,
    exe: &std::path::Path,
    lib: &std::path::Path,
    address: &str,
    language: &str,
    args: &[&str],
) -> anyhow::Result<std::process::Child> {
    let mut c = Command::new("timeout");
    c.arg("15s");
    if language == "c" {
        c.arg(exe);
    } else {
        c.arg("python3")
            .arg(root.join("tools/testing/application_client/client.py"));
    }
    Ok(c.args(args)
        .env("DBUS_SYSTEM_BUS_ADDRESS", address)
        .env("LIBSPARKLINK_PATH", lib)
        .env("LD_LIBRARY_PATH", lib.parent().unwrap())
        .env("PYTHONPATH", root.join("bindings/python"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?)
}
fn line(
    reader: &mut std::io::BufReader<std::process::ChildStdout>,
    transcript: &mut String,
) -> anyhow::Result<String> {
    let mut s = String::new();
    anyhow::ensure!(
        reader.read_line(&mut s)? != 0,
        "missing helper output after {transcript:?}"
    );
    *transcript += &s;
    Ok(s)
}
fn json_line(
    reader: &mut std::io::BufReader<std::process::ChildStdout>,
    transcript: &mut String,
) -> anyhow::Result<serde_json::Value> {
    Ok(serde_json::from_str(&line(reader, transcript)?)?)
}
fn deadline(v: &serde_json::Value) {
    let (a, b, c) = (
        v["started_ns"].as_u64().unwrap(),
        v["returned_ns"].as_u64().unwrap(),
        v["deadline_ns"].as_u64().unwrap(),
    );
    assert!(a <= b && b < c);
    assert_eq!(c - a, 5_000_000_000);
}
fn finish(
    mut child: std::process::Child,
    mut reader: std::io::BufReader<std::process::ChildStdout>,
    mut transcript: String,
    directory: &std::path::Path,
    name: &str,
    success: bool,
) -> anyhow::Result<()> {
    child.stdin.take();
    let mut rest = String::new();
    reader.read_to_string(&mut rest)?;
    transcript += &rest;
    let output = child.wait_with_output()?;
    std::fs::write(directory.join(format!("{name}.stdout")), &transcript)?;
    std::fs::write(directory.join(format!("{name}.stderr")), &output.stderr)?;
    anyhow::ensure!(
        output.status.success() == success,
        "{name}: {output:?};{transcript}"
    );
    if success {
        anyhow::ensure!(output.stderr.is_empty(), "{name}: {output:?}");
    } else {
        anyhow::ensure!(
            !output.stderr.is_empty() && !rest.contains("checked_reply"),
            "unexpected success output"
        );
    }
    Ok(())
}
fn hex(b: &[u8]) -> String {
    b.iter().map(|v| format!("{v:02x}")).collect()
}
pub(super) async fn exercise(
    root: &std::path::Path,
    exe: &std::path::Path,
    lib: &std::path::Path,
    directory: &std::path::Path,
    address: &str,
    metadata: &subscription::Metadata,
    lifetime: &AtomicU64,
) -> anyhow::Result<()> {
    lifetime.store(11, Ordering::SeqCst);
    for language in ["c", "python"] {
        metadata.reset_event_fixture(vec![0x42]);
        let mut sender = child(
            root,
            exe,
            lib,
            address,
            language,
            &[
                "owned-events",
                "2",
                "7",
                "0800",
                "0200",
                "070809",
                PATH,
                "0600",
                "0",
            ],
        )?;
        let mut reader = std::io::BufReader::new(sender.stdout.take().unwrap());
        let mut text = String::new();
        assert!(line(&mut reader, &mut text)?.contains("client_closed=true"));
        assert!(line(&mut reader, &mut text)?.contains("start=16 end=18 property=17"));
        let binding = line(&mut reader, &mut text)?;
        let binding: serde_json::Value =
            serde_json::from_str(binding.strip_prefix("SdkOwnedEventBinding: ").unwrap())?;
        assert_eq!(
            (
                binding["event"].as_u64(),
                binding["reply_property"].as_u64()
            ),
            (Some(18), Some(17))
        );
        assert_eq!(
            metadata.event_sends.load(Ordering::SeqCst),
            if language == "c" { 0 } else { 16 }
        );
        for n in [0, 1, 249, 250, 253, 254, 255, 2042] {
            let payload: Vec<_> = (0..n).map(|i| ((i * 73 + n) % 256) as u8).collect();
            *metadata.event_payload.lock().unwrap() = Some(payload.clone());
            for indication in [false, true] {
                let command = if indication {
                    "event-indicate"
                } else {
                    "event-notify"
                };
                sender.stdin.as_mut().unwrap().write_all(
                    format!(
                        "{command} {}\n",
                        if n == 0 { "-".into() } else { hex(&payload) }
                    )
                    .as_bytes(),
                )?;
                let row = line(&mut reader, &mut text)?;
                let row: serde_json::Value =
                    serde_json::from_str(row.strip_prefix("SdkOwnedEvent: ").unwrap())?;
                deadline(&row);
                assert_eq!(row["stage"], if indication { 2 } else { 1 });
                assert_eq!(row["handle"], 18);
                assert_eq!(row["minimum"], 0);
                let mut expected = vec![if indication { 16 } else { 15 }, 7, 18, 0];
                expected.extend_from_slice(&(n as u16).to_le_bytes());
                expected.extend(payload.clone());
                assert_eq!(row["pdu"], hex(&expected));
                assert_eq!(row["ack"], if indication { "110701" } else { "" });
            }
        }
        sender.stdin.as_mut().unwrap().write_all(b"quit\n")?;
        finish(
            sender,
            reader,
            text,
            directory,
            &format!("event-tools-{language}-sender"),
            true,
        )?;
        for (case, n) in [0, 1, 249, 250, 253, 254, 255, 2042]
            .into_iter()
            .enumerate()
        {
            let payload: Vec<_> = (0..n).map(|i| ((i * 73 + n) % 256) as u8).collect();
            metadata.reset_event_fixture(payload.clone());
            let minimum = (case % 3).to_string();
            let mut peer = child(
                root,
                exe,
                lib,
                address,
                language,
                &[
                    "event-subscription",
                    "2",
                    "7",
                    PATH,
                    "18",
                    "2",
                    "1000",
                    &minimum,
                    "17",
                ],
            )?;
            let mut reader = std::io::BufReader::new(peer.stdout.take().unwrap());
            let mut text = String::new();
            let ready = json_line(&mut reader, &mut text)?;
            assert_eq!(ready["stage"], "ssap_event_listener_ready");
            deadline(&ready);
            assert_eq!(ready["event"], 18);
            assert_eq!(ready["reply_property"], 17);
            assert_eq!(ready["minimum"], case % 3);
            peer.stdin.as_mut().unwrap().write_all(
                format!(
                    "check {} cd\n",
                    if n == 0 { "-".into() } else { hex(&payload) }
                )
                .as_bytes(),
            )?;
            let checked = json_line(&mut reader, &mut text)?;
            assert_eq!(checked["stage"], "ssap_event_checked_reply");
            deadline(&checked);
            assert_eq!(checked["value"], hex(&payload));
            assert_eq!(checked["reply"], "cd");
            assert_eq!(checked["event"], 18);
            let batch = json_line(&mut reader, &mut text)?;
            assert_eq!(
                batch["packets"][0]["pdu"],
                format!(
                    "10071200{}{}",
                    hex(&(n as u16).to_le_bytes()),
                    hex(&payload)
                )
            );
            peer.stdin.as_mut().unwrap().write_all(b"quit\n")?;
            let closed = json_line(&mut reader, &mut text)?;
            assert_eq!(closed["flags"], 1);
            finish(
                peer,
                reader,
                text,
                directory,
                &format!("event-tools-{language}-peer-{n}"),
                true,
            )?;
        }
        for (case, command) in [
            ("bad-payload", "check ff cd\n"),
            ("same-reply", "check ab ab\n"),
            ("unchecked-cache", "drain\nquit\n"),
        ] {
            metadata.reset_event_fixture(vec![0xab]);
            let before = metadata.event_writes.load(Ordering::SeqCst);
            let mut peer = child(
                root,
                exe,
                lib,
                address,
                language,
                &[
                    "event-subscription",
                    "2",
                    "7",
                    PATH,
                    "18",
                    "2",
                    "1000",
                    "0",
                    "17",
                ],
            )?;
            let mut reader = std::io::BufReader::new(peer.stdout.take().unwrap());
            let mut text = String::new();
            assert_eq!(
                json_line(&mut reader, &mut text)?["stage"],
                "ssap_event_listener_ready"
            );
            peer.stdin.as_mut().unwrap().write_all(command.as_bytes())?;
            finish(
                peer,
                reader,
                text,
                directory,
                &format!("event-tools-{language}-{case}"),
                false,
            )?;
            assert_eq!(
                metadata.event_writes.load(Ordering::SeqCst),
                before,
                "rejected input cannot generate application reply"
            );
        }
    }
    assert_eq!(metadata.event_sends.load(Ordering::SeqCst), 32);
    assert_eq!(metadata.event_writes.load(Ordering::SeqCst), 16);
    metadata.event_payload.lock().unwrap().take();
    Ok(())
}
