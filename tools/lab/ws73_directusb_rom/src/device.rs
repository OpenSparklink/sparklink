// SPDX-License-Identifier: GPL-2.0-only
//! One exclusive interface opener, shared by ROM and Runtime control consumers.
use crate::authority::{OwnerToken, TransportOwner};
use crate::memory_control::ControlFailure;
use nusb::Interface;
use nusb::descriptors::{ConfigurationDescriptor, TransferType};
use nusb::transfer::{Buffer, Bulk, Completion, EndpointDirection};
use nusb::transfer::{ControlIn, ControlType, Recipient};
use nusb::{Endpoint, MaybeFuture};
use std::io;
use std::marker::PhantomData;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProbeKind {
    RomRead,
    MemoryBackpressure,
    RuntimeReceive,
}
impl ProbeKind {
    fn token(self) -> &'static str {
        match self {
            Self::RomRead => "ws73.directusb_rom=1",
            Self::MemoryBackpressure => "ws73.directusb_control=1",
            Self::RuntimeReceive => "ws73.directusb_receive=1",
        }
    }
}

pub fn selected_port(port: &str) -> bool {
    let Some((bus, chain)) = port.split_once('-') else {
        return false;
    };
    let component = |s: &str| {
        !s.is_empty()
            && s.len() <= 3
            && s.bytes().all(|b| b.is_ascii_digit())
            && s.parse::<u16>().is_ok_and(|v| v > 0 && v <= 255)
    };
    component(bus) && chain.split('.').count() <= 7 && chain.split('.').all(component)
}

pub fn boot_allowed(
    kind: ProbeKind,
    vendor: &str,
    scratch: bool,
    cmdline: &str,
    port: &str,
) -> bool {
    let expected_guest = format!("ws73.directusb_guest={port}");
    let selectors: Vec<_> = cmdline
        .split_whitespace()
        .filter(|t| t.starts_with("ws73.directusb_"))
        .collect();
    vendor.trim() == "QEMU"
        && scratch
        && selected_port(port)
        && selectors.len() == 2
        && selectors.iter().filter(|t| **t == kind.token()).count() == 1
        && selectors.iter().filter(|t| **t == expected_guest).count() == 1
}

pub fn endpoint_layout(kind: ProbeKind, entries: &[(u8, TransferType, usize)]) -> bool {
    let mut addresses: Vec<_> = entries.iter().map(|e| e.0).collect();
    addresses.sort_unstable();
    match kind {
        ProbeKind::RomRead => {
            addresses == [1, 129] && entries.iter().all(|e| e.1 == TransferType::Bulk)
        }
        ProbeKind::MemoryBackpressure | ProbeKind::RuntimeReceive => {
            addresses == [1, 2, 129, 130, 131]
                && entries.iter().all(|&(address, kind, size)| {
                    if address == 131 {
                        kind == TransferType::Interrupt && size == 8
                    } else {
                        kind == TransferType::Bulk && size == 512
                    }
                })
        }
    }
}

pub fn runtime_configuration_allowed(config: &ConfigurationDescriptor<'_>) -> bool {
    let interfaces: Vec<_> = config.interface_alt_settings().collect();
    if config.configuration_value() != 1
        || config.num_interfaces() != 1
        || config.as_bytes().len() != 53
        || interfaces.len() != 1
    {
        return false;
    }
    let i = &interfaces[0];
    if (
        i.interface_number(),
        i.alternate_setting(),
        i.class(),
        i.subclass(),
        i.protocol(),
        i.num_endpoints(),
    ) != (0, 0, 0xe0, 2, 2, 5)
    {
        return false;
    }
    let endpoints: Vec<_> = i.endpoints().collect();
    if endpoints.iter().any(|e| {
        if e.address() == 131 {
            e.attributes() != 3 || e.max_packet_size_raw() != 8
        } else {
            e.attributes() != 2 || e.max_packet_size_raw() != 512
        }
    }) {
        return false;
    }
    let fields: Vec<_> = endpoints
        .iter()
        .map(|e| (e.address(), e.transfer_type(), e.max_packet_size()))
        .collect();
    endpoint_layout(ProbeKind::MemoryBackpressure, &fields)
}

pub struct OpenedVmInterface {
    interface: Option<Interface>,
    owner: TransportOwner,
    pub bus: u8,
    /// Observation only; never a controller generation or a model identity.
    pub address: u8,
}

