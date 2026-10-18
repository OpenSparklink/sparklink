//! The existing published directory and its bounded observation journal share
//! one lock. No journal entry retains a Native fd, lease, Ready or link state.
use crate::state::AdapterRegistration;
use slk_contract::{ControllerId, controller_events as wire};
use std::{
    collections::{BTreeMap, VecDeque},
    sync::{Arc, Mutex as StdMutex},
};
use tokio::sync::{Mutex, Notify, OwnedSemaphorePermit, Semaphore};

#[derive(Default)]
struct Journal {
    tail: u64,
    rows: VecDeque<wire::Row>,
    failed: bool,
}
impl Journal {
    fn record(&mut self, id: ControllerId, kind: u8) {
        let Some(next) = self.tail.checked_add(1) else {
            self.failed = true;
            return;
        };
        if self.failed || id.generation == 0 || !matches!(kind, wire::PUBLISHED | wire::WITHDRAWN) {
            self.failed = true;
            return;
        }
        if self.rows.len() == wire::CAPACITY {
            self.rows.pop_front();
        }
        self.rows.push_back((next, id.index, id.generation, kind));
        self.tail = next;
    }
    fn read(&self, after: u64) -> zbus::fdo::Result<wire::Batch> {
        if self.failed {
            return Err(zbus::fdo::Error::Failed(
                "controller journal unavailable; no implicit reset".into(),
            ));
        }
        if after > self.tail {
            return Err(zbus::fdo::Error::InvalidArgs(
                "future directory cursor".into(),
            ));
        }
        let oldest = self.rows.front().map_or(0, |r| r.0);
        let gap = oldest != 0 && after < oldest - 1;
        let rows = if gap {
            Vec::new()
        } else {
            self.rows.iter().copied().filter(|r| r.0 > after).collect()
        };
        Ok((wire::VERSION, oldest, self.tail, gap, rows))
    }
}
#[derive(Default)]
struct Inner {
    entries: BTreeMap<String, AdapterRegistration>,
    journal: Journal,
}
struct WaitBudget {
    slots: Arc<Semaphore>,
    callers: StdMutex<BTreeMap<String, usize>>,
}
impl Default for WaitBudget {
    fn default() -> Self {
        Self {
            slots: Arc::new(Semaphore::new(16)),
            callers: StdMutex::new(BTreeMap::new()),
        }
    }
}
struct WaitGuard {
    budget: Arc<WaitBudget>,
    caller: String,
    _slot: OwnedSemaphorePermit,
}
impl WaitBudget {
    fn acquire(self: &Arc<Self>, caller: &str) -> zbus::fdo::Result<WaitGuard> {
        let mut callers = self
            .callers
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("journal waiter budget unavailable".into()))?;
        if callers.get(caller).copied().unwrap_or(0) >= 2 {
            return Err(zbus::fdo::Error::LimitsExceeded(
                "two controller waits per caller".into(),
            ));
        }
        let slot = self.slots.clone().try_acquire_owned().map_err(|_| {
            zbus::fdo::Error::LimitsExceeded("controller waiter budget full".into())
        })?;
        *callers.entry(caller.to_owned()).or_default() += 1;
        Ok(WaitGuard {
            budget: self.clone(),
            caller: caller.to_owned(),
            _slot: slot,
        })
    }
}
impl Drop for WaitGuard {
    fn drop(&mut self) {
        if let Ok(mut callers) = self.budget.callers.lock()
            && let Some(count) = callers.get_mut(&self.caller)
        {
            *count -= 1;
            if *count == 0 {
                callers.remove(&self.caller);
            }
        }
    }
}

