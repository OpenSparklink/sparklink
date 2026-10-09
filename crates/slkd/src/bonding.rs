use std::collections::HashMap;
use std::path::{Path, PathBuf};

use slk_protocol::SleAddr;

/// Per-device bonding record persisted to disk
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct BondingInfo {
    pub name: String,
    pub method: String,
    pub enc_key_fingerprint: String,
    pub paired_at: String,
}

/// Manages bonding information storage on disk
///
/// Storage layout: `<base_dir>/<adapter>/AA_BB_CC_DD_EE_FF.toml`
pub struct BondingStore {
    base_dir: PathBuf,
    adapter: String,
    cache: HashMap<SleAddr, BondingInfo>,
}

impl BondingStore {
    pub fn new(base_dir: &Path, adapter: &str) -> Self {
        Self {
            base_dir: base_dir.to_path_buf(),
            adapter: adapter.to_string(),
            cache: HashMap::new(),
        }
    }

    fn store_path(&self) -> PathBuf {
        self.base_dir.join(&self.adapter)
    }

    fn device_path(&self, addr: &SleAddr) -> PathBuf {
        let name = addr
            .iter()
            .map(|b| format!("{b:02X}"))
            .collect::<Vec<_>>()
            .join("_");
        self.store_path().join(format!("{name}.toml"))
    }

    /// Load all bonding records from disk into cache
    pub fn load(&mut self) -> std::io::Result<usize> {
        self.cache.clear();
        let dir = self.store_path();
        if !dir.exists() {
            return Ok(0);
        }
        let entries = std::fs::read_dir(&dir)?;
        for entry in entries {
            let entry = entry?;
            let path = entry.path();
            if path.extension().is_some_and(|e| e == "toml") {
                if let Some(addr) = self.parse_filename(&path) {
                    match std::fs::read_to_string(&path) {
                        Ok(content) => match toml::from_str::<BondingInfo>(&content) {
                            Ok(info) => {
                                self.cache.insert(addr, info);
                            }
                            Err(e) => {
                                tracing::warn!("bad bonding file {}: {e}", path.display());
                            }
                        },
                        Err(e) => {
                            tracing::warn!("cannot read {}: {e}", path.display());
                        }
                    }
                }
            }
        }
        Ok(self.cache.len())
    }

    /// Save a bonding record for the given device
    pub fn save(&mut self, addr: &SleAddr, info: BondingInfo) -> std::io::Result<()> {
        let dir = self.store_path();
        std::fs::create_dir_all(&dir)?;
        let path = self.device_path(addr);
        let content = toml::to_string_pretty(&info)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        std::fs::write(&path, content)?;
        self.cache.insert(*addr, info);
        Ok(())
    }

    /// Remove a bonding record
    pub fn remove(&mut self, addr: &SleAddr) -> std::io::Result<()> {
        let path = self.device_path(addr);
        if path.exists() {
            std::fs::remove_file(&path)?;
        }
        self.cache.remove(addr);
        Ok(())
    }

    /// Look up a cached bonding record
    pub fn get(&self, addr: &SleAddr) -> Option<&BondingInfo> {
        self.cache.get(addr)
    }

    /// List all bonded device addresses
    pub fn bonded_addrs(&self) -> Vec<SleAddr> {
        self.cache.keys().copied().collect()
    }

    /// Check if a device is bonded
    pub fn is_bonded(&self, addr: &SleAddr) -> bool {
        self.cache.contains_key(addr)
    }

    fn parse_filename(&self, path: &Path) -> Option<SleAddr> {
        let stem = path.file_stem()?.to_str()?;
        let parts: Vec<&str> = stem.split('_').collect();
        if parts.len() != 6 {
            return None;
        }
        let mut addr = [0u8; 6];
        for (i, part) in parts.iter().enumerate() {
            addr[i] = u8::from_str_radix(part, 16).ok()?;
        }
        Some(addr)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_save_load() {
        let dir = std::env::temp_dir().join("sparklink_bonding_test");
        let _ = std::fs::remove_dir_all(&dir);

        let addr: SleAddr = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF];
        let info = BondingInfo {
            name: "TestDevice".into(),
            method: "just_works".into(),
            enc_key_fingerprint: "deadbeef".into(),
            paired_at: "2025-01-01T00:00:00Z".into(),
        };

        let mut store = BondingStore::new(&dir, "slk0");
        store.save(&addr, info.clone()).unwrap();
        assert!(store.is_bonded(&addr));

        // Reload from disk
        let mut store2 = BondingStore::new(&dir, "slk0");
        let count = store2.load().unwrap();
        assert_eq!(count, 1);
        let loaded = store2.get(&addr).unwrap();
        assert_eq!(loaded.name, "TestDevice");
        assert_eq!(loaded.method, "just_works");

        // Remove
        store2.remove(&addr).unwrap();
        assert!(!store2.is_bonded(&addr));

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn empty_store_loads_zero() {
        let dir = std::env::temp_dir().join("sparklink_bonding_empty");
        let _ = std::fs::remove_dir_all(&dir);

        let mut store = BondingStore::new(&dir, "slk0");
        let count = store.load().unwrap();
        assert_eq!(count, 0);
        assert!(store.bonded_addrs().is_empty());
    }

    #[test]
    fn filename_parse() {
        let store = BondingStore::new(Path::new("/tmp"), "slk0");
        let path = PathBuf::from("/tmp/slk0/AA_BB_CC_DD_EE_FF.toml");
        let addr = store.parse_filename(&path).unwrap();
        assert_eq!(addr, [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]);
    }
}