pub struct OwnedBulkEndpoint<'device, D: EndpointDirection> {
    endpoint: Endpoint<Bulk, D>,
    owner: TransportOwner,
    token: OwnerToken,
    _device: PhantomData<&'device OpenedVmInterface>,
}
impl<D: EndpointDirection> OwnedBulkEndpoint<'_, D> {
    pub fn pending(&self) -> usize {
        self.endpoint.pending()
    }
    pub fn max_packet_size(&self) -> usize {
        self.endpoint.max_packet_size()
    }
    pub(crate) fn submit(&mut self, buffer: Buffer, deadline: Instant) -> io::Result<()> {
        self.owner
            .submit(&self.token, deadline, || self.endpoint.submit(buffer))
    }
    pub(crate) fn wait(&mut self, timeout: Duration) -> Option<Completion> {
        self.endpoint.wait_next_complete(timeout)
    }
    pub(crate) fn cancel(&mut self) {
        self.endpoint.cancel_all();
    }
}
impl OpenedVmInterface {
    pub fn owner(&self) -> TransportOwner {
        self.owner.clone()
    }
    pub fn endpoint<D: EndpointDirection>(
        &self,
        address: u8,
    ) -> io::Result<OwnedBulkEndpoint<'_, D>> {
        let token = self.owner.token()?;
        let endpoint = self
            .interface
            .as_ref()
            .expect("live interface")
            .endpoint::<Bulk, D>(address)?;
        Ok(OwnedBulkEndpoint {
            endpoint,
            owner: self.owner.clone(),
            token,
            _device: PhantomData,
        })
    }
    pub fn release(mut self) -> io::Result<()> {
        self.owner.try_revoke()?;
        self.interface
            .take()
            .expect("live interface")
            .release()
            .wait()
            .map_err(io::Error::from)
    }
    pub fn read_memory_control(
        &self,
        request: ControlIn,
        deadline: Instant,
    ) -> Result<Vec<u8>, ControlFailure> {
        if request.control_type != ControlType::Class
            || request.recipient != Recipient::Interface
            || (
                request.request,
                request.value,
                request.index,
                request.length,
            ) != (5, 0, 0, 4)
        {
            return Err(ControlFailure::NotSubmitted(io::Error::other(
                "only fixed memory control is allowed",
            )));
        }
        let token = self.owner.token().map_err(ControlFailure::NotSubmitted)?;
        // Linux nusb constructs/submits immediately. Keep the original absolute
        // deadline, and never hold the authority guard across completion wait.
        let future = self
            .owner
            .submit(&token, deadline, || {
                let timeout = deadline
                    .checked_duration_since(Instant::now())
                    .filter(|duration| !duration.is_zero())
                    .ok_or_else(|| {
                        io::Error::new(io::ErrorKind::TimedOut, "not submitted: original deadline")
                    })?;
                Ok::<_, io::Error>(
                    self.interface
                        .as_ref()
                        .expect("live interface")
                        .control_in(request, timeout),
                )
            })
            .map_err(ControlFailure::NotSubmitted)?
            .map_err(ControlFailure::NotSubmitted)?;
        future
            .wait()
            .map_err(|error| ControlFailure::Submitted(error.into()))
    }
}
impl Drop for OpenedVmInterface {
    fn drop(&mut self) {
        self.owner.retire_on_drop();
    }
}

