//! Internal implementation of the slktest executable, not a stable SDK API.
//! All payloads use the ordinary delegated channel fd. No Host/protocol Engine.
mod benchmark;
mod channel;
mod cli;
mod connection;

pub fn main_entry() -> anyhow::Result<()> {
    cli::main_entry()
}
