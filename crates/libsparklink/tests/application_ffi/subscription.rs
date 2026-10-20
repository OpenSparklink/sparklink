//! Actual C/Python entry over the existing private-bus fixture. Finite metadata
//! only,no SSAP/Native/USB success or protocol cleanup proof is supplied here.
use super::*;
use slk_contract::ssap::subscription as wire;

#[derive(Default)]
pub(super) struct Metadata {
    current: Mutex<Option<(String, wire::Info)>>,
    sequence: AtomicU64,
    reads: AtomicUsize,
    closes: AtomicUsize,
}
impl Metadata {
    pub(super) fn subscribe(
        &self,
        handles: Vec<u16>,
        modes: u8,
        duration: u32,
        stamp: slk_contract::Deadline,
        caller: String,
        lifetime: u64,
    ) -> zbus::fdo::Result<wire::Info> {
        let original =
            slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp))
                .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        if handles != [17] || modes != 2 || duration != 1000 || lifetime != 11 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "exact finite subscription fixture required".into(),
            ));
        }
        let mut current = self.current.lock().unwrap();
        if current
            .as_ref()
            .is_some_and(|(_, v)| v.state != wire::CLOSED)
        {
            return Err(zbus::fdo::Error::LimitsExceeded(
                "occupied fixture lease".into(),
            ));
        }
        let info = wire::Info {
            version: 1,
            controller: 2,
            generation: 7,
            lifetime,
            handle: 3,
            security_epoch: 13,
            token: 17,
            expires_ns: original.stamp().monotonic_ns + u64::from(duration) * 1_000_000,
            handles,
            modes,
            state: wire::ACTIVE,
            capacity: 16,
        };
        *current = Some((caller, info.clone()));
        self.sequence.store(0, Ordering::SeqCst);
        Ok(info)
    }
    fn get(&self, token: u64, caller: &str) -> zbus::fdo::Result<wire::Info> {
        let current = self.current.lock().unwrap();
        match current.as_ref() {
            Some((owner, info)) if owner == caller && info.token == token => Ok(info.clone()),
            _ => Err(zbus::fdo::Error::AccessDenied(
                "fixture owner/token mismatch".into(),
            )),
        }
    }
    pub(super) fn read(
        &self,
        token: u64,
        stamp: slk_contract::Deadline,
        caller: &str,
    ) -> zbus::fdo::Result<wire::Batch> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp))
            .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        let info = self.get(token, caller)?;
        if info.state != wire::ACTIVE {
            return Err(zbus::fdo::Error::Failed("closed fixture lease".into()));
        }
        self.reads.fetch_add(1, Ordering::SeqCst);
        let sequence = self.sequence.fetch_add(1, Ordering::SeqCst) + 1;
        Ok(wire::Batch {
            info,
            last_sequence: sequence,
            dropped_notifications: 0,
            refused_indications: 0,
            discarded_on_close: 0,
            flags: 0,
            reason: 0,
            packets: vec![wire::Packet {
                sequence,
                security_epoch: 13,
                security_level: 2,
                indication: true,
                pdu: vec![16, 3, 17, 0, 1, 0, 0xab],
            }],
        })
    }
    pub(super) fn renew(
        &self,
        token: u64,
        duration: u32,
        stamp: slk_contract::Deadline,
        caller: &str,
    ) -> zbus::fdo::Result<wire::Info> {
        let original =
            slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp))
                .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        let mut info = self.get(token, caller)?;
        if duration != 2000 || info.state != wire::ACTIVE {
            return Err(zbus::fdo::Error::InvalidArgs(
                "exact fixture renewal required".into(),
            ));
        }
        info.expires_ns = original.stamp().monotonic_ns + u64::from(duration) * 1_000_000;
        *self.current.lock().unwrap() = Some((caller.into(), info.clone()));
        Ok(info)
    }
    pub(super) fn close(
        &self,
        token: u64,
        stamp: slk_contract::Deadline,
        caller: &str,
    ) -> zbus::fdo::Result<wire::Batch> {
        slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(stamp))
            .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        let mut info = self.get(token, caller)?;
        info.state = wire::CLOSED;
        *self.current.lock().unwrap() = Some((caller.into(), info.clone()));
        self.closes.fetch_add(1, Ordering::SeqCst);
        Ok(wire::Batch {
            info,
            last_sequence: self.sequence.load(Ordering::SeqCst),
            dropped_notifications: 0,
            refused_indications: 0,
            discarded_on_close: 0,
            flags: wire::CLEANUP_CONFIRMED,
            reason: wire::RELEASED,
            packets: vec![],
        })
    }
}

