use serde::Deserialize;
use std::{
    io,
    path::{Path, PathBuf},
};

pub const DEFAULT_CONFIG: &str = "/etc/sparklink/main.conf";

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("cannot read configuration {path}: {source}")]
    Read {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("invalid configuration {path}: {source}")]
    Parse {
        path: PathBuf,
        #[source]
        source: toml::de::Error,
    },
    #[error("unsupported configuration: {0}")]
    Unsupported(&'static str),
    #[error("invalid configuration: {0}")]
    Invalid(&'static str),
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DaemonConfig {
    #[serde(default)]
    pub general: GeneralConfig,
    #[serde(default)]
    pub policy: PolicyConfig,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeneralConfig {
    /// Legacy discovery filter; native WS73 currently supports the basic policy only.
    #[serde(default = "default_discovery_level")]
    pub discovery_level: u8,
    /// Only true is supported until per-controller enable policy is implemented.
    #[serde(default = "default_true")]
    pub auto_enable: bool,
    /// Daemon adapter alias, not proof of an advertised radio name.
    #[serde(default = "default_name")]
    pub name: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyConfig {
    #[serde(default)]
    pub auto_pair: bool,
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
    /// An explicit path is mandatory, even when it equals DEFAULT_CONFIG.
    pub fn load(path: impl AsRef<Path>) -> Result<Self, ConfigError> {
        let path = path.as_ref();
        Self::finish_load(path, false, std::fs::read_to_string(path))
    }

    /// Only an absent implicit default file allows built-in defaults. Parse,
    /// permission and all other I/O errors always abort before D-Bus/ownership.
    pub fn startup(explicit: Option<&Path>) -> Result<Self, ConfigError> {
        match explicit {
            Some(path) => Self::load(path),
            None => {
                let path = Path::new(DEFAULT_CONFIG);
                Self::finish_load(path, true, std::fs::read_to_string(path))
            }
        }
    }

    fn finish_load(
        path: &Path,
        implicit_default: bool,
        read: io::Result<String>,
    ) -> Result<Self, ConfigError> {
        let config = match read {
            Err(e) if implicit_default && e.kind() == io::ErrorKind::NotFound => {
                tracing::info!(path = %path.display(), "default configuration absent; using built-in defaults");
                Self::default()
            }
            Err(source) => {
                return Err(ConfigError::Read {
                    path: path.to_owned(),
                    source,
                });
            }
            Ok(contents) => toml::from_str(&contents).map_err(|source| ConfigError::Parse {
                path: path.to_owned(),
                source,
            })?,
        };
        config.validate()?;
        Ok(config)
    }

    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.general.discovery_level > 4 {
            return Err(ConfigError::Invalid("general.discovery_level must be 0..4"));
        }
        if !self.general.auto_enable {
            return Err(ConfigError::Unsupported(
                "general.auto_enable=false: controller enable policy is not implemented",
            ));
        }
        if self.policy.auto_pair {
            return Err(ConfigError::Unsupported(
                "policy.auto_pair=true: authenticated automatic pairing is not implemented",
            ));
        }
        if self.policy.min_encryption != 0 {
            return Err(ConfigError::Unsupported(
                "policy.min_encryption must be 0 until encryption enforcement is implemented",
            ));
        }
        Ok(())
    }

    /// Reject a policy a backend cannot honor before taking its management lease.
    pub fn validate_for_profile(&self, profile: u32) -> Result<(), ConfigError> {
        self.validate()?;
        match profile {
            0 => Ok(()),
            1 if self.general.discovery_level == 1 => Ok(()),
            1 => Err(ConfigError::Unsupported(
                "native WS73 only supports discovery_level=1; configured legacy filter cannot be applied",
            )),
            _ => Err(ConfigError::Unsupported(
                "controller protocol profile is not supported by this daemon",
            )),
        }
    }
}

fn default_discovery_level() -> u8 {
    1
}
fn default_true() -> bool {
    true
}
fn default_name() -> String {
    "SparkLink".into()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn parse(text: &str) -> Result<DaemonConfig, ConfigError> {
        DaemonConfig::finish_load(Path::new("fixture.conf"), false, Ok(text.to_owned()))
    }
    #[test]
    fn supported_defaults_and_alias() {
        for text in [
            "",
            "[general]\nname='TestNode'",
            "[general]\ndiscovery_level=3\nname='TestNode'\n[policy]\nauto_pair=false\nmin_encryption=0",
        ] {
            let c = parse(text).unwrap();
            c.validate_for_profile(0).unwrap();
            assert!(c.general.auto_enable && !c.policy.auto_pair);
            assert_eq!(c.policy.min_encryption, 0);
        }
        parse("").unwrap().validate_for_profile(1).unwrap();
    }
    #[test]
    fn unsupported_policies_and_invalid_range_rejected() {
        for text in [
            "[general]\nauto_enable=false",
            "[policy]\nauto_pair=true",
            "[policy]\nmin_encryption=1",
            "[policy]\nmin_encryption=255",
        ] {
            assert!(matches!(parse(text), Err(ConfigError::Unsupported(_))));
        }
        assert!(matches!(
            parse("[general]\ndiscovery_level=5"),
            Err(ConfigError::Invalid(_))
        ));
    }
    #[test]
    fn native_does_not_ignore_legacy_filter_or_unknown_profile() {
        let c = parse("[general]\ndiscovery_level=3").unwrap();
        c.validate_for_profile(0).unwrap();
        assert!(matches!(
            c.validate_for_profile(1),
            Err(ConfigError::Unsupported(_))
        ));
        assert!(matches!(
            DaemonConfig::default().validate_for_profile(99),
            Err(ConfigError::Unsupported(_))
        ));
    }
    #[test]
    fn unknown_fields_wrong_types_and_invalid_syntax_rejected() {
        for text in [
            "[invalid",
            "bogus=true",
            "[general]\nauto_enabl=true",
            "[policy]\nmin_encrypt=0",
            "[policy]\nmin_encryption='2'",
        ] {
            assert!(matches!(parse(text), Err(ConfigError::Parse { .. })));
        }
    }
    #[test]
    fn only_missing_implicit_default_can_fall_back() {
        let path = Path::new("fixture-default.conf");
        for kind in [
            io::ErrorKind::NotFound,
            io::ErrorKind::PermissionDenied,
            io::ErrorKind::InvalidData,
            io::ErrorKind::Other,
        ] {
            for implicit in [true, false] {
                let r = DaemonConfig::finish_load(path, implicit, Err(io::Error::from(kind)));
                if implicit && kind == io::ErrorKind::NotFound {
                    r.unwrap();
                } else {
                    assert!(
                        matches!(r, Err(ConfigError::Read { source, .. }) if source.kind() == kind)
                    );
                }
            }
        }
        assert!(matches!(
            DaemonConfig::finish_load(path, true, Ok("[bad".into())),
            Err(ConfigError::Parse { .. })
        ));
    }
    #[test]
    fn explicit_missing_file_is_an_error() {
        let path =
            std::env::temp_dir().join(format!("sparklink-missing-config-{}", std::process::id()));
        assert!(!path.exists());
        assert!(
            matches!(DaemonConfig::load(path), Err(ConfigError::Read { source, .. }) if source.kind() == io::ErrorKind::NotFound)
        );
    }
}
