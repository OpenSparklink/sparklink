//! Real external C/Python SDK consumers. Private broker metadata is a fixture;
//! callback RPC completion is not Native transmission or RF application delivery.
use super::*;
use slk_contract::ssap::{
    ReadProviderReply, ReadProviderRequest, WriteProviderReply, WriteProviderRequest,
};
use std::{path::Path, time::Duration};

#[expect(
    clippy::too_many_arguments,
    reason = "Explicit existing external consumer build,private bus and metadata dependencies"
)]
pub(super) async fn exercise(
    root: &Path,
    compiler: &str,
    library: &Path,
    runtime_library: &Path,
    directory: &Path,
    address: &str,
    server: &zbus::Connection,
    metadata: &OwnedMetadata,
) -> anyhow::Result<()> {
    let executable = directory.join("provider-composition");
    let source = root.join("crates/libsparklink/tests/fixtures/provider_composition.c");
    let compile = Command::new(compiler)
        .args(["-std=c11", "-Wall", "-Wextra", "-Werror"])
        .arg(&source)
        .arg("-I")
        .arg(root.join("crates/libsparklink/include"))
        .arg(library)
        .arg("-o")
        .arg(&executable)
        .output()?;
    std::fs::write(
        directory.join("provider-composition-compile.log"),
        [compile.stdout.as_slice(), compile.stderr.as_slice()].concat(),
    )?;
    anyhow::ensure!(
        compile.status.success(),
        "C composition consumer compile failed;retained compile log"
    );
    let hashes = Command::new("sha256sum")
        .arg(&source)
        .arg(root.join("crates/libsparklink/tests/fixtures/provider_composition.py"))
        .arg(&executable)
        .arg(runtime_library)
        .output()?;
    anyhow::ensure!(hashes.status.success(), "consumer identities unavailable");
    std::fs::write(
        directory.join("provider-composition-identities.txt"),
        hashes.stdout,
    )?;
    for language in ["c", "python"] {
        for order in ["read", "write"] {
            let binds = metadata.provider_binds.load(Ordering::SeqCst);
            let mut command = Command::new("timeout");
            command.arg("15s");
            if language == "c" {
                command.arg(&executable);
            } else {
                command
                    .arg("python3")
                    .arg(root.join("crates/libsparklink/tests/fixtures/provider_composition.py"));
            }
            let name = format!("composition-{language}-{order}");
            let mut child = command
                .arg(order)
                .env("DBUS_SYSTEM_BUS_ADDRESS", address)
                .env("LIBSPARKLINK_PATH", runtime_library)
                .env("PYTHONPATH", root.join("bindings/python"))
                .env("PYTHONDONTWRITEBYTECODE", "1")
                .env("LD_LIBRARY_PATH", directory)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(std::fs::File::create(
                    directory.join(format!("{name}.stderr")),
                )?)
                .spawn()?;
            let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
            let mut transcript = String::new();
            assert_eq!(
                read_provider::line(&mut reader, &mut transcript)?,
                "COMPOSITION_READY\n"
            );
            assert_eq!(metadata.provider_binds.load(Ordering::SeqCst), binds + 2);
            assert_eq!(metadata.provider_directions.load(Ordering::SeqCst), 3);
            let owner = metadata.owner.lock().unwrap().clone();
            let path = metadata.provider.lock().unwrap().clone();
            let mut expected = vec![0x51, 0xa3];
            for n in 0..4 {
                let deadline = slk_channel::deadline::Deadline::after(Duration::from_secs(2))?
                    .stamp()
                    .monotonic_ns;
                let identity = (2, 7, 13, 1, 41, 0, 10, 10, 0);
                if n % 2 == 0 {
                    let request = ReadProviderRequest {
                        request_id: n + 1,
                        identity,
                        property: 17,
                        deadline_ns: deadline,
                        maximum_bytes: 32,
                    };
                    let reply = server
                        .call_method(
                            Some(owner.as_str()),
                            path.as_str(),
                            Some("org.sparklink.SsapReadProvider"),
                            "ReadValue",
                            &(request,),
                        )
                        .await?
                        .body()
                        .deserialize::<ReadProviderReply>()?;
                    assert_eq!(
                        reply,
                        (0, expected.clone()),
                        "{language}/{order} live application read"
                    );
                } else {
                    expected = if n == 1 {
                        vec![0x47, 0x31]
                    } else {
                        vec![0x29, 0x62]
                    };
                    let request = WriteProviderRequest {
                        request_id: n + 1,
                        identity,
                        property: 17,
                        deadline_ns: deadline,
                        operation: 13,
                        data_type: 0,
                        offset: 0,
                        value: expected.clone(),
                        verify: true,
                    };
                    let reply = server
                        .call_method(
                            Some(owner.as_str()),
                            path.as_str(),
                            Some("org.sparklink.SsapWriteProvider"),
                            "WriteValue",
                            &(request,),
                        )
                        .await?
                        .body()
                        .deserialize::<WriteProviderReply>()?;
                    assert_eq!(
                        reply,
                        (0, expected.clone()),
                        "{language}/{order} actual accepted application value"
                    );
                }
                if n == 2 {
                    // Final reply must reach the actual callback consumer before
                    // closing that inbox. Local reply acceptance is not drain.
                    child.stdin.as_mut().unwrap().write_all(b"CLOSE_READ\n")?;
                    child.stdin.as_mut().unwrap().flush()?;
                    assert_eq!(
                        read_provider::line(&mut reader, &mut transcript)?,
                        "READ_CLOSED\n"
                    );
                }
            }
            child.stdin.as_mut().unwrap().write_all(b"UNREGISTER\n")?;
            child.stdin.as_mut().unwrap().flush()?;
            assert_eq!(
                read_provider::line(&mut reader, &mut transcript)?,
                "COMPOSITION_COMPLETE\n"
            );
            std::fs::write(directory.join(format!("{name}.stdout")), transcript)?;
            anyhow::ensure!(
                child.wait()?.success(),
                "{name} consumer failed;retained stderr"
            );
        }
    }
    Ok(())
}
