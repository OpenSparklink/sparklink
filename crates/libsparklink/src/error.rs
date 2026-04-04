use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    #[error("failed to open device: {0}")]
    OpenDevice(#[source] std::io::Error),

    #[error("ioctl failed: {0}")]
    Ioctl(#[source] nix::Error),

    #[error("device not found: index {0}")]
    DeviceNotFound(u16),

    #[error("connection handle {0:#06x} not found")]
    ConnectionNotFound(u16),

    #[error("invalid parameter: {0}")]
    InvalidParam(&'static str),

    #[error("operation timed out")]
    Timeout,
}

impl From<nix::Error> for Error {
    fn from(e: nix::Error) -> Self {
        Error::Ioctl(e)
    }
}
