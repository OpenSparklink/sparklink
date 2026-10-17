use zbus::interface;

use crate::state::SharedState;

/// Actual selected-controller link and event-watermark observations.
pub struct ControllerIface {
    state: SharedState,
}

impl ControllerIface {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

#[interface(name = "org.sparklink.Controller")]
impl ControllerIface {
    // ----- Subsystem Stats -----

    /// One validated physical-link snapshot; not PM or historical counters.
    async fn get_link_summary(&self) -> zbus::fdo::Result<(u16, u64, u64, u64, u32)> {
        let (adapter, generation) = {
            let state = self.state.lock().await;
            (state.adapter.clone(), state.controller.generation)
        };
        if generation == 0 {
            return Err(zbus::fdo::Error::NotSupported(
                "no native controller identity".into(),
            ));
        }
        let snapshot =
            tokio::task::spawn_blocking(move || adapter.native_link_snapshot(generation))
                .await
                .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?
                .map_err(map_err)?;
        known_link_summary(&snapshot)
    }

    /// Registration-local event watermark, not queue depth or delivery ACK.
    async fn get_controller_event_position(&self) -> zbus::fdo::Result<(u16, u64, u64)> {
        let (adapter, generation) = {
            let state = self.state.lock().await;
            (state.adapter.clone(), state.controller.generation)
        };
        if generation == 0 {
            return Err(zbus::fdo::Error::NotSupported(
                "no native controller identity".into(),
            ));
        }
        let snapshot =
            tokio::task::spawn_blocking(move || adapter.native_link_snapshot(generation))
                .await
                .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?
                .map_err(map_err)?;
        Ok((snapshot.dev_index, snapshot.generation, snapshot.event_seq))
    }

    /// Get active connection count
    async fn conn_count(&self) -> zbus::fdo::Result<i32> {
        let summary = self.get_link_summary().await?;
        Ok(summary.4 as i32)
    }
}

/// The SDK accepts a well-formed Unknown representation; it is not an empty
/// physical-link set and must not become a successful summary.
fn known_link_summary(
    snapshot: &slk_protocol::SleLinkSnapshot,
) -> zbus::fdo::Result<(u16, u64, u64, u64, u32)> {
    if snapshot.flags != slk_protocol::LINK_SNAPSHOT_KNOWN || snapshot.error != 0 {
        return Err(zbus::fdo::Error::Failed(format!(
            "physical link state is unknown (error={})",
            snapshot.error
        )));
    }
    Ok((
        snapshot.dev_index,
        snapshot.generation,
        snapshot.revision,
        snapshot.event_seq,
        snapshot.count,
    ))
}

fn map_err(e: slk_native::Error) -> zbus::fdo::Error {
    zbus::fdo::Error::Failed(e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn actual_summary_refuses_valid_unknown_representation() {
        let snapshot = slk_protocol::SleLinkSnapshot {
            version: 1,
            generation: 9,
            profile: 1,
            error: -5,
            ..Default::default()
        };
        assert!(snapshot.valid_for(9));
        assert!(matches!(
            known_link_summary(&snapshot),
            Err(zbus::fdo::Error::Failed(_))
        ));
    }

    #[test]
    fn actual_summary_accepts_observed_known_empty_set() {
        let snapshot = slk_protocol::SleLinkSnapshot {
            version: 1,
            generation: 9,
            profile: 1,
            flags: slk_protocol::LINK_SNAPSHOT_KNOWN,
            dev_index: 2,
            revision: 7,
            event_seq: 11,
            ..Default::default()
        };
        assert!(snapshot.valid_for(9));
        assert_eq!(known_link_summary(&snapshot).unwrap(), (2, 9, 7, 11, 0));
    }
}
