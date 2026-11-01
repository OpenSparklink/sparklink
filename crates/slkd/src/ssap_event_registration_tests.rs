//! Real private bus -> production Owned registration/DB/discovery/owner watches.
//! Ready/Native lease are existing explicit fixtures. Direct event preparation/ACK functions use explicit security receipts; no actual transmission,
//! kernel concurrency, peer receipt, Windows or RF qualification.
use super::*;
use slk_protocol::ssap::discovery::{EntryClass, FindKind, FindRequest, decode_page};

async fn register_events(
    owner: &Connection,
    events: Vec<Vec<u8>>,
) -> zbus::Result<slk_contract::ssap::local::Registration> {
    let proxy = zbus::Proxy::new(
        owner,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await?;
    proxy
        .call(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                Vec::<slk_contract::ssap::local::PropertyDefinition>::new(),
                Vec::<slk_contract::ssap::local::MethodDefinition>::new(),
                events,
                OwnedObjectPath::try_from("/").unwrap(),
                owned_deadline(),
            ),
        )
        .await
}
fn request(start: u16, end: u16, kind: FindKind) -> FindRequest<'static> {
    FindRequest {
        kind,
        class: EntryClass::Mixed,
        start,
        end,
        uuid: None,
    }
}
#[tokio::test]
async fn owned_event_uuid_discovery_rejects_property_method_and_configuration_routes() {
    let (_bus, state, _server, owner, _policy) = setup(true, Duration::ZERO).await;
    let (start, end, handles) = register_events(&owner, vec![vec![4, 0], vec![7; 16]])
        .await
        .unwrap();
    assert_eq!((start, end, handles.as_slice()), (16, 18, &[17, 18][..]));
    let db = store(&state).await;
    for (kind, categories) in [
        (FindKind::Events, vec![4, 12]),
        (FindKind::Structure, vec![0, 4, 12]),
    ] {
        let req = request(start, end, kind);
        let bytes = db.lock().unwrap().find(req, 249).unwrap();
        let page = decode_page(req, 249, &bytes).unwrap();
        assert_eq!(
            page.iter().map(|e| e.category).collect::<Vec<_>>(),
            categories
        );
        for entry in &page {
            assert_eq!(entry.operations, 0);
            assert!(
                entry.descriptors.is_empty(),
                "events cannot invent property CPCD"
            );
        }
        // Structure entries do not carry the Primary member mask.
        assert_eq!(page[0].members, 0);
    }
    let req = request(start, end, FindKind::Primary);
    let bytes = db.lock().unwrap().find(req, 249).unwrap();
    assert_eq!(decode_page(req, 249, &bytes).unwrap()[0].members, 8);
    let uuid = [7; 16];
    let req = FindRequest {
        uuid: Some(&uuid),
        ..request(start, end, FindKind::Events)
    };
    let bytes = db.lock().unwrap().find(req, 249).unwrap();
    let page = decode_page(req, 249, &bytes).unwrap();
    assert_eq!(
        (page.len(), page[0].handle, page[0].uuid.as_slice()),
        (1, 18, &uuid[..])
    );
    let proxy = zbus::Proxy::new(
        &owner,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    assert!(
        proxy
            .call::<_, _, Vec<u8>>("ReadOwnedLocalValue", &(17u16, owned_deadline()))
            .await
            .is_err()
    );
    assert!(
        proxy
            .call::<_, _, ()>(
                "ReplaceOwnedLocalValue",
                &(17u16, vec![3u8], owned_deadline())
            )
            .await
            .is_err()
    );
    assert!(
        proxy
            .call::<_, _, ()>(
                "SetOwnedLocalDescription",
                &(17u16, "no event descriptor", owned_deadline())
            )
            .await
            .is_err()
    );
    for method in [
        "BindOwnedReadProvider",
        "BindOwnedWriteProvider",
        "BindOwnedMethodProvider",
    ] {
        assert!(
            proxy
                .call::<_, _, ()>(
                    method,
                    &(
                        17u16,
                        OwnedObjectPath::try_from("/callback").unwrap(),
                        owned_deadline()
                    )
                )
                .await
                .is_err()
        );
    }
    assert!(db.lock().unwrap().local_read(17).is_err());
    let req = request(17, 18, FindKind::Properties);
    assert_eq!(
        db.lock().unwrap().find(req, 249).unwrap(),
        [1, 0, 4, 17, 0, 11]
    );
    proxy
        .call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
        .await
        .unwrap();
    let req = request(start, end, FindKind::Events);
    assert_eq!(
        db.lock().unwrap().find(req, 249).unwrap(),
        [1, 0, 4, 16, 0, 11]
    );
    let (next, _, _) = register_events(&owner, vec![vec![4, 0]]).await.unwrap();
    assert!(next > end, "removed event handles must not be reused");
}
#[tokio::test]
async fn owned_event_budget_failure_is_atomic_and_owner_exit_preserves_other_service() {
    let (bus, state, _server, owner, _policy) = setup(true, Duration::ZERO).await;
    let db = store(&state).await;
    for events in [
        vec![],
        vec![vec![0, 0]],
        vec![vec![1]],
        vec![vec![4, 0]; 65],
    ] {
        assert!(register_events(&owner, events).await.is_err());
        assert!(db.lock().unwrap().list().is_empty());
    }
    let (first, _, _) = register_events(&owner, vec![vec![4, 0]; 63]).await.unwrap();
    assert_eq!(first, 16, "failed registrations consumed handles");
    let peer = client(&bus).await;
    let (peer_start, peer_handle) = register(&peer, 0).await;
    assert!(
        register_events(&owner, vec![vec![5, 0]]).await.is_err(),
        "events share property/method capacity"
    );
    owner.close().await.unwrap();
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            if db.lock().unwrap().list().len() == 1 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
    let services = db.lock().unwrap().list();
    assert_eq!(services[0].0, peer_start);
    assert_eq!(db.lock().unwrap().local_read(peer_handle).unwrap(), [7]);
    let req = request(first, peer_start - 1, FindKind::Events);
    assert_eq!(
        db.lock().unwrap().find(req, 249).unwrap(),
        [1, 0, 4, 16, 0, 11]
    );
}

#[tokio::test]
async fn owned_event_original_deadline_old_signature_and_mixed_handle_order() {
    let (_bus, state, _server, owner, _policy) = setup(true, Duration::ZERO).await;
    let proxy = zbus::Proxy::new(
        &owner,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let properties = vec![(vec![2u8, 0], 1u32, 0u32, vec![7u8])];
    let methods = vec![(vec![3u8, 0], 0u32)];
    let authorizer = OwnedObjectPath::try_from("/").unwrap();
    let mut expired = owned_deadline();
    expired.0 = 1;
    let error = proxy
        .call::<_, _, slk_contract::ssap::local::Registration>(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                properties.clone(),
                methods.clone(),
                vec![vec![4u8, 0]],
                authorizer.clone(),
                expired,
            ),
        )
        .await
        .unwrap_err();
    assert!(
        matches!(error,zbus::Error::MethodError(ref name,_,_) if name.as_str()=="org.freedesktop.DBus.Error.Timeout")
    );
    let error = proxy
        .call::<_, _, slk_contract::ssap::local::Registration>(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                properties.clone(),
                methods.clone(),
                authorizer.clone(),
                owned_deadline(),
            ),
        )
        .await
        .unwrap_err();
    assert!(
        matches!(error,zbus::Error::MethodError(ref name,Some(ref text),_) if name.as_str()=="org.freedesktop.zbus.Error" && text == "Signature mismatch: got `(aya(ayuuay)a(ayu)o(ttttt))`, expected `(aya(ayuuay)a(ayu)aayo(ttttt))`"),
        "{error:?}"
    );
    let db = store(&state).await;
    assert!(db.lock().unwrap().list().is_empty());
    let receipt: slk_contract::ssap::local::Registration = proxy
        .call(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                properties,
                methods,
                vec![vec![4u8, 0]],
                authorizer,
                owned_deadline(),
            ),
        )
        .await
        .unwrap();
    assert_eq!(receipt, (16, 19, vec![17, 18, 19]));
    let req = request(16, 19, FindKind::Primary);
    let bytes = db.lock().unwrap().find(req, 249).unwrap();
    assert_eq!(decode_page(req, 249, &bytes).unwrap()[0].members, 14);
    let req = request(16, 19, FindKind::Structure);
    let bytes = db.lock().unwrap().find(req, 249).unwrap();
    assert_eq!(
        decode_page(req, 249, &bytes)
            .unwrap()
            .iter()
            .map(|e| (e.handle, e.category))
            .collect::<Vec<_>>(),
        [(16, 0), (17, 2), (18, 3), (19, 4)]
    );
}

