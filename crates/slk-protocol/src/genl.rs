/// Optional registry-only Generic Netlink; no controller or event transport.
pub const GENL_FAMILY_NAME: &str = "sparklink";
pub const GENL_VERSION: u8 = 2;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum GenlCmd {
    Unspec = 0,
    GetRegistryCount = 1,
    // Removed unpublished numbers are not reused.
    GetVersion = 28,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u16)]
pub enum GenlAttr {
    Unspec = 0,
    DevCount = 5,
    ProtoVersion = 6,
    GenlVersion = 7,
}
