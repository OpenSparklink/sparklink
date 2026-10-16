type UuidValues = (Vec<(u16, bool, u16, Vec<u8>)>, Vec<u8>, Vec<u8>);
use zbus::Connection;

type NativeReportRecord = (u64, u64, u64, String, i16, Vec<u8>, Vec<u8>, u64);
type NativeLinksRecord = (u64, u64, u64, u32, i32, Vec<(u64, u16, u8, u8, String)>);
type NativeObjectsRecord = (u64, u64, u64, bool, Vec<(String, u64, u16, u8, u8, String)>);
type NativeObjectInfo = (u64, u64, u16, u8, u8, String, bool, bool);
type NativePeerInfo = (u64, u8, String, bool, bool, Vec<String>);

pub struct Context {
    conn: Connection,
    selected: Option<String>,
}

struct DynamicExercise {
    rounds: u32,
    bytes: usize,
    hold: bool,
    mode: crate::channel::Mode,
}

impl Context {
    pub fn new(conn: Connection) -> Self {
        Self {
            conn,
            selected: None,
        }
    }

    pub async fn dispatch(&mut self, args: &[&str]) -> anyhow::Result<()> {
        match args[0] {
            "agent" if args.len() == 1 => {
                let controller = self.selected_path().await?;
                crate::security_agent::run_agent(&self.conn, &controller).await
            }
            "security-request" if args.len() == 2 || args.len() == 3 => {
                let controller = self.selected_path().await?;
                let timeout_ms = args.get(2).map(|v| v.parse()).transpose()?.unwrap_or(5000);
                crate::security_agent::request(&self.conn, &controller, args[1], timeout_ms).await
            }
            "ssap-discover" => {
                if args.len() != 2 && args.len() != 4 {
                    anyhow::bail!(
                        "ssap-discover requires path [structure|service|property uuid-hex]"
                    );
                }
                let kind = if args.len() == 2 {
                    1u8
                } else {
                    match args[2] {
                        "structure" => 0,
                        "service" => 1,
                        "property" => 3,
                        _ => anyhow::bail!("unknown discovery kind"),
                    }
                };
                let uuid = if args.len() == 4 {
                    parse_hex_bytes(args[3])?
                } else {
                    Vec::new()
                };
                let object = self.ssap_proxy(args[1]).await?;
                type Entry = (u8, u16, u16, Vec<u8>, u32, Vec<u8>, u8);
                type Discovery = (Vec<Entry>, Vec<(Vec<u8>, Vec<u8>)>);
                let (entries, trace): Discovery =
                    object.call("DiscoverSsap", &(uuid, kind)).await?;
                for (category, handle, end, uuid, operations, descriptors, members) in &entries {
                    println!(
                        "SsapRemoteEntry: category={category} handle={handle} end={end} uuid={} operations={operations} descriptors={} members={members}",
                        hex_bytes(uuid),
                        hex_bytes(descriptors)
                    );
                }
                if args.len() == 2 {
                    let cached: Vec<Entry> = object.call("GetCachedSsap", &()).await?;
                    if cached != entries {
                        anyhow::bail!("lifetime remote cache differs from actual discovery");
                    }
                }
                println!(
                    "SsapRemoteDiscovery: path={} kind={} entries={} requests={} responses={}",
                    args[1],
                    kind,
                    entries.len(),
                    trace
                        .iter()
                        .map(|(req, _)| hex_bytes(req))
                        .collect::<Vec<_>>()
                        .join("|"),
                    trace
                        .iter()
                        .map(|(_, rsp)| hex_bytes(rsp))
                        .collect::<Vec<_>>()
                        .join("|")
                );
                Ok(())
            }
            "ssap-register" if args.len() == 5 => {
                let path = format!("{}/services", self.selected_path().await?);
                let object = zbus::Proxy::new(
                    &self.conn,
                    "org.sparklink",
                    path,
                    "org.sparklink.ServiceManager",
                )
                .await?;
                let service = parse_hex_bytes(args[1])?;
                let property = parse_hex_bytes(args[2])?;
                let ops: u32 = args[3].parse()?;
                let value = parse_hex_bytes(args[4])?;
                let registered: (u16, u16, Vec<u16>) = object
                    .call(
                        "RegisterLocalService",
                        &(service, vec![(property, ops, value)]),
                    )
                    .await?;
                println!(
                    "SsapLocalService: start={} end={} properties={}",
                    registered.0,
                    registered.1,
                    registered
                        .2
                        .iter()
                        .map(u16::to_string)
                        .collect::<Vec<_>>()
                        .join(",")
                );
                Ok(())
            }
            "ssap-remove" if args.len() == 2 => {
                let path = format!("{}/services", self.selected_path().await?);
                let object = zbus::Proxy::new(
                    &self.conn,
                    "org.sparklink",
                    path,
                    "org.sparklink.ServiceManager",
                )
                .await?;
                let handle: u16 = args[1].parse()?;
                let _: () = object.call("RemoveLocalService", &(handle,)).await?;
                println!("SsapLocalRemoved: start={handle}");
                Ok(())
            }
            "ssap-local-read" if args.len() == 2 => {
                let path = format!("{}/services", self.selected_path().await?);
                let object = zbus::Proxy::new(
                    &self.conn,
                    "org.sparklink",
                    path,
                    "org.sparklink.ServiceManager",
                )
                .await?;
                let handle: u16 = args[1].parse()?;
                let value: Vec<u8> = object.call("ReadLocalValue", &(handle,)).await?;
                println!(
                    "SsapLocalValue: handle={handle} value={}",
                    hex_bytes(&value)
                );
                Ok(())
            }
            "ssap-observe" => {
                if !(3..=5).contains(&args.len()) {
                    anyhow::bail!(
                        "ssap-observe CONNECTION HANDLE [notify|indicate|both] [WAIT_MS]"
                    );
                }
                let object = self.ssap_proxy(args[1]).await?;
                let handle: u16 = args[2].parse()?;
                let modes: u8 = match args.get(3).copied().unwrap_or("both") {
                    "notify" => 1,
                    "indicate" => 2,
                    "both" => 3,
                    _ => anyhow::bail!("invalid local receive mode"),
                };
                let wait: u32 = args.get(4).copied().unwrap_or("5000").parse()?;
                let (indication, raw): (bool, Vec<u8>) = object
                    .call("ObserveSsapIncoming", &(vec![handle], modes, wait))
                    .await?;
                let packet = slk_protocol::ssap::updates::Update::decode(65535, &raw)
                    .map_err(|e| anyhow::anyhow!("incoming codec: {e:?}"))?;
                if packet.indication != indication {
                    anyhow::bail!("incoming kind mismatch");
                }
                for item in packet.items {
                    println!(
                        "SsapIncoming: path={} kind={} handle={} value={} raw={}",
                        args[1],
                        if indication { "indicate" } else { "notify" },
                        item.handle,
                        hex_bytes(item.value),
                        hex_bytes(&raw)
                    );
                }
                Ok(())
            }
            "ssap-read-uuid" => {
                if args.len() != 5 {
                    anyhow::bail!("ssap-read-uuid CONNECTION START END UUID_HEX");
                }
                let object = self.ssap_proxy(args[1]).await?;
                let start: u16 = args[2].parse()?;
                let end: u16 = args[3].parse()?;
                let (entries, request, response): UuidValues = object
                    .call(
                        "ReadSsapByUuid",
                        &(start, end, 0u8, parse_hex_bytes(args[4])?),
                    )
                    .await?;
                for (handle, success, error, value) in entries {
                    println!(
                        "SsapUuidValue: path={} handle={handle} success={success} error={error} value={}",
                        args[1],
                        hex_bytes(&value)
                    );
                }
                println!(
                    "SsapUuidTrace: request={} response={}",
                    hex_bytes(&request),
                    hex_bytes(&response)
                );
                Ok(())
            }
            "ssap-read" | "ssap-write" => {
                if (args[0] == "ssap-read" && args.len() != 3)
                    || (args[0] == "ssap-write" && args.len() != 4)
                {
                    anyhow::bail!(
                        "SSAP value requires connection path, handle and write hex value"
                    );
                }
                let object = self.ssap_proxy(args[1]).await?;
                let handle: u16 = args[2].parse()?;
                let value: Vec<u8> = if args[0] == "ssap-read" {
                    object.call("ReadSsapValue", &(handle,)).await?
                } else {
                    object
                        .call("WriteSsapValue", &(handle, parse_hex_bytes(args[3])?))
                        .await?
                };
                println!(
                    "SsapPeerValue: operation={} path={} handle={} value={}",
                    args[0],
                    args[1],
                    handle,
                    hex_bytes(&value)
                );
                Ok(())
            }
            "ssap-info" => {
                if args.len() != 2 {
                    anyhow::bail!("ssap-info requires one immutable connection path");
                }
                self.cmd_ssap_info(args[1]).await
            }
            "dynamic-peer" | "dynamic-roundtrip" | "dynamic-burst" => {
                if !(5..=8).contains(&args.len()) {
                    anyhow::bail!(
                        "dynamic command: path source-port destination-port aid [rounds] [bytes] [hold]"
                    );
                }
                let rounds = args.get(5).unwrap_or(&"4").parse()?;
                let bytes = args.get(6).unwrap_or(&"61").parse()?;
                if args.get(7).is_some_and(|s| *s != "hold") {
                    anyhow::bail!("last dynamic argument must be hold");
                }
                let burst = args[0] == "dynamic-burst";
                if burst && (rounds != 16 || bytes != 2042) {
                    anyhow::bail!("dynamic-burst requires16 rounds of2042 bytes");
                }
                self.cmd_dynamic_channel(
                    args[1],
                    args[0] == "dynamic-peer",
                    (args[2].parse()?, args[3].parse()?, args[4].parse()?),
                    DynamicExercise {
                        rounds,
                        bytes,
                        hold: args.len() == 8,
                        mode: if burst {
                            crate::channel::Mode::Burst
                        } else {
                            crate::channel::Mode::Regular
                        },
                    },
                )
                .await
            }
            "channel-peer" | "channel-roundtrip" => {
                let path = args.get(1).ok_or_else(|| {
                    anyhow::anyhow!("channel command requires connection object path")
                })?;
                let rounds = args.get(2).unwrap_or(&"4").parse()?;
                let bytes = args.get(3).unwrap_or(&"61").parse()?;
                let mode = match args.get(4) {
                    None => crate::channel::Mode::Regular,
                    Some(&"boundaries") => crate::channel::Mode::Boundaries,
                    Some(&"prefix-close") => crate::channel::Mode::PrefixClose,
                    Some(&"burst") => crate::channel::Mode::Burst,
                    _ => anyhow::bail!("channel mode must be boundaries, prefix-close or burst"),
                };
                if mode == crate::channel::Mode::PrefixClose
                    && (args[0] != "channel-roundtrip" || rounds != 1 || bytes != 2042)
                {
                    anyhow::bail!("prefix-close requires one initiator round of2042 bytes");
                }
                if mode == crate::channel::Mode::Burst
                    && (args[0] != "channel-roundtrip" || rounds != 16 || bytes != 2042)
                {
                    anyhow::bail!("burst requires16 initiator messages of2042 bytes");
                }
                if args.len() > 5 {
                    anyhow::bail!("too many channel arguments");
                }
                self.cmd_channel(path, args[0] == "channel-peer", rounds, bytes, mode)
                    .await
            }
            "list" => self.cmd_list().await,
            "registrations" if args.len() == 1 => self.cmd_registrations().await,
            "registration" if args.len() == 2 => self.cmd_registration(args[1]).await,
            "daemon" => self.cmd_daemon().await,
            "select" => self.cmd_select(args.get(1).copied().unwrap_or("")).await,
            "reports" => self.cmd_reports().await,
            "advertise" => self.cmd_advertise(args).await,
            "cancel-discovery" if args.len() == 1 => self.cmd_cancel_discovery().await,
            "management" if args.len() == 1 => self.cmd_management().await,
            "result" => self.cmd_result(args.get(1).copied().unwrap_or("")).await,
            "show" => self.cmd_show().await,
            "scan" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: scan on|off");
                }
                self.cmd_scan(args).await
            }
            "devices" => self.cmd_devices().await,
            "info" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: info <address>");
                }
                self.cmd_info(args[1]).await
            }
            "pair" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: pair <address>");
                }
                self.cmd_pair(args[1]).await
            }
            "connect" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: connect <address> [address-type]");
                }
                self.cmd_connect(args[1], args.get(2).copied()).await
            }
            "connection-result" => {
                let id: u64 = args
                    .get(1)
                    .ok_or_else(|| anyhow::anyhow!("usage: connection-result <request-id>"))?
                    .parse()?;
                let proxy = self.adapter_proxy().await?;
                let r: NativeConnectionRecord = proxy.call("GetConnectionResult", &(id,)).await?;
                println!(
                    "NativeConnectionResult: generation={} request={} operation={} state={} errno={} fault={} command_status={} outcome_status={} handle={} flags={}",
                    r.0, r.1, r.2, r.3, r.4, r.5, r.6, r.7, r.8, r.9
                );
                Ok(())
            }
            "disconnect" => {
                let addr = args.get(1).copied().unwrap_or("");
                self.cmd_disconnect(addr, args.get(2).copied()).await
            }
            "connections" => self.cmd_connections().await,
            "connection-objects" => self.cmd_connection_objects().await,
            "peer-info" => {
                if args.len() != 2 {
                    anyhow::bail!("usage: peer-info <typed-peer-path>");
                }
                self.cmd_peer_info(args[1]).await
            }
            "connection-info" | "disconnect-object" => {
                if args.len() != 2 {
                    anyhow::bail!("usage: {} <connection-object-path>", args[0]);
                }
                self.cmd_connection_object(args[1], args[0] == "disconnect-object")
                    .await
            }
            "disconnect-link" => {
                if args.len() != 6 {
                    anyhow::bail!(
                        "usage: disconnect-link <address> <type> <handle> <lifetime> <role>"
                    );
                }
                let address = parse_peer_address(args[1])?;
                let kind: u8 = args[2].parse()?;
                let handle: u16 = args[3].parse()?;
                let lifetime: u64 = args[4].parse()?;
                let role: u8 = args[5].parse()?;
                let proxy = self.adapter_proxy().await?;
                let id: u64 = proxy.call("AllocateConnectionRequest", &()).await?;
                println!(
                    "NativeDisconnectReference: request={id} address={address} type={kind} handle={handle} lifetime={lifetime} role={role}"
                );
                let _: () = proxy
                    .call(
                        "SubmitDisconnectReference",
                        &(id, address, kind, handle, lifetime, role),
                    )
                    .await?;
                wait_connection(&proxy, id).await
            }
            "services" => self.cmd_services().await,
            "remote-services" => self.cmd_remote_services().await,
            "read" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: read <handle>");
                }
                self.cmd_read(args[1]).await
            }
            "write" => {
                if args.len() < 3 {
                    anyhow::bail!("usage: write <handle> <hex>");
                }
                self.cmd_write(args[1], args[2]).await
            }
            "security" => self.cmd_security().await,
            "role" => {
                let value = args.get(1).copied();
                self.cmd_role(value).await
            }
            "phy" => self.cmd_phy().await,
            "stats" => self.cmd_stats().await,
            "extadv" => self.cmd_extadv(args).await,
            "power" => self.cmd_power().await,
            "dli" => self.cmd_dli().await,
            "mcs" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: mcs <index>");
                }
                self.cmd_set_mcs(args[1]).await
            }
            "txpower" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: txpower <dBm>");
                }
                self.cmd_set_txpower(args[1]).await
            }
            "afh" => self.cmd_afh(args).await,
            "ral" => self.cmd_ral(args).await,
            "rpa" => self.cmd_rpa(args).await,
            "sync" => self.cmd_sync(args).await,
            "meas" => self.cmd_meas(args).await,
            "peer" => self.cmd_peer(args).await,
            "bandwidth" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: bandwidth <MHz>");
                }
                self.cmd_set_bandwidth(args[1]).await
            }
            "events" => self.cmd_events().await,
            "mgmt" => self.cmd_mgmt().await,
            "bonded" => self.cmd_bonded(args).await,
            _ => {
                anyhow::bail!("unknown command '{}' — type 'help'", args[0]);
            }
        }
    }

    async fn selected_path(&self) -> anyhow::Result<String> {
        let paths: Vec<String> = self
            .manager_proxy()
            .await?
            .call("ListAdapters", &())
            .await?;
        if let Some(selected) = &self.selected {
            if paths.contains(selected) {
                return Ok(selected.clone());
            }
            anyhow::bail!("selected registration removed; run list and select its replacement");
        }
        if paths.len() == 1 {
            return Ok(paths[0].clone());
        }
        anyhow::bail!("select one of the live adapter paths using 'select <path>'");
    }
    async fn cmd_select(&mut self, path: &str) -> anyhow::Result<()> {
        let paths: Vec<String> = self
            .manager_proxy()
            .await?
            .call("ListAdapters", &())
            .await?;
        let candidate = if path.starts_with('/') {
            path.to_owned()
        } else {
            format!("/org/sparklink/{path}")
        };
        if !paths.contains(&candidate) {
            anyhow::bail!("adapter is not a live registration: {candidate}");
        }
        self.selected = Some(candidate.clone());
        println!("Selected {candidate}");
        Ok(())
    }
    async fn cmd_daemon(&self) -> anyhow::Result<()> {
        let bus = zbus::fdo::DBusProxy::new(&self.conn).await?;
        let service = zbus::names::BusName::try_from("org.sparklink")?;
        let owner = bus.get_name_owner(service).await?;
        let pid = bus
            .get_connection_unix_process_id(owner.as_ref().into())
            .await?;
        let uid = bus.get_connection_unix_user(owner.as_ref().into()).await?;
        println!("DaemonIdentity: owner={owner} pid={pid} uid={uid}");
        Ok(())
    }

    async fn cmd_reports(&self) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let reports: Vec<NativeReportRecord> = proxy.call("GetReports", &()).await?;
        for (seq, generation, ms, address, rssi, header, data, lost) in reports {
            let hex = |bytes: &[u8]| bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
            println!(
                "seq={seq} generation={generation} time_ms={ms} address={address} RSSI={rssi} header={} data={} lost={lost}",
                hex(&header),
                hex(&data)
            );
        }
        Ok(())
    }

    async fn adapter_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            self.selected_path().await?,
            "org.sparklink.Adapter",
        )
        .await?)
    }

    async fn security_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            format!("{}/security", self.selected_path().await?),
            "org.sparklink.Security",
        )
        .await?)
    }

    async fn service_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            format!("{}/services", self.selected_path().await?),
            "org.sparklink.ServiceManager",
        )
        .await?)
    }

    async fn manager_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            "/org/sparklink",
            "org.sparklink.Manager",
        )
        .await?)
    }

    async fn controller_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            format!("{}/controller", self.selected_path().await?),
            "org.sparklink.Controller",
        )
        .await?)
    }

    async fn extadv_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            format!("{}/extadv", self.selected_path().await?),
            "org.sparklink.ExtAdv",
        )
        .await?)
    }

    async fn cmd_list(&self) -> anyhow::Result<()> {
        let proxy = self.manager_proxy().await?;
        let adapters: Vec<String> = proxy.call("ListAdapters", &()).await?;
        if adapters.is_empty() {
            println!("No adapters found");
        } else {
            for a in &adapters {
                println!("  {a}");
            }
        }
        Ok(())
    }

    async fn cmd_registrations(&self) -> anyhow::Result<()> {
        let paths: Vec<String> = self
            .manager_proxy()
            .await?
            .call("ListRegistrations", &())
            .await?;
        for path in paths {
            self.cmd_registration(&path).await?;
        }
        Ok(())
    }
    async fn cmd_registration(&self, path: &str) -> anyhow::Result<()> {
        let path = if path.starts_with('/') {
            path.to_owned()
        } else {
            format!("/org/sparklink/{path}")
        };
        let proxy = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            path.as_str(),
            "org.sparklink.Registration",
        )
        .await?;
        let (generation,version,state,profile,phase,error,index,bus): slk_protocol::RegistrationSnapshotRecord = proxy.call("GetSnapshot", &()).await?;
        let snapshot = slk_protocol::SleRegistrationSnapshot {
            generation,
            version,
            state,
            profile,
            phase,
            error,
            dev_index: index,
            bus,
            ..Default::default()
        };
        anyhow::ensure!(
            snapshot.valid_for(index, generation),
            "invalid registration observation"
        );
        anyhow::ensure!(
            path == format!("/org/sparklink/slk{index}_g{generation}"),
            "registration path/identity mismatch"
        );
        let name = match state {
            slk_protocol::REGISTRATION_PENDING => "Pending",
            slk_protocol::REGISTRATION_FAULT => "Fault",
            slk_protocol::REGISTRATION_INSTALLED => "Installed",
            slk_protocol::REGISTRATION_RETIRING => "Retiring",
            _ => unreachable!(),
        };
        println!(
            "Registration {path}: index={index} generation={generation} state={name} profile={profile} bus={bus} phase={phase} error={error}"
        );
        Ok(())
    }

    async fn cmd_show(&self) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let name: String = proxy.get_property("Name").await?;
        let powered: bool = proxy.get_property("Powered").await?;
        let discovering: bool = proxy.get_property("Discovering").await?;

        let status: String = proxy.get_property("ControllerState").await?;
        let generation: u64 = proxy.get_property("Generation").await?;
        let address: String = proxy.get_property("Address").await?;
        let profile: u32 = proxy.get_property("Profile").await?;
        let error: String = proxy.get_property("InitializationError").await?;
        println!("Adapter {}:", self.selected_path().await?);
        println!("  State:       {status}");
        println!("  Generation:  {generation}");
        println!("  Address:     {address}");
        println!("  Profile:     {profile}");
        if profile == 1 {
            let (seq, revision, known): (u64, u64, bool) =
                proxy.get_property("NativeLinkObservation").await?;
            let lost: u64 = proxy.get_property("EventsLost").await?;
            println!(
                "  Native links: event_seq={seq} revision={revision} known={known} lost={lost}"
            );
            let (version, min, max, power, interval, window): (u32, u32, u32, i32, u32, u32) =
                proxy.call("GetDiscoveryPolicy", &()).await?;
            println!(
                "  Radio policy: version={version} adv_slots={min}..{max} tx_power_dbm={power} scan_slots={interval}/{window}"
            );
        }
        if !error.is_empty() {
            println!("  Init error:  {error}");
        }
        println!("  Name:        {name}");
        println!("  Powered:     {powered}");
        println!("  Discovering: {discovering}");
        Ok(())
    }

    async fn cmd_advertise(&self, args: &[&str]) -> anyhow::Result<()> {
        if args == ["advertise", "initialized-off"] {
            return self
                .cmd_initialization_off(slk_protocol::DISCOVERY_ADV_CONFIGURE_OFF)
                .await;
        }
        let proxy = self.adapter_proxy().await?;
        let id = random_bytes::<8>()?;
        let id = u64::from_ne_bytes(id).max(1);
        match args.get(1).copied() {
            Some("on" | "connectable" | "negotiable") => {
                let marker: [u8; 16] = if let Some(hex) = args.get(2) {
                    parse_hex_bytes(hex)?
                        .try_into()
                        .map_err(|_| anyhow::anyhow!("marker must be 16 bytes (32 hex digits)"))?
                } else {
                    random_bytes()?
                };
                println!(
                    "NativeAdvertisementRequest: request={id} marker={}",
                    hex_bytes(&marker)
                );
                let data: Vec<u8> = if args[1] == "on" {
                    tokio::time::timeout(
                        std::time::Duration::from_secs(7),
                        proxy.call("SubmitAdvertising", &(id, marker.to_vec())),
                    )
                    .await??
                } else {
                    tokio::time::timeout(
                        std::time::Duration::from_secs(7),
                        proxy.call(
                            "SubmitConnectableAdvertising",
                            &(id, marker.to_vec(), args[1] == "negotiable"),
                        ),
                    )
                    .await??
                };
                println!(
                    "NativeAdvertisementAccepted: request={id} marker={} data={}",
                    hex_bytes(&marker),
                    hex_bytes(&data)
                );
            }
            Some("off") => {
                println!("NativeStopAdvertisingRequest: request={id}");
                let _: () = tokio::time::timeout(
                    std::time::Duration::from_secs(7),
                    proxy.call("SubmitStopAdvertising", &(id,)),
                )
                .await??;
            }
            _ => anyhow::bail!("usage: advertise on|connectable|negotiable [32-hex-marker]|off"),
        }
        self.wait_native_result(&proxy, id).await
    }
    async fn cmd_result(&self, id: &str) -> anyhow::Result<()> {
        let id: u64 = id.parse()?;
        let proxy = self.adapter_proxy().await?;
        let result: slk_protocol::DiscoveryResultRecord =
            proxy.call("GetDiscoveryResult", &(id,)).await?;
        print_native_result(result)?;
        Ok(())
    }
    async fn cmd_initialization_off(&self, operation: u32) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let result: slk_protocol::DiscoveryResultRecord = tokio::time::timeout(
            std::time::Duration::from_secs(3),
            proxy.call("GetInitializationOff", &(operation,)),
        )
        .await??;
        print_native_result(result)
    }
    async fn wait_native_result(&self, proxy: &zbus::Proxy<'_>, id: u64) -> anyhow::Result<()> {
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(7);
        let generation: u64 =
            tokio::time::timeout_at(deadline, proxy.get_property("Generation")).await??;
        loop {
            let result: slk_protocol::DiscoveryResultRecord =
                tokio::time::timeout_at(deadline, proxy.call("GetDiscoveryResult", &(id,)))
                    .await??;
            if result.1 != id || result.0 != generation || result.13 != 1 {
                anyhow::bail!("operation result identity mismatch");
            }
            if result.3 >= 3 {
                print_native_result(result)?;
                return Ok(());
            }
            if tokio::time::Instant::now() >= deadline {
                anyhow::bail!(
                    "operation wait timeout; inspect 'result {id}' or explicitly stop it"
                );
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    }

    async fn cmd_cancel_discovery(&self) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let generation: u64 = proxy.get_property("Generation").await?;
        println!("NativePoliciesCancelRequest: generation={generation}");
        let confirmed: u64 = tokio::time::timeout(
            std::time::Duration::from_secs(8),
            proxy.call("CancelDiscoveryPolicies", &()),
        )
        .await??;
        anyhow::ensure!(
            confirmed == generation,
            "policy cancellation changed generation"
        );
        println!("NativePoliciesCancelled: generation={confirmed}");
        Ok(())
    }

    async fn cmd_management(&self) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let expected: u64 = proxy.get_property("Generation").await?;
        let (generation, mode, state, flags, error, status, opcode): (
            u64,
            u32,
            u32,
            u32,
            i32,
            u32,
            u32,
        ) = tokio::time::timeout(
            std::time::Duration::from_secs(3),
            proxy.call("GetManagementStatus", &()),
        )
        .await??;
        anyhow::ensure!(generation == expected, "management generation mismatch");
        println!(
            "NativeManagementStatus: generation={generation} mode={mode} state={state} flags={flags} errno={error} status=0x{status:02x} opcode=0x{opcode:04x}"
        );
        Ok(())
    }

    async fn cmd_scan(&self, args: &[&str]) -> anyhow::Result<()> {
        if args == ["scan", "initialized-off"] {
            return self
                .cmd_initialization_off(slk_protocol::DISCOVERY_SCAN_INITIALIZE_OFF)
                .await;
        }
        let toggle = args[1];
        let proxy = self.adapter_proxy().await?;
        if proxy.get_property::<u32>("Profile").await? == 1 {
            let id = u64::from_ne_bytes(random_bytes::<8>()?).max(1);
            let method = match toggle {
                "on" => "SubmitScanning",
                "off" => "SubmitStopScanning",
                _ => anyhow::bail!("usage: scan on|off"),
            };
            let matching = match args.len() {
                2 => None,
                4 if toggle == "on" => {
                    let marker: [u8; 16] = parse_hex_bytes(args[2])?
                        .try_into()
                        .map_err(|_| anyhow::anyhow!("marker must have 32 hex digits"))?;
                    let address = parse_peer_address(args[3])?;
                    Some((marker, address))
                }
                _ => anyhow::bail!("usage: scan on [32-hex-marker advertiser-address]|off"),
            };
            let generation: u64 = proxy.get_property("Generation").await?;
            let before: Vec<slk_protocol::TimedDiscoveryReportRecord> =
                proxy.call("GetTimedReports", &()).await?;
            let watermark = before.iter().map(|r| r.0).max().unwrap_or(0);
            // The invocation lower bound rejects queued older kernel RX;
            // the discovery deadline separately starts at matched Complete.
            let scan_boottime_ns = boottime_ns()?;
            println!(
                "NativeScanWindow: generation={generation} request={id} start_boottime_ns={scan_boottime_ns}"
            );
            println!("NativeScanRequest: request={id} enable={toggle}");
            let _: () = tokio::time::timeout(
                std::time::Duration::from_secs(7),
                proxy.call(method, &(id,)),
            )
            .await??;
            self.wait_native_result(&proxy, id).await?;
            if let Some((marker, address)) = matching {
                let expected = libsparklink::ws73_marker_data(&marker);
                let timing: (u64, u64, u64, u32, u32, u16, u8) = tokio::time::timeout(
                    std::time::Duration::from_secs(7),
                    proxy.call("GetDiscoveryTiming", &(id,)),
                )
                .await??;
                let completed = timing.2;
                let observed = boottime_ns()?;
                if timing.0 != generation
                    || timing.1 != id
                    || timing.3 != 3
                    || timing.4 != 3
                    || timing.5 != 0x1002
                    || timing.6 != 0
                    || completed < scan_boottime_ns
                    || completed > observed
                {
                    anyhow::bail!("invalid correlated Scan Complete timing");
                }
                println!(
                    "NativeScanComplete: generation={generation} request={id} completed_boottime_ns={completed}"
                );
                let expires = completed
                    .checked_add(10_000_000_000)
                    .ok_or_else(|| anyhow::anyhow!("scan deadline overflow"))?;
                loop {
                    let rows: Vec<slk_protocol::TimedDiscoveryReportRecord> = tokio::time::timeout(
                        std::time::Duration::from_nanos(
                            expires
                                .checked_sub(boottime_ns()?)
                                .filter(|n| *n > 0)
                                .ok_or_else(|| {
                                    anyhow::anyhow!(
                                        "fresh marker discovery timeout (10s after Scan Complete)"
                                    )
                                })?,
                        ),
                        proxy.call("GetTimedReports", &()),
                    )
                    .await??;
                    let observed_boottime_ns = boottime_ns()?;
                    if observed_boottime_ns >= expires {
                        anyhow::bail!("fresh marker discovery timeout (10s after Scan Complete)");
                    }
                    for row in rows {
                        if row.0 > watermark
                            && row.1 == generation
                            && (completed..=observed_boottime_ns).contains(&row.2)
                            && row.8 == 0
                            && row.4 == address
                            && row.7 == expected
                        {
                            println!(
                                "NativeScanObserved: generation={generation} request={id} observed_boottime_ns={observed_boottime_ns}"
                            );
                            println!(
                                "NativeDiscoveryMatch: generation={} seq={} address={} RSSI={} marker={} data={} kernel_boottime_ns={} elapsed_ms={} lost={}",
                                row.1,
                                row.0,
                                row.4,
                                row.5,
                                hex_bytes(&marker),
                                hex_bytes(&row.7),
                                row.2,
                                (observed_boottime_ns - completed) / 1_000_000,
                                row.8
                            );
                            return Ok(());
                        }
                    }
                    tokio::time::sleep(std::time::Duration::from_millis(20)).await;
                }
            }
            return Ok(());
        }
        match toggle {
            "on" => {
                let _: () = proxy.call("StartControllerScan", &()).await?;
                println!("Discovery started");
            }
            "off" => {
                let _: () = proxy.call("StopControllerScan", &()).await?;
                println!("Discovery stopped");
            }
            _ => anyhow::bail!("usage: scan on|off"),
        }
        Ok(())
    }

    async fn cmd_devices(&self) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let devices: Vec<(String, String, i16, bool)> = proxy.call("GetDevices", &()).await?;
        if devices.is_empty() {
            println!("No devices found");
        } else {
            for (addr, name, rssi, connected) in &devices {
                let status = if *connected { "connected" } else { "" };
                println!("  {addr}  {name:<20} RSSI={rssi:>4} {status}");
            }
        }
        Ok(())
    }

    async fn cmd_info(&self, address: &str) -> anyhow::Result<()> {
        let object_path = format!(
            "{}/dev_{}",
            self.selected_path().await?,
            address.replace(':', "").to_lowercase()
        );
        let proxy = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            object_path.as_str(),
            "org.sparklink.Device",
        )
        .await?;

        let name: String = proxy.get_property("Name").await?;
        let rssi: i16 = proxy.get_property("Rssi").await?;
        let connected: bool = proxy.get_property("Connected").await?;

        println!("Device {address}:");
        println!("  Name:      {name}");
        println!("  RSSI:      {rssi} dBm");
        println!("  Connected: {connected}");
        Ok(())
    }

    async fn cmd_pair(&self, address: &str) -> anyhow::Result<()> {
        let sec = self.security_proxy().await?;
        println!("Pairing with {address}...");
        let _: () = sec.call("Pair", &("just_works",)).await?;
        println!("Pairing initiated");
        Ok(())
    }

    async fn cmd_connect(&self, address: &str, address_type: Option<&str>) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let profile: u32 = proxy.get_property("Profile").await?;
        if profile == 1 {
            let address_type: u8 = address_type
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "usage: connect <address> <address-type>; type is explicit, not inferred"
                    )
                })?
                .parse()?;
            let id: u64 = proxy.call("AllocateConnectionRequest", &()).await?;
            println!(
                "NativeConnectionRequest: request={id} address={address} address_type={address_type}"
            );
            let _: () = proxy
                .call("SubmitConnect", &(id, address, address_type))
                .await?;
            wait_connection(&proxy, id).await?;
        } else {
            let _: () = proxy.call("ConnectDevice", &(address,)).await?;
            println!("Connection request accepted for {address}");
            return Ok(());
        }
        println!("Connection procedure completed for {address}");
        Ok(())
    }
    async fn cmd_disconnect(
        &self,
        address: &str,
        address_type: Option<&str>,
    ) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let profile: u32 = proxy.get_property("Profile").await?;
        if profile == 1 {
            let id: u64 = proxy.call("AllocateConnectionRequest", &()).await?;
            println!("NativeDisconnectRequest: request={id} address={address}");
            if let Some(kind) = address_type {
                let kind: u8 = kind.parse()?;
                let _: () = proxy
                    .call("SubmitDisconnectTyped", &(id, address, kind))
                    .await?;
            } else {
                let _: () = proxy.call("SubmitDisconnect", &(id, address)).await?;
            }
            wait_connection(&proxy, id).await?;
        } else {
            let _: () = proxy.call("DisconnectAddress", &(address,)).await?;
            println!("Disconnect request accepted for {address}");
            return Ok(());
        }
        println!("Disconnect procedure completed for {address}");
        Ok(())
    }
    async fn cmd_connections(&self) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let (generation, seq, revision, flags, error, links): NativeLinksRecord =
            proxy.call("GetNativeConnections", &()).await?;
        println!(
            "NativeLinksSnapshot: generation={generation} event_seq={seq} revision={revision} flags={flags} errno={error}"
        );
        if flags != 1 || error != 0 {
            anyhow::bail!("physical connection table unknown");
        }
        for (lifetime, handle, role, kind, address) in links {
            println!(
                "NativeLink: lifetime={lifetime} handle={handle} role={role} type={kind} address={address}"
            );
        }
        Ok(())
    }
    async fn cmd_connection_objects(&self) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let (generation, seq, revision, known, objects): NativeObjectsRecord =
            proxy.call("GetNativeConnectionObjects", &()).await?;
        println!(
            "NativeConnectionObjects: generation={generation} event_seq={seq} revision={revision} known={known}"
        );
        if !known {
            anyhow::bail!("physical connection observation unknown");
        }
        for (path, lifetime, handle, role, kind, address) in objects {
            println!(
                "NativeConnectionObject: generation={generation} lifetime={lifetime} handle={handle} role={role} type={kind} address={address} path={path}"
            );
        }
        Ok(())
    }
    async fn cmd_peer_info(&self, path: &str) -> anyhow::Result<()> {
        let adapter = self.adapter_proxy().await?;
        let selected = self.selected_path().await?;
        if !path.starts_with(&format!("{selected}/peer_t")) {
            anyhow::bail!("peer does not belong to the selected adapter");
        }
        let peer =
            zbus::Proxy::new(&self.conn, "org.sparklink", path, "org.sparklink.Peer").await?;
        let (generation, kind, address, known, connected, objects): NativePeerInfo =
            peer.call("GetInfo", &()).await?;
        let selected_generation: u64 = adapter.get_property("Generation").await?;
        let expected = format!(
            "{selected}/peer_t{kind:02x}_{}",
            address.replace(':', "").to_lowercase()
        );
        if generation != selected_generation || path != expected {
            anyhow::bail!("typed peer identity mismatch");
        }
        println!(
            "NativePeerInfo: generation={generation} type={kind} address={address} known={known} connected={connected} path={path}"
        );
        for object in objects {
            println!("NativePeerConnection: path={object}");
        }
        Ok(())
    }
    async fn ssap_proxy(&self, path: &str) -> anyhow::Result<zbus::Proxy<'_>> {
        let selected = self.selected_path().await?;
        if !path.starts_with(&format!("{selected}/peer_t")) {
            anyhow::bail!("SSAP connection belongs to another adapter");
        }
        let object = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            path.to_owned(),
            "org.sparklink.Connection",
        )
        .await?;
        let identity: NativeObjectInfo = object.call("GetInfo", &()).await?;
        let expected = format!(
            "{selected}/peer_t{:02x}_{}/link_{:016x}",
            identity.4,
            identity.5.replace(':', "").to_lowercase(),
            identity.1
        );
        let adapter = self.adapter_proxy().await?;
        let generation: u64 = adapter.get_property("Generation").await?;
        if path != expected || generation != identity.0 || !identity.6 || !identity.7 {
            anyhow::bail!("SSAP lifetime unknown/retired");
        }
        Ok(object)
    }
    async fn cmd_ssap_info(&self, path: &str) -> anyhow::Result<()> {
        let object = self.ssap_proxy(path).await?;
        let identity: NativeObjectInfo = object.call("GetInfo", &()).await?;
        type SsapInfo = (
            u16,
            u64,
            u64,
            u16,
            u16,
            u16,
            Vec<u8>,
            Vec<u8>,
            Vec<u8>,
            Vec<u8>,
        );
        let info: SsapInfo = object.call("GetSsapInfo", &()).await?;
        if info.1 != identity.0 || info.2 != identity.1 || info.3 != identity.2 {
            anyhow::bail!("SSAP reply lifetime mismatch");
        }
        let hex = |v: &[u8]| v.iter().map(|b| format!("{b:02x}")).collect::<String>();
        println!(
            "SsapExchangeInfo: index={} generation={} lifetime={} handle={} local_mtu={} negotiated_mtu={} request={} peer_reply={} peer_request={} response={}",
            info.0,
            info.1,
            info.2,
            info.3,
            info.4,
            info.5,
            hex(&info.6),
            hex(&info.7),
            hex(&info.8),
            hex(&info.9)
        );
        Ok(())
    }

    async fn cmd_dynamic_channel(
        &self,
        path: &str,
        responder: bool,
        route: (u16, u16, u16),
        exercise: DynamicExercise,
    ) -> anyhow::Result<()> {
        let DynamicExercise {
            rounds,
            bytes,
            hold,
            mode,
        } = exercise;
        use std::os::fd::AsRawFd;
        let selected = self.selected_path().await?;
        if !path.starts_with(&format!("{selected}/peer_t")) {
            anyhow::bail!("dynamic connection belongs to another adapter");
        }
        if !(29..=2042).contains(&bytes) || !(1..=20).contains(&rounds) {
            anyhow::bail!("dynamic exercise requires1..20 rounds and29..2042 bytes");
        }
        let object = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            path,
            "org.sparklink.Connection",
        )
        .await?;
        let info: NativeObjectInfo = object.call("GetInfo", &()).await?;
        let generation: u64 = self
            .adapter_proxy()
            .await?
            .get_property("Generation")
            .await?;
        let expected = format!(
            "{selected}/peer_t{:02x}_{}/link_{:016x}",
            info.4,
            info.5.replace(':', "").to_lowercase(),
            info.1
        );
        if info.0 != generation || path != expected || !info.6 || !info.7 {
            anyhow::bail!("dynamic immutable connection is not known/live");
        }
        let mtu = u16::try_from(bytes.max(249))?;
        let request = (route.0, route.1, route.2, mtu, mtu + 5, 1u8, responder);
        let fd: zbus::zvariant::OwnedFd = object.call("PrepareDynamicChannel", &(request,)).await?;
        let fd: std::os::fd::OwnedFd = fd.into();
        // An explicit test/coordinated-service hold keeps the final VFS
        // reference alive until both applications have validated their data.
        let retained = if hold {
            // SAFETY: fd is live; success creates a distinct owned reference.
            let raw = unsafe { nix::libc::fcntl(fd.as_raw_fd(), nix::libc::F_DUPFD_CLOEXEC, 0) };
            if raw < 0 {
                return Err(std::io::Error::last_os_error().into());
            }
            use std::os::fd::FromRawFd;
            // SAFETY: unique newly returned descriptor.
            Some(unsafe { std::os::fd::OwnedFd::from_raw_fd(raw) })
        } else {
            None
        };
        println!(
            "NativeDynamicStaged: source={} destination={} aid={} passive={responder}",
            route.0, route.1, route.2
        );
        crate::channel::exercise_dynamic(fd, responder, rounds, bytes, mode)?;
        println!("NativeDynamicBusinessDone: rounds={rounds} held={hold}");
        if hold {
            let mut command = String::new();
            if std::io::stdin().read_line(&mut command)? == 0 || command.trim() != "close" {
                anyhow::bail!("explicit dynamic hold requires close; EOF is author withdrawal");
            }
        }
        drop(retained);
        println!(
            "NativeDynamicLastClose: source={} destination={} aid={}",
            route.0, route.1, route.2
        );
        Ok(())
    }
    async fn cmd_channel(
        &self,
        path: &str,
        responder: bool,
        rounds: u32,
        bytes: usize,
        mode: crate::channel::Mode,
    ) -> anyhow::Result<()> {
        let selected = self.selected_path().await?;
        if !path.starts_with(&format!("{selected}/peer_t")) {
            anyhow::bail!("connection object belongs to another adapter");
        }
        let object = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            path,
            "org.sparklink.Connection",
        )
        .await?;
        let info: NativeObjectInfo = object.call("GetInfo", &()).await?;
        let adapter = self.adapter_proxy().await?;
        let generation: u64 = adapter.get_property("Generation").await?;
        let expected = format!(
            "{selected}/peer_t{:02x}_{}/link_{:016x}",
            info.4,
            info.5.replace(':', "").to_lowercase(),
            info.1
        );
        if info.0 != generation || path != expected {
            anyhow::bail!("immutable channel connection identity mismatch");
        }
        if !info.6 || !info.7 {
            anyhow::bail!("connection is not known/live");
        }
        let fd: zbus::zvariant::OwnedFd = object.call("OpenChannel", &()).await?;
        crate::channel::exercise(fd.into(), responder, rounds, bytes, mode)?;
        // Last-close must not silently recreate the connection CMTC session.
        // Basic CUTC has no qualified close/rebind barrier in this lifetime.
        let reopened: zbus::Result<zbus::zvariant::OwnedFd> = object.call("OpenChannel", &()).await;
        match reopened {
            Err(zbus::Error::MethodError(name, _, _))
                if name.as_str() == "org.freedesktop.DBus.Error.NotSupported" =>
            {
                println!("NativeChannelLastClose: same_lifetime_reopen=NotSupported");
                Ok(())
            }
            Err(error) => Err(error.into()),
            Ok(_) => {
                anyhow::bail!("same-lifetime CUTC unexpectedly rebound without a protocol barrier")
            }
        }
    }
    async fn cmd_connection_object(&self, path: &str, disconnect: bool) -> anyhow::Result<()> {
        let adapter = self.adapter_proxy().await?;
        let selected = self.selected_path().await?;
        if !path.starts_with(&format!("{selected}/peer_t")) {
            anyhow::bail!("connection object does not belong to the selected adapter");
        }
        let object = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            path,
            "org.sparklink.Connection",
        )
        .await?;
        let (generation, lifetime, handle, role, kind, address, known, connected): NativeObjectInfo = object.call("GetInfo", &()).await?;
        let selected_generation: u64 = adapter.get_property("Generation").await?;
        let expected = format!(
            "{selected}/peer_t{kind:02x}_{}/link_{lifetime:016x}",
            address.replace(':', "").to_lowercase()
        );
        if generation != selected_generation || path != expected {
            anyhow::bail!("connection object identity mismatch");
        }
        if disconnect {
            let id: u64 = adapter.call("AllocateConnectionRequest", &()).await?;
            println!(
                "NativeDisconnectObject: request={id} generation={generation} lifetime={lifetime} handle={handle} role={role} type={kind} address={address} path={path}"
            );
            let _: () = object.call("SubmitDisconnect", &(id,)).await?;
            wait_connection(&adapter, id).await
        } else {
            println!(
                "NativeConnectionInfo: generation={generation} lifetime={lifetime} handle={handle} role={role} type={kind} address={address} known={known} connected={connected} path={path}"
            );
            Ok(())
        }
    }

    async fn cmd_services(&self) -> anyhow::Result<()> {
        let proxy = self.service_proxy().await?;
        let services: Vec<(u16, u16, u16, bool)> = proxy.call("ListServices", &()).await?;
        if services.is_empty() {
            println!("No services registered");
        } else {
            for (start, end, uuid16, primary) in &services {
                let kind = if *primary { "Primary" } else { "Secondary" };
                println!(
                    "  [{:#06x}-{:#06x}] UUID={:#06x} {kind}",
                    start, end, uuid16
                );
            }
        }
        Ok(())
    }

    async fn cmd_remote_services(&self) -> anyhow::Result<()> {
        println!("Remote service discovery requires an active connection.");
        println!("Use 'connect <address> <address-type>' first, then the daemon exposes");
        println!(
            "org.sparklink.RemoteService at {}/conn_<handle>",
            self.selected_path().await?
        );
        Ok(())
    }

    async fn cmd_read(&self, handle_str: &str) -> anyhow::Result<()> {
        let handle = parse_handle(handle_str)?;
        let proxy = self.service_proxy().await?;
        let data: Vec<u8> = proxy.call("ReadProperty", &(handle,)).await?;
        println!("Property {:#06x} ({} bytes):", handle, data.len());
        print!("  ");
        for b in &data {
            print!("{:02x} ", b);
        }
        println!();
        if let Ok(s) = std::str::from_utf8(&data) {
            println!("  UTF-8: \"{s}\"");
        }
        Ok(())
    }

    async fn cmd_write(&self, handle_str: &str, value_hex: &str) -> anyhow::Result<()> {
        let handle = parse_handle(handle_str)?;
        let value = parse_hex_bytes(value_hex)?;
        let proxy = self.service_proxy().await?;
        let _: () = proxy.call("WriteProperty", &(handle, value)).await?;
        println!("Written to property {:#06x}", handle);
        Ok(())
    }

    async fn cmd_security(&self) -> anyhow::Result<()> {
        let proxy = self.security_proxy().await?;
        let encrypted: bool = proxy.get_property("Encrypted").await?;
        let paired: bool = proxy.get_property("Paired").await?;
        println!("Security:");
        println!("  Encrypted: {encrypted}");
        println!("  Paired:    {paired}");
        Ok(())
    }

    async fn cmd_role(&self, value: Option<&str>) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        match value {
            Some("g") | Some("0") => {
                let _: () = proxy.call("SetRole", &(0u8,)).await?;
                println!("Role set to G-node");
            }
            Some("t") | Some("1") => {
                let _: () = proxy.call("SetRole", &(1u8,)).await?;
                println!("Role set to T-node");
            }
            Some(_) => anyhow::bail!("role: g or t"),
            None => {
                let role: u8 = proxy.call("GetRole", &()).await?;
                let label = if role == 0 { "G-node" } else { "T-node" };
                println!("Role: {label} ({role})");
            }
        }
        Ok(())
    }

    async fn cmd_phy(&self) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let info: (u8, u8, i8, u32, u8, u8) = proxy.call("GetPhyInfo", &()).await?;
        println!("PHY:");
        println!("  MCS Index:    {}", info.0);
        println!("  Bandwidth:    {} MHz", info.1);
        println!("  TX Power:     {} dBm", info.2);
        println!("  Data Rate:    {} kbps", info.3);
        println!("  Hop Channel:  {}", info.4);
        println!("  Modulation:   {}", info.5);
        Ok(())
    }

    async fn cmd_stats(&self) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let stats: (u16, u64, u64, u64, u32) = proxy.call("GetLinkSummary", &()).await?;
        println!(
            "ControllerLinkSummary: index={} generation={} revision={} event_sequence={} connections={}",
            stats.0, stats.1, stats.2, stats.3, stats.4
        );
        println!(
            "Confirmed physical links at this snapshot; not logical channels, queue depth, PM, or delivery ACK."
        );
        Ok(())
    }

    async fn cmd_extadv(&self, args: &[&str]) -> anyhow::Result<()> {
        let proxy = self.extadv_proxy().await?;
        let sub = args.get(1).copied().unwrap_or("help");
        match sub {
            "enable" => {
                let handle: u8 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: extadv enable <handle>"))?
                    .parse()?;
                let _: () = proxy.call("Enable", &(handle,)).await?;
                println!("ExtAdv set {handle} enabled");
            }
            "disable" => {
                let handle: u8 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: extadv disable <handle>"))?
                    .parse()?;
                let _: () = proxy.call("Disable", &(handle,)).await?;
                println!("ExtAdv set {handle} disabled");
            }
            "remove" => {
                let handle: u8 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: extadv remove <handle>"))?
                    .parse()?;
                let _: () = proxy.call("Remove", &(handle,)).await?;
                println!("ExtAdv set {handle} removed");
            }
            "info" => {
                let handle: u8 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: extadv info <handle>"))?
                    .parse()?;
                let info: (u8, u8, u8, u8, u16, u64, u32) =
                    proxy.call("GetInfo", &(handle,)).await?;
                println!("ExtAdv Set {handle}:");
                println!("  State:       {}", info.1);
                println!("  SID:         {}", info.2);
                println!("  Primary PHY: {}", info.3);
                println!("  Data Length: {}", info.4);
                println!("  TX Count:    {}", info.5);
                println!("  Events Sent: {}", info.6);
            }
            _ => {
                println!("Extended Advertising:");
                println!("  extadv enable <handle>   Enable set");
                println!("  extadv disable <handle>  Disable set");
                println!("  extadv remove <handle>   Remove set");
                println!("  extadv info <handle>     Show set info");
            }
        }
        Ok(())
    }

    async fn cmd_power(&self) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let info: (u8, bool, u16, u32) = proxy.call("GetPmInfo", &()).await?;
        let state_label = match info.0 {
            0 => "Active",
            1 => "Sniff",
            2 => "Idle",
            3 => "Suspended",
            _ => "Unknown",
        };
        println!("Power Management:");
        println!("  State:          {state_label}");
        println!("  Force Active:   {}", info.1);
        println!("  Interval:       {} ms", info.2);
        println!("  Transitions:    {}", info.3);
        Ok(())
    }

    async fn cmd_dli(&self) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let info: (u8, u32, u8, u8, u16, String) = proxy.call("GetDliInfo", &()).await?;
        println!("DLI Controller:");
        println!("  Name:            {}", info.5);
        println!("  Bus:             {}", info.0);
        println!("  FW Version:      {:#010x}", info.1);
        println!("  Max Connections:  {}", info.2);
        println!("  Max AdvSets:      {}", info.3);
        println!("  Max MTU:          {}", info.4);
        Ok(())
    }

    async fn cmd_set_mcs(&self, index_str: &str) -> anyhow::Result<()> {
        let index: u8 = index_str.parse()?;
        let proxy = self.controller_proxy().await?;
        let _: () = proxy.call("SetMcs", &(index,)).await?;
        println!("MCS index set to {index}");
        Ok(())
    }

    async fn cmd_set_txpower(&self, dbm_str: &str) -> anyhow::Result<()> {
        let dbm: i8 = dbm_str.parse()?;
        let proxy = self.controller_proxy().await?;
        let _: () = proxy.call("SetTxPower", &(dbm,)).await?;
        println!("TX power set to {dbm} dBm");
        Ok(())
    }

    async fn cmd_afh(&self, args: &[&str]) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let sub = args.get(1).copied().unwrap_or("help");
        match sub {
            "get" => {
                let handle: u16 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: afh get <conn_handle>"))?
                    .parse()?;
                let map: Vec<u8> = proxy.call("AfhGetMap", &(handle,)).await?;
                print!("AFH channel map (handle {handle}): ");
                for b in &map {
                    print!("{b:02x}");
                }
                println!();
            }
            "set" => {
                if args.len() < 4 {
                    anyhow::bail!("usage: afh set <conn_handle> <hex_map>");
                }
                let handle: u16 = args[2].parse()?;
                let map = parse_hex_bytes(args[3])?;
                let _: () = proxy.call("AfhSetMap", &(handle, map)).await?;
                println!("AFH channel map updated for handle {handle}");
            }
            "hop" => {
                let handle: u16 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: afh hop <conn_handle>"))?
                    .parse()?;
                let info: (u16, u8, u8) = proxy.call("AfhHopNext", &(handle,)).await?;
                println!("AFH Hop (handle {handle}):");
                println!("  Channel:    {}", info.0);
                println!("  Increment:  {}", info.1);
                println!("  Map Index:  {}", info.2);
            }
            _ => {
                println!("AFH (Adaptive Frequency Hopping):");
                println!("  afh get <handle>          Get channel map");
                println!("  afh set <handle> <hex>    Set channel map");
                println!("  afh hop <handle>          Next hop info");
            }
        }
        Ok(())
    }

    async fn cmd_ral(&self, args: &[&str]) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let sub = args.get(1).copied().unwrap_or("help");
        match sub {
            "size" => {
                let size: u8 = proxy.call("RalSize", &()).await?;
                println!("RAL size: {size} entries");
            }
            "clear" => {
                let _: () = proxy.call("RalClear", &()).await?;
                println!("RAL cleared");
            }
            "add" => {
                if args.len() < 5 {
                    anyhow::bail!("usage: ral add <peer_irk_hex> <local_irk_hex> <peer_id_hex>");
                }
                let peer_irk = parse_hex_bytes(args[2])?;
                let local_irk = parse_hex_bytes(args[3])?;
                let peer_id = parse_hex_bytes(args[4])?;
                let _: () = proxy
                    .call("RalAdd", &(peer_irk, local_irk, peer_id))
                    .await?;
                println!("RAL entry added");
            }
            "remove" => {
                if args.len() < 3 {
                    anyhow::bail!("usage: ral remove <peer_id_hex>");
                }
                let peer_id = parse_hex_bytes(args[2])?;
                let _: () = proxy.call("RalRemove", &(peer_id,)).await?;
                println!("RAL entry removed");
            }
            _ => {
                println!("RAL (Resolving Address List):");
                println!("  ral size                            Show list capacity");
                println!("  ral clear                           Clear all entries");
                println!("  ral add <peer_irk> <local_irk> <id> Add entry");
                println!("  ral remove <peer_id>                Remove entry");
            }
        }
        Ok(())
    }

    async fn cmd_rpa(&self, args: &[&str]) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let sub = args.get(1).copied().unwrap_or("help");
        match sub {
            "on" => {
                let _: () = proxy.call("RpaEnable", &(true,)).await?;
                println!("RPA enabled");
            }
            "off" => {
                let _: () = proxy.call("RpaEnable", &(false,)).await?;
                println!("RPA disabled");
            }
            "timeout" => {
                let secs: u16 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: rpa timeout <seconds>"))?
                    .parse()?;
                let _: () = proxy.call("RpaSetTimeout", &(secs,)).await?;
                println!("RPA timeout set to {secs}s");
            }
            _ => {
                println!("RPA (Resolvable Private Address):");
                println!("  rpa on                Enable RPA");
                println!("  rpa off               Disable RPA");
                println!("  rpa timeout <secs>    Set refresh timeout");
            }
        }
        Ok(())
    }

    async fn cmd_sync(&self, args: &[&str]) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let sub = args.get(1).copied().unwrap_or("help");
        match sub {
            "info" => {
                let handle: u16 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: sync info <handle>"))?
                    .parse()?;
                let info: (u16, u8, u8, u8, u16, u16) = proxy.call("SyncInfo", &(handle,)).await?;
                println!("Sync Link {handle}:");
                println!("  State:          {}", info.1);
                println!("  Direction:      {}", info.2);
                println!("  PHY:            {}", info.3);
                println!("  Interval:       {} slots", info.4);
                println!("  Latency:        {}", info.5);
            }
            "ucast-rm" => {
                let cig_id: u8 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: sync ucast-rm <cig_id>"))?
                    .parse()?;
                let _: () = proxy.call("SyncUcastRemove", &(cig_id,)).await?;
                println!("Unicast CIG {cig_id} removed");
            }
            "mcast-rm" => {
                let big_id: u8 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: sync mcast-rm <big_id>"))?
                    .parse()?;
                let _: () = proxy.call("SyncMcastRemove", &(big_id,)).await?;
                println!("Multicast BIG {big_id} removed");
            }
            _ => {
                println!("Sync Link:");
                println!("  sync info <handle>        Show sync link info");
                println!("  sync ucast-rm <cig_id>    Remove unicast CIG");
                println!("  sync mcast-rm <big_id>    Remove multicast BIG");
            }
        }
        Ok(())
    }

    async fn cmd_meas(&self, args: &[&str]) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let sub = args.get(1).copied().unwrap_or("help");
        match sub {
            "cap" => {
                let cap: (u8, u8, u16) = proxy.call("MeasReadCap", &()).await?;
                println!("Measurement Capability:");
                println!("  Supported:     {}", if cap.0 != 0 { "yes" } else { "no" });
                println!("  Methods:       {}", cap.1);
                println!("  Max Sessions:  {}", cap.2);
            }
            "on" => {
                let _: () = proxy.call("MeasEnable", &(true,)).await?;
                println!("Measurement enabled");
            }
            "off" => {
                let _: () = proxy.call("MeasEnable", &(false,)).await?;
                println!("Measurement disabled");
            }
            _ => {
                println!("Measurement / Ranging:");
                println!("  meas cap      Show measurement capability");
                println!("  meas on       Enable measurement");
                println!("  meas off      Disable measurement");
            }
        }
        Ok(())
    }

    async fn cmd_peer(&self, args: &[&str]) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let sub = args.get(1).copied().unwrap_or("help");
        match sub {
            "features" => {
                let handle: u16 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: peer features <conn_handle>"))?
                    .parse()?;
                let feats: Vec<u8> = proxy.call("ConnReadPeerFeatures", &(handle,)).await?;
                print!("Peer features (handle {handle}): ");
                for b in &feats {
                    print!("{b:02x}");
                }
                println!();
            }
            "version" => {
                let handle: u16 = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: peer version <conn_handle>"))?
                    .parse()?;
                let ver: (u8, u16, u16) = proxy.call("ConnReadPeerVersion", &(handle,)).await?;
                println!("Peer version (handle {handle}):");
                println!("  Version:        {}", ver.0);
                println!("  Company ID:     {:#06x}", ver.1);
                println!("  Sub-version:    {:#06x}", ver.2);
            }
            _ => {
                println!("Peer Capability:");
                println!("  peer features <handle>    Read peer features");
                println!("  peer version <handle>     Read peer version");
            }
        }
        Ok(())
    }

    async fn cmd_set_bandwidth(&self, bw_str: &str) -> anyhow::Result<()> {
        let bw: u8 = bw_str.parse()?;
        let proxy = self.controller_proxy().await?;
        let _: () = proxy.call("SetBandwidth", &(bw,)).await?;
        println!("Bandwidth set to {bw} MHz");
        Ok(())
    }

    async fn cmd_events(&self) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let (index, generation, sequence): (u16, u64, u64) =
            proxy.call("GetControllerEventPosition", &()).await?;
        println!(
            "ControllerEventPosition: index={index} generation={generation} sequence={sequence}"
        );
        println!(
            "Registration-local watermark; independent readers report loss. This is not a delivery acknowledgement."
        );
        Ok(())
    }

    async fn cmd_mgmt(&self) -> anyhow::Result<()> {
        let proxy = self.controller_proxy().await?;
        let stats: (u32, u32, u32, u16) = proxy.call("GetMgmtStats", &()).await?;
        println!("Management Plane:");
        println!("  Commands Sent:     {}", stats.0);
        println!("  Events Received:   {}", stats.1);
        println!("  Timeouts:          {}", stats.2);
        println!("  Queue Depth:       {}", stats.3);
        Ok(())
    }

    async fn cmd_bonded(&self, args: &[&str]) -> anyhow::Result<()> {
        let proxy = self.security_proxy().await?;
        let subcmd = args.get(1).copied().unwrap_or("list");
        match subcmd {
            "list" | "" => {
                let addrs: Vec<String> = proxy.call("ListBonded", &()).await?;
                if addrs.is_empty() {
                    println!("No bonded devices.");
                } else {
                    println!("Bonded devices ({}):", addrs.len());
                    for addr in &addrs {
                        println!("  {addr}");
                    }
                }
            }
            "remove" => {
                let addr = args
                    .get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: bonded remove <AA:BB:CC:DD:EE:FF>"))?;
                proxy.call::<_, _, ()>("RemoveBond", &(*addr,)).await?;
                println!("Bond removed: {addr}");
            }
            _ => anyhow::bail!("usage: bonded [list|remove <addr>]"),
        }
        Ok(())
    }
}

