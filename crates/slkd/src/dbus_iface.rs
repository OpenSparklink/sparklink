use zbus::interface;

use crate::config::DaemonConfig;

/// Root D-Bus object at /org/sparklink
pub struct Root {
    config: DaemonConfig,
}

impl Root {
    pub fn new(config: DaemonConfig) -> Self {
        Self { config }
    }
}

#[interface(name = "org.sparklink.Manager")]
impl Root {
    /// Get the daemon version
    fn version(&self) -> &str {
        env!("CARGO_PKG_VERSION")
    }

    /// List available adapter object paths
    async fn list_adapters(&self) -> Vec<String> {
        // TODO: enumerate real adapters
        vec!["/org/sparklink/slk0".into()]
    }
}

/// Adapter D-Bus object at /org/sparklink/slk0
pub struct AdapterIface {
    powered: bool,
    discovering: bool,
    name: String,
}

impl AdapterIface {
    pub fn new(name: String) -> Self {
        Self {
            powered: false,
            discovering: false,
            name,
        }
    }
}

#[interface(name = "org.sparklink.Adapter")]
impl AdapterIface {
    /// Start device discovery (scanning)
    async fn start_discovery(&mut self) -> zbus::fdo::Result<()> {
        self.discovering = true;
        // TODO: invoke kernel scan
        Ok(())
    }

    /// Stop device discovery
    async fn stop_discovery(&mut self) -> zbus::fdo::Result<()> {
        self.discovering = false;
        Ok(())
    }

    /// Adapter power state
    #[zbus(property)]
    fn powered(&self) -> bool {
        self.powered
    }

    #[zbus(property)]
    fn set_powered(&mut self, value: bool) {
        self.powered = value;
        // TODO: invoke kernel power on/off
    }

    /// Whether discovery is active
    #[zbus(property)]
    fn discovering(&self) -> bool {
        self.discovering
    }

    /// Adapter name
    #[zbus(property)]
    fn name(&self) -> &str {
        &self.name
    }
}
