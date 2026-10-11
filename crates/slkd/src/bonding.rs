use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use tokio::sync::Mutex;

use slk_protocol::SleAddr;

/// Legacy pairing metadata, not a reconnect credential or proof of bonding.
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

struct StorageState {
    store: BondingStore,
    closed: bool,
}

/// Serializes disk operations independently of the adapter business-state lock.
/// Once submitted to spawn_blocking, an operation retains the storage lock even
/// if its caller is cancelled. The disk and cache update therefore finish together.
#[derive(Clone)]
pub struct BondingService {
    state: Arc<Mutex<StorageState>>,
    runtime: tokio::runtime::Handle,
}

impl BondingService {
    pub fn new(store: BondingStore) -> Self {
        Self {
            // zbus may dispatch on its own executor thread. Capture the daemon
            // runtime here rather than requiring a Tokio context at each call.
            runtime: tokio::runtime::Handle::current(),
            state: Arc::new(Mutex::new(StorageState {
                store,
                closed: false,
            })),
        }
    }

    pub(crate) async fn run<T: Send + 'static>(
        &self,
        operation: impl FnOnce(&mut BondingStore) -> std::io::Result<T> + Send + 'static,
    ) -> std::io::Result<T> {
        let mut state = self.state.clone().lock_owned().await;
        if state.closed {
            return Err(std::io::Error::new(
                std::io::ErrorKind::BrokenPipe,
                "bond storage is closed",
            ));
        }
        self.runtime
            .spawn_blocking(move || operation(&mut state.store))
            .await
            .map_err(std::io::Error::other)?
    }

    pub async fn save(&self, addr: SleAddr, info: BondingInfo) -> std::io::Result<()> {
        self.run(move |store| store.save(&addr, info)).await
    }

    pub async fn remove(&self, addr: SleAddr) -> std::io::Result<()> {
        self.run(move |store| store.remove(&addr)).await
    }

    pub async fn bonded_addrs(&self) -> Vec<SleAddr> {
        self.state.lock().await.store.bonded_addrs()
    }

    /// Wait for in-flight writes and reject subsequent writes from all clones.
    pub async fn shutdown(&self) {
        self.state.lock().await.closed = true;
    }
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
            if path.extension().is_some_and(|e| e == "toml")
                && let Some(addr) = self.parse_filename(&path)
            {
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
        Ok(self.cache.len())
    }

    /// Save a bonding record for the given device
    pub fn save(&mut self, addr: &SleAddr, info: BondingInfo) -> std::io::Result<()> {
        let dir = self.store_path();
        std::fs::create_dir_all(&dir)?;
        let path = self.device_path(addr);
        let content = toml::to_string_pretty(&info).map_err(std::io::Error::other)?;
        std::fs::write(&path, content)?;
        self.cache.insert(*addr, info);
        Ok(())
    }

    /// Remove a bonding record
    pub fn remove(&mut self, addr: &SleAddr) -> std::io::Result<()> {
        let path = self.device_path(addr);
        match std::fs::remove_file(&path) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e),
        }
        self.cache.remove(addr);
        Ok(())
    }

    /// Look up a cached bonding record
    #[cfg(test)]
    pub fn get(&self, addr: &SleAddr) -> Option<&BondingInfo> {
        self.cache.get(addr)
    }

    /// List all bonded device addresses
    pub fn bonded_addrs(&self) -> Vec<SleAddr> {
        self.cache.keys().copied().collect()
    }

    /// Check if a device is bonded
    #[cfg(test)]
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
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::Duration;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            static NEXT: AtomicU64 = AtomicU64::new(0);
            Self(std::env::temp_dir().join(format!(
                "sparklink-bonding-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed),
            )))
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn record() -> BondingInfo {
        BondingInfo {
            name: "TestDevice".into(),
            method: "just_works".into(),
            enc_key_fingerprint: "deadbeef".into(),
            paired_at: "2025-01-01T00:00:00Z".into(),
        }
    }

    #[test]
    fn roundtrip_save_load() {
        let dir = TestDir::new();

        let addr: SleAddr = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF];
        let info = record();

        let mut store = BondingStore::new(&dir.0, "slk0");
        store.save(&addr, info.clone()).unwrap();
        assert!(store.is_bonded(&addr));

        // Reload from disk
        let mut store2 = BondingStore::new(&dir.0, "slk0");
        let count = store2.load().unwrap();
        assert_eq!(count, 1);
        let loaded = store2.get(&addr).unwrap();
        assert_eq!(loaded.name, "TestDevice");
        assert_eq!(loaded.method, "just_works");

        // Remove
        store2.remove(&addr).unwrap();
        assert!(!store2.is_bonded(&addr));
    }

    #[test]
    fn empty_store_loads_zero() {
        let dir = TestDir::new();

        let mut store = BondingStore::new(&dir.0, "slk0");
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

    #[tokio::test]
    async fn cancelled_writer_finishes_before_remove() {
        let dir = TestDir::new();
        let service = BondingService::new(BondingStore::new(&dir.0, "slk0"));
        let addr = [1; 6];
        let (entered, entered_rx) = tokio::sync::oneshot::channel();
        let (release, release_rx) = std::sync::mpsc::channel();
        let writer_service = service.clone();
        let writer = tokio::spawn(async move {
            writer_service
                .run(move |store| {
                    entered.send(()).unwrap();
                    release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    store.save(&addr, record())
                })
                .await
        });
        entered_rx.await.unwrap();
        writer.abort();
        assert!(writer.await.unwrap_err().is_cancelled());
        let remover_service = service.clone();
        let mut remover = tokio::spawn(async move { remover_service.remove(addr).await });
        assert!(
            tokio::time::timeout(Duration::from_millis(50), &mut remover)
                .await
                .is_err()
        );
        release.send(()).unwrap();
        remover.await.unwrap().unwrap();
        assert!(service.bonded_addrs().await.is_empty());
        let mut reloaded = BondingStore::new(&dir.0, "slk0");
        assert_eq!(reloaded.load().unwrap(), 0);
        service.shutdown().await;
    }

    #[tokio::test]
    async fn shutdown_drains_write_and_closes_all_clones() {
        let dir = TestDir::new();
        let service = BondingService::new(BondingStore::new(&dir.0, "slk0"));
        let (entered, entered_rx) = tokio::sync::oneshot::channel();
        let (release, release_rx) = std::sync::mpsc::channel();
        let writer_service = service.clone();
        let writer = tokio::spawn(async move {
            writer_service
                .run(move |store| {
                    entered.send(()).unwrap();
                    release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    store.save(&[2; 6], record())
                })
                .await
        });
        entered_rx.await.unwrap();
        let closing_service = service.clone();
        let mut closing = tokio::spawn(async move { closing_service.shutdown().await });
        assert!(
            tokio::time::timeout(Duration::from_millis(50), &mut closing)
                .await
                .is_err()
        );
        release.send(()).unwrap();
        closing.await.unwrap();
        writer.await.unwrap().unwrap();
        let mut reloaded = BondingStore::new(&dir.0, "slk0");
        assert_eq!(reloaded.load().unwrap(), 1);
        assert_eq!(
            service.remove([2; 6]).await.unwrap_err().kind(),
            std::io::ErrorKind::BrokenPipe
        );
        assert_eq!(
            service.save([3; 6], record()).await.unwrap_err().kind(),
            std::io::ErrorKind::BrokenPipe
        );
    }

    #[tokio::test]
    async fn failed_write_is_not_published_to_cache() {
        let dir = TestDir::new();
        std::fs::create_dir_all(&dir.0).unwrap();
        std::fs::write(dir.0.join("slk0"), "not a directory").unwrap();
        let service = BondingService::new(BondingStore::new(&dir.0, "slk0"));
        assert!(service.save([4; 6], record()).await.is_err());
        assert!(service.bonded_addrs().await.is_empty());
        service.shutdown().await;
    }
}
