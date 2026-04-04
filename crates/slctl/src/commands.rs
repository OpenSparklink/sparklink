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
        match value {
            Some("g") | Some("0") => {
                println!("Setting role to G-node (requires direct ioctl via slkconfig)");
            }
            Some("t") | Some("1") => {
                println!("Setting role to T-node (requires direct ioctl via slkconfig)");
            }
            Some(_) => anyhow::bail!("role: g or t"),
            None => {
                println!("Use 'slkconfig role' to query/set role (direct ioctl)");
            }
        }
        Ok(())
    }

    async fn cmd_phy(&self) -> anyhow::Result<()> {
        println!("Use 'slkconfig phy' for PHY details (direct ioctl)");
        Ok(())
    }

    async fn cmd_stats(&self) -> anyhow::Result<()> {
        println!("Use 'slkconfig stats' for subsystem statistics (direct ioctl)");
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
