//! Read-only capabilities of an already delegated logical-channel socket.
//! Successful metadata is coherent at kernel admission, not future connectivity
//! or controller completion. No management lease is revealed or acquired.
//! Only ABI values and validation live here. Operations require `slk-channel`.
//!
//! The retired unpublished syscall entry is deliberately absent:
//! ```compile_fail
//! use slk_protocol::channel::query;
//! ```
use std::io;

#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleChannelInfo {
    pub version: u16,
    pub size: u16,
    pub controller: u16,
    pub handle: u16,
    pub generation: u64,
    pub lifetime: u64,
    pub mtu: u16,
    pub mps: u16,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub mode: u8,
    pub directions: u32,
    pub reserved: u32,
}
const _: () = assert!(std::mem::size_of::<SleChannelInfo>() == 40);

/// cbindgen:ignore
impl SleChannelInfo {
    pub fn validate(&self) -> io::Result<()> {
        let key = (self.local_tcid, self.remote_tcid, self.pi);
        let dynamic = (0x80..=0xdf).contains(&self.local_tcid)
            && (0x80..=0xdf).contains(&self.remote_tcid)
            && (241..=250).contains(&self.pi);
        let header = if self.remote_tcid <= 0x1d { 4 } else { 5 };
        if self.version != 1
            || self.size != 40
            || self.reserved != 0
            || self.generation == 0
            || self.lifetime == 0
            || self.mtu == 0
            || self.mps == 0
            || self.mode != 0
            || self.directions == 0
            || self.directions & !3 != 0
            || u32::from(self.mtu) + header > u32::from(self.mps)
            || !(dynamic || matches!(key, (31, 31, 241) | (10, 10, 0)))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid channel capability snapshot",
            ));
        }
        Ok(())
    }
}

/// Read-only coherent software queue and native controller reservation state.
/// Peak includes rolled-back reservations; it does not mean USB or peer delivery.
#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleChannelTxStatus {
    pub version: u16,
    pub size: u16,
    pub controller: u16,
    pub handle: u16,
    pub generation: u64,
    pub lifetime: u64,
    pub packet_maximum: u16,
    pub capacity: u16,
    pub outstanding: u16,
    pub connection_debt: u16,
    pub peak_reserved: u16,
    pub queued: u16,
    pub queue_limit: u16,
    pub busy: u16,
    pub active_pdu_bytes: u32,
    pub active_pdu_offset: u32,
    pub flags: u32,
    pub reserved: u32,
    pub pool_exhaustions: u64,
}
const _: () = assert!(std::mem::size_of::<SleChannelTxStatus>() == 64);

/// cbindgen:ignore
impl SleChannelTxStatus {
    pub fn validate(&self) -> io::Result<()> {
        if self.version != 1
            || self.size != 64
            || self.generation == 0
            || self.lifetime == 0
            || self.packet_maximum == 0
            || self.packet_maximum > 2047
            || self.capacity == 0
            || self.capacity > 255
            || self.outstanding > self.capacity
            || self.connection_debt > self.outstanding
            || self.peak_reserved < self.outstanding
            || self.peak_reserved > self.capacity
            || self.queue_limit != 8
            || self.busy > 1
            || u32::from(self.queued) + u32::from(self.busy) > u32::from(self.queue_limit)
            || self.flags & !3 != 0
            || self.reserved != 0
            || self.active_pdu_bytes > 2047
            || self.active_pdu_offset > self.active_pdu_bytes
            || (self.flags & 1 == 0
                && (self.active_pdu_bytes != 0
                    || self.active_pdu_offset != 0
                    || self.flags & 2 != 0
                    || self.busy != 0))
            || (self.flags & 1 != 0 && (self.active_pdu_bytes == 0 || self.busy != 1))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid channel TX snapshot",
            ));
        }
        Ok(())
    }
}

/// Read-only Session mechanism snapshot through an already authorized fd.
/// It never grants readiness, clears credit, proves callback drain or permits reuse.
#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleSessionTxStatus {
    pub version: u16,
    pub size: u16,
    pub controller: u16,
    pub handle: u16,
    pub generation: u64,
    pub lifetime: u64,
    pub capacity: u16,
    pub outstanding: u16,
    pub connection_debt: u16,
    pub queued: u16,
    pub active_pdus: u16,
    pub dynamic_open: u16,
    pub dynamic_pending: u16,
    pub dynamic_retired: u16,
    pub dynamic_failed: u16,
    pub dynamic_allocated: u16,
    pub flags: u32,
    pub reserved: [u64; 2],
}
const _: () = assert!(std::mem::size_of::<SleSessionTxStatus>() == 64);

/// cbindgen:ignore
impl SleSessionTxStatus {
    pub fn validate(&self) -> io::Result<()> {
        let dynamic = u32::from(self.dynamic_open)
            + u32::from(self.dynamic_pending)
            + u32::from(self.dynamic_retired)
            + u32::from(self.dynamic_failed);
        if self.version != 1
            || self.size != 64
            || self.generation == 0
            || self.lifetime == 0
            || self.capacity == 0
            || self.capacity > 255
            || self.outstanding > self.capacity
            || self.connection_debt > self.outstanding
            || self.active_pdus > 1
            || u32::from(self.queued) + u32::from(self.active_pdus) > 48
            || self.dynamic_allocated > 4
            || dynamic != u32::from(self.dynamic_allocated)
            || self.flags & !15 != 0
            || self.reserved != [0; 2]
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid Session TX snapshot",
            ));
        }
        Ok(())
    }
}
