//! Actual CLI -> SDK -> private bus. No service database/Engine or RF fixture.
mod support;
const BASE: &str = "/org/sparklink/slk2_g7";
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into()]
    }
}
struct Adapter;
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property)]
    fn generation(&self) -> u64 {
        7
    }
}
type Definition = (Vec<u8>, u32, u32, Vec<u8>);
type Record = (u16, u16, Vec<u8>, Vec<(u16, Vec<u8>, u32, u32)>);
struct Services;
#[zbus::interface(name = "org.sparklink.ServiceManager")]
impl Services {
    fn list_local_services(&self) -> Vec<Record> {
        vec![(16, 17, vec![1, 0], vec![(17, vec![2, 0], 1, 0)])]
    }
    fn register_local_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<Definition>,
    ) -> zbus::fdo::Result<(u16, u16, Vec<u16>)> {
        if uuid != [1, 0] || properties != vec![(vec![2, 0], 1, 0, vec![0xab])] {
            return Err(zbus::fdo::Error::InvalidArgs(
                "exact fixture arguments".into(),
            ));
        }
        Ok((16, 17, vec![17]))
    }
    fn read_local_value(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        if handle != 17 {
            return Err(zbus::fdo::Error::InvalidArgs("unknown handle".into()));
        }
        Ok(vec![0xab])
    }
    fn remove_local_service(&self, start: u16) -> zbus::fdo::Result<()> {
        if start != 16 {
            return Err(zbus::fdo::Error::AccessDenied("foreign service".into()));
        }
        Ok(())
    }
}
#[tokio::test]
async fn all_actual_staging_commands_use_sdk_and_preserve_results_and_errors() -> anyhow::Result<()>
{
    let bus = support::Bus::start();
    let _server = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter)?
        .serve_at(format!("{BASE}/services"), Services)?
        .build()
        .await?;
    for (args, expected) in [
        (vec!["ssap-list"], "SsapLocalServices:"),
        (
            vec!["ssap-register", "0100", "0200", "1", "0", "ab"],
            "SsapLocalService: start=16 end=17 properties=17",
        ),
        (
            vec!["ssap-local-read", "17"],
            "SsapLocalValue: handle=17 value=ab",
        ),
        (vec!["ssap-remove", "16"], "SsapLocalRemoved: start=16"),
    ] {
        let o = tokio::process::Command::new(env!("CARGO_BIN_EXE_slctl"))
            .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
            .args(["--session", "--adapter", BASE])
            .args(args)
            .output()
            .await?;
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        assert!(String::from_utf8(o.stdout)?.contains(expected));
    }
    let o = tokio::process::Command::new(env!("CARGO_BIN_EXE_slctl"))
        .env("DBUS_SESSION_BUS_ADDRESS", &bus.address)
        .args(["--session", "--adapter", BASE, "ssap-remove", "19"])
        .output()
        .await?;
    assert!(!o.status.success());
    assert!(String::from_utf8(o.stderr)?.contains("AccessDenied"));
    assert!(!String::from_utf8(o.stdout)?.contains("SsapLocalRemoved:"));
    Ok(())
}
