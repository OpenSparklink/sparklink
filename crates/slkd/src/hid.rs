//! SparkLink HID Profile (T/XS 30013-2025)
//!
//! Implements the "人机数据交互" (HID Data Interaction) service as defined in
//! the SparkLink USB HID Application Configuration and Management standard.
//!
//! Service UUID: 0x0003 (application-layer assignment)
//!
//! Mandatory characteristics:
//!   - Type and Format Description (0x1010) — read
//!   - Report Index Info (0x1011) — read
//!   - Input Report (0x1012) — read + notify
//!
//! Optional characteristics:
//!   - Working Status Indicator (0x1013) — read + write
//!   - Output Report (0x1014) — write
//!   - Feature Report (0x1015) — read + write

use std::collections::HashMap;
use std::sync::Mutex;

use crate::profile::{CharacteristicDef, Profile, ProfileError};

/// HID device type identifiers as defined in T/XS 30013-2025 section 7.2
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum HidDeviceType {
    Keyboard = 0x01,
    Mouse = 0x02,
    GenericHid = 0x03,
    Stylus = 0x04,
    Mouse1Khz = 0x05,
    Mouse2Khz = 0x06,
    Mouse4Khz = 0x07,
}

impl HidDeviceType {
    pub fn label(self) -> &'static str {
        match self {
            Self::Keyboard => "USB Standard Keyboard",
            Self::Mouse => "USB Standard Mouse",
            Self::GenericHid => "USB HID Device",
            Self::Stylus => "High-precision Stylus",
            Self::Mouse1Khz => "1KHz Mouse",
            Self::Mouse2Khz => "2KHz Mouse",
            Self::Mouse4Khz => "4KHz Mouse",
        }
    }
}

/// HID working status
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum HidStatus {
    Idle = 0x00,
    Active = 0x01,
    Suspended = 0x02,
}

// Characteristic UUID assignments (application-layer range 0x1000-0x6FFF)
const UUID_TYPE_FORMAT: u16 = 0x1010;
const UUID_REPORT_INDEX: u16 = 0x1011;
const UUID_INPUT_REPORT: u16 = 0x1012;
const UUID_STATUS: u16 = 0x1013;
const UUID_OUTPUT_REPORT: u16 = 0x1014;
const UUID_FEATURE_REPORT: u16 = 0x1015;

/// HID service UUID (application-layer range 0x0002-0x0FFF)
const HID_SERVICE_UUID: u16 = 0x0003;

/// SparkLink HID Data Interaction profile.
///
/// Implements the server side of the HID service, managing report
/// descriptors and I/O report buffers.  The input report buffer is
/// updated via `set_input_report` and delivered to the peer through
/// SSAP notification.
pub struct HidProfile {
    device_type: HidDeviceType,
    status: HidStatus,
    /// USB HID Report Descriptor (type and format description)
    report_descriptor: Vec<u8>,
    /// Current input report data (sent via notification)
    input_report: Mutex<Vec<u8>>,
    /// Last received output report data
    output_report: Mutex<Vec<u8>>,
    /// Feature report data
    feature_report: Mutex<Vec<u8>>,
    /// Assigned SSAP handles after registration
    handles: HashMap<u16, u16>,
}

impl HidProfile {
    /// Create a new HID profile instance.
    ///
    /// `device_type` — the HID device category (keyboard, mouse, etc.)
    /// `report_descriptor` — the USB HID Report Descriptor bytes that
    ///   describe the data format of input/output/feature reports.
    pub fn new(device_type: HidDeviceType, report_descriptor: Vec<u8>) -> Self {
        Self {
            device_type,
            status: HidStatus::Idle,
            report_descriptor,
            input_report: Mutex::new(Vec::new()),
            output_report: Mutex::new(Vec::new()),
            feature_report: Mutex::new(Vec::new()),
            handles: HashMap::new(),
        }
    }

