// SPDX-License-Identifier: GPL-2.0-only
//! One passive Runtime register-IN endpoint operation. No register setup OUT.
use nusb::MaybeFuture;
use nusb::transfer::{Buffer, Bulk, In};
use serde_json::{Value, json};
use std::io;
use std::time::Instant;
use ws73_directusb_rom::bulk::{IO_LIMIT, MAX_TRANSFER_BYTES, exchange};
use ws73_directusb_rom::device::{ProbeKind, open_vm_interface};

fn run(port: &str, report: &mut Value) -> Result<(), Box<dyn std::error::Error>> {
    let opened = open_vm_interface(ProbeKind::RuntimeReceive, port)?;
    let mut endpoint = opened.interface.endpoint::<Bulk, In>(0x82)?;
    report["guest_port"] = json!(port);
    report["bus"] = json!(opened.bus);
    report["device_number_observation"] = json!(opened.address);
    report["receive"] = json!({"endpoint":130,"requested":MAX_TRANSFER_BYTES});
    let result = exchange(
        &mut endpoint,
        Buffer::new(MAX_TRANSFER_BYTES),
        Instant::now() + IO_LIMIT,
        &mut report["receive"],
    );
    let pending = endpoint.pending();
    report["endpoint_pending_after"] = json!(pending);
    drop(endpoint);
    let release = if pending == 0 {
        let release = opened.interface.release().wait();
        report["interface_release"] =
            json!({"result":format!("{release:?}"),"physical_drain_proven":false});
        release.map_err(io::Error::from)
    } else {
        report["interface_release"] =
            json!({"result":"NOT_REQUESTED_UNDRAINED_ENDPOINT","physical_drain_proven":false});
        Err(io::Error::other(
            "endpoint remains quarantined; no release/drain claim",
        ))
    };
    // The original deadline/error always wins, even after successful cancellation
    // completion and interface release. Never turn an expected timeout into PASS.
    result?;
    release?;
    report["status"] = json!("RUNTIME_BULK_BYTES_OBSERVED_NOT_HOST_OR_REGISTER_VALUE");
    Ok(())
}
fn main() {
    let mut report = json!({"schema":1,"status":"REFUSED_OR_FAILED","scope":"VM_RUNTIME_BULK_IN_ONLY_NOT_HOST_OR_RECOVERY"});
    let args: Vec<_> = std::env::args().collect();
    let result = if args.len() == 2 {
        run(&args[1], &mut report)
    } else {
        Err(io::Error::other("usage: ws73-directusb-receive EXPLICIT_GUEST_PORT").into())
    };
    if let Err(error) = &result {
        report["error"] = json!(error.to_string());
    }
    println!("{report}");
    if result.is_err() {
        std::process::exit(1);
    }
}
