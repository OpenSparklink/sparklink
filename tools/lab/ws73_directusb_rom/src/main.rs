// SPDX-License-Identifier: GPL-2.0-only
//! One fixed read-only ROM exchange in an explicitly selected scratch VM.
//! No enumeration fallback, detach/reset, firmware download or Host/Ready claim.
use nusb::transfer::{Buffer, Bulk, Completion, EndpointDirection, In, Out};
use nusb::{Endpoint, MaybeFuture};
use serde_json::{Value, json};
use std::io;
use std::time::{Duration, Instant};
use ws73_directusb_rom::device::{ProbeKind, open_vm_interface};

const COMMAND: &[u8] = b"READM 0x40019000 4 ";
const IO_LIMIT: Duration = Duration::from_secs(2);
const DRAIN_LIMIT: Duration = Duration::from_secs(1);

fn refuse(reason: &str) -> io::Error {
    io::Error::other(reason)
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
    let opened = open_vm_interface(ProbeKind::RomRead, port)?;
    let (intf, bus, address) = (opened.interface, opened.bus, opened.address);
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
