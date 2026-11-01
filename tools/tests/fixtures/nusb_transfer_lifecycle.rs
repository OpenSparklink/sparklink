// Audit tests injected into the checksum-pinned upstream module, not a copy of
// its implementation. Completion is manually delivered exactly once; no OS,
// USB callback, cancellation, firmware or hardware behavior is proved here.
#[cfg(test)]
mod sparklink_audit {
    use super::*;
    use std::sync::atomic::{AtomicPtr, AtomicUsize};

    struct Payload {
        id: usize,
        dropped: Arc<AtomicUsize>,
    }
    impl Drop for Payload {
        fn drop(&mut self) {
            self.dropped.fetch_add(1, Ordering::SeqCst);
        }
    }
    fn idle(id: usize, dropped: &Arc<AtomicUsize>) -> Idle<Payload> {
        Idle::new(
            Arc::new(Notify::new()),
            Payload {
                id,
                dropped: dropped.clone(),
            },
        )
    }

    #[test]
    fn abandoned_pending_keeps_payload_until_completion() {
        let dropped = Arc::new(AtomicUsize::new(0));
        let pending = idle(1, &dropped).pre_submit();
        let ptr = pending.as_ptr();
        drop(pending);
        assert_eq!(dropped.load(Ordering::SeqCst), 0);
        // No kernel owns this test payload; deliver the sole callback now.
        unsafe { notify_completion(ptr) };
        assert_eq!(dropped.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn completion_queue_preserves_submission_order() {
        let dropped = Arc::new(AtomicUsize::new(0));
        let first = idle(1, &dropped).pre_submit();
        let second = idle(2, &dropped).pre_submit();
        let first_ptr = first.as_ptr();
        let second_ptr = second.as_ptr();
        let mut queue = VecDeque::from([first, second]);
        unsafe { notify_completion(second_ptr) };
        assert!(take_completed_from_queue(&mut queue).is_none());
        unsafe { notify_completion(first_ptr) };
        assert_eq!(take_completed_from_queue(&mut queue).unwrap().id, 1);
        assert_eq!(take_completed_from_queue(&mut queue).unwrap().id, 2);
        assert!(queue.is_empty());
        assert_eq!(dropped.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn control_future_submits_on_construction_and_drop_does_not_drain() {
        let dropped = Arc::new(AtomicUsize::new(0));
        let pointer = AtomicPtr::new(std::ptr::null_mut());
        let future = TransferFuture::new(
            (),
            Payload {
                id: 3,
                dropped: dropped.clone(),
            },
            |_, t| {
                let pending = t.pre_submit();
                pointer.store(pending.as_ptr(), Ordering::SeqCst);
                pending
            },
        );
        // The real TransferFuture implementation invoked submit without poll.
        let ptr = pointer.load(Ordering::SeqCst);
        assert!(!ptr.is_null());
        drop(future);
        assert_eq!(dropped.load(Ordering::SeqCst), 0);
        unsafe { notify_completion(ptr) };
        assert_eq!(dropped.load(Ordering::SeqCst), 1);
    }
}
