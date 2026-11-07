// SPDX-License-Identifier: GPL-2.0-only
//! One fixed read-only ROM exchange in an explicitly selected scratch VM.
//! No enumeration fallback, detach/reset, firmware download or Host/Ready claim.
use nusb::transfer::{Buffer, In, Out};
use serde_json::{Value, json};
use std::io;
use std::time::Instant;
use ws73_directusb_rom::bulk::{IO_LIMIT, exchange};
use ws73_directusb_rom::device::{ProbeKind, open_vm_interface};

const COMMAND: &[u8] = b"READM 0x40019000 4 ";

fn refuse(reason: &str) -> io::Error {
    io::Error::other(reason)
}

fn run(port: &str, report: &mut Value) -> Result<(), Box<dyn std::error::Error>> {
    let opened = open_vm_interface(ProbeKind::RomRead, port)?;
    let (bus, address) = (opened.bus, opened.address);
    let mut output = opened.endpoint::<Out>(1)?;
    let mut input = opened.endpoint::<In>(0x81)?;
    if input.max_packet_size() == 0 || 512 % input.max_packet_size() != 0 {
        return Err(refuse("unsupported ROM max packet size").into());
    }
    report["guest_port"] = json!(port);
    report["bus"] = json!(bus);
    report["device_number_observation"] = json!(address);
    report["command"] = json!(String::from_utf8_lossy(COMMAND));
    let result = (|| -> io::Result<()> {
        report["out"] = json!({"endpoint":1,"requested":COMMAND.len()});
        let out = exchange(
            &mut output,
            Buffer::from(COMMAND.to_vec()),
            Instant::now() + IO_LIMIT,
            &mut report["out"],
        )?;
        if out.actual_len != COMMAND.len() {
            return Err(refuse("short ROM command; no input submission"));
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
            return Err(refuse("exact four-byte ROM reply required"));
        }
        Ok(())
    })();
    let pending = input.pending() + output.pending();
    report["endpoint_pending_after"] = json!(pending);
    drop(input);
    drop(output);
    let release = if pending == 0 {
        let release = opened.release();
        report["interface_release"] =
            json!({"result":format!("{release:?}"),"physical_drain_proven":false});
        release
    } else {
        report["interface_release"] =
            json!({"result":"NOT_REQUESTED_UNDRAINED_ENDPOINT","physical_drain_proven":false});
        Err(refuse(
            "endpoint remains quarantined; release is not a drain barrier",
        ))
    };
    result?;
    release?;
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
