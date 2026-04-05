//! SparkLink HID Data Interaction Service (T/XS 30004-2025)
//!
//! Implements the "人机数据交互" service as defined in TXS-30004-2025.
//! UUID assignments from Appendix A (normative).
//!
//! Service UUID: 0x060B
//!
//! Mandatory properties:
//!   - 类型和格式描述 (0x1039) — read/notify/indicate/broadcast
//!   - 工作状态指示   (0x103A) — read/write/notify/indicate/broadcast
//!   - 报告索引信息   (0x103B) — read/notify/indicate/broadcast
//!
//! Conditional properties (at least one required):
//!   - 输入报告信息   (0x103C) — read/notify/indicate/broadcast
//!   - 输出报告信息   (0x103D) — read/write/notify/indicate/broadcast
//!   - 特性报告信息   (0x103E) — read/write/notify/indicate/broadcast

use std::collections::HashMap;
use std::sync::Mutex;

use crate::profile::{CharacteristicDef, Profile, ProfileError};

/// HID device type identifiers (T/XS 30004-2025 section 8.2, table 4 byte 2)
///
/// 0x00 — no specific device type
/// 0x01 — USB Boot Keyboard
/// 0x02 — USB Boot Mouse
/// Other values defined by application instance standards (T/XS 30013-2025)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum HidDeviceType {
    Unspecified = 0x00,
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
            Self::Unspecified => "Unspecified",
            Self::Keyboard => "USB Boot Keyboard",
            Self::Mouse => "USB Boot Mouse",
            Self::GenericHid => "USB HID Device",
            Self::Stylus => "High-precision Stylus",
            Self::Mouse1Khz => "1KHz Mouse",
            Self::Mouse2Khz => "2KHz Mouse",
            Self::Mouse4Khz => "4KHz Mouse",
        }
    }
}

/// Working status (T/XS 30004-2025 section 7.2.1)
///
/// 0x00 — normal operation
/// 0x01 — suspended
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum HidStatus {
    Normal = 0x00,
    Suspended = 0x01,
}

/// Report type identifiers (T/XS 30004-2025 Report Index byte 1)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum ReportType {
    Input = 0x01,
    Output = 0x02,
    Feature = 0x03,
}

/// Type format indicator (T/XS 30004-2025 section 7.2.1 byte 0)
///
/// 0x00 — custom report descriptor follows in bytes 1..N
/// 0x01 — USB HID Boot Keyboard format, no descriptor bytes
/// 0x02 — USB HID Boot Mouse format, no descriptor bytes
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum TypeFormatIndicator {
    CustomDescriptor = 0x00,
    BootKeyboard = 0x01,
    BootMouse = 0x02,
}

/// Report Index entry (T/XS 30004-2025 section 7.2.1)
///
/// 8 bytes:
///   [0]     Report ID
///   [1]     Report type (0x01=input, 0x02=output, 0x03=feature)
///   [2..3]  Handle of the matching report property (big-endian)
///   [4..5]  Data plane source port (0=unsupported, 0xFFFF=BSL passthrough)
///   [6..7]  Data plane destination port
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReportIndexEntry {
    pub report_id: u8,
    pub report_type: ReportType,
    pub handle: u16,
    pub src_port: u16,
    pub dst_port: u16,
}

impl ReportIndexEntry {
    pub fn to_bytes(&self) -> [u8; 8] {
        [
            self.report_id,
            self.report_type as u8,
            (self.handle >> 8) as u8,
            (self.handle & 0xFF) as u8,
            (self.src_port >> 8) as u8,
            (self.src_port & 0xFF) as u8,
            (self.dst_port >> 8) as u8,
            (self.dst_port & 0xFF) as u8,
        ]
    }

    pub fn from_bytes(b: &[u8; 8]) -> Option<Self> {
        let rt = match b[1] {
            0x01 => ReportType::Input,
            0x02 => ReportType::Output,
            0x03 => ReportType::Feature,
            _ => return None,
        };
        Some(Self {
            report_id: b[0],
            report_type: rt,
            handle: u16::from_be_bytes([b[2], b[3]]),
            src_port: u16::from_be_bytes([b[4], b[5]]),
            dst_port: u16::from_be_bytes([b[6], b[7]]),
        })
    }
}

// UUID assignments per TXS-30004-2025 Appendix A (normative)
const UUID_TYPE_FORMAT: u16 = 0x1039;
const UUID_STATUS: u16 = 0x103A;
const UUID_REPORT_INDEX: u16 = 0x103B;
const UUID_INPUT_REPORT: u16 = 0x103C;
const UUID_OUTPUT_REPORT: u16 = 0x103D;
const UUID_FEATURE_REPORT: u16 = 0x103E;

/// 人机数据交互 service UUID (TXS-30004-2025 Appendix A)
const HID_SERVICE_UUID: u16 = 0x060B;