    /// Create a minimal boot keyboard profile with standard report descriptor.
    pub fn boot_keyboard() -> Self {
        // Minimal USB HID Boot Keyboard descriptor: 8-byte input report
        // (modifier, reserved, 6 keycodes), 1-byte output (LEDs)
        let descriptor = vec![
            0x05, 0x01, // Usage Page (Generic Desktop)
            0x09, 0x06, // Usage (Keyboard)
            0xA1, 0x01, // Collection (Application)
            0x05, 0x07, //   Usage Page (Key Codes)
            0x19, 0xE0, //   Usage Minimum (224)
            0x29, 0xE7, //   Usage Maximum (231)
            0x15, 0x00, //   Logical Minimum (0)
            0x25, 0x01, //   Logical Maximum (1)
            0x75, 0x01, //   Report Size (1)
            0x95, 0x08, //   Report Count (8)
            0x81, 0x02, //   Input (Data, Variable, Absolute) — Modifier keys
            0x95, 0x01, //   Report Count (1)
            0x75, 0x08, //   Report Size (8)
            0x81, 0x01, //   Input (Constant) — Reserved byte
            0x95, 0x06, //   Report Count (6)
            0x75, 0x08, //   Report Size (8)
            0x15, 0x00, //   Logical Minimum (0)
            0x25, 0x65, //   Logical Maximum (101)
            0x05, 0x07, //   Usage Page (Key Codes)
            0x19, 0x00, //   Usage Minimum (0)
            0x29, 0x65, //   Usage Maximum (101)
            0x81, 0x00, //   Input (Data, Array) — Key array
            0x95, 0x01, //   Report Count (1)
            0x75, 0x08, //   Report Size (8)
            0x05, 0x08, //   Usage Page (LEDs)
            0x19, 0x01, //   Usage Minimum (1)
            0x29, 0x05, //   Usage Maximum (5)
            0x91, 0x02, //   Output (Data, Variable, Absolute) — LED state
            0xC0,       // End Collection
        ];
        let mut p = Self::new(HidDeviceType::Keyboard, descriptor);
        *p.input_report.get_mut().unwrap() = vec![0u8; 8]; // 8-byte boot report
        *p.output_report.get_mut().unwrap() = vec![0u8; 1]; // 1-byte LED
        p
    }

    /// Create a minimal boot mouse profile with standard report descriptor.
    pub fn boot_mouse() -> Self {
        let descriptor = vec![
            0x05, 0x01, // Usage Page (Generic Desktop)
            0x09, 0x02, // Usage (Mouse)
            0xA1, 0x01, // Collection (Application)
            0x09, 0x01, //   Usage (Pointer)
            0xA1, 0x00, //   Collection (Physical)
            0x05, 0x09, //     Usage Page (Button)
            0x19, 0x01, //     Usage Minimum (1)
            0x29, 0x03, //     Usage Maximum (3)
            0x15, 0x00, //     Logical Minimum (0)
            0x25, 0x01, //     Logical Maximum (1)
            0x95, 0x03, //     Report Count (3)
            0x75, 0x01, //     Report Size (1)
            0x81, 0x02, //     Input (Data, Variable, Absolute) — Buttons
            0x95, 0x01, //     Report Count (1)
            0x75, 0x05, //     Report Size (5)
            0x81, 0x01, //     Input (Constant) — Padding
            0x05, 0x01, //     Usage Page (Generic Desktop)
            0x09, 0x30, //     Usage (X)
            0x09, 0x31, //     Usage (Y)
            0x15, 0x81, //     Logical Minimum (-127)
            0x25, 0x7F, //     Logical Maximum (127)
            0x75, 0x08, //     Report Size (8)
            0x95, 0x02, //     Report Count (2)
            0x81, 0x06, //     Input (Data, Variable, Relative) — X, Y
            0xC0,       //   End Collection
            0xC0,       // End Collection
        ];
        let mut p = Self::new(HidDeviceType::Mouse, descriptor);
        *p.input_report.get_mut().unwrap() = vec![0u8; 3]; // buttons + X + Y
        p
    }

    /// Update the input report data.  The daemon should call this when
    /// new HID data arrives, then trigger an SSAP notification on the
    /// input report handle.
    pub fn set_input_report(&self, data: Vec<u8>) {
        if let Ok(mut buf) = self.input_report.lock() {
            *buf = data;
        }
    }

    /// Read the last output report received from the host.
    pub fn get_output_report(&self) -> Vec<u8> {
        self.output_report.lock().map(|b| b.clone()).unwrap_or_default()
    }

    /// Get the device type.
    pub fn device_type(&self) -> HidDeviceType {
        self.device_type
    }

    /// Get the input report handle (if registered).
    pub fn input_report_handle(&self) -> Option<u16> {
        self.handles.get(&UUID_INPUT_REPORT).copied()
    }
}

