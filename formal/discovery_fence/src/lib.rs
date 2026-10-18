//! Direct inclusion of production code. No Native/firmware/environment stubs.
#[path = "../../../crates/slkd/src/discovery_fence.rs"]
mod production;
#[cfg(kani)]
mod proofs {
    use super::production::Fence;
    #[kani::proof]
    fn initial_state_does_not_accept_any_identity() {
        let fence = Fence::default();
        let id: u64 = kani::any();
        assert!(!fence.accepts(id));
        assert_eq!(fence.current(), 0);
        assert!(!fence.retired());
    }
    #[kani::proof]
    fn arbitrary_transition_never_reuses_or_revives() {
        let mut fence = Fence { counter: kani::any(), retired: kani::any() };
        let old = fence.current();
        let was_retired = fence.retired();
        let next = fence.advance();
        if next.is_ok() {
            assert!(!was_retired);
            assert!(old < u64::MAX);
            assert_eq!(fence.current(), old + 1);
            assert!(!fence.accepts(old));
            assert!(fence.accepts(fence.current()));
        } else {
            assert!(fence.retired());
            assert!(!fence.accepts(old));
        }
        fence.retire();
        let arbitrary: u64 = kani::any();
        assert!(!fence.accepts(arbitrary));
        assert!(fence.advance().is_err());
        assert!(!fence.accepts(arbitrary));
    }
    #[kani::proof]
    #[kani::unwind(10)]
    fn bounded_eight_step_cancel_reopen_retire_sequence() {
        let mut fence = Fence::default();
        let saved: u64 = kani::any();
        let mut seen_retired = false;
        let mut step = 0;
        while step < 8 {
            let retire: bool = kani::any();
            step += 1;
            let previous = fence.current();
            if retire { fence.retire(); seen_retired = true; }
            else { let _ = fence.advance(); }
            if seen_retired {
                assert!(fence.retired());
                assert!(!fence.accepts(saved));
            }
            assert!(fence.current() >= previous);
            if fence.current() != previous { assert!(!fence.accepts(previous)); }
        }
    }
    /// Deliberately false property over actual production transitions. This
    /// harness MUST fail; its rejection tests the verifier/verdict boundary.
    #[kani::proof]
    fn negative_control_old_epoch_is_still_accepted() {
        let mut fence = Fence::default();
        assert!(fence.advance().is_ok());
        let old = fence.current();
        assert!(fence.advance().is_ok());
        assert!(fence.accepts(old), "NEGATIVE_CONTROL_STALE_EPOCH_ACCEPTED");
    }
}