/// SparkLink HID Data Interaction profile.
///
/// Implements the server side of the HID service, managing report
/// descriptors and I/O report buffers.  The input report buffer is
/// updated via `set_input_report` and delivered to the peer through
/// SSAP notification.
pub struct HidProfile {
    device_type: HidDeviceType,
    type_indicator: TypeFormatIndicator,
    status: HidStatus,
    /// USB HID Report Descriptor (only present when type_indicator == CustomDescriptor)
    report_descriptor: Vec<u8>,
    /// Report index entries for this service instance
    report_indices: Vec<ReportIndexEntry>,
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
    pub fn new(
        device_type: HidDeviceType,
        type_indicator: TypeFormatIndicator,
        report_descriptor: Vec<u8>,
    ) -> Self {
        Self {
            device_type,
            type_indicator,
            status: HidStatus::Normal,
            report_descriptor,
            report_indices: Vec::new(),
            input_report: Mutex::new(Vec::new()),
            output_report: Mutex::new(Vec::new()),
            feature_report: Mutex::new(Vec::new()),
            handles: HashMap::new(),
        }
    }

    /// Build the type format description property value.
    ///
    /// For BootKeyboard/BootMouse the value is a single byte (0x01/0x02).
    /// For CustomDescriptor byte 0 is 0x00 followed by the report descriptor.
    fn type_format_value(&self) -> Vec<u8> {
        match self.type_indicator {
            TypeFormatIndicator::BootKeyboard => vec![0x01],
            TypeFormatIndicator::BootMouse => vec![0x02],
            TypeFormatIndicator::CustomDescriptor => {
                let mut v = vec![0x00];
                v.extend_from_slice(&self.report_descriptor);
                v
            }
        }
    }

    /// Serialize all report index entries into a byte vector.
    fn report_index_value(&self) -> Vec<u8> {
        self.report_indices.iter().flat_map(|e| e.to_bytes()).collect()
    }

