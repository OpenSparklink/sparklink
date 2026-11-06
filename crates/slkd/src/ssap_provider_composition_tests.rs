//! Actual manager/DB/Owner callbacks/Engine transitions on a private D-Bus.
//! Native receipt, transport and security remain the existing explicit fixture;
//! no RF, kernel concurrency or rollback qualification is implied.
use super::*;
use write_provider_tests::{bind_writer, finish, wire};

#[tokio::test]
async fn read_write_providers_work_in_both_orders_without_staging_or_wrong_direction_fallback() {
    for operations in [3, 5, 7] {
        for reader_first in [false, true] {
            let mut f = Fixture::new().await;
            let (_, h) = register_operations(&f.owner, 0, operations).await;
            let db = store(&f.state).await;
            let wire = wire();
            if reader_first {
                bind(&f.owner, h, "/provider").await.unwrap();
                let command = operations == 3;
                let missing = resolve_server(
                    write_provider_tests::write(h, command, false, 1),
                    db.clone(),
                    wire.clone(),
                )
                .await;
                if command {
                    assert!(finish(&wire, missing, &db).unwrap().is_none());
                } else {
                    assert_eq!(
                        finish(&wire, missing, &db).unwrap().unwrap().bytes,
                        [14, 7, 1, h as u8, (h >> 8) as u8, 0xaf]
                    );
                }
                assert!(f.calls.try_recv().is_err());
                assert!(f.write_calls.try_recv().is_err());
                bind_writer(&f.owner, h, "/writer").await.unwrap();
            } else {
                bind_writer(&f.owner, h, "/writer").await.unwrap();
                let missing = resolve_server(read(h, 1, 0), db.clone(), wire.clone()).await;
                assert_eq!(resolved(&missing, &db), [9, 11, 0xaf, 0]);
                assert!(f.calls.try_recv().is_err());
                assert!(f.write_calls.try_recv().is_err());
                bind(&f.owner, h, "/provider").await.unwrap();
            }
            for result in [
                bind(&f.owner, h, "/wrong").await,
                bind_writer(&f.owner, h, "/wrong_writer").await,
            ] {
                refusal(result, "org.freedesktop.DBus.Error.NotSupported");
            }
            let stranger = client(&f.bus).await;
            refusal(
                bind(&stranger, h, "/provider").await,
                "org.freedesktop.DBus.Error.AccessDenied",
            );
            refusal(
                bind_writer(&stranger, h, "/writer").await,
                "org.freedesktop.DBus.Error.AccessDenied",
            );
            let mut application_value = vec![0x51, 0xa3];
            for (id, writing) in [(2, false), (3, true), (4, false)] {
                let command = operations == 3;
                let packet = if writing {
                    write_provider_tests::write(h, command, !command, id)
                } else {
                    read(h, id, 0)
                };
                let original = packet.constraint.unwrap();
                let task = tokio::spawn(resolve_server(packet, db.clone(), wire.clone()));
                if writing {
                    let call = write_provider_tests::next(&mut f).await;
                    assert_eq!(call.request.property, h);
                    assert_eq!(call.request.deadline_ns, original.deadline_monotonic_ns);
                    assert_eq!(call.request.operation, if command { 12 } else { 13 });
                    application_value = call.request.value.clone(); // Actual application effect before reply.
                    call.reply
                        .send((
                            0,
                            if command {
                                vec![]
                            } else {
                                application_value.clone()
                            },
                        ))
                        .unwrap();
                    assert!(f.calls.try_recv().is_err());
                    let response = finish(&wire, task.await.unwrap(), &db).unwrap();
                    if command {
                        assert!(response.is_none());
                    } else {
                        assert_eq!(
                            ValuePdu::decode(249, &response.unwrap().bytes).unwrap(),
                            ValuePdu::WrittenValue {
                                handle: h,
                                data_type: 0,
                                value: &application_value
                            }
                        );
                    }
                } else {
                    let call = f.next().await;
                    assert_eq!(call.request.property, h);
                    assert_eq!(call.request.deadline_ns, original.deadline_monotonic_ns);
                    call.reply.send((0, application_value.clone())).unwrap();
                    assert!(f.write_calls.try_recv().is_err());
                    assert_eq!(
                        ValuePdu::decode(249, &resolved(&task.await.unwrap(), &db)).unwrap(),
                        ValuePdu::ReadValue(&application_value)
                    );
                }
                assert_eq!(
                    db.lock().unwrap().local_read(h),
                    Err(crate::ssap_database::LocalValueError::Unsupported)
                );
            }
            // Combining callbacks never grants a missing wire operation bit.
            if operations != 7 {
                let command = operations == 5;
                let missing = resolve_server(
                    write_provider_tests::write(h, command, false, 5),
                    db.clone(),
                    wire.clone(),
                )
                .await;
                let result = finish(&wire, missing, &db).unwrap();
                if command {
                    assert!(result.is_none());
                } else {
                    assert_eq!(
                        result.unwrap().bytes,
                        [14, 7, 1, h as u8, (h >> 8) as u8, 7]
                    );
                }
                assert!(f.write_calls.try_recv().is_err());
            } else {
                let task = tokio::spawn(resolve_server(
                    write_provider_tests::write(h, true, false, 5),
                    db.clone(),
                    wire.clone(),
                ));
                write_provider_tests::next(&mut f)
                    .await
                    .reply
                    .send((0, vec![]))
                    .unwrap();
                assert!(finish(&wire, task.await.unwrap(), &db).unwrap().is_none());
            }
        }
    }
}

