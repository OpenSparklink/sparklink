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
    #[serde(default)]
    pub ws73: Ws73Config,
}

/// Applied only to the queried WS73 registration, before acquiring its lease.
/// Overrides use controller addresses, never unstable enumeration indices.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Ws73Config {
    #[serde(default)]
    pub defaults: Ws73PolicyConfig,
    #[serde(default)]
    pub connection: Ws73ConnectionConfig,
    #[serde(default)]
    pub adapters: Vec<Ws73AdapterConfig>,
}

/// Explicit WS73 111 candidate policy from the reference Host. This is
/// configurable application policy, not a hardware capability/RF claim.
#[derive(Debug, Clone, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Ws73ConnectionConfig {
    pub filter: u32,
    pub own_address_type: u32,
    pub gt_negotiate: u32,
    pub frame: u32,
    pub scan_interval: u32,
    pub scan_window: u32,
    pub interval_min: u32,
    pub interval_max: u32,
    pub latency: u32,
    pub supervision_timeout: u32,
    pub event_min: u32,
    pub event_max: u32,
    pub timeout_ms: u32,
}
impl Default for Ws73ConnectionConfig {
    fn default() -> Self {
        Self {
            filter: 0,
            own_address_type: 0,
            gt_negotiate: 1,
            frame: 1,
            scan_interval: 32,
            scan_window: 32,
            interval_min: 12,
            interval_max: 12,
            latency: 0,
            supervision_timeout: 508,
            event_min: 0,
            event_max: 0,
            timeout_ms: 10000,
        }
    }
}
impl Ws73ConnectionConfig {
    pub fn parameters(&self) -> slk_protocol::SleConnectionParameters {
        slk_protocol::SleConnectionParameters {
            filter: self.filter,
            own_address_type: self.own_address_type,
            gt_negotiate: self.gt_negotiate,
            frame: self.frame,
            scan_interval: self.scan_interval,
            scan_window: self.scan_window,
            interval_min: self.interval_min,
            interval_max: self.interval_max,
            latency: self.latency,
            supervision_timeout: self.supervision_timeout,
            event_min: self.event_min,
            event_max: self.event_max,
            ..Default::default()
        }
    }
    fn validate(&self) -> Result<(), ConfigError> {
        if self.filter > 1
            || self.own_address_type > 255
            || self.gt_negotiate > 3
            || self.frame != 1
            || self.scan_interval == 0
            || self.scan_interval > 65535
            || self.scan_window == 0
            || self.scan_window > self.scan_interval
            || self.interval_min == 0
            || self.interval_min > self.interval_max
            || self.interval_max > 65535
            || self.latency > 65535
            || self.supervision_timeout == 0
            || self.supervision_timeout > 65535
            || self.event_min > self.event_max
            || self.event_max > 65535
            || !(1..=10000).contains(&self.timeout_ms)
        {
            return Err(ConfigError::Invalid("invalid ws73 connection policy"));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Ws73AdapterConfig {
    pub address: String,
    pub policy: Ws73PolicyConfig,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Ws73PolicyConfig {
    pub advertising_interval_min_slots: u32,
    pub advertising_interval_max_slots: u32,
    pub tx_power_dbm: i32,
    pub scan_interval_slots: u32,
    pub scan_window_slots: u32,
}

impl Default for Ws73PolicyConfig {
    fn default() -> Self {
        let (_, min, max, power, interval, window) =
            libsparklink::Ws73DiscoveryPolicy::default().parameters();
        Self {
            advertising_interval_min_slots: min,
            advertising_interval_max_slots: max,
            tx_power_dbm: power,
            scan_interval_slots: interval,
            scan_window_slots: window,
        }
    }
}

impl Ws73PolicyConfig {
    fn build(&self) -> Result<libsparklink::Ws73DiscoveryPolicy, ConfigError> {
        libsparklink::Ws73DiscoveryPolicy::new(
            self.advertising_interval_min_slots,
            self.advertising_interval_max_slots,
            self.tx_power_dbm,
            self.scan_interval_slots,
            self.scan_window_slots,
        )
        .map_err(|_| ConfigError::Invalid("ws73 policy has invalid slots, ordering or TX power"))
    }
}

fn ws73_address(text: &str) -> Result<[u8; 6], ConfigError> {
    let mut address = [0; 6];
    let mut parts = text.split(':');
    for byte in &mut address {
        let part = parts
            .next()
            .ok_or(ConfigError::Invalid("invalid ws73 adapter address"))?;
        if part.len() != 2 || !part.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err(ConfigError::Invalid("invalid ws73 adapter address"));
        }
        *byte = u8::from_str_radix(part, 16)
            .map_err(|_| ConfigError::Invalid("invalid ws73 adapter address"))?;
    }
    if parts.next().is_some() || address == [0; 6] {
        return Err(ConfigError::Invalid("invalid ws73 adapter address"));
    }
    Ok(address)
}

impl Ws73Config {
    /// Offline host configuration only, never firmware or RF qualification.
    pub fn diagnostic_policies(&self) -> Result<String, ConfigError> {
        self.validate()?;
        let line = |prefix: &str, policy: libsparklink::Ws73DiscoveryPolicy| {
            let (version, min, max, power, interval, window) = policy.parameters();
            format!(
                "{prefix} version={version} adv_slots={min}..{max} tx_power_dbm={power} scan_slots={interval}/{window}\n"
            )
        };
        let mut result = line("Ws73DefaultPolicy:", self.defaults.build()?);
        for adapter in &self.adapters {
            let address = ws73_address(&adapter.address)?;
            let text = address
                .iter()
                .map(|b| format!("{b:02X}"))
                .collect::<Vec<_>>()
                .join(":");
            result.push_str(&line(
                &format!("Ws73AdapterPolicy: address={text}"),
                self.for_address(address)?,
            ));
        }
        Ok(result)
    }

    fn validate(&self) -> Result<(), ConfigError> {
        self.connection.validate()?;
        self.defaults.build()?;
        let mut addresses = std::collections::BTreeSet::new();
        for adapter in &self.adapters {
            if !addresses.insert(ws73_address(&adapter.address)?) {
                return Err(ConfigError::Invalid("duplicate ws73 adapter address"));
            }
            adapter.policy.build()?;
        }
        Ok(())
    }

    pub fn for_address(
        &self,
        address: [u8; 6],
    ) -> Result<libsparklink::Ws73DiscoveryPolicy, ConfigError> {
        self.validate()?;
        if address == [0; 6] {
            return Err(ConfigError::Invalid(
                "WS73 policy requires queried nonzero address",
            ));
        }
        for adapter in &self.adapters {
            if ws73_address(&adapter.address)? == address {
                return adapter.policy.build();
            }
        }
        self.defaults.build()
    }
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
        self.ws73.validate()?;
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
    #[test]
    fn ws73_overrides_are_address_scoped_and_do_not_mutate_defaults() {
        let c = parse("[ws73.defaults]\ntx_power_dbm=0\n[[ws73.adapters]]\naddress='00:01:09:32:54:cD'\n[ws73.adapters.policy]\nadvertising_interval_min_slots=1237\nadvertising_interval_max_slots=1301\ntx_power_dbm=-20\n").unwrap();
        let a = [0, 1, 9, 0x32, 0x54, 0xcd];
        let b = [0, 1, 9, 0x30, 0xd1, 0xac];
        let first = c.ws73.for_address(a).unwrap();
        assert_eq!(first.parameters(), (3, 1237, 1301, -20, 1600, 800));
        assert_eq!(
            c.ws73.for_address(b).unwrap().parameters(),
            (3, 1200, 1200, 0, 1600, 800)
        );
        assert_eq!(c.ws73.for_address(a).unwrap(), first);
        assert!(c.ws73.for_address([0; 6]).is_err());
    }
    #[test]
    fn ws73_invalid_and_ambiguous_policies_never_fall_back() {
        for text in [
            "[ws73.defaults]\nadvertising_interval_min_slots=31",
            "[ws73.defaults]\nadvertising_interval_min_slots=1300",
            "[ws73.defaults]\ntx_power_dbm=21",
            "[ws73.defaults]\nscan_window_slots=1601",
            "[[ws73.adapters]]\naddress='00:00:00:00:00:00'\npolicy={}",
            "[[ws73.adapters]]\naddress='0:01:09:32:54:CD'\npolicy={}",
            "[[ws73.adapters]]\naddress='00:01:09:32:54:CD'\npolicy={}\n[[ws73.adapters]]\naddress='00:01:09:32:54:cd'\npolicy={}",
            "[[ws73.adapters]]\naddress='00:01:09:32:54:CD'\npolicy={tx_power_dbm=126}",
        ] {
            assert!(
                matches!(parse(text), Err(ConfigError::Invalid(_))),
                "{text}"
            );
        }
        for text in [
            "[ws73.defaults]\nscan_window_slot=800",
            "[ws73.defaults]\nscan_window_slots=-1",
            "[[ws73.adapters]]\naddress='00:01:09:32:54:CD'",
            "[[ws73.adapters]]\naddress='00:01:09:32:54:CD'\npolicy={bad=true}",
        ] {
            assert!(
                matches!(parse(text), Err(ConfigError::Parse { .. })),
                "{text}"
            );
        }
    }
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
