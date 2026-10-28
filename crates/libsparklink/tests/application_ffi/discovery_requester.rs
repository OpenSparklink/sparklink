//! Existing VM consumers against finite D-Bus metadata, not remote wire/RF.
use super::*;
use std::path::Path;
pub(super) fn exercise(
    root: &Path,
    probe: &Path,
    library: &Path,
    directory: &Path,
    address: &str,
    calls: &AtomicUsize,
) -> anyhow::Result<()> {
    let before = calls.load(Ordering::SeqCst);
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
        for (label, uuid, handle, success) in [
            ("match", "0102", "17", true),
            ("wrong-handle", "0102", "18", false),
            ("malformed", "0304", "17", false),
            ("refused", "0506", "17", false),
            ("timeout", "0708", "17", false),
        ] {
            let mut child = command()
                .args(["ssap-find-method", "2", "7", PATH, uuid, handle])
                .spawn()?;
            let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
            let mut barrier = String::new();
            reader.read_line(&mut barrier)?;
            let first: serde_json::Value = serde_json::from_str(&barrier)?;
            assert_eq!(first["stage"], "ssap_discovery_start_barrier");
            assert_eq!(first["api"], language);
            assert_eq!(first["schema_version"], 1);
            assert_eq!(first["client_closed"], true);
            child.stdin.as_mut().unwrap().write_all(b"start\n")?;
            let mut text = String::new();
            reader.read_to_string(&mut text)?;
            let output = child.wait_with_output()?;
            std::fs::write(
                directory.join(format!("discovery-{language}-{label}.stdout")),
                barrier + &text,
            )?;
            std::fs::write(
                directory.join(format!("discovery-{language}-{label}.stderr")),
                &output.stderr,
            )?;
            assert_eq!(output.status.success(), success, "{language}:{label}");
            if !success {
                assert!(text.is_empty(), "no success receipt on rejection");
                continue;
            }
            assert!(output.stderr.is_empty());
            let value: serde_json::Value = serde_json::from_str(&text)?;
            assert_eq!(value["stage"], "ssap_method_discovered");
            assert_eq!(value["api"], language);
            assert_eq!(value["schema_version"], 1);
            assert_eq!(value["index"], 2);
            assert_eq!(value["generation"], 7);
            assert_eq!(value["deadline_ns"], first["deadline_ns"]);
            assert!(value["call_ns"].as_u64().unwrap() < value["returned_ns"].as_u64().unwrap());
            assert!(
                value["returned_ns"].as_u64().unwrap() < first["deadline_ns"].as_u64().unwrap()
            );
            assert_eq!(value["category"], 3);
            assert_eq!(value["handle"], 17);
            assert_eq!(value["end"], 17);
            assert_eq!(value["uuid"], "0102");
            assert_eq!(value["operations"], 0);
            assert_eq!(value["descriptors"], "80");
            assert_eq!(value["members"], 0);
            assert_eq!(
                value["trace"],
                serde_json::json!([{"request":"06140100ffff0102","response":"070b0111000102000000000180"}])
            );
        }
        for (uuid, handle) in [
            ("0g02", "17"),
            ("01", "17"),
            ("0102", "0"),
            ("0102", "65536"),
        ] {
            let output = command()
                .args(["ssap-find-method", "2", "7", PATH, uuid, handle])
                .output()?;
            assert!(!output.status.success());
            assert!(output.stdout.is_empty());
        }
        // Keep stdin open without releasing: original5s, not a supervisor timeout.
        let mut child = command()
            .args(["ssap-find-method", "2", "7", PATH, "0102", "17"])
            .spawn()?;
        let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut first = String::new();
        reader.read_line(&mut first)?;
        assert!(first.contains("ssap_discovery_start_barrier"));
        let mut rest = String::new();
        reader.read_to_string(&mut rest)?;
        let output = child.wait_with_output()?;
        assert_eq!(output.status.code(), Some(1));
        assert!(rest.is_empty());
        let barrier: serde_json::Value = serde_json::from_str(&first)?;
        let observed = slk_channel::deadline::monotonic_timestamp_at(std::time::Instant::now())?;
        let original = barrier["deadline_ns"].as_u64().unwrap();
        assert!(
            observed >= original,
            "unreleased barrier must not fail before original deadline"
        );
        std::fs::write(
            directory.join(format!("discovery-{language}-barrier.json")),
            serde_json::to_vec_pretty(&serde_json::json!({"deadline_ns":original,
                "observed_exit_ns":observed,"exit":output.status.code(),"rpc_submitted":false}))?,
        )?;
        std::fs::write(
            directory.join(format!("discovery-{language}-barrier.stdout")),
            first,
        )?;
        std::fs::write(
            directory.join(format!("discovery-{language}-barrier.stderr")),
            output.stderr,
        )?;
    }
    assert_eq!(
        calls.load(Ordering::SeqCst) - before,
        10,
        "no RPC on invalid/barrier expiry, no retry"
    );
    Ok(())
}
