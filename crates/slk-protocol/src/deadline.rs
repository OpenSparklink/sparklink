//! Pure deadline identity. No clocks, files, authorization or new wire protocol.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DeadlineStamp {
    pub monotonic_ns: u64,
    pub boot_id: [u8; 16],
    pub time_namespace_device: u64,
    pub time_namespace_inode: u64,
}
impl DeadlineStamp {
    pub fn valid(&self) -> bool {
        self.monotonic_ns != 0
            && self.boot_id.iter().any(|b| *b != 0)
            && self.time_namespace_device != 0
            && self.time_namespace_inode != 0
    }
}
