use zbus::Connection;

type NativeReportRecord = (u64, u64, u64, String, i16, Vec<u8>, Vec<u8>, u64);

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
            "list" => self.cmd_list().await,
            "select" => self.cmd_select(args.get(1).copied().unwrap_or("")).await,
            "reports" => self.cmd_reports().await,
            "show" => self.cmd_show().await,
            "scan" => {
                if args.len() < 2 {
                    anyhow::bail!("usage: scan on|off");
                }
                self.cmd_scan(args[1]).await
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
                    anyhow::bail!("usage: connect <address>");
                }
                self.cmd_connect(args[1]).await
            }
            "disconnect" => {
                let addr = args.get(1).copied().unwrap_or("");
                self.cmd_disconnect(addr).await
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
        if !error.is_empty() {
            println!("  Init error:  {error}");
        }
        println!("  Name:        {name}");
        println!("  Powered:     {powered}");
        println!("  Discovering: {discovering}");
        Ok(())
    }

    async fn cmd_scan(&self, toggle: &str) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        match toggle {
            "on" => {
                let _: () = proxy.call("StartDiscovery", &()).await?;
                println!("Discovery started");
            }
            "off" => {
                let _: () = proxy.call("StopDiscovery", &()).await?;
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

    async fn cmd_connect(&self, address: &str) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let _: () = proxy.call("ConnectDevice", &(address,)).await?;
        println!("Connected to {address}");
        Ok(())
    }

    async fn cmd_disconnect(&self, address: &str) -> anyhow::Result<()> {
        let proxy = self.adapter_proxy().await?;
        let _: () = proxy.call("DisconnectDevice", &(address,)).await?;
        println!("Disconnected {address}");
        Ok(())
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
        println!("Use 'connect <address>' first, then the daemon exposes");
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
        let stats: (u16, u16, u32, u32, u32, u32, u8) = proxy.call("GetStats", &()).await?;
        println!("Subsystem Statistics:");
        println!("  Devices:         {}", stats.0);
        println!("  Connections:     {}", stats.1);
        println!("  Total Created:   {}", stats.2);
        println!("  Mgmt Submitted:  {}", stats.3);
        println!("  Mgmt Timeouts:   {}", stats.4);
        println!("  CRC Errors:      {}", stats.5);
        let pm_label = match stats.6 {
            0 => "Active",
            1 => "Sniff",
            2 => "Idle",
            3 => "Suspended",
            _ => "Unknown",
        };
        println!("  Power State:     {pm_label}");
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
        let count: i32 = proxy.call("EventCount", &()).await?;
        let stats: (u64, u64, u64, u64, u64, u64) = proxy.call("GetEventStats", &()).await?;
        println!("Event Queue:");
        println!("  Pending:      {count}");
        println!("  ConnState:    {}", stats.0);
        println!("  AdvReport:    {}", stats.1);
        println!("  DataRecv:     {}", stats.2);
        println!("  SecChanged:   {}", stats.3);
        println!("  PwrChanged:   {}", stats.4);
        println!("  HwError:      {}", stats.5);
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
