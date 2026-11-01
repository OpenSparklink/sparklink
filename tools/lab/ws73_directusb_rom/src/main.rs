// SPDX-License-Identifier: GPL-2.0-only
//! One fixed read-only ROM exchange in an explicitly selected scratch VM.
//! No enumeration fallback, detach/reset, firmware download or Host/Ready claim.
use nusb::transfer::{Buffer, Bulk, Completion, EndpointDirection, In, Out};
use nusb::{Endpoint, MaybeFuture};
use serde_json::{Value, json};
use std::fs::{self, OpenOptions};
use std::io;
use std::path::Path;
use std::time::{Duration, Instant};

const COMMAND: &[u8] = b"READM 0x40019000 4 ";
const IO_LIMIT: Duration = Duration::from_secs(2);
const DRAIN_LIMIT: Duration = Duration::from_secs(1);

fn refuse(reason: &str) -> io::Error {
    io::Error::other(reason)
}

fn selected_port(port: &str) -> bool {
    // Guest topology only. Host leaf authorization remains in the VM runner.
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

fn boot_allowed(vendor: &str, scratch: bool, cmdline: &str, port: &str) -> bool {
    vendor.trim() == "QEMU"
        && scratch
        && selected_port(port)
        && cmdline
            .split_whitespace()
            .filter(|t| t.starts_with("ws73.directusb_rom="))
            .collect::<Vec<_>>()
            == ["ws73.directusb_rom=1"]
        && cmdline
            .split_whitespace()
            .filter(|t| t.starts_with("ws73.directusb_guest="))
            .collect::<Vec<_>>()
            == [format!("ws73.directusb_guest={port}")]
}

fn completion_record(c: &Completion) -> Value {
    json!({"actual":c.actual_len,"status":format!("{:?}",c.status),"buffer_length":c.buffer.len()})
}

/// One outstanding transfer. Admission owns the buffer until actual completion.
/// A deadline/cancel does not refund anything or authorize another submission.
fn exchange<D: EndpointDirection>(
    endpoint: &mut Endpoint<Bulk, D>,
    buffer: Buffer,
    deadline: Instant,
    row: &mut Value,
) -> io::Result<Completion> {
    if endpoint.pending() != 0 || Instant::now() >= deadline {
        return Err(refuse("not submitted: busy or original deadline"));
    }
    row["stage"] = json!("SUBMIT_CALLED_OUTCOME_PENDING");
    endpoint.submit(buffer);
    // No future construction or queued closure can submit later in this tool.
    if let Some(c) = endpoint.wait_next_complete(deadline.saturating_duration_since(Instant::now()))
    {
        row["completion"] = completion_record(&c);
        row["pending_after"] = json!(endpoint.pending());
        if Instant::now() >= deadline {
            row["stage"] = json!("LATE_COMPLETION_REJECTED");
            return Err(refuse("completion after original deadline"));
        }
        row["stage"] = json!("USB_COMPLETION_NOT_PROTOCOL_DELIVERY");
        c.status.map_err(io::Error::from)?;
        return Ok(c);
    }
    row["cancel_requested"] = json!(true);
    endpoint.cancel_all();
    let drain = Instant::now() + DRAIN_LIMIT;
    if let Some(c) = endpoint.wait_next_complete(drain.saturating_duration_since(Instant::now())) {
        row["completion"] = completion_record(&c);
        row["pending_after"] = json!(endpoint.pending());
        row["stage"] = json!("DEADLINE_COMPLETION_RETAINED_NOT_SUCCESS");
    } else {
        row["pending_after"] = json!(endpoint.pending());
        row["stage"] = json!("QUARANTINED_UNDRAINED");
        // The dependency keeps pending buffers alive until callback. Process
        // exit is not recorded as device reset, drain or recovered readiness.
    }
    Err(refuse("original deadline; no retry or follow-up transfer"))
}

fn run(port: &str, report: &mut Value) -> Result<(), Box<dyn std::error::Error>> {
    if !boot_allowed(
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
    let intf = device.claim_interface(0).wait()?;
    let desc = intf
        .descriptor()
        .ok_or_else(|| refuse("missing interface descriptor"))?;
    let endpoints: Vec<_> = desc.endpoints().map(|e| e.address()).collect();
    if desc.interface_number() != 0
        || desc.alternate_setting() != 0
        || endpoints.len() != 2
        || !endpoints.contains(&1)
        || !endpoints.contains(&0x81)
    {
        return Err(refuse("two-endpoint ROM interface required before download").into());
    }
    let mut output = intf.endpoint::<Bulk, Out>(1)?;
    let mut input = intf.endpoint::<Bulk, In>(0x81)?;
    if input.max_packet_size() == 0 || 512 % input.max_packet_size() != 0 {
        return Err(refuse("unsupported ROM max packet size").into());
    }
    report["guest_port"] = json!(port);
    report["bus"] = json!(bus);
    report["device_number_observation"] = json!(address);
    report["command"] = json!(String::from_utf8_lossy(COMMAND));
    report["out"] = json!({"endpoint":1,"requested":COMMAND.len()});
    let out = exchange(
        &mut output,
        Buffer::from(COMMAND.to_vec()),
        Instant::now() + IO_LIMIT,
        &mut report["out"],
    )?;
    if out.actual_len != COMMAND.len() {
        return Err(refuse("short ROM command; no input submission").into());
    }
    report["in"] = json!({"endpoint":129,"requested":512});
    let incoming = exchange(
        &mut input,
        Buffer::new(512),
        Instant::now() + IO_LIMIT,
        &mut report["in"],
    )?;
    report["reply"] = json!(&incoming.buffer[..]);
    if incoming.actual_len != 4 || incoming.buffer.len() != 4 {
        return Err(refuse("exact four-byte ROM reply required").into());
    }
    drop(input);
    drop(output);
    intf.release().wait()?;
    report["status"] = json!("ROM_BYTES_OBSERVED_NOT_MODEL_AUTHENTICATION");
    Ok(())
}

fn main() {
    let mut report = json!({"schema":1,"status":"REFUSED_OR_FAILED","scope":"VM_ROM_READ_ONLY_NOT_HOST_OR_RECOVERY"});
    let args: Vec<_> = std::env::args().collect();
    let result = if args.len() == 2 {
        run(&args[1], &mut report)
    } else {
        Err(refuse("usage: ws73-directusb-rom EXPLICIT_GUEST_PORT").into())
    };
    if let Err(error) = &result {
        report["error"] = json!(error.to_string());
    }
    println!("{report}");
    if result.is_err() {
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_missing_duplicate_mismatched_and_host_inputs() {
        let valid = "ws73.directusb_rom=1 ws73.directusb_guest=1-1.2";
        assert!(boot_allowed("QEMU\n", true, valid, "1-1.2"));
        for (vendor, scratch, tokens, port) in [
            ("host", true, valid, "1-1.2"),
            ("QEMU", false, valid, "1-1.2"),
            ("QEMU", true, valid, "1-1.3"),
            ("QEMU", true, "ws73.directusb_rom=1", "1-1.2"),
            (
                "QEMU",
                true,
                "ws73.directusb_rom=1 ws73.directusb_rom=1 ws73.directusb_guest=1-1.2",
                "1-1.2",
            ),
        ] {
            assert!(!boot_allowed(vendor, scratch, tokens, port));
        }
        for port in ["", "../1-1", "1-0", "1-1:1.0", "1-256", "1-1/../2"] {
            assert!(!selected_port(port));
        }
    }
}