impl Profile for HidProfile {
    fn name(&self) -> &str { "hid" }
    fn uuid16(&self) -> u16 { HID_SERVICE_UUID }

    fn characteristics(&self) -> Vec<CharacteristicDef> {
        vec![
            // Type and Format Description — mandatory, read-only
            CharacteristicDef {
                uuid16: UUID_TYPE_FORMAT,
                ops: 0x01, // read
                initial_value: self.report_descriptor.clone(),
            },
            // Report Index — mandatory, read-only
            // Byte 0: device type, Byte 1: report count
            CharacteristicDef {
                uuid16: UUID_REPORT_INDEX,
                ops: 0x01, // read
                initial_value: vec![self.device_type as u8, 0x01],
            },
            // Input Report — mandatory, read + notify
            CharacteristicDef {
                uuid16: UUID_INPUT_REPORT,
                ops: 0x01 | 0x04, // read + notify
                initial_value: self.input_report.lock()
                    .map(|b| b.clone()).unwrap_or_default(),
            },
            // Working Status — optional, read + write
            CharacteristicDef {
                uuid16: UUID_STATUS,
                ops: 0x01 | 0x02, // read + write
                initial_value: vec![self.status as u8],
            },
            // Output Report — optional, write only
            CharacteristicDef {
                uuid16: UUID_OUTPUT_REPORT,
                ops: 0x02, // write
                initial_value: self.output_report.lock()
                    .map(|b| b.clone()).unwrap_or_default(),
            },
            // Feature Report — optional, read + write
            CharacteristicDef {
                uuid16: UUID_FEATURE_REPORT,
                ops: 0x01 | 0x02, // read + write
                initial_value: self.feature_report.lock()
                    .map(|b| b.clone()).unwrap_or_default(),
            },
        ]
    }

    fn on_registered(&mut self, handles: &HashMap<u16, u16>) {
        self.handles = handles.clone();
        tracing::info!(
            device_type = self.device_type.label(),
            chars = handles.len(),
            "HID profile registered"
        );
    }

    fn on_read(&self, handle: u16) -> Result<Vec<u8>, ProfileError> {
        // Reverse-map handle to characteristic UUID
        let uuid = self.handles.iter()
            .find(|(_, h)| **h == handle)
            .map(|(&u, _)| u)
            .ok_or(ProfileError::NotSupported)?;

        match uuid {
            UUID_TYPE_FORMAT => Ok(self.report_descriptor.clone()),
            UUID_REPORT_INDEX => Ok(vec![self.device_type as u8, 0x01]),
            UUID_INPUT_REPORT => {
                Ok(self.input_report.lock()
                    .map(|b| b.clone())
                    .unwrap_or_default())
            }
            UUID_STATUS => Ok(vec![self.status as u8]),
            UUID_OUTPUT_REPORT => {
                Ok(self.output_report.lock()
                    .map(|b| b.clone())
                    .unwrap_or_default())
            }
            UUID_FEATURE_REPORT => {
                Ok(self.feature_report.lock()
                    .map(|b| b.clone())
                    .unwrap_or_default())
            }
            _ => Err(ProfileError::NotSupported),
        }
    }

    fn on_write(&mut self, handle: u16, data: &[u8]) -> Result<(), ProfileError> {
        let uuid = self.handles.iter()
            .find(|(_, h)| **h == handle)
            .map(|(&u, _)| u)
            .ok_or(ProfileError::NotSupported)?;

        match uuid {
            UUID_STATUS => {
                if data.len() != 1 {
                    return Err(ProfileError::InvalidValue);
                }
                self.status = match data[0] {
                    0x00 => HidStatus::Idle,
                    0x01 => HidStatus::Active,
                    0x02 => HidStatus::Suspended,
                    _ => return Err(ProfileError::InvalidValue),
                };
                Ok(())
            }
            UUID_OUTPUT_REPORT => {
                if let Ok(mut buf) = self.output_report.lock() {
                    *buf = data.to_vec();
                }
                Ok(())
            }
            UUID_FEATURE_REPORT => {
                if let Ok(mut buf) = self.feature_report.lock() {
                    *buf = data.to_vec();
                }
                Ok(())
            }
            _ => Err(ProfileError::NotSupported),
        }
    }