// These exercise the actual UpdateSource/UpdateRequest production transitions.
// The receipt is an explicit already-validated Native RX dependency fixture.
#[tokio::test]
async fn owned_event_send_uses_live_owner_payload_budget_and_no_property_cpcd() {
    let (_bus, state, _server, caller, _policy) = setup(true, Duration::ZERO).await;
    let (_, _, handles) = register_events(&caller, vec![vec![4, 0]]).await.unwrap();
    let handle = handles[0];
    let db = store(&state).await;
    let mut configurations = crate::ssap_engine_config::ClientConfigurations::default();
    let name = caller.unique_name().unwrap().as_str();
    for length in [0, 1, 243, 244, 249, 250, 253, 254, 255, 2042] {
        for indication in [false, true] {
            let value = (0..length).map(|i| (i % 251) as u8).collect::<Vec<_>>();
            let source = UpdateSource::Event {
                value: value.clone(),
                minimum: 1,
            };
            let (owner, raw) = source
                .encode(
                    &db.lock().unwrap(),
                    &mut configurations,
                    handle,
                    name,
                    indication,
                    41,
                    2048,
                )
                .unwrap();
            assert!(owner.current());
            let mut expected = vec![if indication { 16 } else { 15 }, 7];
            expected.extend_from_slice(&handle.to_le_bytes());
            expected.extend_from_slice(&(length as u16).to_le_bytes());
            expected.extend_from_slice(&value);
            assert_eq!(raw, expected, "independent event bytes");
            assert_eq!(
                configurations.get(handle, &owner, 41),
                0,
                "must not fabricate a property CPCD"
            );
            assert_eq!(
                source
                    .encode(
                        &db.lock().unwrap(),
                        &mut configurations,
                        handle,
                        name,
                        indication,
                        41,
                        249
                    )
                    .is_ok(),
                length <= 243
            );
        }
    }
    for (value, minimum, target, who) in [
        (vec![0; 2043], 0, handle, name),
        (vec![], 3, handle, name),
        (vec![], 0, 0, name),
        (vec![], 0, handle, ":999.999"),
    ] {
        assert!(
            UpdateSource::Event { value, minimum }
                .encode(
                    &db.lock().unwrap(),
                    &mut configurations,
                    target,
                    who,
                    false,
                    41,
                    2048
                )
                .is_err()
        );
    }
    assert!(
        UpdateSource::Property
            .encode(
                &db.lock().unwrap(),
                &mut configurations,
                handle,
                name,
                false,
                41,
                2048
            )
            .is_err()
    );
    let (owner, pdu) = UpdateSource::Event {
        value: vec![],
        minimum: 0,
    }
    .encode(
        &db.lock().unwrap(),
        &mut configurations,
        handle,
        name,
        true,
        41,
        2048,
    )
    .unwrap();
    let current = UpdateRequest {
        kind: UpdateKind::Event,
        minimum: 0,
        submitted_all: false,
        handle,
        owner,
        mode: 2,
        epoch: 41,
        deadline: Instant::now() + Duration::from_secs(5),
        drain: None,
        pdu,
        reply: None,
    };
    assert!(current.permitted(&db.lock().unwrap(), &mut configurations));
    caller.close().await.unwrap();
    tokio::time::timeout(Duration::from_secs(1), current.owner.withdrawn())
        .await
        .unwrap();
    assert!(!current.permitted(&db.lock().unwrap(), &mut configurations));
}
#[tokio::test]
async fn owned_event_ack_is_kind_epoch_floor_and_original_obligation_bound() {
    let (_bus, state, _server, caller, _policy) = setup(true, Duration::ZERO).await;
    let (_, _, handles) = register_events(&caller, vec![vec![4, 0]]).await.unwrap();
    let db = store(&state).await;
    let owner = db
        .lock()
        .unwrap()
        .owned_event(handles[0], caller.unique_name().unwrap().as_str())
        .unwrap();
    let first = Instant::now();
    for case in [
        "success",
        "refusal",
        "property_ack",
        "old_epoch",
        "below_floor",
        "invalid_security",
        "missing_receipt",
        "partial",
        "late_drain",
        "late_author",
        "closed_author",
    ] {
        let (reply, mut result) = oneshot::channel();
        let mut request = UpdateRequest {
            kind: UpdateKind::Event,
            minimum: 1,
            submitted_all: false,
            handle: handles[0],
            owner: owner.clone(),
            mode: 2,
            epoch: 41,
            deadline: first + Duration::from_secs(1),
            drain: None,
            pdu: vec![16, 7, 17, 0, 0, 0],
            reply: Some(reply),
        };
        request.admit_part(first, case != "partial");
        let mut receipt = Some(slk_protocol::SleMessageSecurity {
            security_epoch: 41,
            security: 1,
            ..Default::default()
        });
        let mut raw = vec![17, 7, 1];
        let mut now = first;
        match case {
            "refusal" => raw[2] = 0,
            "property_ack" => raw[1] = 3,
            "old_epoch" => receipt.as_mut().unwrap().security_epoch = 40,
            "below_floor" => receipt.as_mut().unwrap().security = 0,
            "invalid_security" => receipt.as_mut().unwrap().security = 3,
            "missing_receipt" => receipt = None,
            "late_drain" => now = first + Duration::from_secs(5),
            "late_author" => now = first + Duration::from_secs(2),
            "closed_author" => result.close(),
            _ => {}
        }
        let status = request.acknowledge(&raw, receipt, 249, now);
        match case {
            "success" => {
                status.unwrap();
                let r = result.await.unwrap().unwrap();
                assert_eq!((r.stage, r.acknowledgement), (2, raw));
            }
            "refusal" => {
                status.unwrap();
                assert!(result.await.unwrap().is_err());
            }
            "late_author" | "closed_author" => {
                status.unwrap();
                assert!(
                    result.await.is_err(),
                    "late result must not resurrect author"
                );
            }
            _ => {
                assert!(status.is_err(), "{case}");
                assert!(result.await.is_err());
            }
        }
    }
}
