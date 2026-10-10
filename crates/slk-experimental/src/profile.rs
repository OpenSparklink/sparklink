//! Legacy kernel-SSAP Profile development model. Request callbacks are not
//! routed by slkd; UUID/permission/interop qualification remains outstanding.
use std::collections::HashMap;

use libsparklink::Adapter;
use slk_protocol::SsapOperations;

/// Definition of a characteristic to register with the SSAP database
#[derive(Debug, Clone)]
pub struct CharacteristicDef {
    pub uuid16: u16,
    /// Validated standard operations; legacy narrowing is explicit.
    pub ops: SsapOperations,
    pub initial_value: Vec<u8>,
}

/// Profile plugin interface
///
/// Each profile represents a self-contained SSAP service (similar to a
/// Bluetooth LE GATT profile). The daemon discovers registered profiles at
/// startup and delegates read/write/notification events to the corresponding
/// profile implementation.
pub trait Profile: Send + Sync {
    /// Human-readable profile name (e.g. "battery", "device_info")
    fn name(&self) -> &str;

    /// Primary service UUID16
    fn uuid16(&self) -> u16;

    /// Characteristics that belong to this profile
    fn characteristics(&self) -> Vec<CharacteristicDef>;

    /// Called once after the service and its characteristics have been
    /// registered in the SSAP database.  `handles` maps each characteristic
    /// UUID16 to the assigned handle.
    fn on_registered(&mut self, _handles: &HashMap<u16, u16>) {}

    /// Handle a read request for the given characteristic handle.
    /// Return the value to send back.
    fn on_read(&self, handle: u16) -> Result<Vec<u8>, ProfileError>;

    /// Handle a write request.
    fn on_write(&mut self, handle: u16, data: &[u8]) -> Result<(), ProfileError>;

    /// Called when a new peer connection is established.
    fn on_connect(&mut self, _conn_handle: u16) {}

    /// Called when a peer disconnects.
    fn on_disconnect(&mut self, _conn_handle: u16) {}
}

#[derive(Debug)]
pub enum ProfileError {
    NotSupported,
    InvalidValue,
    Io(String),
}

impl std::fmt::Display for ProfileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotSupported => write!(f, "operation not supported"),
            Self::InvalidValue => write!(f, "invalid value"),
            Self::Io(msg) => write!(f, "I/O error: {msg}"),
        }
    }
}

impl std::error::Error for ProfileError {}

/// Manages profile registration and lifecycle
#[derive(Default)]
pub struct ProfileRegistry {
    profiles: Vec<Box<dyn Profile>>,
    /// Maps SSAP handle -> profile index
    handle_map: HashMap<u16, usize>,
}

