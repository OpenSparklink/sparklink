//! Caller lifetime and bounded output for the existing SSAP receive transaction.
//! No wire codec/loop,Native owner or application-client dependency lives here.
use slk_contract::ssap::subscription as wire;
use std::{
    collections::VecDeque,
    sync::{Arc, Mutex},
};
use tokio::{
    sync::{OwnedSemaphorePermit, oneshot, watch},
    task::JoinHandle,
    time::Instant,
};

pub(crate) struct CallerLease {
    pub name: String,
    alive: watch::Receiver<bool>,
    task: JoinHandle<()>,
}
struct Revoke(watch::Sender<bool>);
impl Drop for Revoke {
    fn drop(&mut self) {
        self.0.send_replace(false);
    }
}
impl CallerLease {
    pub async fn pin(
        connection: &zbus::Connection,
        name: String,
        slot: OwnedSemaphorePermit,
        original: Instant,
    ) -> Result<Self, String> {
        let (active, alive) = watch::channel(true);
        let guard = Revoke(active);
        let (ready, result) = oneshot::channel();
        let bus = connection.clone();
        let caller = name.clone();
        let task = tokio::spawn(async move {
            // Captured before spawn: capacity stays charged through actual
            // watch-future destruction,including cancellation before polling.
            let _slot = slot;
            let _guard = guard;
            let _ = crate::connection_object::caller_scoped(&bus, &caller, async move {
                let _ = ready.send(());
                std::future::pending::<zbus::fdo::Result<()>>().await
            })
            .await;
        });
        let lease = Self { name, alive, task };
        tokio::time::timeout_at(original, result)
            .await
            .map_err(|_| "subscription owner original deadline".to_string())?
            .map_err(|_| "subscription owner unavailable".to_string())?;
        if !lease.current() {
            return Err("subscription owner retired".into());
        }
        Ok(lease)
    }
    pub fn current(&self) -> bool {
        *self.alive.borrow()
    }
    pub fn observer(&self) -> watch::Receiver<bool> {
        self.alive.clone()
    }
}
impl Drop for CallerLease {
    fn drop(&mut self) {
        self.task.abort();
    }
}

pub(crate) struct Queue {
    pub info: wire::Info,
    pub expires: Instant,
    entries: VecDeque<wire::Packet>,
    bytes: usize,
    sequence: u64,
    dropped: u64,
    refused: u64,
    discarded: u64,
    reason: u8,
}
pub(crate) type SharedQueue = Arc<Mutex<Queue>>;
impl Queue {
    pub fn new(info: wire::Info, expires: Instant) -> SharedQueue {
        Arc::new(Mutex::new(Self {
            info,
            expires,
            entries: VecDeque::new(),
            bytes: 0,
            sequence: 0,
            dropped: 0,
            refused: 0,
            discarded: 0,
            reason: 0,
        }))
    }
    pub fn active(&mut self) {
        self.info.state = wire::ACTIVE;
    }
    pub fn is_closing(&self) -> bool {
        self.info.state >= wire::CLOSING
    }
    pub fn has_data(&self) -> bool {
        !self.entries.is_empty()
    }
    pub fn close(&mut self, reason: u8) -> Result<(), String> {
        if !self.is_closing() {
            self.info.state = wire::CLOSING;
            self.reason = reason;
            self.discarded = self
                .discarded
                .checked_add(self.entries.len() as u64)
                .ok_or("subscription discard counter exhausted")?;
            self.entries.clear();
            self.bytes = 0;
        }
        Ok(())
    }
    pub fn renew(&mut self, duration_ms: u32, now: Instant) -> Result<wire::Info, String> {
        if self.info.state != wire::ACTIVE
            || now >= self.expires
            || !(250..=60000).contains(&duration_ms)
        {
            return Err("subscription not active/expired/invalid renewal".into());
        }
        let expires = now + std::time::Duration::from_millis(u64::from(duration_ms));
        let expires_ns =
            slk_channel::security::deadline_at(expires.into_std()).map_err(|e| e.to_string())?;
        self.expires = expires;
        self.info.expires_ns = expires_ns;
        Ok(self.info.clone())
    }
    pub fn take_batch(&mut self) -> wire::Batch {
        self.bytes = 0;
        wire::Batch {
            info: self.info.clone(),
            last_sequence: self.sequence,
            dropped_notifications: self.dropped,
            refused_indications: self.refused,
            discarded_on_close: self.discarded,
            flags: 0,
            reason: self.reason,
            packets: self.entries.drain(..).collect(),
        }
    }
    pub fn restore(&mut self, batch: wire::Batch) {
        // Only the sole actor consumes/produces. This is used when its local
        // oneshot rejects the batch,not after an uncertain D-Bus delivery.
        for packet in batch.packets.into_iter().rev() {
            self.bytes += packet.pdu.len();
            self.entries.push_front(packet);
        }
    }
    pub fn closed(&mut self, confirmed: bool) -> wire::Batch {
        self.info.state = wire::CLOSED;
        let mut result = self.take_batch();
        if confirmed {
            result.flags = wire::CLEANUP_CONFIRMED;
        }
        result
    }
}