#[tokio::test]
async fn pending_either_direction_cannot_outlive_original_deadline_or_registration() {
    for writing in [false, true] {
        for remove in [false, true] {
            let mut f = Fixture::new().await;
            let (start, h) = register_operations(&f.owner, 0, 5).await;
            bind(&f.owner, h, "/provider").await.unwrap();
            bind_writer(&f.owner, h, "/writer").await.unwrap();
            let (_, sibling) = register_operations(&f.owner, 0, 5).await;
            bind(&f.owner, sibling, "/provider").await.unwrap();
            bind_writer(&f.owner, sibling, "/writer").await.unwrap();
            let db = store(&f.state).await;
            let wire = wire();
            let mut packet = if writing {
                write_provider_tests::write(h, false, false, 1)
            } else {
                read(h, 1, 0)
            };
            if !remove {
                packet.deadline = Instant::now() + Duration::from_millis(100);
                packet.constraint.as_mut().unwrap().deadline_monotonic_ns =
                    monotonic_deadline(packet.deadline).unwrap();
            }
            let task = tokio::spawn(resolve_server(packet, db.clone(), wire.clone()));
            let late: Box<dyn FnOnce()> = if writing {
                let call = write_provider_tests::next(&mut f).await;
                Box::new(move || {
                    let _ = call.reply.send((0, vec![]));
                })
            } else {
                let call = f.next().await;
                Box::new(move || {
                    let _ = call.reply.send((0, vec![9]));
                })
            };
            if remove {
                manager(&f.owner)
                    .await
                    .call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
                    .await
                    .unwrap();
            }
            let decision = tokio::time::timeout(Duration::from_secs(1), task)
                .await
                .unwrap()
                .unwrap();
            late();
            let result = finish(&wire, decision, &db);
            if remove {
                assert_eq!(
                    result.unwrap().unwrap().bytes,
                    if writing {
                        vec![14, 7, 1, h as u8, (h >> 8) as u8, 4]
                    } else {
                        vec![9, 11, 4, 0]
                    }
                );
            } else {
                assert_eq!(result.err().unwrap().kind(), io::ErrorKind::TimedOut);
            }
            // Removal/expiry of this obligation cannot retire another service.
            let next = tokio::spawn(resolve_server(
                read(sibling, 2, 0),
                db.clone(),
                wire.clone(),
            ));
            f.next().await.reply.send((0, vec![0x71, 0x82])).unwrap();
            assert_eq!(resolved(&next.await.unwrap(), &db), [9, 3, 0x71, 0x82]);
        }
    }
}
