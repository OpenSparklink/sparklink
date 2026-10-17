type LocalProperty = (u16, Vec<u8>, u32, u32);
type LocalService = (u16, u16, Vec<u8>, Vec<LocalProperty>);
type UuidValues = (Vec<(u16, bool, u16, Vec<u8>)>, Vec<u8>, Vec<u8>);
use zbus::Connection;

type NativeReportRecord = (u64, u64, u64, String, i16, Vec<u8>, Vec<u8>, u64);
type NativeLinksRecord = (u64, u64, u64, u32, i32, Vec<(u64, u16, u8, u8, String)>);
type NativeObjectsRecord = (u64, u64, u64, bool, Vec<(String, u64, u16, u8, u8, String)>);
use slk_contract::ConnectionInfo as NativeObjectInfo;
use slk_contract::PeerInfo as NativePeerInfo;

pub struct Context {
    conn: Connection,
    selected: Option<String>,
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
            "agent" if args.len() <= 2 => {
                let controller = self.selected_path().await?;
                crate::security_agent::run_agent(
                    &self.conn,
                    &controller,
                    args.get(1)
                        .copied()
                        .unwrap_or(crate::security_agent::METHOD),
                )
                .await
            }
            "security-request" if (2..=4).contains(&args.len()) => {
                let controller = self.selected_path().await?;
                let timeout_ms = args.get(2).map(|v| v.parse()).transpose()?.unwrap_or(5000);
                crate::security_agent::request(
                    &self.conn,
                    &controller,
                    args[1],
                    timeout_ms,
                    args.get(3)
                        .copied()
                        .unwrap_or(crate::security_agent::METHOD),
                )
                .await
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
                let object = self.connection_proxy(args[1]).await?;
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
            "ssap-list" if args.len() == 1 => {
                let path = format!("{}/services", self.selected_path().await?);
                let object = zbus::Proxy::new(
                    &self.conn,
                    "org.sparklink",
                    path,
                    "org.sparklink.ServiceManager",
                )
                .await?;
                let services: Vec<LocalService> = object.call("ListLocalServices", &()).await?;
                println!("SsapLocalServices: {}", serde_json::to_string(&services)?);
                Ok(())
            }
            "ssap-serve" if matches!(args.len(), 6 | 7) => {
                crate::ssap_server::serve(
                    &self.conn,
                    &self.selected_path().await?,
                    parse_hex_bytes(args[1])?,
                    (
                        parse_hex_bytes(args[2])?,
                        args[3].parse()?,
                        args[4].parse()?,
                        parse_hex_bytes(args[5])?,
                    ),
                    args.get(6).copied().unwrap_or("ask"),
                )
                .await
            }
            "ssap-register" if args.len() == 6 => {
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
                let access: u32 = args[4].parse()?;
                let value = parse_hex_bytes(args[5])?;
                let registered: (u16, u16, Vec<u16>) = object
                    .call(
                        "RegisterLocalService",
                        &(service, vec![(property, ops, access, value)]),
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
                let object = self.connection_proxy(args[1]).await?;
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
                if !(5..=6).contains(&args.len()) {
                    anyhow::bail!("ssap-read-uuid CONNECTION START END UUID_HEX [MINIMUM]");
                }
                let object = self.connection_proxy(args[1]).await?;
                let start: u16 = args[2].parse()?;
                let end: u16 = args[3].parse()?;
                let (entries, request, response): UuidValues = object
                    .call(
                        "ReadSsapByUuid",
                        &(
                            start,
                            end,
                            0u8,
                            parse_hex_bytes(args[4])?,
                            args.get(5).map_or(Ok(0u32), |v| v.parse())?,
                        ),
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
                if (args[0] == "ssap-read" && !(3..=4).contains(&args.len()))
                    || (args[0] == "ssap-write" && !(4..=5).contains(&args.len()))
                {
                    anyhow::bail!(
                        "SSAP value requires connection path, handle and write hex value"
                    );
                }
                let object = self.connection_proxy(args[1]).await?;
                let handle: u16 = args[2].parse()?;
                let value: Vec<u8> = if args[0] == "ssap-read" {
                    object
                        .call(
                            "ReadSsapValue",
                            &(handle, args.get(3).map_or(Ok(0u32), |v| v.parse())?),
                        )
                        .await?
                } else {
                    object
                        .call(
                            "WriteSsapValue",
                            &(
                                handle,
                                parse_hex_bytes(args[3])?,
                                args.get(4).map_or(Ok(0u32), |v| v.parse())?,
                            ),
                        )
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
            "transport-status" => {
                if args.len() != 2 {
                    anyhow::bail!("transport-status requires one immutable connection path");
                }
                self.cmd_transport_status(args[1]).await
            }
            "ssap-info" => {
                if args.len() != 2 {
                    anyhow::bail!("ssap-info requires one immutable connection path");
                }
                self.cmd_ssap_info(args[1]).await
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
            "stats" => self.cmd_stats().await,
            "events" => self.cmd_events().await,
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
        let scanning: u32 = proxy.get_property("ScanningState").await?;

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
        println!("  ScanningState: {scanning}");
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
                let expected = slk_protocol::ws73_marker_data(&marker);
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
            anyhow::bail!("standard Native connection control is not connected");
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
            anyhow::bail!("standard Native connection control is not connected");
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
    async fn connection_proxy(&self, path: &str) -> anyhow::Result<zbus::Proxy<'_>> {
        let selected = self.selected_path().await?;
        if !path.starts_with(&format!("{selected}/peer_t")) {
            anyhow::bail!("connection belongs to another adapter");
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
            anyhow::bail!("connection lifetime unknown/retired");
        }
        Ok(object)
    }
    async fn cmd_transport_status(&self, path: &str) -> anyhow::Result<()> {
        let object = self.connection_proxy(path).await?;
        let identity: NativeObjectInfo = object.call("GetInfo", &()).await?;
        type View = (
            u16,
            u64,
            u64,
            u16,
            u16,
            u16,
            u16,
            u16,
            u16,
            u16,
            u16,
            u16,
            u16,
            u16,
            u32,
        );
        let v: View = object.call("GetTransportStatus", &()).await?;
        if (v.1, v.2, v.3) != (identity.0, identity.1, identity.2) {
            anyhow::bail!("transport observation lifetime mismatch");
        }
        println!(
            "SessionTxStatus: index={} generation={} lifetime={} handle={} capacity={} outstanding={} debt={} queued={} active={} open={} pending={} retired={} failed={} allocated={} flags={}",
            v.0, v.1, v.2, v.3, v.4, v.5, v.6, v.7, v.8, v.9, v.10, v.11, v.12, v.13, v.14
        );
        Ok(())
    }
    async fn cmd_ssap_info(&self, path: &str) -> anyhow::Result<()> {
        let object = self.connection_proxy(path).await?;
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
pub(crate) fn hex_bytes(bytes: &[u8]) -> String {
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