impl ProfileRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a profile.  Call before `init_all`.
    pub fn add(&mut self, profile: Box<dyn Profile>) {
        self.profiles.push(profile);
    }

    /// Register all profile services and characteristics with the adapter's
    /// SSAP database.  Returns the number of profiles successfully registered.
    pub fn init_all(&mut self, adapter: &Adapter) -> usize {
        let mut count = 0;
        for (idx, profile) in self.profiles.iter_mut().enumerate() {
            let chars = profile.characteristics();
            let properties = chars
                .iter()
                .map(|ch| {
                    slk_protocol::SsapAddProperty::for_legacy_staging(
                        ch.uuid16,
                        ch.ops,
                        &ch.initial_value,
                    )
                })
                .collect::<Result<Vec<_>, _>>();
            let properties = match properties {
                Ok(properties) => properties,
                Err(e) => {
                    tracing::warn!(profile = profile.name(), %e, "invalid legacy property definitions");
                    continue;
                }
            };
            let mut svc = slk_protocol::SsapAddService {
                uuid16: profile.uuid16(),
                primary: 1,
                _pad: 0,
                uuid128: [0; 16],
                start_handle: 0,
                _reserved: [0; 6],
            };
            if let Err(e) = adapter.ssap_add_svc(&mut svc) {
                tracing::warn!(profile = profile.name(), %e, "failed to add service");
                continue;
            }

            let mut handles = HashMap::new();
            let mut ok = true;
            for (ch, mut prop) in chars.iter().zip(properties) {
                if let Err(e) = adapter.ssap_add_prop(&mut prop) {
                    tracing::warn!(
                        profile = profile.name(),
                        uuid = ch.uuid16,
                        %e,
                        "failed to add property"
                    );
                    ok = false;
                    break;
                }
                handles.insert(ch.uuid16, prop.handle);
                self.handle_map.insert(prop.handle, idx);
            }

            if ok {
                profile.on_registered(&handles);
                count += 1;
                tracing::info!(
                    name = profile.name(),
                    uuid = format!("0x{:04X}", profile.uuid16()),
                    chars = chars.len(),
                    "profile registered"
                );
            }
        }
        count
    }

    /// Dispatch a read to the owning profile
    pub fn dispatch_read(&self, handle: u16) -> Result<Vec<u8>, ProfileError> {
        let idx = self
            .handle_map
            .get(&handle)
            .ok_or(ProfileError::NotSupported)?;
        self.profiles[*idx].on_read(handle)
    }

    /// Dispatch a write to the owning profile
    pub fn dispatch_write(&mut self, handle: u16, data: &[u8]) -> Result<(), ProfileError> {
        let idx = *self
            .handle_map
            .get(&handle)
            .ok_or(ProfileError::NotSupported)?;
        self.profiles[idx].on_write(handle, data)
    }

    /// Notify all profiles of a new connection
    pub fn on_connect(&mut self, conn_handle: u16) {
        for p in &mut self.profiles {
            p.on_connect(conn_handle);
        }
    }

    /// Notify all profiles of a disconnection
    pub fn on_disconnect(&mut self, conn_handle: u16) {
        for p in &mut self.profiles {
            p.on_disconnect(conn_handle);
        }
    }

    /// List registered profile names
    pub fn list(&self) -> Vec<&str> {
        self.profiles.iter().map(|p| p.name()).collect()
    }

    /// Number of registered profiles
    pub fn count(&self) -> usize {
        self.profiles.len()
    }
}

// ---------------------------------------------------------------------------
// Built-in: Battery Service (UUID 0x060A)
// ---------------------------------------------------------------------------

/// Minimal Battery Service profile.
///
/// Exposes a single read-only characteristic (Battery Level, UUID 0x1034)
/// with notify capability.
pub struct BatteryProfile {
    level: u8,
    handle: Option<u16>,
}

impl BatteryProfile {
    pub fn new(initial_level: u8) -> Self {
        Self {
            level: initial_level.min(100),
            handle: None,
        }
    }
}

impl Profile for BatteryProfile {
    fn name(&self) -> &str {
        "battery"
    }
    fn uuid16(&self) -> u16 {
        0x060A
    }

    fn characteristics(&self) -> Vec<CharacteristicDef> {
        vec![CharacteristicDef {
            uuid16: 0x1034, // Battery Level
            ops: SsapOperations::READ | SsapOperations::NOTIFY,
            initial_value: vec![self.level],
        }]
    }

    fn on_registered(&mut self, handles: &HashMap<u16, u16>) {
        self.handle = handles.get(&0x1034).copied();
    }

    fn on_read(&self, _handle: u16) -> Result<Vec<u8>, ProfileError> {
        Ok(vec![self.level])
    }

    fn on_write(&mut self, _handle: u16, _data: &[u8]) -> Result<(), ProfileError> {
        Err(ProfileError::NotSupported)
    }
}

// ---------------------------------------------------------------------------
// Built-in: Device Information Service (UUID 0x180A)
// ---------------------------------------------------------------------------

