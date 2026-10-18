use slk_native::Adapter;

/// Wraps the kernel device fd and adapter for the daemon
pub struct KernelLink {
    adapter: Adapter,
}

impl KernelLink {
    pub fn open(path: &str) -> slk_native::Result<Self> {
        let adapter = Adapter::open(path)?;
        Ok(Self { adapter })
    }

    pub fn adapter(&self) -> &Adapter {
        &self.adapter
    }

    pub fn into_adapter(self) -> Adapter {
        self.adapter
    }
}