#[derive(Clone)]
pub(crate) struct Sink {
    pub queue: SharedQueue,
    pub alive: watch::Receiver<bool>,
}
impl Sink {
    pub fn offer(
        &self,
        packet: super::ssap_engine::Incoming,
        receipt: Option<slk_protocol::SleMessageSecurity>,
        now: Instant,
    ) -> Result<bool, String> {
        let mut q = self
            .queue
            .lock()
            .map_err(|_| "subscription queue poisoned")?;
        if !*self.alive.borrow() || q.is_closing() || now >= q.expires {
            return Ok(false);
        }
        let m = receipt.ok_or("missing subscription Native receipt")?;
        m.validate()
            .map_err(|_| "invalid subscription Native receipt")?;
        if (
            m.controller,
            m.generation,
            m.lifetime,
            m.handle,
            m.local_tcid,
            m.remote_tcid,
            m.pi,
            m.security_epoch,
        ) != (
            q.info.controller,
            q.info.generation,
            q.info.lifetime,
            q.info.handle,
            10,
            10,
            0,
            q.info.security_epoch,
        ) || m.flags != 3
            || m.security < 2
        {
            return Err("subscription original Native identity/security changed".into());
        }
        if packet.1.len() > 2048 {
            return Err("subscription PDU budget".into());
        }
        q.sequence = q
            .sequence
            .checked_add(1)
            .ok_or("subscription sequence exhausted")?;
        if q.entries.len() >= wire::CAPACITY || q.bytes + packet.1.len() > wire::BYTE_BUDGET {
            let count = if packet.0 {
                &mut q.refused
            } else {
                &mut q.dropped
            };
            *count = count
                .checked_add(1)
                .ok_or("subscription loss counter exhausted")?;
            return Ok(false);
        }
        let sequence = q.sequence;
        q.bytes += packet.1.len();
        q.entries.push_back(wire::Packet {
            sequence,
            security_epoch: m.security_epoch,
            security_level: m.security,
            indication: packet.0,
            pdu: packet.1,
        });
        Ok(true)
    }
}

pub(crate) struct Closed {
    pub owner: String,
    pub token: u64,
    pub result: Result<wire::Batch, String>,
}

#[cfg(test)]
mod tests {
    //! Direct production queue transitions. Native receipt values below are
    //! explicit input fixtures, not a successful Native ioctl or radio proof.
    use super::*;
    use slk_protocol::SleMessageSecurity;
    use std::time::Duration;

    fn queue(now: Instant) -> (Sink, watch::Sender<bool>, SleMessageSecurity) {
        let expires = now + Duration::from_secs(2);
        let info = wire::Info {
            version: 1,
            controller: 2,
            generation: 7,
            lifetime: 9,
            handle: 11,
            security_epoch: 13,
            token: 17,
            expires_ns: slk_channel::security::deadline_at(expires.into_std()).unwrap(),
            handles: vec![19],
            modes: 3,
            state: wire::STARTING,
            capacity: wire::CAPACITY as u16,
        };
        let receipt = SleMessageSecurity {
            version: 1,
            size: 40,
            controller: 2,
            generation: 7,
            lifetime: 9,
            handle: 11,
            local_tcid: 10,
            remote_tcid: 10,
            pi: 0,
            security_epoch: 13,
            flags: 3,
            security: 2,
        };
        let (alive, observed) = watch::channel(true);
        (
            Sink {
                queue: Queue::new(info, expires),
                alive: observed,
            },
            alive,
            receipt,
        )
    }

