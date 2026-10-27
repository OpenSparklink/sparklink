use slk_contract::ssap::local::ServiceRecord as LocalService;
use zbus::Connection;

use slk_contract::ConnectionInfo as NativeObjectInfo;
use slk_contract::ConnectionObjects as NativeObjectsRecord;
use slk_contract::PeerInfo as NativePeerInfo;
use slk_contract::controller::Links as NativeLinksRecord;

pub struct Context {
    conn: Connection,
    client: tokio::sync::OnceCell<libsparklink::Client>,
    selected: Option<String>,
}

impl Context {
    pub fn new(conn: Connection) -> Self {
        Self {
            conn,
            client: tokio::sync::OnceCell::new(),
            selected: None,
        }
    }

    pub async fn dispatch(&mut self, args: &[&str]) -> anyhow::Result<()> {
        match args[0] {
            "agent" if args.len() <= 2 => {
                let controller = self.selected_path().await?;
                crate::security_agent::run_agent(
                    &self.conn,
                    self.application().await?,
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
                    self.application().await?,
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
                        "ssap-discover requires path [structure|service|property|method uuid-hex]"
                    );
                }
                let kind = if args.len() == 2 {
                    1u8
                } else {
                    match args[2] {
                        "structure" => 0,
                        "service" => 1,
                        "property" => 3,
                        "method" => 4,
                        _ => anyhow::bail!("unknown discovery kind"),
                    }
                };
                let uuid = if args.len() == 4 {
                    parse_hex_bytes(args[3])?
                } else {
                    Vec::new()
                };
                let link = self.application_connection(args[1]).await?;
                let object = link.ssap();
                let (entries, trace) = object.discover(uuid, kind).await?;
                for (category, handle, end, uuid, operations, descriptors, members) in &entries {
                    println!(
                        "SsapRemoteEntry: category={category} handle={handle} end={end} uuid={} operations={operations} descriptors={} members={members}",
                        hex_bytes(uuid),
                        hex_bytes(descriptors)
                    );
                }
                if args.len() == 2 {
                    let cached = object.cached().await?;
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
                let services = self.controller().await?.management().local_services();
                let services: Vec<LocalService> = services.list().await?;
                println!("SsapLocalServices: {}", serde_json::to_string(&services)?);
                Ok(())
            }
            "ssap-serve" if matches!(args.len(), 6 | 7) => {
                crate::ssap_server::serve(
                    &self.conn,
                    self.application().await?,
                    &self.selected_path().await?,
                    parse_hex_bytes(args[1])?,
                    crate::ssap_server::Definition::Property((
                        parse_hex_bytes(args[2])?,
                        args[3].parse()?,
                        args[4].parse()?,
                        parse_hex_bytes(args[5])?,
                    )),
                    args.get(6).copied().unwrap_or("ask"),
                )
                .await
            }
            "ssap-serve-method" if matches!(args.len(), 4 | 5) => {
                crate::ssap_server::serve(
                    &self.conn,
                    self.application().await?,
                    &self.selected_path().await?,
                    parse_hex_bytes(args[1])?,
                    crate::ssap_server::Definition::Method(
                        parse_hex_bytes(args[2])?,
                        args[3].parse()?,
                    ),
                    args.get(4).copied().unwrap_or("ask"),
                )
                .await
            }
            "ssap-register" if args.len() == 6 => {
                let services = self.controller().await?.management().local_services();
                let service = parse_hex_bytes(args[1])?;
                let property = parse_hex_bytes(args[2])?;
                let ops: u32 = args[3].parse()?;
                let access: u32 = args[4].parse()?;
                let value = parse_hex_bytes(args[5])?;
                let registered = services
                    .register(service, vec![(property, ops, access, value)])
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
                let services = self.controller().await?.management().local_services();
                let handle: u16 = args[1].parse()?;
                let _: () = services.remove(handle).await?;
                println!("SsapLocalRemoved: start={handle}");
                Ok(())
            }
            "ssap-local-read" if args.len() == 2 => {
                let services = self.controller().await?.management().local_services();
                let handle: u16 = args[1].parse()?;
                let value: Vec<u8> = services.read_local(handle).await?;
                println!(
                    "SsapLocalValue: handle={handle} value={}",
                    hex_bytes(&value)
                );
                Ok(())
            }
            "ssap-receive" => {
                if !(3..=5).contains(&args.len()) {
                    anyhow::bail!(
                        "ssap-receive CONNECTION HANDLE [notify|indicate|both] [WAIT_MS]"
                    );
                }
                let link = self.application_connection(args[1]).await?;
                let object = link.ssap();
                let handle: u16 = args[2].parse()?;
                let modes = crate::ssap_subscription::mode(args.get(3).copied().unwrap_or("both"))?;
                let wait: u32 = args.get(4).copied().unwrap_or("5000").parse()?;
                let (indication, raw) = object.receive_update(vec![handle], modes, wait).await?;
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
            "ssap-subscribe" if args.len() >= 3 => {
                let link = self.application_connection(args[1]).await?;
                crate::ssap_subscription::run(&link, &args[2..]).await
            }
            "ssap-read-uuid" => {
                if !(5..=6).contains(&args.len()) {
                    anyhow::bail!("ssap-read-uuid CONNECTION START END UUID_HEX [MINIMUM]");
                }
                let link = self.application_connection(args[1]).await?;
                let object = link.ssap();
                let start: u16 = args[2].parse()?;
                let end: u16 = args[3].parse()?;
                let (entries, request, response) = object
                    .read_by_uuid(
                        start,
                        end,
                        0,
                        parse_hex_bytes(args[4])?,
                        args.get(5).map_or(Ok(0u32), |v| v.parse())?,
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
            "ssap-read"
            | "ssap-read-description"
            | "ssap-write"
            | "ssap-write-command"
            | "ssap-call-method"
            | "ssap-call-method-command" => {
                let original = libsparklink::Deadline::after(std::time::Duration::from_secs(5))?;
                let reading = matches!(args[0], "ssap-read" | "ssap-read-description");
                if (reading && !(3..=4).contains(&args.len()))
                    || (!reading && !(4..=5).contains(&args.len()))
                {
                    anyhow::bail!(
                        "SSAP value requires connection path, handle and write hex value"
                    );
                }
                let link = self.application_connection(args[1]).await?;
                let object = link.ssap();
                let handle: u16 = args[2].parse()?;
                if matches!(args[0], "ssap-write-command" | "ssap-call-method-command") {
                    if args[0] == "ssap-call-method-command" {
                        object
                            .call_method_without_response(
                                handle,
                                parse_hex_bytes(args[3])?,
                                args.get(4).map_or(Ok(0u32), |v| v.parse())?,
                                original,
                            )
                            .await?;
                    } else {
                        object
                            .write_without_response(
                                handle,
                                parse_hex_bytes(args[3])?,
                                args.get(4).map_or(Ok(0u32), |v| v.parse())?,
                                original,
                            )
                            .await?;
                    }
                    println!(
                        "SsapCommandAdmission: path={} handle={} stage=software_socket_admission peer_delivery=unconfirmed",
                        args[1], handle
                    );
                    return Ok(());
                }
                let value = if args[0] == "ssap-call-method" {
                    object
                        .call_method(
                            handle,
                            parse_hex_bytes(args[3])?,
                            args.get(4).map_or(Ok(0u32), |v| v.parse())?,
                            original,
                        )
                        .await?
                } else if args[0] == "ssap-read-description" {
                    object
                        .read_description(
                            handle,
                            args.get(3).map_or(Ok(0u32), |v| v.parse())?,
                            original,
                        )
                        .await?
                } else if args[0] == "ssap-read" {
                    object
                        .read(
                            handle,
                            args.get(3).map_or(Ok(0u32), |v| v.parse())?,
                            original,
                        )
                        .await?
                } else {
                    object
                        .write(
                            handle,
                            parse_hex_bytes(args[3])?,
                            args.get(4).map_or(Ok(0u32), |v| v.parse())?,
                            original,
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

            "discover" if args.len() <= 5 => {
                let prefix = match args.get(1).copied().unwrap_or("-") {
                    "-" => Vec::new(),
                    value => parse_hex_bytes(value)?,
                };
                let count: usize = args.get(2).map(|s| s.parse()).transpose()?.unwrap_or(1);
                let duration: u32 = args
                    .get(3)
                    .map(|s| s.parse())
                    .transpose()?
                    .unwrap_or(10_000);
                let rssi: i16 = args.get(4).map(|s| s.parse()).transpose()?.unwrap_or(-128);
                if !(1..=1024).contains(&count)
                    || duration > 30_000
                    || !slk_contract::discovery::valid_filter(&prefix, rssi, duration)
                {
                    anyhow::bail!(
                        "discover [raw-prefix-hex|-] [count1..1024] [duration250..30000ms] [minimumRSSI -128..20]"
                    );
                }
                let path = self.selected_path().await?;
                let controller = slk_contract::ControllerId::from_path(&path)
                    .ok_or_else(|| anyhow::anyhow!("immutable controller path required"))?;
                let client = self.application().await?;
                let mut session = client
                    .discover(
                        controller,
                        prefix,
                        rssi,
                        duration,
                        libsparklink::Deadline::after(std::time::Duration::from_secs(5))?,
                    )
                    .await?;
                println!(
                    "DiscoverySession: id={} path={} state=active source=broker",
                    session.id(),
                    path
                );
                let original = libsparklink::Deadline::after(std::time::Duration::from_millis(
                    duration.into(),
                ))?;
                let outcome = async {
                    let mut received = 0;
                    while received < count {
                        let batch = match session.read(true, original).await {
                            Ok(batch) => batch,
                            Err(libsparklink::ApplicationError::Bus(zbus::Error::MethodError(name, _, _)))
                                if name.as_str() == "org.freedesktop.DBus.Error.Timeout" && original.remaining().is_ok() => continue,
                            Err(error) => return Err(error.into()),
                        };
                        if batch.dropped != 0 || batch.kernel_lost != 0 {
                            anyhow::bail!("discovery observation gap: dropped={} kernel_lost={}",batch.dropped,batch.kernel_lost);
                        }
                        for report in batch.reports.into_iter().take(count-received) {
                            println!("DiscoveryReport: session={} generation={} sequence={} address_type={} address={} rssi={} data={}",
                                session.id(),controller.generation,report.sequence,report.address_type,hex_bytes(&report.address),
                                if report.rssi_known {report.rssi.to_string()} else {"unknown".into()},hex_bytes(&report.data));
                            received += 1;
                        }
                    }
                    Ok::<_,anyhow::Error>(())
                }.await;
                let cleanup = session
                    .close(libsparklink::Deadline::after(
                        std::time::Duration::from_secs(5),
                    )?)
                    .await;
                match (outcome, cleanup) {
                    (Err(first), Err(cleanup)) => {
                        Err(first.context(format!("discovery close also unconfirmed: {cleanup}")))
                    }
                    (Err(first), Ok(_)) => Err(first),
                    (Ok(()), Err(cleanup)) => Err(cleanup.into()),
                    (Ok(()), Ok(stopped)) => {
                        println!(
                            "DiscoveryReleased: session={} last_physical_stop_confirmed={stopped}",
                            session.id()
                        );
                        Ok(())
                    }
                }
            }
            "controller-events" if args.len() <= 3 => {
                let count: usize = args.get(1).map(|s| s.parse()).transpose()?.unwrap_or(1);
                let timeout: u64 = args.get(2).map(|s| s.parse()).transpose()?.unwrap_or(5000);
                if !(1..=512).contains(&count) || !(1..=30000).contains(&timeout) {
                    anyhow::bail!("controller-events count1..512, per-next timeout1..30000ms");
                }
                let client = self.application().await?;
                let budget =
                    || libsparklink::Deadline::after(std::time::Duration::from_millis(timeout));
                let mut events = client.controller_events(budget()?).await?;
                for _ in 0..count {
                    use libsparklink::controller_events::ControllerEvent;
                    match events.next(budget()?).await? {
                        ControllerEvent::Snapshot {
                            before,
                            controllers,
                        } => println!(
                            "ControllerDirectorySnapshot: cursor={before} controllers={}",
                            controllers
                                .into_iter()
                                .map(|id| id.path())
                                .collect::<Vec<_>>()
                                .join("|")
                        ),
                        ControllerEvent::Published {
                            sequence,
                            controller,
                        } => println!(
                            "ControllerDirectoryEvent: sequence={sequence} action=published path={}",
                            controller.path()
                        ),
                        ControllerEvent::Withdrawn {
                            sequence,
                            controller,
                        } => println!(
                            "ControllerDirectoryEvent: sequence={sequence} action=withdrawn path={}",
                            controller.path()
                        ),
                        ControllerEvent::Gap {
                            after,
                            oldest,
                            current,
                        } => anyhow::bail!(
                            "ControllerDirectoryGap: after={after} oldest={oldest} current={current}; resnapshot required"
                        ),
                    }
                    use std::io::Write;
                    std::io::stdout().flush()?;
                }
                Ok(())
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
            "peers" if args.len() == 1 => self.cmd_peers().await,
            "peer-observation" => {
                if args.len() != 2 {
                    anyhow::bail!("usage: peer-observation <typed-peer-path>");
                }
                self.cmd_peer_observation(args[1]).await
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
                let proxy = self.controller().await?;
                let r: NativeConnectionRecord = proxy.management().connection_result(id).await?;
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
            "link-payload-preference" => {
                if !(3..=4).contains(&args.len()) {
                    anyhow::bail!(
                        "usage: link-payload-preference <connection-path> <octets> [timeout-ms]"
                    );
                }
                let requested_octets = args[2].parse::<u16>()?;
                let timeout_ms = args.get(3).map(|v| v.parse()).transpose()?.unwrap_or(5000);
                if requested_octets == 0 || !(1..=5000).contains(&timeout_ms) {
                    anyhow::bail!("nonzero16bit payload preference and1..5000ms required");
                }
                let value = self
                    .controller()
                    .await?
                    .management()
                    .set_link_payload_preference(args[1], requested_octets, timeout_ms)
                    .await?;
                println!(
                    "NativeLinkPayloadAcknowledgment: {}",
                    serde_json::to_string(&value)?
                );
                if value.state != 2 || value.flags != 5 {
                    anyhow::bail!("no successful current controller acknowledgment");
                }
                Ok(())
            }
            "link-measurement" => {
                if !(3..=4).contains(&args.len()) {
                    anyhow::bail!(
                        "usage: link-measurement <connection-path> <rssi|phy> [timeout-ms]"
                    );
                }
                let kind = match args[2] {
                    "rssi" => 1,
                    "phy" => 2,
                    _ => anyhow::bail!("kind must be rssi or phy"),
                };
                let timeout_ms = args.get(3).map(|v| v.parse()).transpose()?.unwrap_or(5000);
                let value = self
                    .controller()
                    .await?
                    .management()
                    .read_link_measurement(args[1], kind, timeout_ms)
                    .await?;
                println!("NativeLinkMeasurement: {}", serde_json::to_string(&value)?);
                if value.state != 2 || value.flags & 7 != 7 {
                    anyhow::bail!("no successful current valid measurement");
                }
                Ok(())
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
                let proxy = self.controller().await?;
                let id: u64 = proxy.management().allocate_connection_request().await?;
                println!(
                    "NativeDisconnectReference: request={id} address={address} type={kind} handle={handle} lifetime={lifetime} role={role}"
                );
                let _: () = proxy
                    .management()
                    .disconnect_reference(id, &address, kind, handle, lifetime, role)
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
        let paths = self.controller_paths().await?;
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
        let paths = self.controller_paths().await?;
        let candidate = if path.starts_with('/') {
            path.to_owned()
        } else {
            format!("{}/{path}", slk_contract::MANAGER_PATH)
        };
        if !paths.contains(&candidate) {
            anyhow::bail!("adapter is not a live registration: {candidate}");
        }
        self.selected = Some(candidate.clone());
        println!("Selected {candidate}");
        Ok(())
    }
    async fn cmd_daemon(&self) -> anyhow::Result<()> {
        let (owner, pid, uid) = self.application().await?.daemon_identity().await?;
        println!("DaemonIdentity: owner={owner} pid={pid} uid={uid}");
        Ok(())
    }

    async fn cmd_reports(&self) -> anyhow::Result<()> {
        let proxy = self.controller().await?;
        let reports = proxy.reports().await?;
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

    async fn application(&self) -> anyhow::Result<&libsparklink::Client> {
        Ok(self
            .client
            .get_or_try_init(|| libsparklink::Client::from_connection(self.conn.clone()))
            .await?)
    }
    async fn controller(&self) -> anyhow::Result<libsparklink::controller::Controller> {
        Ok(self
            .application()
            .await?
            .controller(&self.selected_path().await?)
            .await?)
    }
    async fn controller_paths(&self) -> anyhow::Result<Vec<String>> {
        Ok(self
            .application()
            .await?
            .controllers()
            .await?
            .into_iter()
            .map(|id| id.path())
            .collect())
    }
    async fn cmd_list(&self) -> anyhow::Result<()> {
        let adapters = self.controller_paths().await?;
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
        let paths = self.application().await?.registrations().await?;
        for path in paths {
            self.cmd_registration(&path).await?;
        }
        Ok(())
    }
    async fn cmd_registration(&self, path: &str) -> anyhow::Result<()> {
        let path = if path.starts_with('/') {
            path.to_owned()
        } else {
            format!("{}/{path}", slk_contract::MANAGER_PATH)
        };
        let snapshot = self.application().await?.registration(&path).await?;
        let slk_protocol::SleRegistrationSnapshot {
            generation,
            version: _,
            state,
            profile,
            phase,
            error,
            dev_index: index,
            bus,
            ..
        } = snapshot;
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
        let proxy = self.controller().await?;
        let name: String = proxy.name().await?;
        let scanning: u32 = proxy.scanning_state().await?;

        let status: String = proxy.state().await?;
        let generation: u64 = proxy.generation().await?;
        let address: String = proxy.address().await?;
        let profile: u32 = proxy.profile().await?;
        let error: String = proxy.initialization_error().await?;
        println!("Adapter {}:", self.selected_path().await?);
        println!("  State:       {status}");
        println!("  Generation:  {generation}");
        println!("  Address:     {address}");
        println!("  Profile:     {profile}");
        if profile == 1 {
            let (seq, revision, known): (u64, u64, bool) = proxy.link_observation().await?;
            let lost: u64 = proxy.events_lost().await?;
            println!(
                "  Native links: event_seq={seq} revision={revision} known={known} lost={lost}"
            );
            let (version, min, max, power, interval, window): (u32, u32, u32, i32, u32, u32) =
                proxy.discovery_policy().await?;
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
        let proxy = self.controller().await?;
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
                        proxy.management().advertise(id, marker.to_vec()),
                    )
                    .await??
                } else {
                    tokio::time::timeout(
                        std::time::Duration::from_secs(7),
                        proxy.management().advertise_connectable(
                            id,
                            marker.to_vec(),
                            args[1] == "negotiable",
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
                    proxy.management().stop_advertising(id),
                )
                .await??;
            }
            _ => anyhow::bail!("usage: advertise on|connectable|negotiable [32-hex-marker]|off"),
        }
        self.wait_native_result(&proxy, id).await
    }
    async fn cmd_result(&self, id: &str) -> anyhow::Result<()> {
        let id: u64 = id.parse()?;
        let proxy = self.controller().await?;
        let result: slk_protocol::DiscoveryResultRecord =
            proxy.management().discovery_result(id).await?;
        print_native_result(result)?;
        Ok(())
    }
    async fn cmd_initialization_off(&self, operation: u32) -> anyhow::Result<()> {
        let proxy = self.controller().await?;
        let result: slk_protocol::DiscoveryResultRecord = tokio::time::timeout(
            std::time::Duration::from_secs(3),
            proxy.management().initialization_off(operation),
        )
        .await??;
        print_native_result(result)
    }
    async fn wait_native_result(
        &self,
        proxy: &libsparklink::controller::Controller,
        id: u64,
    ) -> anyhow::Result<()> {
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(7);
        let generation: u64 = tokio::time::timeout_at(deadline, proxy.generation()).await??;
        loop {
            let result: slk_protocol::DiscoveryResultRecord =
                tokio::time::timeout_at(deadline, proxy.management().discovery_result(id))
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
        let proxy = self.controller().await?;
        let generation: u64 = proxy.generation().await?;
        println!("NativePoliciesCancelRequest: generation={generation}");
        let confirmed: u64 = tokio::time::timeout(
            std::time::Duration::from_secs(8),
            proxy.management().cancel_discovery(),
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
        let proxy = self.controller().await?;
        let expected: u64 = proxy.generation().await?;
        let (generation, mode, state, flags, error, status, opcode): (
            u64,
            u32,
            u32,
            u32,
            i32,
            u32,
            u32,
        ) = tokio::time::timeout(std::time::Duration::from_secs(3), proxy.management_status())
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
        let toggle = args
            .get(1)
            .copied()
            .ok_or_else(|| anyhow::anyhow!("usage: scan on|off"))?;
        let proxy = self.controller().await?;
        if proxy.profile().await? == 1 {
            let id = u64::from_ne_bytes(random_bytes::<8>()?).max(1);
            let enable = match toggle {
                "on" => true,
                "off" => false,
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
            let generation: u64 = proxy.generation().await?;
            let before: Vec<slk_protocol::TimedDiscoveryReportRecord> =
                proxy.timed_reports().await?;
            let watermark = before.iter().map(|r| r.0).max().unwrap_or(0);
            // The invocation lower bound rejects queued older kernel RX;
            // the discovery deadline separately starts at matched Complete.
            let scan_boottime_ns = boottime_ns()?;
            println!(
                "NativeScanWindow: generation={generation} request={id} start_boottime_ns={scan_boottime_ns}"
            );
            println!("NativeScanRequest: request={id} enable={toggle}");
            let _: () = tokio::time::timeout(std::time::Duration::from_secs(7), async {
                if enable {
                    proxy.management().scan(id).await
                } else {
                    proxy.management().stop_scanning(id).await
                }
            })
            .await??;
            self.wait_native_result(&proxy, id).await?;
            if let Some((marker, address)) = matching {
                let expected = slk_protocol::ws73_marker_data(&marker);
                let timing: (u64, u64, u64, u32, u32, u16, u8) = tokio::time::timeout(
                    std::time::Duration::from_secs(7),
                    proxy.management().discovery_timing(id),
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
                        proxy.timed_reports(),
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
                let _: () = proxy.management().start_controller_scan().await?;
                println!("Discovery started");
            }
            "off" => {
                let _: () = proxy.management().stop_controller_scan().await?;
                println!("Discovery stopped");
            }
            _ => anyhow::bail!("usage: scan on|off"),
        }
        Ok(())
    }

    async fn cmd_peers(&self) -> anyhow::Result<()> {
        let peers = self.controller().await?.peers().await?;
        if peers.is_empty() {
            println!("No peers observed");
        }
        for peer in peers {
            let info = peer.info().await?;
            let observation = peer.observation().await?;
            println!(
                "Peer: path={} address={} address_type={} observation_valid={} rssi={} connection={}",
                peer.path(),
                info.2,
                info.1,
                observation.valid,
                observation
                    .rssi
                    .map(|v| v.to_string())
                    .unwrap_or_else(|| "unknown".into()),
                if !info.3 {
                    "unknown"
                } else if info.4 {
                    "connected"
                } else {
                    "disconnected"
                }
            );
        }
        Ok(())
    }
    async fn cmd_peer_observation(&self, path: &str) -> anyhow::Result<()> {
        let controller = self.controller().await?;
        let id = slk_contract::PeerId::from_path(path)
            .ok_or_else(|| anyhow::anyhow!("typed Peer path required"))?;
        if id.controller != controller.id() {
            anyhow::bail!("foreign controller Peer");
        }
        let peer = self.application().await?.peer(path).await?;
        let o = peer.observation().await?;
        println!(
            "PeerObservation: path={} generation={} address_type={} valid={} rssi={} sequence={} kernel_boottime_ns={} lost={} header={} data={}",
            peer.path(),
            o.id.controller.generation,
            o.id.address_type,
            o.valid,
            o.rssi
                .map(|v| v.to_string())
                .unwrap_or_else(|| "unknown".into()),
            o.sequence,
            o.kernel_boottime_ns,
            o.lost,
            hex_bytes(&o.header),
            hex_bytes(&o.data)
        );
        Ok(())
    }

    async fn cmd_connect(&self, address: &str, address_type: Option<&str>) -> anyhow::Result<()> {
        let proxy = self.controller().await?;
        let profile: u32 = proxy.profile().await?;
        if profile == 1 {
            let address_type: u8 = address_type
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "usage: connect <address> <address-type>; type is explicit, not inferred"
                    )
                })?
                .parse()?;
            let id: u64 = proxy.management().allocate_connection_request().await?;
            println!(
                "NativeConnectionRequest: request={id} address={address} address_type={address_type}"
            );
            let _: () = proxy
                .management()
                .connect(id, address, address_type)
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
        let proxy = self.controller().await?;
        let profile: u32 = proxy.profile().await?;
        if profile == 1 {
            let id: u64 = proxy.management().allocate_connection_request().await?;
            println!("NativeDisconnectRequest: request={id} address={address}");
            if let Some(kind) = address_type {
                let kind: u8 = kind.parse()?;
                let _: () = proxy
                    .management()
                    .disconnect_typed(id, address, kind)
                    .await?;
            } else {
                let _: () = proxy.management().disconnect(id, address).await?;
            }
            wait_connection(&proxy, id).await?;
        } else {
            anyhow::bail!("standard Native connection control is not connected");
        }
        println!("Disconnect procedure completed for {address}");
        Ok(())
    }
    async fn cmd_connections(&self) -> anyhow::Result<()> {
        let proxy = self.controller().await?;
        let (generation, seq, revision, flags, error, links): NativeLinksRecord =
            proxy.links().await?;
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
        let proxy = self.controller().await?;
        let (generation, seq, revision, known, objects): NativeObjectsRecord =
            proxy.connection_objects().await?;
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
        let (generation, kind, address, known, connected, objects): NativePeerInfo = self
            .application()
            .await?
            .peer_info(&self.selected_path().await?, path)
            .await?;
        println!(
            "NativePeerInfo: generation={generation} type={kind} address={address} known={known} connected={connected} path={path}"
        );
        for object in objects {
            println!("NativePeerConnection: path={object}");
        }
        Ok(())
    }
    async fn application_connection(
        &self,
        path: &str,
    ) -> anyhow::Result<libsparklink::ApplicationConnection> {
        Ok(self
            .application()
            .await?
            .connection(&self.selected_path().await?, path)
            .await?)
    }

    async fn cmd_transport_status(&self, path: &str) -> anyhow::Result<()> {
        let v = self
            .application_connection(path)
            .await?
            .transport_status()
            .await?;
        println!(
            "SessionTxStatus: index={} generation={} lifetime={} handle={} capacity={} outstanding={} debt={} queued={} active={} open={} pending={} retired={} failed={} allocated={} flags={}",
            v.0, v.1, v.2, v.3, v.4, v.5, v.6, v.7, v.8, v.9, v.10, v.11, v.12, v.13, v.14
        );
        Ok(())
    }
    async fn cmd_ssap_info(&self, path: &str) -> anyhow::Result<()> {
        let link = self.application_connection(path).await?;
        let info = link.ssap().exchange_info().await?;
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
        let adapter = self.controller().await?;
        let (generation, lifetime, handle, role, kind, address, known, connected): NativeObjectInfo = self.application_connection(path).await?.info().await?;
        if disconnect {
            let id: u64 = adapter.management().allocate_connection_request().await?;
            println!(
                "NativeDisconnectObject: request={id} generation={generation} lifetime={lifetime} handle={handle} role={role} type={kind} address={address} path={path}"
            );
            let _: () = adapter.management().disconnect_object(id, path).await?;
            wait_connection(&adapter, id).await
        } else {
            println!(
                "NativeConnectionInfo: generation={generation} lifetime={lifetime} handle={handle} role={role} type={kind} address={address} known={known} connected={connected} path={path}"
            );
            Ok(())
        }
    }

    async fn cmd_stats(&self) -> anyhow::Result<()> {
        let proxy = self.controller().await?;
        let stats: (u16, u64, u64, u64, u32) = proxy.link_summary().await?;
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
        let proxy = self.controller().await?;
        let (index, generation, sequence): (u16, u64, u64) = proxy.event_position().await?;
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
    let bytes = slk_contract::parse_address(text)
        .ok_or_else(|| anyhow::anyhow!("peer address requires six two-digit hex octets"))?;
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

pub(crate) fn parse_hex_bytes(hex: &str) -> anyhow::Result<Vec<u8>> {
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

use slk_contract::controller::ConnectionResult as NativeConnectionRecord;
async fn wait_connection(
    proxy: &libsparklink::controller::Controller,
    id: u64,
) -> anyhow::Result<()> {
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(16);
    loop {
        let r: NativeConnectionRecord =
            tokio::time::timeout_at(deadline, proxy.management().connection_result(id)).await??;
        if tokio::time::Instant::now() >= deadline {
            anyhow::bail!("connection observation timeout; query request={id}");
        }
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
