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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config() {
        let cfg = DaemonConfig::default();
        assert_eq!(cfg.general.discovery_level, 1);
        assert!(cfg.general.auto_enable);
        assert_eq!(cfg.general.name, "SparkLink");
        assert!(!cfg.policy.auto_pair);
        assert_eq!(cfg.policy.min_encryption, 0);
    }

    #[test]
    fn parse_empty_toml() {
        let cfg: DaemonConfig = toml::from_str("").unwrap();
        assert_eq!(cfg.general.discovery_level, 1);
        assert!(cfg.general.auto_enable);
        assert_eq!(cfg.general.name, "SparkLink");
    }

    #[test]
    fn parse_full_toml() {
        let toml_str = r#"
[general]
discovery_level = 3
auto_enable = false
name = "MyDevice"

[policy]
auto_pair = true
min_encryption = 2
"#;
        let cfg: DaemonConfig = toml::from_str(toml_str).unwrap();
        assert_eq!(cfg.general.discovery_level, 3);
        assert!(!cfg.general.auto_enable);
        assert_eq!(cfg.general.name, "MyDevice");
        assert!(cfg.policy.auto_pair);
        assert_eq!(cfg.policy.min_encryption, 2);
    }

    #[test]
    fn parse_partial_toml() {
        let toml_str = r#"
[general]
name = "TestNode"
"#;
        let cfg: DaemonConfig = toml::from_str(toml_str).unwrap();
        assert_eq!(cfg.general.name, "TestNode");
        assert_eq!(cfg.general.discovery_level, 1); // default
        assert!(cfg.general.auto_enable); // default
        assert!(!cfg.policy.auto_pair); // default
    }

    #[test]
    fn load_nonexistent_file() {
        let result = DaemonConfig::load("/tmp/sparklink_nonexistent_cfg.toml");
        assert!(result.is_err());
    }

    #[test]
    fn parse_invalid_toml() {
        let result: Result<DaemonConfig, _> = toml::from_str("[invalid");
        assert!(result.is_err());
    }
}