pub(super) async fn exercise(
    root: &std::path::Path,
    executable: &std::path::Path,
    library: &std::path::Path,
    directory: &std::path::Path,
    address: &str,
    metadata: &Metadata,
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
            .args(["subscription", "2", "7", PATH, "17", "2", "1000"])
            .env("DBUS_SYSTEM_BUS_ADDRESS", address)
            .env("LIBSPARKLINK_PATH", library)
            .env("LD_LIBRARY_PATH", directory)
            .env("PYTHONPATH", root.join("bindings/python"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut transcript = String::new();
        let mut line = String::new();
        anyhow::ensure!(
            reader.read_line(&mut line)? != 0,
            "subscription consumer ended"
        );
        let active: serde_json::Value = serde_json::from_str(&line)?;
        transcript += &line;
        assert_eq!(active["stage"], "ssap_subscription_active");
        assert_eq!(active["api"], language);
        assert_eq!(active["token"], 17);
        assert_eq!(active["epoch"], 13);
        assert_eq!(active["client_closed"], true);
        let started = active["started_ns"].as_u64().unwrap();
        let deadline = active["deadline_ns"].as_u64().unwrap();
        let returned = active["returned_ns"].as_u64().unwrap();
        assert_eq!(deadline - started, 5_000_000_000);
        assert!(started <= returned && returned < deadline);
        assert!(active["expires_ns"].as_u64().unwrap() > started);
        for (operation, stage) in [
            ("parent-close", "ssap_subscription_parent_closed"),
            ("poll", "ssap_subscription_batch"),
            ("renew 2000", "ssap_subscription_renewed"),
            ("read", "ssap_subscription_batch"),
            ("release", "ssap_subscription_released"),
        ] {
            child
                .stdin
                .as_mut()
                .unwrap()
                .write_all(format!("{operation}\n").as_bytes())?;
            line.clear();
            anyhow::ensure!(reader.read_line(&mut line)? != 0, "missing {stage}");
            let value: serde_json::Value = serde_json::from_str(&line)?;
            transcript += &line;
            assert_eq!(value["stage"], stage);
            assert_eq!(value["api"], language);
            if stage == "ssap_subscription_batch" {
                assert_eq!(value["last"], if operation == "poll" { 1 } else { 2 });
                assert_eq!(value["dropped"], 0);
                assert_eq!(value["refused"], 0);
                let packets = value["packets"].as_array().unwrap();
                assert_eq!(packets.len(), 1);
                assert_eq!(packets[0]["pdu"], "100311000100ab");
                assert_eq!(packets[0]["epoch"], 13);
                assert_eq!(packets[0]["level"], 2);
                assert_eq!(packets[0]["sequence"], value["last"]);
                assert_eq!(packets[0]["indication"], true);
            } else if stage == "ssap_subscription_renewed" {
                assert!(value["expires_ns"].as_u64().unwrap() > 0);
                assert_eq!(value["token"], active["token"]);
                assert_eq!(value["epoch"], active["epoch"]);
                let start = value["started_ns"].as_u64().unwrap();
                let deadline = value["deadline_ns"].as_u64().unwrap();
                let returned = value["returned_ns"].as_u64().unwrap();
                assert_eq!(deadline - start, 5_000_000_000);
                assert!(start <= returned && returned < deadline);
            } else if stage == "ssap_subscription_released" {
                assert_eq!(value["flags"], 1);
                assert_eq!(value["discarded"], 0);
            }
        }
        child.stdin.as_mut().unwrap().write_all(b"quit\n")?;
        let mut rest = String::new();
        reader.read_to_string(&mut rest)?;
        assert!(rest.is_empty(), "no extra cleanup/retry/result: {rest}");
        let result = child.wait_with_output()?;
        std::fs::write(
            directory.join(format!("{language}-subscription.stdout")),
            transcript,
        )?;
        std::fs::write(
            directory.join(format!("{language}-subscription.stderr")),
            &result.stderr,
        )?;
        anyhow::ensure!(
            result.status.success() && result.stderr.is_empty(),
            "{language} subscription: {result:?}"
        );
    }
    assert_eq!(metadata.reads.load(Ordering::SeqCst), 4);
    assert_eq!(metadata.closes.load(Ordering::SeqCst), 2);
    // Only metadata/bytes cross this private fixture. It supplies no successful
    // Native,verified-write,wire ACK or real cleanup implementation. The real
    // full16/drain/writeback/resume gate is a separate VM qualification.
    for language in ["c", "python"] {
        for (case, operation) in [
            ("empty-cache", "check-cached ab cd"),
            ("pending-read", "poll"),
            ("wrong-payload", "check-cached cd ef"),
            ("pending-release", "release"),
            ("pending-quit", "quit"),
        ] {
            // Explicit fixture teardown only,not a production release/drain.
            *metadata.current.lock().unwrap() = None;
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
                .args(["subscription", "2", "7", PATH, "17", "2", "1000"])
                .env("DBUS_SYSTEM_BUS_ADDRESS", address)
                .env("LIBSPARKLINK_PATH", library)
                .env("LD_LIBRARY_PATH", directory)
                .env("PYTHONPATH", root.join("bindings/python"))
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?;
            let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
            let mut transcript = String::new();
            let mut line = String::new();
            anyhow::ensure!(reader.read_line(&mut line)? != 0, "missing active fixture");
            assert_eq!(
                serde_json::from_str::<serde_json::Value>(&line)?["stage"],
                "ssap_subscription_active"
            );
            transcript += &line;
            if case != "empty-cache" {
                child.stdin.as_mut().unwrap().write_all(b"drain\n")?;
                line.clear();
                anyhow::ensure!(
                    reader.read_line(&mut line)? != 0,
                    "missing actual SDK batch"
                );
                let batch: serde_json::Value = serde_json::from_str(&line)?;
                assert_eq!(batch["stage"], "ssap_subscription_batch");
                assert_eq!(batch["packets"].as_array().unwrap().len(), 1);
                assert_eq!(batch["packets"][0]["pdu"], "100311000100ab");
                transcript += &line;
            }
            child
                .stdin
                .as_mut()
                .unwrap()
                .write_all(format!("{operation}\n").as_bytes())?;
            child.stdin.take();
            let mut rest = String::new();
            reader.read_to_string(&mut rest)?;
            assert!(rest.is_empty(), "no fake check/cleanup: {rest}");
            let result = child.wait_with_output()?;
            anyhow::ensure!(
                !result.status.success() && !result.stderr.is_empty(),
                "{language} {case} must fail: {result:?}"
            );
            std::fs::write(
                directory.join(format!("{language}-subscription-{case}.stdout")),
                transcript,
            )?;
            std::fs::write(
                directory.join(format!("{language}-subscription-{case}.stderr")),
                result.stderr,
            )?;
        }
    }
    assert_eq!(metadata.reads.load(Ordering::SeqCst), 12);
    assert_eq!(metadata.closes.load(Ordering::SeqCst), 2);
    Ok(())
}