    #[test]
    fn bounded_queue_refuses_indications_and_counts_notification_loss_without_eviction() {
        let now = Instant::now();
        let (sink, _owner, receipt) = queue(now);
        for index in 0..wire::CAPACITY {
            assert!(
                sink.offer((false, vec![index as u8; 2048]), Some(receipt), now)
                    .unwrap()
            );
        }
        assert_eq!(sink.queue.lock().unwrap().bytes, wire::BYTE_BUDGET);
        assert!(!sink.offer((true, vec![99]), Some(receipt), now).unwrap());
        assert!(!sink.offer((false, vec![100]), Some(receipt), now).unwrap());
        let batch = sink.queue.lock().unwrap().take_batch();
        assert_eq!(batch.packets.len(), 16);
        assert_eq!(batch.last_sequence, 18);
        assert_eq!(
            (batch.dropped_notifications, batch.refused_indications),
            (1, 1)
        );
        for (index, packet) in batch.packets.iter().enumerate() {
            assert_eq!(packet.sequence, index as u64 + 1);
            assert_eq!(packet.pdu, vec![index as u8; 2048]);
        }
        assert_eq!(sink.queue.lock().unwrap().bytes, 0);
        assert!(sink.offer((true, vec![101]), Some(receipt), now).unwrap());
        let next = sink.queue.lock().unwrap().take_batch();
        assert_eq!(next.packets[0].sequence, 19);
        assert_eq!(
            (next.dropped_notifications, next.refused_indications),
            (1, 1)
        );
    }

    #[test]
    fn receipt_identity_security_and_oversize_rejections_have_no_queue_side_effect() {
        let now = Instant::now();
        let (sink, _owner, receipt) = queue(now);
        let mut invalid = vec![None];
        for field in 0..13 {
            let mut changed = receipt;
            match field {
                0 => changed.controller += 1,
                1 => changed.generation += 1,
                2 => changed.lifetime += 1,
                3 => changed.handle += 1,
                4 => changed.local_tcid += 1,
                5 => changed.remote_tcid += 1,
                6 => changed.pi += 1,
                7 => changed.security_epoch += 1,
                8 => changed.flags = 1,
                9 => changed.security = 1,
                10 => changed.security = 3,
                11 => changed.version = 2,
                _ => changed.size = 0,
            }
            invalid.push(Some(changed));
        }
        for value in invalid {
            assert!(sink.offer((true, vec![1]), value, now).is_err());
        }
        assert!(
            sink.offer((false, vec![0; 2049]), Some(receipt), now)
                .is_err()
        );
        let batch = sink.queue.lock().unwrap().take_batch();
        assert!(batch.packets.is_empty());
        assert_eq!(
            (
                batch.last_sequence,
                batch.dropped_notifications,
                batch.refused_indications
            ),
            (0, 0, 0)
        );
    }

    #[test]
    fn close_discards_once_preserves_first_reason_and_requires_explicit_cleanup_receipt() {
        let now = Instant::now();
        let (sink, _owner, receipt) = queue(now);
        assert!(sink.offer((false, vec![1]), Some(receipt), now).unwrap());
        assert!(sink.offer((true, vec![2]), Some(receipt), now).unwrap());
        let mut q = sink.queue.lock().unwrap();
        q.close(wire::OWNER_LOST).unwrap();
        q.close(wire::RELEASED).unwrap();
        assert_eq!(q.info.state, wire::CLOSING);
        assert!(q.renew(1000, now).is_err());
        let uncertain = q.closed(false);
        assert_eq!(uncertain.reason, wire::OWNER_LOST);
        assert_eq!(uncertain.discarded_on_close, 2);
        assert_eq!(uncertain.flags, 0);
        assert!(uncertain.packets.is_empty());
        drop(q);
        assert!(!sink.offer((true, vec![3]), Some(receipt), now).unwrap());
        let confirmed = sink.queue.lock().unwrap().closed(true);
        assert_eq!(confirmed.flags, wire::CLEANUP_CONFIRMED);
        assert_eq!(confirmed.discarded_on_close, 2);
        assert_eq!(confirmed.last_sequence, 2);
    }

