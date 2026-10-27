//! Actual slctl binary and SDK on a private bus; controller metadata is a
//! fixture. No Native, daemon protocol Engine, wire or hardware qualification.
use super::*;
use slk_contract::ssap::{MethodProviderReply, MethodProviderRequest, SsapAuthorizationPrompt};
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, BufReader};

async fn line(
    reader: &mut BufReader<tokio::process::ChildStdout>,
    prefix: &str,
) -> anyhow::Result<String> {
    loop {
        let mut value = String::new();
        let count =
            tokio::time::timeout(Duration::from_secs(3), reader.read_line(&mut value)).await??;
        anyhow::ensure!(count != 0, "CLI EOF before {prefix}");
        if value.starts_with(prefix) {
            return Ok(value);
        }
    }
}
fn token(prompt: &str) -> &str {
    prompt
        .split("token=")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap()
}
fn deadline() -> u64 {
    libsparklink::Deadline::after(Duration::from_secs(2))
        .unwrap()
        .stamp()
        .monotonic_ns
}

#[tokio::test]
async fn actual_method_cli_preserves_explicit_policy_independent_result_and_original_expiry()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = Arc::new(Mutex::new(State::default()));
    let server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter)?
        .serve_at(format!("{BASE}/services"), Services(state.clone()))?
        .build()
        .await?;
    let mut child = Command::new(env!("CARGO_BIN_EXE_slctl"))
        .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
        .args([
            "--session",
            "--adapter",
            BASE,
            "ssap-serve-method",
            "0400",
            "0300",
            "4",
            "ask",
        ])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()?;
    let mut reader = BufReader::new(child.stdout.take().unwrap());
    assert!(
        line(&mut reader, "SsapOwnedMethod:")
            .await?
            .contains("method=17")
    );
    let stdin = child.stdin.as_mut().unwrap();
    stdin.write_all(b"provider\n").await?;
    line(&mut reader, "SsapMethodProviderBound:").await?;
    let (owner, authorizer, provider) = {
        let s = state.lock().unwrap();
        (s.owner.clone(), s.authorizer.clone(), s.provider.clone())
    };
    // An independent literal signature check does not share the generated type.
    let xml: String = server
        .call_method(
            Some(owner.as_str()),
            provider.as_str(),
            Some("org.freedesktop.DBus.Introspectable"),
            "Introspect",
            &(),
        )
        .await?
        .body()
        .deserialize()?;
    assert!(xml.contains("(t(qttqtuyyy)qtyayq)") && xml.contains("(yay)"));
    let mut prompt: SsapAuthorizationPrompt = (
        1,
        (0, 7, 13, 1, 41, 0, 10, 10, 0),
        17,
        true,
        deadline(),
        vec![0x31; 2043],
        0,
    );
    let denied: bool = server
        .call_method(
            Some(owner.as_str()),
            authorizer.as_str(),
            Some("org.sparklink.SsapAuthorizer"),
            "AuthorizeValue",
            &(prompt.clone(),),
        )
        .await?
        .body()
        .deserialize()?;
    assert!(!denied, "property prompt cannot authorize a method");
    prompt.6 = 3;
    let (bus_call, target, path) = (server.clone(), owner.clone(), authorizer.clone());
    let approval = tokio::spawn(async move {
        bus_call
            .call_method(
                Some(target.as_str()),
                path.as_str(),
                Some("org.sparklink.SsapAuthorizer"),
                "AuthorizeValue",
                &(prompt,),
            )
            .await?
            .body()
            .deserialize::<bool>()
    });
    let observed = line(&mut reader, "SsapAuthorizationPrompt:").await?;
    assert!(observed.contains("data_type=3") && observed.contains("bytes=2043"));
    assert!(!approval.is_finished());
    stdin
        .write_all(format!("yes {}\n", token(&observed)).as_bytes())
        .await?;
    line(&mut reader, "SsapAuthorizationDecision:").await?;
    assert!(approval.await??);
    for n in 0..4 {
        let original = if n == 2 {
            libsparklink::Deadline::after(Duration::from_millis(350))?
                .stamp()
                .monotonic_ns
        } else {
            deadline()
        };
        let request = MethodProviderRequest {
            request_id: 10 + n,
            identity: (0, 7, 13, 1, 41, 0, 10, 10, 0),
            method: 17,
            deadline_ns: original,
            operation: if n == 1 { 18 } else { 19 },
            arguments: vec![0x31; 2043],
            maximum_result_bytes: if n == 1 { 0 } else { 2045 },
        };
        let (bus_call, target, path) = (server.clone(), owner.clone(), provider.clone());
        let call = tokio::spawn(async move {
            bus_call
                .call_method(
                    Some(target.as_str()),
                    path.as_str(),
                    Some("org.sparklink.SsapMethodProvider"),
                    "CallMethod",
                    &(request,),
                )
                .await?
                .body()
                .deserialize::<MethodProviderReply>()
        });
        let observed = line(&mut reader, "SsapMethodProviderPrompt:").await?;
        assert!(observed.contains(&format!("arguments={}", "31".repeat(2043))));
        assert!(observed.contains(&format!("deadline_ns={original}")));
        let id = token(&observed);
        if n < 2 {
            stdin
                .write_all(
                    format!(
                        "provide {id} {}\n",
                        "ab".repeat(if n == 0 { 2046 } else { 1 })
                    )
                    .as_bytes(),
                )
                .await?;
            line(&mut reader, "SsapMethodProviderInput:").await?;
            assert!(
                !call.is_finished(),
                "invalid UI input cannot answer the callback"
            );
            stdin
                .write_all(
                    format!(
                        "provide {id} {}\n",
                        if n == 0 {
                            "a6".repeat(2045)
                        } else {
                            "-".into()
                        }
                    )
                    .as_bytes(),
                )
                .await?;
            line(&mut reader, "SsapMethodProviderResult:").await?;
            assert_eq!(
                call.await??,
                (0, if n == 0 { vec![0xa6; 2045] } else { vec![] })
            );
        } else if n == 2 {
            assert_eq!(call.await??, (0xaf, vec![]));
            stdin
                .write_all(format!("provide {id} -\n").as_bytes())
                .await?;
            line(&mut reader, "SsapMethodProviderInput:").await?;
        } else {
            assert!(!call.is_finished());
            stdin.write_all(b"quit\n").await?;
            assert_eq!(call.await??, (0xaf, vec![]));
        }
    }
    let output = tokio::time::timeout(Duration::from_secs(3), child.wait_with_output()).await??;
    anyhow::ensure!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(state.lock().unwrap().removed);
    assert_eq!(state.lock().unwrap().reads, 0);
    Ok(())
}
