//! Actual private D-Bus / production SDK dispatch. The manager supplies explicit
//! metadata only: no Native, Session, RF, daemon Engine or application effect is
//! simulated as qualified. Daemon production method tests cover its own boundary.
use super::*;
use libsparklink::{Deadline, ssap::provider::frontend::Dispatcher};
use slk_contract::ssap::{MethodProviderReply, MethodProviderRequest};
use std::time::Duration;

fn deadline() -> Deadline {
    Deadline::after(Duration::from_secs(2)).unwrap()
}
fn request() -> MethodProviderRequest {
    MethodProviderRequest {
        request_id: 7,
        identity: (2, 7, 13, 1, 41, 0, 10, 10, 0),
        method: 18,
        deadline_ns: deadline().stamp().monotonic_ns,
        operation: 19,
        arguments: vec![1, 9, 2],
        maximum_result_bytes: 2045,
    }
}
async fn callback(
    bus: &Connection,
    caller: &str,
    r: &MethodProviderRequest,
) -> zbus::Result<MethodProviderReply> {
    bus.call_method(
        Some(caller),
        "/org/sparklink/sdk/ssap_read_provider",
        Some("org.sparklink.SsapMethodProvider"),
        "CallMethod",
        &(r,),
    )
    .await?
    .body()
    .deserialize()
}

