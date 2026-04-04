use libsparklink::Adapter;

/// Wraps the kernel device fd and adapter for the daemon
pub struct KernelLink {
    adapter: Adapter,
}

impl KernelLink {
    pub fn open(path: &str) -> libsparklink::Result<Self> {
        let adapter = Adapter::open(path)?;
        Ok(Self { adapter })
    }

    pub fn adapter(&self) -> &Adapter {
        &self.adapter
    }
}