/// Device Information Service profile.
///
/// Exposes read-only characteristics for manufacturer, model, firmware and
/// software revision.
pub struct DeviceInfoProfile {
    manufacturer: String,
    model: String,
    firmware_rev: String,
    software_rev: String,
}

impl Default for DeviceInfoProfile {
    fn default() -> Self {
        Self::new()
    }
}

impl DeviceInfoProfile {
    pub fn new() -> Self {
        Self {
            manufacturer: "SparkLink".into(),
            model: env!("CARGO_PKG_NAME").into(),
            firmware_rev: "1.0".into(),
            software_rev: env!("CARGO_PKG_VERSION").into(),
        }
    }
}

impl Profile for DeviceInfoProfile {
    fn name(&self) -> &str {
        "device_info"
    }
    fn uuid16(&self) -> u16 {
        0x180A
    }

    fn characteristics(&self) -> Vec<CharacteristicDef> {
        vec![
            CharacteristicDef {
                uuid16: 0x2A29, // Manufacturer Name
                ops: SsapOperations::READ,
                initial_value: self.manufacturer.as_bytes().to_vec(),
            },
            CharacteristicDef {
                uuid16: 0x2A24, // Model Number
                ops: SsapOperations::READ,
                initial_value: self.model.as_bytes().to_vec(),
            },
            CharacteristicDef {
                uuid16: 0x2A26, // Firmware Revision
                ops: SsapOperations::READ,
                initial_value: self.firmware_rev.as_bytes().to_vec(),
            },
            CharacteristicDef {
                uuid16: 0x2A28, // Software Revision
                ops: SsapOperations::READ,
                initial_value: self.software_rev.as_bytes().to_vec(),
            },
        ]
    }

    fn on_read(&self, _handle: u16) -> Result<Vec<u8>, ProfileError> {
        // The SSAP database already holds the values set during registration,
        // so reads go through the kernel.  This callback is a fallback.
        Ok(Vec::new())
    }

    fn on_write(&mut self, _handle: u16, _data: &[u8]) -> Result<(), ProfileError> {
        Err(ProfileError::NotSupported)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn battery_profile_read() {
        let p = BatteryProfile::new(85);
        assert_eq!(p.name(), "battery");
        assert_eq!(p.uuid16(), 0x060A);
        let chars = p.characteristics();
        assert_eq!(chars[0].ops.bits(), 9);
        assert!(!chars[0].ops.contains(SsapOperations::WRITE_NO_RSP));
        assert!(!chars[0].ops.contains(SsapOperations::WRITE_WITH_RSP));
        assert_eq!(chars.len(), 1);
        assert_eq!(chars[0].uuid16, 0x1034);
        assert_eq!(p.on_read(0).unwrap(), vec![85]);
    }

    #[test]
    fn battery_profile_write_rejected() {
        let mut p = BatteryProfile::new(50);
        assert!(p.on_write(0, &[42]).is_err());
    }

    #[test]
    fn device_info_profile_chars() {
        let p = DeviceInfoProfile::new();
        assert_eq!(p.name(), "device_info");
        assert_eq!(p.uuid16(), 0x180A);
        let chars = p.characteristics();
        assert_eq!(chars.len(), 4);
        // All characteristics are read-only
        for ch in &chars {
            assert!(!ch.ops.contains(SsapOperations::WRITE_NO_RSP));
            assert!(!ch.ops.contains(SsapOperations::WRITE_WITH_RSP));
        }
    }

    #[test]
    fn registry_add_and_list() {
        let mut reg = ProfileRegistry::new();
        reg.add(Box::new(BatteryProfile::new(100)));
        reg.add(Box::new(DeviceInfoProfile::new()));
        assert_eq!(reg.count(), 2);
        let names = reg.list();
        assert!(names.contains(&"battery"));
        assert!(names.contains(&"device_info"));
    }

    #[test]
    fn registry_dispatch_unregistered_handle() {
        let reg = ProfileRegistry::new();
        assert!(reg.dispatch_read(0x1234).is_err());
    }
}
