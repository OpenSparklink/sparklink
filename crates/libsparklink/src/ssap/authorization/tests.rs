//! The production admission/wait functions with explicit observation/oneshot
//! fixtures. No live kernel state, daemon database, wire Engine or RF proof.
use super::*;
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
        operations: SsapOperations::from_bits(5).unwrap(),
        access: SsapAccess::from_bits(36).unwrap(),
    }
}
fn prompt() -> Prompt {
    (
        1,
        (0, 7, 13, 1, 41, 0, 10, 10, 0),
        17,
        false,
        crate::Deadline::after(Duration::from_secs(1))
            .unwrap()
            .stamp()
            .monotonic_ns,
        vec![],
    )
}

#[test]
fn original_sender_identity_mode_value_and_original_deadline_are_required() {
    let c = context();
    let p = prompt();
    let original = admit(&c, Some(":1.10"), &p).unwrap().unwrap();
    assert!(original > Instant::now());
    assert!(original <= Instant::now() + Duration::from_secs(1));
    for sender in [None, Some(":1.11"), Some("org.sparklink")] {
        assert!(matches!(
            admit(&c, sender, &p),
            Err(zbus::fdo::Error::AccessDenied(_))
        ));
    }
    for case in 0..16 {
        let mut p = prompt();
        match case {
            0 => p.0 = 0,
            1 => p.1.0 = 1,
            2 => p.1.1 = 8,
            3 => p.1.2 = 0,
            4 => p.1.4 = 0,
            5 => p.1.5 = 3,
            6 => p.1.6 = 11,
            7 => p.1.7 = 11,
            8 => p.1.8 = 1,
            9 => p.2 = 18,
            10 => p.4 = 0,
            11 => p.4 = 1,
            12 => p.4 = u64::MAX,
            13 => {
                p.4 = crate::Deadline::after(Duration::from_secs(6))
                    .unwrap()
                    .stamp()
                    .monotonic_ns
            }
            14 => p.5 = vec![7],
            _ => {
                p.3 = true;
                p.5 = vec![7; 2043];
            }
        }
        assert!(
            admit(&c, Some(":1.10"), &p).unwrap().is_none(),
            "case {case}"
        );
    }
    for property in [None, Some(18)] {
        let mut c = context();
        c.property = property;
        assert!(admit(&c, Some(":1.10"), &p).unwrap().is_none());
    }
    let mut c = context();
    c.owner_lost = true;
    assert!(admit(&c, Some(":1.10"), &p).unwrap().is_none());
    let mut c = context();
    c.operations = SsapOperations::from_bits(0).unwrap();
    assert!(admit(&c, Some(":1.10"), &p).unwrap().is_none());
    // Actual maximum proposed write, not a newly enlarged permission scope.
    let mut p = prompt();
    p.3 = true;
    p.5 = vec![0xa5; 2042];
    assert!(admit(&context(), Some(":1.10"), &p).unwrap().is_some());
}

#[test]
fn approval_never_discharges_the_real_operation_or_security_requirements() {
    for bits in 0..=63 {
        for level in 0..=2 {
            for write in [false, true] {
                for operations in [0, 1, 4, 5] {
                    let mut c = context();
                    c.access = SsapAccess::from_bits(bits).unwrap();
                    c.operations = SsapOperations::from_bits(operations).unwrap();
                    let mut p = prompt();
                    p.1.5 = level;
                    p.3 = write;
                    let expected = c
                        .access
                        .check_authorization_result(level, write, true)
                        .is_ok()
                        && c.operations.contains(if write {
                            SsapOperations::WRITE_WITH_RSP
                        } else {
                            SsapOperations::READ
                        });
                    assert_eq!(
                        admit(&c, Some(":1.10"), &p).unwrap().is_some(),
                        expected,
                        "bits={bits} level={level} write={write} operations={operations}"
                    );
                }
            }
        }
    }
}

#[tokio::test]
async fn wait_is_bounded_by_original_expiry_owner_loss_and_actual_reply() {
    for allowed in [false, true] {
        let (_owner, lost) = watch::channel(false);
        let (reply, result) = oneshot::channel();
        reply.send(allowed).unwrap();
        assert_eq!(
            await_decision(result, lost, Instant::now() + Duration::from_secs(1)).await,
            allowed
        );
    }
    // Releasing the callback or its owner cannot become approval.
    let (_owner, lost) = watch::channel(false);
    let (reply, result) = oneshot::channel();
    drop(reply);
    assert!(!await_decision(result, lost, Instant::now() + Duration::from_secs(1)).await);
    let (owner, lost) = watch::channel(false);
    let (reply, result) = oneshot::channel();
    reply.send(true).unwrap();
    drop(owner);
    assert!(!await_decision(result, lost, Instant::now() + Duration::from_secs(1)).await);
    // Both readiness sources are real: the terminal owner wins over ready yes.
    let (owner, lost) = watch::channel(false);
    let (reply, result) = oneshot::channel();
    reply.send(true).unwrap();
    owner.send_replace(true);
    assert!(!await_decision(result, lost, Instant::now() + Duration::from_secs(1)).await);
    let (_owner, lost) = watch::channel(false);
    let (reply, result) = oneshot::channel();
    reply.send(true).unwrap();
    assert!(!await_decision(result, lost, Instant::now()).await);
    let (_owner, lost) = watch::channel(false);
    let (reply, result) = oneshot::channel();
    assert!(!await_decision(result, lost, Instant::now() + Duration::from_millis(5)).await);
    assert!(
        reply.send(true).is_err(),
        "late approval must have no receiver"
    );
    // An admitted snapshot is not an enduring capability: frontend rechecks.
    let mut c = context();
    let p = prompt();
    assert!(admit(&c, Some(":1.10"), &p).unwrap().is_some());
    c.owner_lost = true;
    assert!(admit(&c, Some(":1.10"), &p).unwrap().is_none());
}
