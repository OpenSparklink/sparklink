//! Application-side admission and bounded replies for dynamic type0 reads.
//! These helpers own no registration, protocol Engine or security authority.
pub mod frontend;
use super::authorization::{self, AuthorizationContext};
use slk_contract::ssap::{
    MAX_PROVIDER_VALUE_BYTES, PROVIDER_UNAVAILABLE, ReadProviderReply, ReadProviderRequest,
};
use slk_protocol::SsapOperations;
use std::time::Instant;
use tokio::sync::{oneshot, watch};

/// Check the original daemon, read context and value budget before dispatch.
/// Admission is not local approval. The caller must retain the original
/// deadline and re-run this check with a fresh snapshot before returning a value.
pub fn admit(
    context: &AuthorizationContext<'_>,
    sender: Option<&str>,
    request: &ReadProviderRequest,
) -> zbus::fdo::Result<Option<Instant>> {
    let original = authorization::admit(
        context,
        sender,
        &(
            request.request_id,
            request.identity,
            request.property,
            false,
            request.deadline_ns,
            Vec::new(),
            0,
        ),
    )?;
    if request.property == 0
        || request.identity.1 == 0
        || request.identity.3 > 0x0fff
        || context.operations != SsapOperations::READ
        || usize::from(request.maximum_bytes) > MAX_PROVIDER_VALUE_BYTES
    {
        return Ok(None);
    }
    Ok(original)
}

