mod adapter;
mod error;
mod event;
pub mod ffi;

pub use adapter::Adapter;
pub use error::Error;
pub use event::Event;
pub use slk_protocol as protocol;

pub type Result<T> = std::result::Result<T, Error>;