    #[test]
    fn lease_expiry_owner_loss_and_renewal_cannot_reopen_or_extend_closed_scope() {
        let now = Instant::now();
        let (sink, owner, receipt) = queue(now);
        let mut q = sink.queue.lock().unwrap();
        let original_expiry = q.expires;
        assert!(q.renew(1000, now).is_err()); // Not active yet.
        q.active();
        for invalid in [0, 249, 60001, u32::MAX] {
            assert!(q.renew(invalid, now).is_err());
            assert_eq!(q.expires, original_expiry);
        }
        q.renew(500, now).unwrap();
        assert_eq!(q.expires, now + Duration::from_millis(500));
        let expiry = q.expires;
        assert!(q.renew(1000, expiry).is_err());
        assert_eq!(q.expires, expiry);
        drop(q);
        assert!(!sink.offer((true, vec![1]), Some(receipt), expiry).unwrap());
        owner.send_replace(false);
        assert!(!sink.offer((true, vec![1]), Some(receipt), now).unwrap());
        assert_eq!(sink.queue.lock().unwrap().sequence, 0);
    }

    #[test]
    fn local_oneshot_rejection_restores_exact_queue_and_keeps_loss_history() {
        let now = Instant::now();
        let (sink, _owner, receipt) = queue(now);
        for n in 1..=3 {
            assert!(
                sink.offer((n % 2 == 0, vec![n; 7]), Some(receipt), now)
                    .unwrap()
            );
        }
        let mut q = sink.queue.lock().unwrap();
        let original = q.take_batch();
        assert_eq!(q.bytes, 0);
        q.restore(original.clone());
        assert_eq!(q.bytes, 21);
        assert_eq!(q.take_batch(), original);
    }

    #[tokio::test]
    async fn real_bus_owner_loss_revokes_watch_and_releases_its_capacity() {
        let bus = crate::event_loop::tests::PrivateBus::start();
        let service = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let caller = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let slots = Arc::new(tokio::sync::Semaphore::new(1));
        let lease = CallerLease::pin(
            &service,
            caller.unique_name().unwrap().to_string(),
            slots.clone().acquire_owned().await.unwrap(),
            Instant::now() + Duration::from_secs(2),
        )
        .await
        .unwrap();
        assert!(lease.current());
        assert_eq!(slots.available_permits(), 0);
        let mut lost = lease.observer();
        caller.close().await.unwrap();
        tokio::time::timeout(Duration::from_secs(2), lost.wait_for(|alive| !*alive))
            .await
            .unwrap()
            .unwrap();
        let _released = tokio::time::timeout(Duration::from_secs(2), slots.acquire_owned())
            .await
            .unwrap()
            .unwrap();
        assert!(!lease.current());
    }

    #[tokio::test]
    async fn drop_retires_only_its_watch_and_absent_owner_cannot_acquire_scope() {
        let bus = crate::event_loop::tests::PrivateBus::start();
        let service = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let caller = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let name = caller.unique_name().unwrap().to_string();
        let slots = Arc::new(tokio::sync::Semaphore::new(1));
        let lease = CallerLease::pin(
            &service,
            name.clone(),
            slots.clone().acquire_owned().await.unwrap(),
            Instant::now() + Duration::from_secs(2),
        )
        .await
        .unwrap();
        let mut lost = lease.observer();
        drop(lease);
        tokio::time::timeout(Duration::from_secs(2), lost.wait_for(|alive| !*alive))
            .await
            .unwrap()
            .unwrap();
        let slot = tokio::time::timeout(Duration::from_secs(2), slots.clone().acquire_owned())
            .await
            .unwrap()
            .unwrap();
        assert!(
            zbus::fdo::DBusProxy::new(&service)
                .await
                .unwrap()
                .name_has_owner(name.as_str().try_into().unwrap())
                .await
                .unwrap()
        );
        caller.close().await.unwrap();
        assert!(
            CallerLease::pin(
                &service,
                name,
                slot,
                Instant::now() + Duration::from_secs(2)
            )
            .await
            .is_err()
        );
        let _released = tokio::time::timeout(Duration::from_secs(2), slots.acquire_owned())
            .await
            .unwrap()
            .unwrap();
    }
}
