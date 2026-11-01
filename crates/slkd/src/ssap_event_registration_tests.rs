//! Real private bus -> production Owned registration/DB/discovery/owner watches.
//! Ready/Native lease are existing explicit fixtures. No event transmission,
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
