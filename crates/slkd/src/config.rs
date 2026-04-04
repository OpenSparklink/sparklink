use serde::Deserialize;
use std::path::Path;

#[derive(Debug, Default, Deserialize)]
pub struct DaemonConfig {
    #[serde(default)]
    pub general: GeneralConfig,

    #[serde(default)]
    pub policy: PolicyConfig,
}

#[derive(Debug, Deserialize)]
pub struct GeneralConfig {
    /// Default discovery level for this adapter
    #[serde(default = "default_discovery_level")]
    pub discovery_level: u8,

    /// Auto-power-on at startup
    #[serde(default = "default_true")]
    pub auto_enable: bool,

    /// Default device name
    #[serde(default = "default_name")]
    pub name: String,
}

#[derive(Debug, Default, Deserialize)]
pub struct PolicyConfig {
    /// Auto-pair with JustWorks when possible
    #[serde(default)]
    pub auto_pair: bool,

    /// Minimum encryption level required
    #[serde(default)]
    pub min_encryption: u8,
}


impl Default for GeneralConfig {
    fn default() -> Self {
        Self {
            discovery_level: 1,
            auto_enable: true,
            name: "SparkLink".into(),
        }
    }
}


impl DaemonConfig {
    pub fn load(path: impl AsRef<Path>) -> Result<Self, Box<dyn std::error::Error>> {
        let contents = std::fs::read_to_string(path)?;
        let config: Self = toml::from_str(&contents)?;
        Ok(config)
    }
}

fn default_discovery_level() -> u8 { 1 }
fn default_true() -> bool { true }
fn default_name() -> String { "SparkLink".into() }
