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
    task: Mutex<Option<tokio::task::JoinHandle<()>>>,
    // At most 16 registered or being-registered owner watches per adapter.
    _slot: OwnedSemaphorePermit,
}
impl Owner {
    pub(crate) async fn pin(
        connection: &Connection,
        name: String,
        path: OwnedObjectPath,
        store: &Store,
        slot: OwnedSemaphorePermit,
    ) -> zbus::fdo::Result<Arc<Self>> {
        let (active, mut revoked) = watch::channel(true);
        let callback_connection = Arc::new(connection.clone());
        let owner = Arc::new(Self {
            name: name.clone(),
            path,
            connection: Arc::downgrade(&callback_connection),
            active,
            task: Mutex::new(None),
            _slot: slot,
        });
        let weak = Arc::downgrade(&owner);
        let database = Arc::downgrade(store);
        let connection = callback_connection;
        let (ready, result) = oneshot::channel();
        let original_deadline = Instant::now() + std::time::Duration::from_secs(2);
        let task = tokio::spawn(async move {
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
    pub(crate) fn current(&self) -> bool {
        *self.active.borrow()
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
        prompt: slk_protocol::ssap::SsapAuthorizationPrompt,
        deadline: Instant,
    ) -> bool {
        if !self.current() || !self.supports_authorization() || Instant::now() >= deadline {
            return false;
        }
        let mut revoked = self.active.subscribe();
        let Some(connection) = self.connection.upgrade() else {
            return false;
        };
        let callback = async {
            let message = connection
                .call_method(
                    Some(self.name.as_str()),
                    self.path.as_str(),
                    Some("org.sparklink.SsapAuthorizer"),
                    "AuthorizeValue",
                    &(prompt,),
                )
                .await
                .ok()?;
            // Do not accept a method return from another bus participant.
            if message
                .header()
                .sender()
                .is_none_or(|name| name.as_str() != self.name)
            {
                return None;
            }
            let allow: bool = message.body().deserialize().ok()?;
            let bus = zbus::fdo::DBusProxy::new(&connection).await.ok()?;
            if !bus
                .name_has_owner(self.name.as_str().try_into().ok()?)
                .await
                .ok()?
            {
                return None;
            }
            Some(allow)
        };
        tokio::select! {
            biased;
            _ = revoked.changed() => false,
            _ = tokio::time::sleep_until(deadline) => false,
            decision = callback => self.current() && decision == Some(true),
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
    pub(crate) owner: Arc<Owner>,
}
pub(crate) struct Approval {
    pub(crate) handle: u16,
    pub(crate) owner: Arc<Owner>,
}