#[cfg(target_os = "linux")]
pub fn open_vm_interface(
    kind: ProbeKind,
    port: &str,
) -> Result<OpenedVmInterface, Box<dyn std::error::Error>> {
    use nusb::MaybeFuture;
    use std::fs::{self, OpenOptions};
    use std::path::Path;
    let refuse = |s| io::Error::other(s);
    if !boot_allowed(
        kind,
        &fs::read_to_string("/sys/class/dmi/id/sys_vendor")?,
        Path::new("/scratch-root-uuid").is_file(),
        &fs::read_to_string("/proc/cmdline")?,
        port,
    ) {
        return Err(refuse("explicit selected scratch QEMU VM only").into());
    }
    let path = Path::new("/sys/bus/usb/devices").join(port);
    let interface = Path::new("/sys/bus/usb/devices").join(format!("{port}:1.0"));
    if interface.join("driver").exists() {
        return Err(refuse("device already owned; no detach").into());
    }
    let bus: u8 = fs::read_to_string(path.join("busnum"))?.trim().parse()?;
    let address: u8 = fs::read_to_string(path.join("devnum"))?.trim().parse()?;
    if fs::read_to_string(path.join("idVendor"))?.trim() != "ffff"
        || fs::read_to_string(path.join("idProduct"))?.trim() != "3733"
    {
        return Err(refuse("selected USB identity mismatch").into());
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(format!("/dev/bus/usb/{bus:03}/{address:03}"))?;
    let device = nusb::Device::from_fd(file.into()).wait()?;
    let d = device.device_descriptor();
    if (d.vendor_id(), d.product_id()) != (0xffff, 0x3733) {
        return Err(refuse("opened USB identity changed").into());
    }
    if kind != ProbeKind::RomRead
        && (d.num_configurations() != 1
            || device.configurations().count() != 1
            || !runtime_configuration_allowed(&device.active_configuration()?))
    {
        return Err(refuse("one exact active Runtime configuration/interface required").into());
    }
    let intf = device.claim_interface(0).wait()?;
    let desc = intf
        .descriptor()
        .ok_or_else(|| refuse("missing interface descriptor"))?;
    let fields: Vec<_> = desc
        .endpoints()
        .map(|e| (e.address(), e.transfer_type(), e.max_packet_size()))
        .collect();
    if desc.interface_number() != 0
        || desc.alternate_setting() != 0
        || !endpoint_layout(kind, &fields)
    {
        return Err(refuse("exact selected ROM/Runtime interface required").into());
    }
    Ok(OpenedVmInterface {
        interface: Some(intf),
        owner: TransportOwner::new(),
        bus,
        address,
    })
}

#[cfg(not(target_os = "linux"))]
pub fn open_vm_interface(
    _: ProbeKind,
    _: &str,
) -> Result<OpenedVmInterface, Box<dyn std::error::Error>> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "Linux scratch transport only; Windows execution not implemented",
    )
    .into())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn actual_shared_guard_rejects_host_missing_duplicate_mixed_and_foreign_guest() {
        for kind in [
            ProbeKind::RomRead,
            ProbeKind::MemoryBackpressure,
            ProbeKind::RuntimeReceive,
        ] {
            let valid = format!("{} ws73.directusb_guest=1-1.2", kind.token());
            assert!(boot_allowed(kind, "QEMU\n", true, &valid, "1-1.2"));
            for (vendor, scratch, tokens, port) in [
                ("host", true, valid.clone(), "1-1.2"),
                ("QEMU", false, valid.clone(), "1-1.2"),
                ("QEMU", true, valid.clone(), "1-1.3"),
                ("QEMU", true, kind.token().into(), "1-1.2"),
                ("QEMU", true, format!("{valid} {}", kind.token()), "1-1.2"),
                (
                    "QEMU",
                    true,
                    format!("{valid} ws73.directusb_guest=1-1.2"),
                    "1-1.2",
                ),
                (
                    "QEMU",
                    true,
                    format!("{valid} ws73.directusb_unknown=1"),
                    "1-1.2",
                ),
                (
                    "QEMU",
                    true,
                    "ws73.directusb_rom=1 ws73.directusb_control=1 ws73.directusb_guest=1-1.2"
                        .into(),
                    "1-1.2",
                ),
            ] {
                assert!(!boot_allowed(kind, vendor, scratch, &tokens, port));
            }
        }
        for port in ["", "../1-1", "1-0", "1-1:1.0", "1-256", "1-1/../2"] {
            assert!(!selected_port(port));
        }
    }
    #[test]
    fn actual_configuration_parser_rejects_extra_interface_class_alt_and_reserved_bits() {
        let bytes = [
            9, 2, 53, 0, 1, 1, 0, 192, 1, 9, 4, 0, 0, 5, 224, 2, 2, 1, 7, 5, 129, 2, 0, 2, 0, 7, 5,
            1, 2, 0, 2, 0, 7, 5, 131, 3, 8, 0, 1, 7, 5, 2, 2, 0, 2, 0, 7, 5, 130, 2, 0, 2, 0,
        ];
        assert!(runtime_configuration_allowed(
            &ConfigurationDescriptor::new(&bytes).unwrap()
        ));
        for (index, value) in [
            (4, 2),
            (5, 2),
            (11, 1),
            (12, 1),
            (13, 4),
            (14, 255),
            (15, 0),
            (16, 0),
            (20, 1),
            (21, 130),
            (23, 10),
            (37, 10),
        ] {
            let mut changed = bytes;
            changed[index] = value;
            if let Some(parsed) = ConfigurationDescriptor::new(&changed) {
                assert!(
                    !runtime_configuration_allowed(&parsed),
                    "accepted mutated byte {index}"
                );
            }
        }
    }

    #[test]
    fn exact_mode_geometry_has_no_cross_mode_or_duplicate_endpoint_fallback() {
        let runtime = [
            (1, TransferType::Bulk, 512),
            (2, TransferType::Bulk, 512),
            (129, TransferType::Bulk, 512),
            (130, TransferType::Bulk, 512),
            (131, TransferType::Interrupt, 8),
        ];
        let rom = [(1, TransferType::Bulk, 64), (129, TransferType::Bulk, 64)];
        assert!(endpoint_layout(ProbeKind::MemoryBackpressure, &runtime));
        assert!(endpoint_layout(ProbeKind::RomRead, &rom));
        assert!(!endpoint_layout(ProbeKind::RomRead, &runtime));
        assert!(!endpoint_layout(ProbeKind::MemoryBackpressure, &rom));
        for index in 0..runtime.len() {
            let mut fields = runtime;
            fields[index].0 = 1;
            if index != 0 {
                assert!(!endpoint_layout(ProbeKind::MemoryBackpressure, &fields));
            }
            fields = runtime;
            fields[index].1 = TransferType::Isochronous;
            assert!(!endpoint_layout(ProbeKind::MemoryBackpressure, &fields));
            fields = runtime;
            fields[index].2 = 0;
            assert!(!endpoint_layout(ProbeKind::MemoryBackpressure, &fields));
        }
    }
}