    fn on_connect(&mut self, _conn_handle: u16) {
        self.status = HidStatus::Active;
    }

    fn on_disconnect(&mut self, _conn_handle: u16) {
        self.status = HidStatus::Idle;
        // Clear input report on disconnect
        if let Ok(mut buf) = self.input_report.lock() {
            buf.iter_mut().for_each(|b| *b = 0);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boot_keyboard_characteristics() {
        let p = HidProfile::boot_keyboard();
        assert_eq!(p.name(), "hid");
        assert_eq!(p.uuid16(), HID_SERVICE_UUID);
        assert_eq!(p.device_type(), HidDeviceType::Keyboard);
        let chars = p.characteristics();
        assert_eq!(chars.len(), 6);
        // input report should be 8 bytes for boot keyboard
        let input = &chars[2];
        assert_eq!(input.uuid16, UUID_INPUT_REPORT);
        assert_eq!(input.initial_value.len(), 8);
    }

    #[test]
    fn boot_mouse_characteristics() {
        let p = HidProfile::boot_mouse();
        assert_eq!(p.device_type(), HidDeviceType::Mouse);
        let chars = p.characteristics();
        assert_eq!(chars.len(), 6);
        // input report 3 bytes for boot mouse (buttons + X + Y)
        let input = &chars[2];
        assert_eq!(input.initial_value.len(), 3);
    }

    #[test]
    fn hid_read_write_status() {
        let mut p = HidProfile::boot_keyboard();
        let mut handles = HashMap::new();
        handles.insert(UUID_STATUS, 100u16);
        handles.insert(UUID_OUTPUT_REPORT, 101u16);
        handles.insert(UUID_INPUT_REPORT, 102u16);
        handles.insert(UUID_TYPE_FORMAT, 103u16);
        handles.insert(UUID_REPORT_INDEX, 104u16);
        handles.insert(UUID_FEATURE_REPORT, 105u16);
        p.on_registered(&handles);

        // Read status — should be Idle (0x00)
        let status = p.on_read(100).unwrap();
        assert_eq!(status, vec![0x00]);

        // Write status to Active
        p.on_write(100, &[0x01]).unwrap();
        let status = p.on_read(100).unwrap();
        assert_eq!(status, vec![0x01]);

        // Invalid status value
        assert!(p.on_write(100, &[0xFF]).is_err());
    }

    #[test]
    fn hid_output_report_write() {
        let mut p = HidProfile::boot_keyboard();
        let mut handles = HashMap::new();
        handles.insert(UUID_OUTPUT_REPORT, 200u16);
        handles.insert(UUID_STATUS, 201u16);
        handles.insert(UUID_INPUT_REPORT, 202u16);
        handles.insert(UUID_TYPE_FORMAT, 203u16);
        handles.insert(UUID_REPORT_INDEX, 204u16);
        handles.insert(UUID_FEATURE_REPORT, 205u16);
        p.on_registered(&handles);

        // Write LED state
        p.on_write(200, &[0x07]).unwrap();
        assert_eq!(p.get_output_report(), vec![0x07]);
    }

    #[test]
    fn hid_input_report_update() {
        let p = HidProfile::boot_keyboard();
        p.set_input_report(vec![0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]);
        let report = p.input_report.lock().unwrap().clone();
        assert_eq!(report[0], 0x02); // Left Shift
        assert_eq!(report[2], 0x04); // 'a' key
    }

    #[test]
    fn hid_device_type_labels() {
        assert_eq!(HidDeviceType::Keyboard.label(), "USB Standard Keyboard");
        assert_eq!(HidDeviceType::Mouse4Khz.label(), "4KHz Mouse");
        assert_eq!(HidDeviceType::Stylus.label(), "High-precision Stylus");
    }

    #[test]
    fn hid_connect_disconnect_lifecycle() {
        let mut p = HidProfile::boot_mouse();
        assert_eq!(p.status, HidStatus::Idle);

        p.on_connect(1);
        assert_eq!(p.status, HidStatus::Active);

        // Set some input data
        p.set_input_report(vec![0x01, 0x10, 0x20]);

        p.on_disconnect(1);
        assert_eq!(p.status, HidStatus::Idle);
        // Input report should be zeroed after disconnect
        let report = p.input_report.lock().unwrap().clone();
        assert_eq!(report, vec![0x00, 0x00, 0x00]);
    }
}
