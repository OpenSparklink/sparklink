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
        let st = self.state.lock().await;
        let info = st.adapter.sec_info().map_err(|e| {
            zbus::fdo::Error::Failed(format!("sec_info failed: {e}"))
        })?;
        Ok(SecurityInfo {
            state: sec_state_label(info.state),
            method: pair_method_label(info.method),
            mode: info.mode,
            encrypted: info.enc_enabled != 0,
        })
    }

    /// Set Pre-Shared Key (16 bytes hex string)
    async fn set_psk(&self, psk_hex: &str) -> zbus::fdo::Result<()> {
        let psk = parse_hex_key(psk_hex, 16).map_err(|e| {
            zbus::fdo::Error::InvalidArgs(e.to_string())
        })?;
        let mut params = slk_protocol::SlePskParams { psk: [0; 16] };
        params.psk.copy_from_slice(&psk);
        let st = self.state.lock().await;
        st.adapter.set_psk(&params).map_err(|e| {
            zbus::fdo::Error::Failed(format!("set_psk failed: {e}"))
        })
    }

    /// Initiate pairing with the given method
    /// method: "just_works", "psk", "none"
    async fn pair(&self, method: &str) -> zbus::fdo::Result<()> {
        let m = match method {
            "just_works" => slk_protocol::PairMethod::JustWorks as u8,
            "psk" => slk_protocol::PairMethod::Psk as u8,
            "none" | "" => slk_protocol::PairMethod::None as u8,
            _ => return Err(zbus::fdo::Error::InvalidArgs(
                "method must be 'just_works', 'psk', or 'none'".into()
            )),
        };
        let params = slk_protocol::SlePairParams {
            method: m,
            _reserved: [0; 3],
        };
        let st = self.state.lock().await;
        st.adapter.pair(&params).map_err(|e| {
            zbus::fdo::Error::Failed(format!("pair failed: {e}"))
        })
    }

    /// Enable encryption on the active connection
    async fn encrypt(&self) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.encrypt_on().map_err(|e| {
            zbus::fdo::Error::Failed(format!("encrypt_on failed: {e}"))
        })
    }

    /// Get the passkey displayed by the controller (for numeric comparison)
    async fn get_passkey(&self) -> zbus::fdo::Result<u32> {
        let st = self.state.lock().await;
        st.adapter.get_passkey().map_err(|e| {
            zbus::fdo::Error::Failed(format!("get_passkey failed: {e}"))
        })
    }

    /// Confirm passkey match (user accepted numeric comparison)
    async fn confirm_passkey(&self) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.confirm_passkey().map_err(|e| {
            zbus::fdo::Error::Failed(format!("confirm_passkey failed: {e}"))
        })
    }

    /// Reject passkey match (user rejected)
    async fn reject_passkey(&self) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.reject_passkey().map_err(|e| {
            zbus::fdo::Error::Failed(format!("reject_passkey failed: {e}"))
        })
    }

    /// Input a passkey (user-entered 6-digit code)
    async fn input_passkey(&self, passkey: u32) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.input_passkey(passkey).map_err(|e| {
            zbus::fdo::Error::Failed(format!("input_passkey failed: {e}"))
        })
    }

    /// Reset security state
    async fn reset(&self) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.sec_reset().map_err(|e| {
            zbus::fdo::Error::Failed(format!("sec_reset failed: {e}"))
        })
    }

    /// Current security state as property
    #[zbus(property)]
    async fn encrypted(&self) -> bool {
        let st = self.state.lock().await;
        st.adapter.sec_info()
            .map(|info| info.enc_enabled != 0)
            .unwrap_or(false)
    }

    /// Current pairing state as property
    #[zbus(property)]
    async fn paired(&self) -> bool {
        let st = self.state.lock().await;
        st.adapter.sec_info()
            .map(|info| info.state >= slk_protocol::SecState::Paired as u8)
            .unwrap_or(false)
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

fn sec_state_label(state: u8) -> String {
    match state {
        0 => "none".into(),
        1 => "pairing".into(),
        2 => "paired".into(),
        3 => "encrypted".into(),
        _ => format!("unknown({state})"),
    }
}

fn pair_method_label(method: u8) -> String {
    match method {
        0 => "none".into(),
        1 => "just_works".into(),
        2 => "psk".into(),
        _ => format!("unknown({method})"),
    }
}

fn parse_hex_key(hex: &str, expected_len: usize) -> Result<Vec<u8>, &'static str> {
    let hex = hex.strip_prefix("0x").unwrap_or(hex);
    if hex.len() != expected_len * 2 {
        return Err("hex string has wrong length");
    }
    let mut bytes = Vec::with_capacity(expected_len);
    for i in (0..hex.len()).step_by(2) {
        let byte = u8::from_str_radix(&hex[i..i + 2], 16)
            .map_err(|_| "invalid hex character")?;
        bytes.push(byte);
    }
    Ok(bytes)
}
