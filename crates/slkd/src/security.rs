use zbus::interface;

use crate::state::SharedState;

/// D-Bus interface for security operations on an adapter
pub struct SecurityIface {
    state: SharedState,
}

impl SecurityIface {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

#[interface(name = "org.sparklink.Security")]
impl SecurityIface {
    /// Get current security state
    async fn get_info(&self) -> zbus::fdo::Result<SecurityInfo> {
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Set Pre-Shared Key (16 bytes hex string)
    async fn set_psk(&self, psk_hex: &str) -> zbus::fdo::Result<()> {
        parse_hex_key(psk_hex, 16).map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Initiate pairing with the given method
    /// method: "just_works", "psk", "none"
    async fn pair(&self, method: &str) -> zbus::fdo::Result<()> {
        if !matches!(method, "just_works" | "psk" | "none" | "") {
            return Err(zbus::fdo::Error::InvalidArgs(
                "method must be 'just_works', 'psk', or 'none'".into(),
            ));
        }
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Unsupported until a lifetime-bound key installation mechanism is connected
    async fn encrypt(&self) -> zbus::fdo::Result<()> {
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Get the passkey displayed by the controller (for numeric comparison)
    async fn get_passkey(&self) -> zbus::fdo::Result<u32> {
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Confirm passkey match (user accepted numeric comparison)
    async fn confirm_passkey(&self) -> zbus::fdo::Result<()> {
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Reject passkey match (user rejected)
    async fn reject_passkey(&self) -> zbus::fdo::Result<()> {
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Input a passkey (user-entered 6-digit code)
    async fn input_passkey(&self, passkey: u32) -> zbus::fdo::Result<()> {
        if passkey > 999_999 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "passkey must be 0..999999".into(),
            ));
        }
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Reset security state
    async fn reset(&self) -> zbus::fdo::Result<()> {
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// List bonded device addresses
    async fn list_bonded(&self) -> zbus::fdo::Result<Vec<String>> {
        let bonding = self.state.lock().await.bonding.clone();
        let addrs = bonding.bonded_addrs().await;
        Ok(addrs
            .iter()
            .map(|a| {
                a.iter()
                    .map(|b| format!("{b:02X}"))
                    .collect::<Vec<_>>()
                    .join(":")
            })
            .collect())
    }

    /// Remove bonding for a device
    async fn remove_bond(&self, addr_hex: &str) -> zbus::fdo::Result<()> {
        let parts: Vec<&str> = addr_hex.split(':').collect();
        if parts.len() != 6 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "expected AA:BB:CC:DD:EE:FF".into(),
            ));
        }
        let mut addr = [0u8; 6];
        for (i, part) in parts.iter().enumerate() {
            addr[i] = u8::from_str_radix(part, 16)
                .map_err(|_| zbus::fdo::Error::InvalidArgs("invalid hex byte".into()))?;
        }
        let bonding = self.state.lock().await.bonding.clone();
        bonding
            .remove(addr)
            .await
            .map_err(|e| zbus::fdo::Error::Failed(format!("remove_bond failed: {e}")))
    }

    /// Current security state as property
    #[zbus(property)]
    async fn encrypted(&self) -> zbus::fdo::Result<bool> {
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }

    /// Current pairing state as property
    #[zbus(property)]
    async fn paired(&self) -> zbus::fdo::Result<bool> {
        Err(zbus::fdo::Error::NotSupported(
            "per-connection authenticated security is not implemented".into(),
        ))
    }
}

/// Structured security info returned over D-Bus
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct SecurityInfo {
    pub state: String,
    pub method: String,
    pub mode: u8,
    pub encrypted: bool,
}

fn parse_hex_key(hex: &str, expected_len: usize) -> Result<Vec<u8>, &'static str> {
    let hex = hex.strip_prefix("0x").unwrap_or(hex);
    if hex.len() != expected_len * 2 {
        return Err("hex string has wrong length");
    }
    if !hex.is_ascii() {
        return Err("invalid hex character");
    }
    let mut bytes = Vec::with_capacity(expected_len);
    for i in (0..hex.len()).step_by(2) {
        let byte = u8::from_str_radix(&hex[i..i + 2], 16).map_err(|_| "invalid hex character")?;
        bytes.push(byte);
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn key_input_rejects_unicode_at_expected_byte_length() {
        assert!(parse_hex_key(&"aéa".repeat(8), 16).is_err());
        assert_eq!(parse_hex_key(&"a1".repeat(16), 16).unwrap(), vec![0xA1; 16]);
    }
}
