// SPDX-License-Identifier: GPL-2.0-only
//! Transport-local authority, not controller generation, Native Grant or Ready.
//! Exact production LeaseAuthority is shared. The lock/execution adapter is new.
include!(concat!(env!("OUT_DIR"), "/production_authority.rs"));
use production_lease::LeaseAuthority;
use std::io;
use std::sync::{Arc, Mutex, TryLockError};
use std::time::Instant;

#[derive(Clone)]
pub struct TransportOwner {
    authority: Arc<Mutex<LeaseAuthority>>,
}
pub(crate) struct OwnerToken {
    authority: Arc<Mutex<LeaseAuthority>>,
    epoch: u64,
}

fn lock_error<T>(error: TryLockError<T>) -> io::Error {
    match error {
        TryLockError::WouldBlock => {
            io::Error::new(io::ErrorKind::WouldBlock, "transport owner gate busy")
        }
        TryLockError::Poisoned(_) => {
            io::Error::other("transport owner gate poisoned; no new submit")
        }
    }
}

impl TransportOwner {
    pub(crate) fn new() -> Self {
        let mut authority = LeaseAuthority::new();
        assert!(authority.activate(1, true));
        Self {
            authority: Arc::new(Mutex::new(authority)),
        }
    }
    pub(crate) fn token(&self) -> io::Result<OwnerToken> {
        let authority = self.authority.try_lock().map_err(lock_error)?;
        let epoch = authority.current_epoch().ok_or_else(|| {
            io::Error::new(io::ErrorKind::PermissionDenied, "transport owner revoked")
        })?;
        Ok(OwnerToken {
            authority: self.authority.clone(),
            epoch,
        })
    }
    /// Successful return is serialized after any already-entered raw submit.
    /// Busy is not completed revocation. No waiting or physical cancellation here.
    pub fn try_revoke(&self) -> io::Result<()> {
        self.authority.try_lock().map_err(lock_error)?.revoke();
        Ok(())
    }
    pub fn current_epoch(&self) -> io::Result<Option<u64>> {
        Ok(self
            .authority
            .try_lock()
            .map_err(lock_error)?
            .current_epoch())
    }
    // OpenedVmInterface cannot be dropped while a borrowed endpoint/control
    // operation exists. Only metadata readers/revokers can contend here; no I/O.
    pub(crate) fn retire_on_drop(&self) {
        match self.authority.lock() {
            Ok(mut authority) => authority.revoke(),
            Err(poisoned) => poisoned.into_inner().revoke(),
        }
    }
    /// This closure constructs/calls nusb submit while the authority lock is
    /// held; waiting for USB completion MUST happen after this method returns.
    pub(crate) fn submit<T>(
        &self,
        token: &OwnerToken,
        deadline: Instant,
        submit: impl FnOnce() -> T,
    ) -> io::Result<T> {
        if !Arc::ptr_eq(&self.authority, &token.authority) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "foreign transport owner",
            ));
        }
        let authority = self.authority.try_lock().map_err(lock_error)?;
        if !authority.permits(token.epoch) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "transport owner revoked",
            ));
        }
        if Instant::now() >= deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "not submitted: original deadline",
            ));
        }
        let result = submit();
        drop(authority);
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;
    use std::time::Duration;
    #[test]
    fn poisoned_gate_refuses_new_submits_and_drop_retirement_never_reactivates() {
        let owner = TransportOwner::new();
        let token = owner.token().unwrap();
        let panic = std::panic::catch_unwind(|| {
            owner.submit(&token, Instant::now() + Duration::from_secs(1), || {
                panic!("injected caller panic")
            })
        });
        assert!(panic.is_err());
        assert!(
            owner
                .submit(&token, Instant::now() + Duration::from_secs(1), || panic!(
                    "poisoned gate entered submit"
                ))
                .is_err()
        );
        assert!(owner.try_revoke().is_err());
        owner.retire_on_drop();
        assert_eq!(
            owner
                .authority
                .lock()
                .unwrap_err()
                .into_inner()
                .current_epoch(),
            None
        );
    }
    #[test]
    fn revoked_or_foreign_token_never_calls_submit_and_other_owner_survives() {
        let a = TransportOwner::new();
        let b = TransportOwner::new();
        let old = a.token().unwrap();
        let bt = b.token().unwrap();
        let until = Instant::now() + Duration::from_secs(1);
        assert!(
            b.submit(&old, until, || panic!("foreign owner submitted"))
                .is_err()
        );
        a.try_revoke().unwrap();
        assert_eq!(a.current_epoch().unwrap(), None);
        assert!(a.token().is_err());
        assert!(
            a.submit(&old, until, || panic!("revoked owner submitted"))
                .is_err()
        );
        assert_eq!(b.submit(&bt, until, || 42).unwrap(), 42);
        let next = TransportOwner::new();
        assert_eq!(next.current_epoch().unwrap(), Some(1));
        assert!(
            next.submit(&old, until, || panic!("old object became new owner"))
                .is_err()
        );
    }
    #[test]
    fn expired_token_does_not_enter_the_raw_call() {
        let a = TransportOwner::new();
        let token = a.token().unwrap();
        assert_eq!(
            a.submit(&token, Instant::now(), || panic!("expired submit"))
                .unwrap_err()
                .kind(),
            io::ErrorKind::TimedOut
        );
    }
    #[test]
    fn submit_and_revoke_use_the_same_real_mutex_without_holding_it_for_completion() {
        let a = TransportOwner::new();
        let token = a.token().unwrap();
        let (entered, receive) = mpsc::channel();
        let (release, wait) = mpsc::channel();
        std::thread::scope(|scope| {
            let owner = &a;
            let worker = scope.spawn(move || {
                owner.submit(&token, Instant::now() + Duration::from_secs(2), || {
                    entered.send(()).unwrap();
                    wait.recv_timeout(Duration::from_secs(1)).unwrap();
                })
            });
            receive.recv_timeout(Duration::from_secs(1)).unwrap();
            assert_eq!(
                a.try_revoke().unwrap_err().kind(),
                io::ErrorKind::WouldBlock
            );
            release.send(()).unwrap();
            worker.join().unwrap().unwrap();
        });
        a.try_revoke().unwrap();
        assert_eq!(a.current_epoch().unwrap(), None);
    }
}
