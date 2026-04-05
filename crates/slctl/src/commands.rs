use zbus::Connection;

pub struct Context {
    conn: Connection,
}

impl Context {
    pub fn new(conn: Connection) -> Self {
        Self { conn }
    }

    pub async fn dispatch(&mut self, args: &[&str]) -> anyhow::Result<()> {
        match args[0] {
            "list" => self.cmd_list().await,
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
            _ => {
                anyhow::bail!("unknown command '{}' — type 'help'", args[0]);
            }
        }
    }

    async fn adapter_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            "/org/sparklink/slk0",
            "org.sparklink.Adapter",
        ).await?)
    }

    async fn security_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            "/org/sparklink/slk0/security",
            "org.sparklink.Security",
        ).await?)
    }

    async fn service_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            "/org/sparklink/slk0/services",
            "org.sparklink.ServiceManager",
        ).await?)
    }

    async fn manager_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            "/org/sparklink",
            "org.sparklink.Manager",
        ).await?)
    }

    async fn controller_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            "/org/sparklink/slk0/controller",
            "org.sparklink.Controller",
        ).await?)
    }

    async fn extadv_proxy(&self) -> anyhow::Result<zbus::Proxy<'_>> {
        Ok(zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            "/org/sparklink/slk0/extadv",
            "org.sparklink.ExtAdv",
        ).await?)
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

        println!("Adapter slk0:");
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
            "/org/sparklink/slk0/dev_{}",
            address.replace(':', "")
        );
        let proxy = zbus::Proxy::new(
            &self.conn,
            "org.sparklink",
            object_path.as_str(),
            "org.sparklink.Device",
        ).await?;

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
                println!("  [{:#06x}-{:#06x}] UUID={:#06x} {kind}", start, end, uuid16);
            }
        }
        Ok(())
    }

    async fn cmd_remote_services(&self) -> anyhow::Result<()> {
        println!("Remote service discovery requires an active connection.");
        println!("Use 'connect <address>' first, then the daemon exposes");
        println!("org.sparklink.RemoteService at /org/sparklink/slk0/conn_<handle>");
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
        let stats: (u16, u16, u32, u32, u32, u32, u8) =
            proxy.call("GetStats", &()).await?;
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
                let handle: u8 = args.get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: extadv enable <handle>"))?
                    .parse()?;
                let _: () = proxy.call("Enable", &(handle,)).await?;
                println!("ExtAdv set {handle} enabled");
            }
            "disable" => {
                let handle: u8 = args.get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: extadv disable <handle>"))?
                    .parse()?;
                let _: () = proxy.call("Disable", &(handle,)).await?;
                println!("ExtAdv set {handle} disabled");
            }
            "remove" => {
                let handle: u8 = args.get(2)
                    .ok_or_else(|| anyhow::anyhow!("usage: extadv remove <handle>"))?
                    .parse()?;
                let _: () = proxy.call("Remove", &(handle,)).await?;
                println!("ExtAdv set {handle} removed");
            }
            "info" => {
                let handle: u8 = args.get(2)
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
}

fn parse_handle(s: &str) -> anyhow::Result<u16> {
    let s = s.strip_prefix("0x").unwrap_or(s);
    Ok(u16::from_str_radix(s, 16)?)
}

fn parse_hex_bytes(hex: &str) -> anyhow::Result<Vec<u8>> {
    let hex = hex.strip_prefix("0x").unwrap_or(hex);
    if hex.len() % 2 != 0 {
        anyhow::bail!("hex string must have even length");
    }
    let mut bytes = Vec::with_capacity(hex.len() / 2);
    for i in (0..hex.len()).step_by(2) {
        bytes.push(u8::from_str_radix(&hex[i..i + 2], 16)?);
    }
    Ok(bytes)
}
