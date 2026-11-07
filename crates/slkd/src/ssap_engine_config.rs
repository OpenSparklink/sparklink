//! Owned by one physical SSAP actor, never the adapter DB or an application fd.
//! Configuration does not survive this actor's generation/lifetime or an owner
//! retirement. A security-epoch change requires a new authenticated approval.
use crate::ssap_authorization::Owner;
use std::{
    collections::BTreeMap,
    sync::{Arc, Weak},
};

struct Configuration {
    modes: u8,
    epoch: u64,
    owner: Weak<Owner>,
}

#[derive(Default)]
pub(super) struct ClientConfigurations {
    values: BTreeMap<u16, Configuration>,
}
impl ClientConfigurations {
    pub(super) fn get(&mut self, handle: u16, owner: &Arc<Owner>, epoch: u64) -> u8 {
        self.values
            .retain(|_, v| v.epoch == epoch && v.owner.upgrade().is_some_and(|o| o.current()));
        self.values
            .get(&handle)
            .filter(|v| {
                v.owner
                    .upgrade()
                    .is_some_and(|o| Arc::ptr_eq(&o, owner) && o.current())
            })
            .map_or(0, |v| v.modes)
    }
    pub(super) fn set(
        &mut self,
        handle: u16,
        owner: &Arc<Owner>,
        epoch: u64,
        modes: u8,
    ) -> Result<(), u8> {
        // Bound equals the production database's maximum number of properties.
        if handle == 0 || epoch == 0 || modes & !3 != 0 || !owner.current() {
            return Err(9);
        }
        let _ = self.get(handle, owner, epoch);
        if modes == 0 {
            self.values.remove(&handle);
        } else {
            if !self.values.contains_key(&handle) && self.values.len() >= 64 {
                return Err(5);
            }
            self.values.insert(
                handle,
                Configuration {
                    modes,
                    epoch,
                    owner: Arc::downgrade(owner),
                },
            );
        }
        Ok(())
    }
}
