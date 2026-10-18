// SPDX-License-Identifier: GPL-2.0-only
// Production scanner policy identity. A fence is not Native Ready or a lease.
#[derive(Default, Clone, Copy)]
pub(super) struct Fence {
    pub(super) counter: u64,
    pub(super) retired: bool,
}
impl Fence {
    pub(super) fn current(&self) -> u64 {
        self.counter
    }
    pub(super) fn retired(&self) -> bool {
        self.retired
    }
    pub(super) fn accepts(&self, epoch: u64) -> bool {
        !self.retired && epoch != 0 && self.counter == epoch
    }
    pub(super) fn advance(&mut self) -> Result<(), ()> {
        if self.retired {
            return Err(());
        }
        match self.counter.checked_add(1) {
            Some(next) => {
                self.counter = next;
                Ok(())
            }
            None => {
                self.retired = true;
                Err(())
            }
        }
    }
    pub(super) fn retire(&mut self) {
        self.retired = true;
    }
}