#[tokio::test]
async fn method_uses_original_registration_and_shared_inbox_for_independent_results()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = Arc::new(State {
        generation: AtomicU64::new(7),
        read_only_property: AtomicBool::new(true),
        method_entry: AtomicBool::new(true),
        ..Default::default()
    });
    let daemon = fixture(&bus, state.clone()).await;
    let connection = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    let caller = connection.unique_name().unwrap().to_string();
    let client = Client::from_connection(connection).await?;
    let dispatcher = Dispatcher::install(&client).await?;
    let _watch = dispatcher.watch();
    let local = client.controller(BASE).await?.local_services();
    let mut registration = local
        .register_entries(
            vec![1, 0],
            vec![(vec![2, 0], 1, 32, vec![0xab])],
            vec![(vec![3, 0], 4)],
            "/test/authorizer".try_into()?,
            deadline(),
        )
        .await?;
    assert_eq!(registration.receipt(), &(16, 18, vec![17, 18]));
    assert!(registration.read_local(18, deadline()).await.is_err());
    assert!(
        registration
            .replace_local(18, vec![1], deadline())
            .await
            .is_err()
    );
    assert!(
        registration
            .set_description(18, "method".into(), deadline())
            .await
            .is_err()
    );
    assert!(
        dispatcher
            .bind_method(&mut registration, 17, deadline())
            .await
            .is_err()
    );
    assert!(
        dispatcher
            .bind(&mut registration, 18, deadline())
            .await
            .is_err()
    );
    assert!(
        dispatcher
            .bind_write(&mut registration, 18, deadline())
            .await
            .is_err()
    );
    assert!(state.provider_bindings.lock().unwrap().is_empty());
    let inbox = dispatcher
        .bind_method(&mut registration, 18, deadline())
        .await?;
    let reads = dispatcher.bind(&mut registration, 17, deadline()).await?;
    assert!(
        dispatcher
            .bind_method(&mut registration, 18, deadline())
            .await
            .is_err()
    );
    let foreign = zbus::connection::Builder::address(bus.address.as_str())?
        .build()
        .await?;
    assert!(callback(&foreign, &caller, &request()).await.is_err());
    for case in 0..16 {
        let mut r = request();
        match case {
            0 => r.request_id = 0,
            1 => r.method = 17,
            2 => r.identity.1 += 1,
            3 => r.identity.2 = 0,
            4 => r.identity.3 = 0x1000,
            5 => r.identity.4 = 0,
            6 => r.identity.5 = 3,
            7 => r.identity.6 = 11,
            8 => r.identity.7 = 11,
            9 => r.identity.8 = 1,
            10 => r.deadline_ns = 1,
            11 => r.arguments = vec![0; 2044],
            12 => r.maximum_result_bytes = 2046,
            13 => r.operation = 20,
            14 => r.operation = 18, // command must advertise no result budget
            _ => {
                r.deadline_ns = Deadline::after(Duration::from_secs(6))?
                    .stamp()
                    .monotonic_ns
            }
        }
        assert_eq!(
            callback(&daemon, &caller, &r).await?,
            (0xaf, vec![]),
            "case {case}"
        );
        assert!(inbox.try_next().is_err());
    }
    for (operation, maximum, result, status) in [
        (19, 4, vec![8, 7, 6, 5], 0),
        (19, 2045, vec![0xa5; 2045], 0),
        (19, 0, vec![], 0xff),
        (18, 0, vec![], 0),
    ] {
        let mut r = request();
        r.operation = operation;
        r.maximum_result_bytes = maximum;
        r.arguments = vec![0x31; 2043];
        let invoke = callback(&daemon, &caller, &r);
        let consume = async {
            let received = tokio::time::timeout(Duration::from_secs(3), inbox.next()).await??;
            assert_eq!(received.request(), &r);
            assert!(received.is_active());
            assert!(
                received
                    .reply(0, &vec![0; usize::from(maximum) + 1])
                    .is_err()
            );
            assert!(received.reply(1, &[]).is_err());
            assert!(received.reply(0xaf, &[1]).is_err());
            received.reply(status, &result)?;
            assert!(received.reply(status, &result).is_err());
            Ok::<_, anyhow::Error>(())
        };
        let (actual, consumed) = tokio::join!(invoke, consume);
        consumed?;
        assert_eq!(actual?, (status as u8, result));
    }
    // Method command's empty local reply is a callback result, not a wire ACK.
    // The independent READ inbox still serves on the same original dispatcher.
    let read = slk_contract::ssap::ReadProviderRequest {
        request_id: 9,
        identity: request().identity,
        property: 17,
        deadline_ns: deadline().stamp().monotonic_ns,
        maximum_bytes: 2,
    };
    let (actual, consumed) = tokio::join!(
        dispatcher.dispatch(read.clone(), Some(daemon.unique_name().unwrap().as_str())),
        async {
            let received = tokio::time::timeout(Duration::from_secs(3), reads.next()).await??;
            assert_eq!(received.request(), &read);
            received.reply(0, &[4, 3])
        }
    );
    consumed?;
    assert_eq!(actual?.into_reply(), (0, vec![4, 3]));

    // Once the actual request is observed, withdrawal closes pending authority.
    let r = request();
    let (actual, consumed) = tokio::join!(callback(&daemon, &caller, &r), async {
        let received = tokio::time::timeout(Duration::from_secs(3), inbox.next()).await??;
        registration.unregister(deadline()).await?;
        assert!(!received.is_active());
        assert!(received.reply(0, &[1]).is_err());
        Ok::<_, anyhow::Error>(())
    });
    consumed?;
    assert_eq!(actual?, (0xaf, vec![]));
    assert_eq!(state.removals.load(Ordering::SeqCst), 1);
    assert!(inbox.try_next().is_err());
    assert!(reads.try_next().is_err());
    Ok(())
}

#[tokio::test]
async fn method_original_deadline_and_owner_loss_revoke_held_reply() -> anyhow::Result<()> {
    for owner_loss in [false, true] {
        let bus = support::Bus::start();
        let state = Arc::new(State {
            generation: AtomicU64::new(7),
            method_entry: AtomicBool::new(true),
            ..Default::default()
        });
        let daemon = fixture(&bus, state).await;
        let connection = zbus::connection::Builder::address(bus.address.as_str())?
            .build()
            .await?;
        let caller = connection.unique_name().unwrap().to_string();
        let client = Client::from_connection(connection).await?;
        let dispatcher = Dispatcher::install(&client).await?;
        let _watch = dispatcher.watch();
        let mut registration = client
            .controller(BASE)
            .await?
            .local_services()
            .register_entries(
                vec![1, 0],
                vec![(vec![2, 0], 5, 36, vec![0xab])],
                vec![(vec![3, 0], 4)],
                "/test/authorizer".try_into()?,
                deadline(),
            )
            .await?;
        let inbox = dispatcher
            .bind_method(&mut registration, 18, deadline())
            .await?;
        let mut r = request();
        let original = Deadline::after(Duration::from_millis(300))?;
        r.deadline_ns = original.stamp().monotonic_ns;
        let (actual, consumed) = tokio::join!(callback(&daemon, &caller, &r), async {
            let received = tokio::time::timeout(Duration::from_secs(3), inbox.next()).await??;
            if owner_loss {
                daemon.release_name("org.sparklink").await?;
                tokio::time::timeout(Duration::from_secs(1), async {
                    while received.is_active() {
                        tokio::task::yield_now().await;
                    }
                })
                .await?;
            } else {
                tokio::time::sleep_until(original.instant().into()).await;
            }
            assert!(!received.is_active());
            assert!(received.reply(0, &[7]).is_err());
            Ok::<_, anyhow::Error>(())
        });
        consumed?;
        assert_eq!(actual?, (0xaf, vec![]));
    }
    Ok(())
}