/// Await the actual value/error reply using the original scope and deadline.
/// Status0 permits an empty value; application errors require an empty value.
/// Malformed, late, lost or closed replies become the stable application error.
/// The caller retains its finite queue/permit and must re-run `admit` afterwards.
pub async fn await_reply(
    result: oneshot::Receiver<ReadProviderReply>,
    lost: watch::Receiver<bool>,
    original: Instant,
    maximum_bytes: u16,
) -> ReadProviderReply {
    if usize::from(maximum_bytes) > MAX_PROVIDER_VALUE_BYTES {
        return (PROVIDER_UNAVAILABLE, Vec::new());
    }
    authorization::await_reply(result, lost, original)
        .await
        .filter(|(status, value)| {
            if *status == 0 {
                value.len() <= usize::from(maximum_bytes)
            } else {
                (0xaf..=0xff).contains(status) && value.is_empty()
            }
        })
        .unwrap_or_else(|| (PROVIDER_UNAVAILABLE, Vec::new()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use slk_contract::ControllerId;
    use slk_protocol::ssap::access::SsapAccess;
    use std::time::Duration;

    fn context() -> AuthorizationContext<'static> {
        AuthorizationContext {
            daemon_owner: ":1.10",
            owner_lost: false,
            controller: ControllerId {
                index: 0,
                generation: 7,
            },
            property: Some(17),
            operations: SsapOperations::READ,
            access: SsapAccess::from_bits(32).unwrap(),
        }
    }

    fn request() -> ReadProviderRequest {
        ReadProviderRequest {
            request_id: 1,
            identity: (0, 7, 13, 1, 41, 0, 10, 10, 0),
            property: 17,
            deadline_ns: crate::Deadline::after(Duration::from_secs(1))
                .unwrap()
                .stamp()
                .monotonic_ns,
            maximum_bytes: 2042,
        }
    }

    #[test]
    fn admission_requires_original_sender_context_deadline_and_budget() {
        let c = context();
        let r = request();
        let original = admit(&c, Some(":1.10"), &r).unwrap().unwrap();
        assert!(original > Instant::now());
        assert!(original <= Instant::now() + Duration::from_secs(1));
        for sender in [None, Some(":1.11"), Some("org.sparklink")] {
            assert!(matches!(
                admit(&c, sender, &r),
                Err(zbus::fdo::Error::AccessDenied(_))
            ));
        }
        for case in 0..15 {
            let mut r = request();
            match case {
                0 => r.request_id = 0,
                1 => r.identity.0 += 1,
                2 => r.identity.1 += 1,
                3 => r.identity.2 = 0,
                4 => r.identity.4 = 0,
                5 => r.identity.5 = 3,
                6 => r.identity.6 = 11,
                7 => r.identity.7 = 11,
                8 => r.identity.8 = 1,
                9 => r.property += 1,
                10 => r.deadline_ns = 0,
                11 => r.deadline_ns = 1,
                12 => r.deadline_ns = u64::MAX,
                13 => {
                    r.deadline_ns = crate::Deadline::after(Duration::from_secs(6))
                        .unwrap()
                        .stamp()
                        .monotonic_ns
                }
                _ => r.maximum_bytes = 2043,
            }
            assert!(
                admit(&c, Some(":1.10"), &r).unwrap().is_none(),
                "case {case}"
            );
        }
        for property in [None, Some(18)] {
            let mut c = context();
            c.property = property;
            assert!(admit(&c, Some(":1.10"), &r).unwrap().is_none());
        }
        let mut c = context();
        c.owner_lost = true;
        assert!(admit(&c, Some(":1.10"), &r).unwrap().is_none());
        for maximum_bytes in [0, 1, 2042] {
            let mut r = request();
            r.maximum_bytes = maximum_bytes;
            assert!(admit(&context(), Some(":1.10"), &r).unwrap().is_some());
        }
    }

    #[test]
    fn property_generation_and_connection_handle_have_explicit_bounds() {
        for case in 0..3 {
            let mut c = context();
            let mut r = request();
            match case {
                0 => {
                    c.property = Some(0);
                    r.property = 0;
                }
                1 => {
                    c.controller.generation = 0;
                    r.identity.1 = 0;
                }
                _ => r.identity.3 = 0x1000,
            }
            assert!(admit(&c, Some(":1.10"), &r).unwrap().is_none());
        }
        for handle in [0, 0x0fff] {
            let mut r = request();
            r.identity.3 = handle;
            assert!(admit(&context(), Some(":1.10"), &r).unwrap().is_some());
        }
    }

    #[test]
    fn admission_requires_exactly_read_and_preserves_security_requirements() {
        for bits in 0..=SsapOperations::VALID_MASK {
            let Ok(operations) = SsapOperations::from_bits(bits) else {
                continue;
            };
            let mut c = context();
            c.operations = operations;
            assert_eq!(
                admit(&c, Some(":1.10"), &request()).unwrap().is_some(),
                operations == SsapOperations::READ,
                "operations {bits}"
            );
        }
        for bits in 0..=63 {
            for level in 0..=3 {
                let mut c = context();
                c.access = SsapAccess::from_bits(bits).unwrap();
                let mut r = request();
                r.identity.5 = level;
                assert_eq!(
                    admit(&c, Some(":1.10"), &r).unwrap().is_some(),
                    c.access
                        .check_authorization_result(level, false, true)
                        .is_ok(),
                    "access {bits}, level {level}"
                );
            }
        }
        // Provider admission cannot supply the separate owner approval.
        assert_eq!(context().access.check(0, false), Err(9));
    }

    async fn ready(reply: ReadProviderReply, maximum_bytes: u16) -> ReadProviderReply {
        let (_owner, lost) = watch::channel(false);
        let (sender, result) = oneshot::channel();
        sender.send(reply).unwrap();
        await_reply(
            result,
            lost,
            Instant::now() + Duration::from_secs(1),
            maximum_bytes,
        )
        .await
    }

    #[tokio::test]
    async fn actual_reply_preserves_empty_success_values_and_application_errors() {
        for (value, maximum_bytes) in [(vec![], 0), (vec![1, 2], 2), (vec![7; 2042], 2042)] {
            assert_eq!(ready((0, value.clone()), maximum_bytes).await, (0, value));
        }
        for status in 0xaf..=0xff {
            assert_eq!(ready((status, vec![]), 0).await, (status, vec![]));
        }
        for (reply, maximum_bytes) in [
            ((0, vec![1]), 0),
            ((0, vec![7; 2043]), 2042),
            ((0, vec![]), 2043),
            ((1, vec![]), 2042),
            ((9, vec![]), 2042),
            ((0xae, vec![]), 2042),
            ((0x100, vec![]), 2042),
            ((u16::MAX, vec![]), 2042),
            ((0xaf, vec![1]), 2042),
            ((0xff, vec![1]), 2042),
        ] {
            assert_eq!(
                ready(reply, maximum_bytes).await,
                (PROVIDER_UNAVAILABLE, vec![])
            );
        }
    }

    #[tokio::test]
    async fn original_expiry_owner_loss_and_closed_channels_discard_actual_values() {
        let unavailable = (PROVIDER_UNAVAILABLE, vec![]);
        let (_owner, lost) = watch::channel(false);
        let (sender, result) = oneshot::channel();
        drop(sender);
        assert_eq!(
            await_reply(result, lost, Instant::now() + Duration::from_secs(1), 1).await,
            unavailable
        );
        for owner_closed in [false, true] {
            let (owner, lost) = watch::channel(false);
            let (sender, result) = oneshot::channel();
            sender.send((0, vec![1])).unwrap();
            if owner_closed {
                drop(owner);
            } else {
                owner.send_replace(true);
            }
            assert_eq!(
                await_reply(result, lost, Instant::now() + Duration::from_secs(1), 1).await,
                unavailable
            );
        }
        for owner_closed in [false, true] {
            let (owner, lost) = watch::channel(false);
            let (sender, result) = oneshot::channel();
            let (reply, ()) = tokio::join!(
                await_reply(result, lost, Instant::now() + Duration::from_secs(1), 1),
                async {
                    tokio::task::yield_now().await;
                    if owner_closed {
                        drop(owner);
                    } else {
                        owner.send_replace(true);
                    }
                }
            );
            assert_eq!(reply, unavailable);
            assert!(sender.send((0, vec![1])).is_err());
        }
        let (_owner, lost) = watch::channel(false);
        let (sender, result) = oneshot::channel();
        sender.send((0, vec![1])).unwrap();
        assert_eq!(
            await_reply(result, lost, Instant::now(), 1).await,
            unavailable
        );
        let (_owner, lost) = watch::channel(false);
        let (sender, result) = oneshot::channel();
        assert_eq!(
            await_reply(result, lost, Instant::now() + Duration::from_millis(5), 1).await,
            unavailable
        );
        assert!(sender.send((0, vec![1])).is_err());
    }
}
