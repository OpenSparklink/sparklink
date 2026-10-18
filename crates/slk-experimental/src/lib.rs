//! Unqualified legacy development implementations, outside default slkd.
//! Not a supported SSAP Engine, Profile interoperability or transport backend.
//! The old ioctl registration path is only used by an explicit daemon experiment;
//! standalone codecs/models and their regressions do not establish RF support.
pub mod hid;
pub mod profile;
pub mod transport;
