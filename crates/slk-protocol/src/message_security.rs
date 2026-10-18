//! Kernel-supplied receipt facts, not peer identity, policy or future TX consent.
//! A caller must retain its fd throughout the syscall. Missing/truncated facts
//! fail closed in the operation layer (`slk-channel`); these are ABI values only.
//!
//! The old operation path is deliberately absent:
//! ```compile_fail
//! use slk_protocol::message_security::{recv, send, prepare, deadline_at};
//! ```
use std::{io, mem};

pub const SOL_SPARKLINK: i32 = 288;
pub const SCM_RX_SECURITY: i32 = 1;
pub const MESSAGE_SECURITY_KNOWN: u8 = 1;
pub const MESSAGE_SECURITY_CURRENT: u8 = 2;

#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleMessageSecurity {
    pub version: u16,
    pub size: u16,
    pub security: u32,
    pub generation: u64,
    pub lifetime: u64,
    pub security_epoch: u64,
    pub controller: u16,
    pub handle: u16,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub flags: u8,
}
const _: () = assert!(mem::size_of::<SleMessageSecurity>() == 40);

impl SleMessageSecurity {
    pub fn validate(&self) -> io::Result<()> {
        let dynamic = (0x80..=0xdf).contains(&self.local_tcid)
            && (0x80..=0xdf).contains(&self.remote_tcid)
            && (241..=250).contains(&self.pi);
        let fixed = matches!(
            (self.local_tcid, self.remote_tcid, self.pi),
            (10, 10, 0) | (31, 31, 241)
        );
        if self.version != 1
            || self.size != 40
            || !fixed && !dynamic
            || self.generation == 0
            || self.lifetime == 0
            || self.security > 2
            || self.flags & !3 != 0
            || self.flags & MESSAGE_SECURITY_KNOWN == 0 && (self.security != 0 || self.flags != 0)
            || self.flags & MESSAGE_SECURITY_KNOWN != 0 && self.security_epoch == 0
        {
            return Err(io::Error::from_raw_os_error(nix::libc::EPROTO));
        }
        Ok(())
    }
}

/// A restriction of an existing fd Grant, never a replacement authority.
#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleSendConstraint {
    pub version: u16,
    pub size: u16,
    pub minimum: u32,
    pub generation: u64,
    pub lifetime: u64,
    pub security_epoch: u64,
    pub controller: u16,
    pub handle: u16,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub reserved: u8,
    pub deadline_monotonic_ns: u64,
}
pub const SCM_TX_CONSTRAINT: i32 = 2;
const _: () = assert!(mem::size_of::<SleSendConstraint>() == 48);
impl SleSendConstraint {
    pub fn validate(&self) -> io::Result<()> {
        if self.version != 1
            || self.size != 48
            || self.minimum > 2
            || self.reserved != 0
            || self.generation == 0
            || self.lifetime == 0
            || self.security_epoch == 0
            || self.deadline_monotonic_ns == 0
        {
            return Err(io::Error::from_raw_os_error(nix::libc::EINVAL));
        }
        Ok(())
    }
    /// Pins the original receipt epoch. Final kernel submission must still
    /// satisfy both this restriction and the original fd Grant.
    pub fn from_receipt(
        m: SleMessageSecurity,
        minimum: u32,
        deadline_monotonic_ns: u64,
    ) -> io::Result<Self> {
        m.validate()?;
        if m.flags != (MESSAGE_SECURITY_KNOWN | MESSAGE_SECURITY_CURRENT) || minimum > m.security {
            return Err(io::Error::from_raw_os_error(nix::libc::EACCES));
        }
        let c = Self {
            version: 1,
            size: 48,
            minimum,
            generation: m.generation,
            lifetime: m.lifetime,
            security_epoch: m.security_epoch,
            controller: m.controller,
            handle: m.handle,
            local_tcid: m.local_tcid,
            remote_tcid: m.remote_tcid,
            pi: m.pi,
            reserved: 0,
            deadline_monotonic_ns,
        };
        c.validate()?;
        Ok(c)
    }
}