#[derive(Clone, Default)]
pub struct Directory {
    inner: Arc<Mutex<Inner>>,
    changed: Arc<Notify>,
    budget: Arc<WaitBudget>,
}
impl Directory {
    pub async fn entries(&self) -> BTreeMap<String, AdapterRegistration> {
        self.inner.lock().await.entries.clone()
    }
    pub async fn register(&self, path: String, registration: AdapterRegistration) {
        let mut inner = self.inner.lock().await;
        let identity =
            ControllerId::from_path(&path).filter(|id| id.generation == registration.generation);
        let existed = inner.entries.insert(path, registration).is_some();
        if let Some(id) = identity {
            if !existed {
                inner.journal.record(id, wire::PUBLISHED);
            }
        } else {
            inner.journal.failed = true;
        }
        drop(inner);
        self.changed.notify_waiters();
    }
    pub async fn withdraw(&self, path: &str) {
        let mut inner = self.inner.lock().await;
        if let Some(entry) = inner.entries.remove(path) {
            if let Some(id) =
                ControllerId::from_path(path).filter(|id| id.generation == entry.generation)
            {
                inner.journal.record(id, wire::WITHDRAWN);
            } else {
                inner.journal.failed = true;
            }
        }
        drop(inner);
        self.changed.notify_waiters();
    }
    pub async fn changes(
        &self,
        after: u64,
        wait: bool,
        deadline: slk_channel::deadline::Deadline,
        caller: &str,
    ) -> zbus::fdo::Result<wire::Batch> {
        let _guard = if wait {
            Some(self.budget.acquire(caller)?)
        } else {
            None
        };
        let until = tokio::time::Instant::from_std(deadline.instant());
        loop {
            // Arm before inspecting state. notify_waiters does not store a
            // permit for a future waiter; a bare not-yet-polled future loses it.
            let notified = self.changed.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            let batch = self.inner.lock().await.journal.read(after)?;
            if !wait || batch.3 || !batch.4.is_empty() {
                return Ok(batch);
            }
            tokio::select! {
                _ = &mut notified => {},
                _ = tokio::time::sleep_until(until) => return self.inner.lock().await.journal.read(after),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn actual_journal_capacity_gap_and_exhaustion_are_explicit() {
        let mut j = Journal::default();
        let id = ControllerId {
            index: 3,
            generation: 9,
        };
        assert!(wire::valid(0, &j.read(0).unwrap()));
        for _ in 0..wire::CAPACITY {
            j.record(id, wire::PUBLISHED);
        }
        assert_eq!(j.rows.len(), wire::CAPACITY);
        assert!(wire::valid(0, &j.read(0).unwrap()));
        j.record(id, wire::WITHDRAWN);
        assert!(j.read(0).unwrap().3);
        assert!(wire::valid(1, &j.read(1).unwrap()));
        assert!(j.read(j.tail + 1).is_err());
        j.tail = u64::MAX;
        j.record(id, wire::PUBLISHED);
        assert!(j.failed && j.read(0).is_err());
    }
    #[test]
    fn actual_wait_budget_is_per_caller_and_released_on_drop() {
        let b = Arc::new(WaitBudget::default());
        let a = b.acquire(":1.1").unwrap();
        let c = b.acquire(":1.1").unwrap();
        assert!(b.acquire(":1.1").is_err());
        let mut others = Vec::new();
        for n in 2..16 {
            others.push(b.acquire(&format!(":1.{n}")).unwrap());
        }
        assert!(b.acquire(":1.99").is_err());
        drop(a);
        drop(c);
        assert!(b.acquire(":1.99").is_ok());
        drop(others);
        assert!(b.callers.lock().unwrap().is_empty());
    }
    #[tokio::test]
    async fn actual_wait_wakes_and_cancel_does_not_mutate_journal() {
        let d = Directory::default();
        let wait = d.clone();
        let task = tokio::spawn(async move {
            wait.changes(
                0,
                true,
                slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(1)).unwrap(),
                ":1.1",
            )
            .await
        });
        tokio::task::yield_now().await;
        d.inner.lock().await.journal.record(
            ControllerId {
                index: 2,
                generation: 7,
            },
            wire::PUBLISHED,
        );
        d.changed.notify_waiters();
        let batch = task.await.unwrap().unwrap();
        assert!(wire::valid(0, &batch));
        assert_eq!(batch.4.len(), 1);
        let waiting = d.clone();
        let task = tokio::spawn(async move {
            waiting
                .changes(
                    1,
                    true,
                    slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(1))
                        .unwrap(),
                    ":1.1",
                )
                .await
        });
        tokio::task::yield_now().await;
        task.abort();
        assert!(task.await.unwrap_err().is_cancelled());
        assert_eq!(d.inner.lock().await.journal.tail, 1);
        assert!(d.budget.callers.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn actual_directory_does_not_retain_native_fd_after_withdrawal() {
        let d = Directory::default();
        let fd = Arc::new(slk_native::Adapter::open("/dev/null").unwrap());
        let weak = Arc::downgrade(&fd);
        let path = ControllerId {
            index: 2,
            generation: 7,
        }
        .path();
        d.register(
            path.clone(),
            AdapterRegistration {
                adapter: fd,
                generation: 7,
            },
        )
        .await;
        assert!(weak.upgrade().is_some());
        d.withdraw(&path).await;
        assert!(
            weak.upgrade().is_none(),
            "journal contains identities, never retained Native resources"
        );
        let batch = d.inner.lock().await.journal.read(0).unwrap();
        assert!(wire::valid(0, &batch));
        assert_eq!(
            batch.4,
            vec![(1, 2, 7, wire::PUBLISHED), (2, 2, 7, wire::WITHDRAWN)]
        );
        d.withdraw(&path).await;
        assert_eq!(d.inner.lock().await.journal.tail, 2);
    }

    #[tokio::test]
    async fn actual_root_method_waits_on_directory_and_rejects_clock_domain_mismatch() {
        // Production Root, directory and waiter. /dev/null is an explicit fd
        // lifetime fixture only: no Native success/Ready/physical event.
        let bus = crate::event_loop::tests::PrivateBus::start();
        let d = Directory::default();
        let _server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .name("org.sparklink")
            .unwrap()
            .serve_at(
                "/org/sparklink",
                crate::dbus_iface::Root::new(d.clone(), Arc::new(Mutex::new(BTreeMap::new()))),
            )
            .unwrap()
            .build()
            .await
            .unwrap();
        let caller = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let stamp = slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(1))
            .unwrap()
            .stamp();
        let mut bad = stamp;
        bad.time_namespace_inode ^= 1;
        let p = zbus::Proxy::new(
            &caller,
            "org.sparklink",
            "/org/sparklink",
            "org.sparklink.Manager",
        )
        .await
        .unwrap();
        let introspection = zbus::fdo::IntrospectableProxy::builder(&caller)
            .destination("org.sparklink")
            .unwrap()
            .path("/org/sparklink")
            .unwrap()
            .build()
            .await
            .unwrap()
            .introspect()
            .await
            .unwrap();
        let method = introspection
            .split("<method name=\"GetControllerChanges\">")
            .nth(1)
            .unwrap()
            .split("</method>")
            .next()
            .unwrap();
        assert!(method.contains("type=\"(ttttt)\""));
        assert!(
            method.contains("type=\"(qttba(tqty))\""),
            "independent literal return signature: {method}"
        );
        let rejected: Result<wire::Batch, _> = p
            .call(
                wire::METHOD,
                &(0u64, false, slk_contract::deadline_wire(bad)),
            )
            .await;
        assert!(rejected.is_err());
        let selected = caller.clone();
        let waiter = tokio::spawn(async move {
            let p = zbus::Proxy::new(
                &selected,
                "org.sparklink",
                "/org/sparklink",
                "org.sparklink.Manager",
            )
            .await
            .unwrap();
            let batch: wire::Batch = p
                .call(
                    wire::METHOD,
                    &(0u64, true, slk_contract::deadline_wire(stamp)),
                )
                .await
                .unwrap();
            batch
        });
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            while d.budget.callers.lock().unwrap().is_empty() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        d.register(
            "/org/sparklink/slk2_g7".into(),
            AdapterRegistration {
                adapter: Arc::new(slk_native::Adapter::open("/dev/null").unwrap()),
                generation: 7,
            },
        )
        .await;
        let batch = waiter.await.unwrap();
        assert!(wire::valid(0, &batch));
        assert_eq!(batch.4, vec![(1, 2, 7, wire::PUBLISHED)]);
        assert!(d.budget.callers.lock().unwrap().is_empty());
    }
}