    /// Create a boot keyboard profile (type indicator 0x01).
    ///
    /// Per TXS-30004-2025, when type indicator is 0x01 the report format is
    /// defined by USB HID Boot Keyboard and no report descriptor follows.
    /// We still store the descriptor internally for local report parsing.
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
        let mut p = Self::new(
            HidDeviceType::Keyboard,
            TypeFormatIndicator::BootKeyboard,
            descriptor,
        );
        *p.input_report.get_mut().unwrap() = vec![0u8; 8]; // 8-byte boot report
        *p.output_report.get_mut().unwrap() = vec![0u8; 1]; // 1-byte LED
        // Default report indices: input(ID=0) + output(ID=0)
        // Handles and ports are populated after SSAP registration
        p.report_indices = vec![
            ReportIndexEntry {
                report_id: 0,
                report_type: ReportType::Input,
                handle: 0,
                src_port: 0,
                dst_port: 0,
            },
            ReportIndexEntry {
                report_id: 0,
                report_type: ReportType::Output,
                handle: 0,
                src_port: 0,
                dst_port: 0,
            },
        ];
        p
    }

    /// Create a boot mouse profile (type indicator 0x02).
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
        let mut p = Self::new(
            HidDeviceType::Mouse,
            TypeFormatIndicator::BootMouse,
            descriptor,
        );
        *p.input_report.get_mut().unwrap() = vec![0u8; 3]; // buttons + X + Y
        p.report_indices = vec![
            ReportIndexEntry {
                report_id: 0,
                report_type: ReportType::Input,
                handle: 0,
                src_port: 0,
                dst_port: 0,
            },
        ];
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
            // 类型和格式描述 — mandatory, read/notify/indicate/broadcast
            CharacteristicDef {
                uuid16: UUID_TYPE_FORMAT,
                ops: 0x01 | 0x04, // read + notify
                initial_value: self.type_format_value(),
            },
            // 工作状态指示 — mandatory, read/write/notify/indicate/broadcast
            CharacteristicDef {
                uuid16: UUID_STATUS,
                ops: 0x01 | 0x02 | 0x04, // read + write + notify
                initial_value: vec![self.status as u8],
            },
            // 报告索引信息 — mandatory, read/notify/indicate/broadcast
            CharacteristicDef {
                uuid16: UUID_REPORT_INDEX,
                ops: 0x01 | 0x04, // read + notify
                initial_value: self.report_index_value(),
            },
            // 输入报告信息 — conditional, read/notify/indicate/broadcast
            CharacteristicDef {
                uuid16: UUID_INPUT_REPORT,
                ops: 0x01 | 0x04, // read + notify
                initial_value: self.input_report.lock()
                    .map(|b| b.clone()).unwrap_or_default(),
            },
            // 输出报告信息 — conditional, read/write/notify/indicate/broadcast
            CharacteristicDef {
                uuid16: UUID_OUTPUT_REPORT,
                ops: 0x01 | 0x02 | 0x04, // read + write + notify
                initial_value: self.output_report.lock()
                    .map(|b| b.clone()).unwrap_or_default(),
            },
            // 特性报告信息 — conditional, read/write/notify/indicate/broadcast
            CharacteristicDef {
                uuid16: UUID_FEATURE_REPORT,
                ops: 0x01 | 0x02 | 0x04, // read + write + notify
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
            UUID_TYPE_FORMAT => Ok(self.type_format_value()),
            UUID_REPORT_INDEX => Ok(self.report_index_value()),
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
                    0x00 => HidStatus::Normal,
                    0x01 => HidStatus::Suspended,
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
        self.status = HidStatus::Normal;
    }

    fn on_disconnect(&mut self, _conn_handle: u16) {
        self.status = HidStatus::Suspended;
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
        assert_eq!(p.uuid16(), 0x060B);
        assert_eq!(p.device_type(), HidDeviceType::Keyboard);
        let chars = p.characteristics();
        assert_eq!(chars.len(), 6);
        // Type format should be a single byte 0x01 for boot keyboard
        let tf = &chars[0];
        assert_eq!(tf.uuid16, 0x1039);
        assert_eq!(tf.initial_value, vec![0x01]);
        // Input report should be 8 bytes for boot keyboard
        let input = &chars[3];
        assert_eq!(input.uuid16, UUID_INPUT_REPORT);
        assert_eq!(input.initial_value.len(), 8);
        // Report index: 2 entries * 8 bytes = 16 bytes
        let ri = &chars[2];
        assert_eq!(ri.uuid16, 0x103B);
        assert_eq!(ri.initial_value.len(), 16);
    }

    #[test]
    fn boot_mouse_characteristics() {
        let p = HidProfile::boot_mouse();
        assert_eq!(p.device_type(), HidDeviceType::Mouse);
        let chars = p.characteristics();
        assert_eq!(chars.len(), 6);
        // Type format: single byte 0x02 for boot mouse
        assert_eq!(chars[0].initial_value, vec![0x02]);
        // input report 3 bytes for boot mouse (buttons + X + Y)
        let input = &chars[3];
        assert_eq!(input.initial_value.len(), 3);
        // Report index: 1 entry (input only) = 8 bytes
        assert_eq!(chars[2].initial_value.len(), 8);
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

        // Read status — should be Normal (0x00)
        let status = p.on_read(100).unwrap();
        assert_eq!(status, vec![0x00]);

        // Write status to Suspended
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
        assert_eq!(HidDeviceType::Keyboard.label(), "USB Boot Keyboard");
        assert_eq!(HidDeviceType::Mouse4Khz.label(), "4KHz Mouse");
        assert_eq!(HidDeviceType::Stylus.label(), "High-precision Stylus");
        assert_eq!(HidDeviceType::Unspecified.label(), "Unspecified");
    }

    #[test]
    fn hid_connect_disconnect_lifecycle() {
        let mut p = HidProfile::boot_mouse();
        assert_eq!(p.status, HidStatus::Normal);

        p.on_connect(1);
        assert_eq!(p.status, HidStatus::Normal);

        // Set some input data
        p.set_input_report(vec![0x01, 0x10, 0x20]);

        p.on_disconnect(1);
        assert_eq!(p.status, HidStatus::Suspended);
        // Input report should be zeroed after disconnect
        let report = p.input_report.lock().unwrap().clone();
        assert_eq!(report, vec![0x00, 0x00, 0x00]);
    }

    #[test]
    fn report_index_entry_roundtrip() {
        let entry = ReportIndexEntry {
            report_id: 0x01,
            report_type: ReportType::Input,
            handle: 0x0042,
            src_port: 0x1234,
            dst_port: 0x5678,
        };
        let bytes = entry.to_bytes();
        assert_eq!(bytes, [0x01, 0x01, 0x00, 0x42, 0x12, 0x34, 0x56, 0x78]);
        let parsed = ReportIndexEntry::from_bytes(&bytes).unwrap();
        assert_eq!(parsed, entry);
    }

    #[test]
    fn type_format_boot_keyboard() {
        let p = HidProfile::boot_keyboard();
        let val = p.type_format_value();
        assert_eq!(val, vec![0x01]); // single byte, no descriptor
    }

    #[test]
    fn type_format_custom_descriptor() {
        let desc = vec![0x05, 0x01, 0x09, 0x06];
        let p = HidProfile::new(
            HidDeviceType::GenericHid,
            TypeFormatIndicator::CustomDescriptor,
            desc.clone(),
        );
        let val = p.type_format_value();
        assert_eq!(val[0], 0x00); // custom indicator
        assert_eq!(&val[1..], &desc);
    }
}
