//! Local service-owner policy, never a wire/crypto engine or security Agent.
use std::sync::{Arc, Mutex, Weak};
use tokio::sync::{OwnedSemaphorePermit, oneshot, watch};
use tokio::time::Instant;
use zbus::{Connection, export::ordered_stream::OrderedStreamExt, zvariant::OwnedObjectPath};

type Store = Arc<Mutex<crate::ssap_database::Database>>;
pub(crate) struct Owner {
    pub(crate) name: String,
    path: OwnedObjectPath,
    // The owner-watch task holds this box. The database must not strongly
    // retain Connection -> object server -> AdapterState -> database.
    connection: Weak<Connection>,
    active: watch::Sender<bool>,
    // Only initial DB insertion uses this; active service requests get their own deadlines.
    registration_deadline: Instant,
    task: Mutex<Option<tokio::task::JoinHandle<()>>>,
    // At most 16 registered or being-registered owner watches per adapter.
}
impl Owner {
    pub(crate) async fn pin(
        connection: &Connection,
        name: String,
        path: OwnedObjectPath,
        store: &Store,
        slot: OwnedSemaphorePermit,
        original: Instant,
    ) -> zbus::fdo::Result<Arc<Self>> {
        if Instant::now() >= original {
            return Err(zbus::fdo::Error::Timeout(
                "owner registration original deadline".into(),
            ));
        }
        let (active, mut revoked) = watch::channel(true);
        let callback_connection = Arc::new(connection.clone());
        let owner = Arc::new(Self {
            name: name.clone(),
            path,
            connection: Arc::downgrade(&callback_connection),
            active,
            registration_deadline: original,
            task: Mutex::new(None),
        });
        let weak = Arc::downgrade(&owner);
        let database = Arc::downgrade(store);
        let connection = callback_connection;
        let (ready, result) = oneshot::channel();
        let original_deadline = original.min(Instant::now() + std::time::Duration::from_secs(2));
        let task = tokio::spawn(async move {
            // Keep capacity until actual watch-future destruction,including
            // cancellation before first poll. Requesting abort is not drain.
            let _slot = slot;
            let bus = match tokio::time::timeout_at(
                original_deadline,
                zbus::fdo::DBusProxy::new(&connection),
            )
            .await
            {
                Ok(Ok(bus)) => bus,
                e => {
                    let _ = ready.send(Err(format!("owner subscription failed: {e:?}")));
                    return;
                }
            };
            // Subscribe BEFORE checking this unique owner's existence.
            let mut changes = match tokio::time::timeout_at(
                original_deadline,
                bus.receive_name_owner_changed_with_args(&[(0, name.as_str()), (2, "")]),
            )
            .await
            {
                Ok(Ok(changes)) => changes,
                e => {
                    let _ = ready.send(Err(format!("owner subscription failed: {e:?}")));
                    return;
                }
            };
            let exists = match name.as_str().try_into() {
                Ok(name) => {
                    tokio::time::timeout_at(original_deadline, bus.name_has_owner(name)).await
                }
                Err(e) => {
                    let _ = ready.send(Err(format!("invalid unique owner: {e}")));
                    return;
                }
            };
            if !matches!(exists, Ok(Ok(true))) {
                let _ = ready.send(Err("service owner disappeared/expired".into()));
                return;
            }
            if ready.send(Ok(())).is_err() {
                return;
            }
            tokio::select! {
                biased;
                _ = changes.next() => revoke(&database, &weak),
                _ = revoked.changed() => {},
            }
        });
        *owner.task.lock().expect("new owner task mutex") = Some(task);
        result
            .await
            .map_err(|_| zbus::fdo::Error::Failed("owner watch stopped".into()))?
            .map_err(zbus::fdo::Error::Failed)?;
        if !owner.current() {
            return Err(zbus::fdo::Error::Failed("service owner retired".into()));
        }
        Ok(owner)
    }
    pub(crate) fn can_register(&self) -> bool {
        self.current() && Instant::now() < self.registration_deadline
    }
    pub(crate) fn current(&self) -> bool {
        *self.active.borrow()
    }
    /// Notification only: admission must still recheck under the DB mutex.
    /// Subscribe before checking the value so an earlier or concurrent revoke
    /// cannot leave an existing operation asleep until its original deadline.
    pub(crate) async fn withdrawn(&self) {
        let mut active = self.active.subscribe();
        let _ = active.wait_for(|current| !*current).await;
    }
    /// Database removal/owner loss call this under the SAME database mutex as
    /// value admission. Revocation does not undo already committed writes.
    pub(crate) fn revoke(&self) {
        self.active.send_replace(false);
    }
    pub(crate) fn supports_authorization(&self) -> bool {
        self.path.as_str() != "/"
    }
    pub(crate) async fn shutdown(&self) {
        self.revoke();
        let task = self.task.lock().expect("owner task mutex").take();
        if let Some(task) = task {
            let _ = task.await;
        }
    }
    pub(crate) async fn authorize(
        &self,
        prompt: slk_contract::ssap::SsapAuthorizationPrompt,
        deadline: Instant,
    ) -> bool {
        if !self.supports_authorization() {
            return false;
        }
        self.callback(
            self.path.as_str(),
            "org.sparklink.SsapAuthorizer",
            "AuthorizeValue",
            &(prompt,),
            deadline,
        )
        .await
        .is_some_and(|message| matches!(message.body().deserialize::<bool>(), Ok(true)))
    }
    /// One original owner/deadline contract for policy and value callbacks.
    /// Neither callback grants Native permission or prolongs a protocol debt.
    pub(crate) async fn callback<B>(
        &self,
        path: &str,
        interface: &str,
        method: &str,
        body: &B,
        deadline: Instant,
    ) -> Option<zbus::Message>
    where
        B: serde::Serialize + zbus::zvariant::DynamicType + Sync,
    {
        let mut revoked = self.active.subscribe();
        if !self.current() || Instant::now() >= deadline {
            return None;
        }
        let connection = self.connection.upgrade()?;
        let callback = async {
            let message = connection
                .call_method(
                    Some(self.name.as_str()),
                    path,
                    Some(interface),
                    method,
                    body,
                )
                .await
                .ok()?;
            if message
                .header()
                .sender()
                .is_none_or(|name| name.as_str() != self.name)
            {
                return None;
            }
            let bus = zbus::fdo::DBusProxy::new(&connection).await.ok()?;
            if !bus
                .name_has_owner(self.name.as_str().try_into().ok()?)
                .await
                .ok()?
            {
                return None;
            }
            Some(message)
        };
        tokio::select! {
            biased;
            _ = revoked.changed() => None,
            _ = tokio::time::sleep_until(deadline) => None,
            result = callback => {
                if self.current() && Instant::now() < deadline { result } else { None }
            },
        }
    }
}
impl Drop for Owner {
    fn drop(&mut self) {
        if let Ok(task) = self.task.get_mut()
            && let Some(task) = task.take()
        {
            task.abort();
        }
    }
}
fn revoke(database: &Weak<Mutex<crate::ssap_database::Database>>, owner: &Weak<Owner>) {
    if let Some(owner) = owner.upgrade() {
        if let Some(database) = database.upgrade()
            && let Ok(mut database) = database.lock()
        {
            database.revoke_owner(&owner.name);
            owner.revoke();
            return;
        }
        owner.revoke();
    }
}

pub(crate) struct Target {
    pub(crate) handle: u16,
    pub(crate) data_type: u8,
    pub(crate) owner: Arc<Owner>,
}
pub(crate) struct Approval {
    pub(crate) handle: u16,
    pub(crate) data_type: u8,
    pub(crate) write: bool,
    pub(crate) owner: Arc<Owner>,
}
