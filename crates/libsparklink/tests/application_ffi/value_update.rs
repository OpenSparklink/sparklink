//! Actual external SDK consumers over private-bus metadata. The DB/Native/wire
//! path is not supplied by this fixture; production DB tests and VM are separate.
use super::*;
pub(super) async fn exercise(
    root: &std::path::Path,
    executable: &std::path::Path,
    library: &std::path::Path,
    directory: &std::path::Path,
    address: &str,
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
            .args(["owned-readonly", "2", "7", "0100", "0200", "070809"])
            .env("DBUS_SYSTEM_BUS_ADDRESS", address)
            .env("LIBSPARKLINK_PATH", library)
            .env("LD_LIBRARY_PATH", library.parent().unwrap())
            .env("PYTHONPATH", root.join("bindings/python"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut text = String::new();
        for expected in [
            format!("SdkOwnedAPI: api={language} client_closed=true\n"),
            "SsapOwnedService: start=16 end=17 property=17; local registration only\n".to_string(),
        ] {
            let mut line = String::new();
            stdout.read_line(&mut line)?;
            assert_eq!(line, expected);
            text += &line;
        }
        for value in [String::new(), "000102ff".into(), "ab".repeat(2042)] {
            child
                .stdin
                .as_mut()
                .unwrap()
                .write_all(format!("replace {value}\nvalue\n").as_bytes())?;
            let mut line = String::new();
            stdout.read_line(&mut line)?;
            text += &line;
            let receipt: serde_json::Value =
                serde_json::from_str(line.strip_prefix("SdkOwnedReplaced: ").unwrap())?;
            assert_eq!(receipt["api"], language);
            assert_eq!(receipt["handle"], 17);
            assert_eq!(receipt["value"], value);
            let start = receipt["started_ns"].as_u64().unwrap();
            let end = receipt["returned_ns"].as_u64().unwrap();
            let deadline = receipt["deadline_ns"].as_u64().unwrap();
            assert!(start <= end && end < deadline && deadline - start == 5_000_000_000);
            line.clear();
            stdout.read_line(&mut line)?;
            assert_eq!(line, format!("SsapOwnedValue: handle=17 value={value}\n"));
            text += &line;
        }
        child.stdin.as_mut().unwrap().write_all(b"quit\n")?;
        let mut end = String::new();
        stdout.read_to_string(&mut end)?;
        assert_eq!(end, format!("SdkOwnedRemoved: api={language} start=16\n"));
        text += &end;
        let result = child.wait_with_output()?;
        std::fs::write(
            directory.join(format!("{language}-local-replace.stdout")),
            text,
        )?;
        std::fs::write(
            directory.join(format!("{language}-local-replace.stderr")),
            &result.stderr,
        )?;
        assert!(
            result.status.success() && result.stderr.is_empty(),
            "{result:?}"
        );
    }
    Ok(())
}
