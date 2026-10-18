use std::sync::Arc;

use tokio::runtime::Handle;
use tokio::sync::Mutex;

use crate::profile::ProfileRegistry;

struct ProfileState {
    registry: ProfileRegistry,
    closed: bool,
}

#[derive(Debug, thiserror::Error)]
pub enum ProfileRuntimeError {
    #[error("profile service is closed")]
    Closed,
    #[error("profile callback task failed: {0}")]
    Task(#[from] tokio::task::JoinError),
}

/// Owns the legacy Profile registry independently of adapter business state.
/// Callbacks are serialized on the blocking pool, including after cancellation
/// of a waiter. They may block their own service, but never hold SharedState or
/// run on the event receiver's Tokio thread. Construct inside the daemon runtime.
#[derive(Clone)]
pub struct ProfileService {
    state: Arc<Mutex<ProfileState>>,
    runtime: Handle,
}

impl ProfileService {
    pub fn new(registry: ProfileRegistry) -> Self {
        Self {
            state: Arc::new(Mutex::new(ProfileState {
                registry,
                closed: false,
            })),
            runtime: Handle::current(),
        }
    }

    pub async fn connection_changed(
        &self,
        handle: u16,
        connected: bool,
    ) -> Result<(), ProfileRuntimeError> {
        let mut state = self.state.clone().lock_owned().await;
        if state.closed {
            return Err(ProfileRuntimeError::Closed);
        }
        self.runtime
            .spawn_blocking(move || {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    if connected {
                        state.registry.on_connect(handle);
                    } else {
                        state.registry.on_disconnect(handle);
                    }
                }));
                if let Err(panic) = result {
                    // The plugin may have left its mutable state inconsistent.
                    // Close before releasing the lock so no clone re-enters it.
                    state.closed = true;
                    std::panic::resume_unwind(panic);
                }
            })
            .await?;
        Ok(())
    }

    /// Drain accepted callbacks before releasing the registry, and reject new
    /// notifications from every clone. A non-returning trusted callback can
    /// delay shutdown; arbitrary in-process code cannot be forcibly cancelled.
    pub async fn shutdown(&self) {
        self.state.lock().await.closed = true;
    }
}

#[cfg(test)]
#[path = "profile_runtime_tests.rs"]
pub(crate) mod tests;