fn parse_handle(s: &str) -> anyhow::Result<u16> {
    let s = s.strip_prefix("0x").unwrap_or(s);
    Ok(u16::from_str_radix(s, 16)?)
}

fn parse_peer_address(text: &str) -> anyhow::Result<String> {
    let bytes = text
        .split(':')
        .map(|part| {
            if part.len() != 2 {
                anyhow::bail!("invalid peer address");
            }
            Ok(u8::from_str_radix(part, 16)?)
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    if bytes.len() != 6 {
        anyhow::bail!("peer address must contain six bytes");
    }
    Ok(bytes
        .iter()
        .map(|b| format!("{b:02X}"))
        .collect::<Vec<_>>()
        .join(":"))
}

/// Linux kernel native events use CLOCK_BOOTTIME (including suspend).
/// Keep this clock separate from Tokio's command deadline and wall logging.
fn boottime_ns() -> anyhow::Result<u64> {
    let mut value = nix::libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: the pointer is a valid writable timespec and no aliases escape.
    if unsafe { nix::libc::clock_gettime(nix::libc::CLOCK_BOOTTIME, &mut value) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let seconds = u64::try_from(value.tv_sec)?;
    let nanos = u64::try_from(value.tv_nsec)?;
    anyhow::ensure!(nanos < 1_000_000_000, "invalid boottime nanoseconds");
    seconds
        .checked_mul(1_000_000_000)
        .and_then(|n| n.checked_add(nanos))
        .ok_or_else(|| anyhow::anyhow!("boottime overflow"))
}

fn random_bytes<const N: usize>() -> anyhow::Result<[u8; N]> {
    use std::io::Read;
    let mut bytes = [0; N];
    std::fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes)
}
fn hex_bytes(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn print_native_result(r: slk_protocol::DiscoveryResultRecord) -> anyhow::Result<()> {
    println!(
        "NativeOperationResult: generation={} request={} operation={} state={} errno={} status=0x{:02x} opcode=0x{:04x} step={}/{} power={} power_valid={} adv={} scan={} profile={}",
        r.0,
        r.1,
        r.2,
        r.3,
        r.4,
        r.5,
        r.6,
        r.7,
        r.8,
        r.9,
        u8::from(r.10),
        r.11,
        r.12,
        r.13
    );
    if r.3 > 3 {
        anyhow::bail!(
            "native operation failed: request={} state={} status=0x{:02x} errno={} (no radio success inferred)",
            r.1,
            r.3,
            r.5,
            r.4
        );
    }
    Ok(())
}

fn parse_hex_bytes(hex: &str) -> anyhow::Result<Vec<u8>> {
    let hex = hex.strip_prefix("0x").unwrap_or(hex);
    if !hex.len().is_multiple_of(2) {
        anyhow::bail!("hex string must have even length");
    }
    if !hex.is_ascii() {
        anyhow::bail!("invalid hex character");
    }
    let mut bytes = Vec::with_capacity(hex.len() / 2);
    for i in (0..hex.len()).step_by(2) {
        bytes.push(u8::from_str_radix(&hex[i..i + 2], 16)?);
    }
    Ok(bytes)
}

type NativeConnectionRecord = (u64, u64, u32, u32, i32, i32, u32, u32, u32, u32);
async fn wait_connection(proxy: &zbus::Proxy<'_>, id: u64) -> anyhow::Result<()> {
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(16);
    loop {
        let r: NativeConnectionRecord = proxy.call("GetConnectionResult", &(id,)).await?;
        if r.3 >= 4 {
            println!(
                "NativeConnectionResult: generation={} request={} operation={} state={} errno={} fault={} command_status={} outcome_status={} handle={} flags={}",
                r.0, r.1, r.2, r.3, r.4, r.5, r.6, r.7, r.8, r.9
            );
            if r.3 == 4 && r.4 == 0 && r.5 == 0 && r.6 == 0 && r.7 == 0 && r.9 & 7 == 7 {
                return Ok(());
            }
            anyhow::bail!("connection procedure did not succeed; original request={id}")
        }
        if tokio::time::Instant::now() >= deadline {
            anyhow::bail!("connection observation timeout; query request={id}")
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hex_input_handles_ascii_and_rejects_unicode_without_panicking() {
        assert_eq!(parse_hex_bytes("0xaA01").unwrap(), [0xAA, 1]);
        assert!(parse_hex_bytes("aéa").is_err());
        assert!(parse_hex_bytes("GG").is_err());
        assert!(parse_hex_bytes("a").is_err());
    }
}