struct ForeignMethod;
#[zbus::interface(name = "org.sparklink.SsapMethodProvider")]
impl ForeignMethod {
    fn marker(&self) -> bool {
        true
    }
}
#[tokio::test]
async fn occupied_method_endpoint_preserves_foreign_interface_and_removes_partial_install()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let state = Arc::new(State {
        generation: AtomicU64::new(7),
        ..Default::default()
    });
    let daemon = fixture(&bus, state).await;
    let path = "/org/sparklink/sdk/ssap_read_provider";
    let connection = zbus::connection::Builder::address(bus.address.as_str())?
        .serve_at(path, ForeignMethod)?
        .build()
        .await?;
    let client = Client::from_connection(connection.clone()).await?;
    assert!(Dispatcher::install(&client).await.is_err());
    let proxy = zbus::fdo::IntrospectableProxy::builder(&daemon)
        .destination(connection.unique_name().unwrap().as_str())?
        .path(path)?
        .build()
        .await?;
    let xml = proxy.introspect().await?;
    assert!(xml.contains("org.sparklink.SsapMethodProvider"));
    assert!(!xml.contains("org.sparklink.SsapReadProvider"));
    assert!(!xml.contains("org.sparklink.SsapWriteProvider"));
    connection
        .object_server()
        .remove::<ForeignMethod, _>(path)
        .await?;
    let dispatcher = Dispatcher::install(&client).await?;
    let _watch = dispatcher.watch();
    let xml = proxy.introspect().await?;
    for name in [
        "SsapReadProvider",
        "SsapWriteProvider",
        "SsapMethodProvider",
    ] {
        assert!(xml.contains(name));
    }
    // Independent literal method signature, not derived from the shared type.
    let method = xml
        .split("<interface name=\"org.sparklink.SsapMethodProvider\">")
        .nth(1)
        .unwrap()
        .split("</interface>")
        .next()
        .unwrap();
    assert!(method.contains("type=\"(t(qttqtuyyy)qtyayq)\""));
    assert!(method.contains("type=\"(yay)\""));
    Ok(())
}

#[test]
fn method_policy_reuses_permissions_without_property_target_or_payload_limits() {
    use libsparklink::ssap::authorization::{MethodAuthorizationContext, admit_method};
    use slk_protocol::ssap::access::MethodAccess;
    for bits in 0..=7 {
        for level in 0..=3 {
            let access = MethodAccess::from_bits(bits).unwrap();
            let context = MethodAuthorizationContext {
                daemon_owner: ":1.12",
                owner_lost: false,
                controller: slk_contract::ControllerId {
                    index: 2,
                    generation: 7,
                },
                method: Some(18),
                access,
            };
            let mut r = request();
            r.identity.5 = level;
            let mut p = (7, r.identity, 18, true, r.deadline_ns, vec![1; 2043], 3);
            assert_eq!(
                admit_method(&context, Some(":1.12"), &p).unwrap().is_some(),
                access.check(level, true).is_ok()
            );
            assert!(admit_method(&context, Some(":1.13"), &p).is_err());
            for target in [0, 1, 2, 4] {
                p.6 = target;
                assert!(admit_method(&context, Some(":1.12"), &p).unwrap().is_none());
            }
            p.6 = 3;
            p.5.push(0);
            assert!(admit_method(&context, Some(":1.12"), &p).unwrap().is_none());
        }
    }
}
