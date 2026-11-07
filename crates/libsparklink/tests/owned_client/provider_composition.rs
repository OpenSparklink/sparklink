//! Production SDK on real private D-Bus; broker metadata is an explicit fixture.
//! Independent daemon tests cover its real database and callback dispatch.
use super::*;
use libsparklink::{Deadline, ssap::provider::frontend::Dispatcher};
use slk_contract::ssap::{
    ReadProviderReply, ReadProviderRequest, WriteProviderReply, WriteProviderRequest,
};
use std::time::Duration;
fn deadline() -> Deadline {
    Deadline::after(Duration::from_secs(2)).unwrap()
}
#[tokio::test]
async fn original_property_dispatches_read_and_write_to_separate_finite_inboxes()
-> anyhow::Result<()> {
    tokio::time::timeout(Duration::from_secs(8), async {
        for reader_first in [false, true] {
            let bus = support::Bus::start();
            let state = Arc::new(State {
                generation: AtomicU64::new(7),
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
            let mut registration = client
                .controller(BASE)
                .await?
                .local_services()
                .register_service(
                    vec![1, 0],
                    vec![(vec![2, 0], 5, 36, vec![0xab])],
                    "/test/authorizer".try_into()?,
                    deadline(),
                )
                .await?;
            let (reader, writer) = if reader_first {
                let reader = dispatcher.bind(&mut registration, 17, deadline()).await?;
                (
                    reader,
                    dispatcher
                        .bind_write(&mut registration, 17, deadline())
                        .await?,
                )
            } else {
                let writer = dispatcher
                    .bind_write(&mut registration, 17, deadline())
                    .await?;
                (
                    dispatcher.bind(&mut registration, 17, deadline()).await?,
                    writer,
                )
            };
            assert_eq!(
                *state.provider_operations.lock().unwrap(),
                if reader_first {
                    vec!["read", "write"]
                } else {
                    vec!["write", "read"]
                }
            );
            assert!(
                dispatcher
                    .bind(&mut registration, 17, deadline())
                    .await
                    .is_err()
            );
            assert!(
                dispatcher
                    .bind_write(&mut registration, 17, deadline())
                    .await
                    .is_err()
            );
            assert_eq!(
                state.provider_bindings.lock().unwrap().len(),
                2,
                "duplicates must not send RPC"
            );
            let read = ReadProviderRequest {
                request_id: 1,
                identity: (2, 7, 13, 1, 41, 0, 10, 10, 0),
                property: 17,
                deadline_ns: deadline().stamp().monotonic_ns,
                maximum_bytes: 32,
            };
            let write = WriteProviderRequest {
                request_id: 2,
                identity: read.identity,
                property: 17,
                deadline_ns: read.deadline_ns,
                operation: 13,
                data_type: 0,
                offset: 0,
                value: vec![0x47, 0x31],
                verify: true,
            };
            let (r, w) = tokio::join!(
                async {
                    let body = (&read,);
                    let call = daemon.call_method(
                        Some(caller.as_str()),
                        "/org/sparklink/sdk/ssap_read_provider",
                        Some("org.sparklink.SsapReadProvider"),
                        "ReadValue",
                        &body,
                    );
                    let app = async {
                        let request = reader.next().await.unwrap();
                        assert_eq!(request.request().request_id, 1);
                        request.reply(0, &[0x81, 0x19]).unwrap();
                    };
                    let (result, ()) = tokio::join!(call, app);
                    result
                        .unwrap()
                        .body()
                        .deserialize::<ReadProviderReply>()
                        .unwrap()
                },
                async {
                    let body = (&write,);
                    let call = daemon.call_method(
                        Some(caller.as_str()),
                        "/org/sparklink/sdk/ssap_read_provider",
                        Some("org.sparklink.SsapWriteProvider"),
                        "WriteValue",
                        &body,
                    );
                    let app = async {
                        let request = writer.next().await.unwrap();
                        assert_eq!(request.request().request_id, 2);
                        assert_eq!(request.request().value, [0x47, 0x31]);
                        request.reply(0, &[0x47, 0x31]).unwrap();
                    };
                    let (result, ()) = tokio::join!(call, app);
                    result
                        .unwrap()
                        .body()
                        .deserialize::<WriteProviderReply>()
                        .unwrap()
                }
            );
            assert_eq!(r, (0, vec![0x81, 0x19]));
            assert_eq!(w, (0, vec![0x47, 0x31]));
            drop(reader); // Only this callback direction closes.
            let mut write = write;
            write.request_id = 3;
            write.deadline_ns = deadline().stamp().monotonic_ns;
            let body = (&write,);
            let call = daemon.call_method(
                Some(caller.as_str()),
                "/org/sparklink/sdk/ssap_read_provider",
                Some("org.sparklink.SsapWriteProvider"),
                "WriteValue",
                &body,
            );
            let app = async {
                let request = writer.next().await.unwrap();
                request.reply(0, &[0x47, 0x31]).unwrap();
            };
            let (response, ()) = tokio::join!(call, app);
            assert_eq!(
                response?.body().deserialize::<WriteProviderReply>()?,
                (0, vec![0x47, 0x31])
            );
            registration.unregister(deadline()).await?;
            assert_eq!(
                writer.try_next().err().unwrap().raw_os_error(),
                Some(nix::libc::ESHUTDOWN)
            );
        }
        Ok::<(), anyhow::Error>(())
    })
    .await?
}
