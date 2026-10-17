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
    /// Register one explicit Agent for this controller. The system bus policy
    /// requires controller administration, not ordinary channel enrollment.
    async fn register_agent(
        &self,
        path: zbus::zvariant::OwnedObjectPath,
        method: &str,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<u64> {
        crate::security_policy::register(
            &self.state,
            connection,
            crate::security_policy::sender(&header)?,
            path,
            method,
        )
        .await
    }

    async fn unregister_agent(
        &self,
        path: zbus::zvariant::OwnedObjectPath,
        epoch: u64,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<()> {
        crate::security_policy::unregister(
            &self.state,
            &crate::security_policy::sender(&header)?,
            path,
            epoch,
        )
        .await
    }
}

#[cfg(test)]
mod tests {
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
            let byte =
                u8::from_str_radix(&hex[i..i + 2], 16).map_err(|_| "invalid hex character")?;
            bytes.push(byte);
        }
        Ok(bytes)
    }

    #[test]
    fn key_input_rejects_unicode_at_expected_byte_length() {
        assert!(parse_hex_key(&"aéa".repeat(8), 16).is_err());
        assert_eq!(parse_hex_key(&"a1".repeat(16), 16).unwrap(), vec![0xA1; 16]);
    }
}
