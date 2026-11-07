// SPDX-License-Identifier: GPL-2.0-only
//! Fixed passive HCC IN81 window; no command, firmware or register operation.
use nusb::transfer::In;
use serde_json::{Value, json};
use std::{io, time::Instant};
use ws73_directusb_rom::{
    bulk::IO_LIMIT,
    device::{ProbeKind, open_vm_interface},
    runtime_receive,
};
fn run(port: &str, report: &mut Value) -> Result<(), Box<dyn std::error::Error>> {
    let opened = open_vm_interface(ProbeKind::RuntimePackets, port)?;
    let mut endpoint = opened.endpoint::<In>(0x81)?;
    let owner = opened.owner();
    report["transport_authority_origin"] = json!("LOCAL_PROCESS_INTERFACE_NOT_NATIVE_GRANT");
    report["transport_owner_epoch_before"] = json!(owner.current_epoch()?);
    report["guest_port"] = json!(port);
    report["bus"] = json!(opened.bus);
    report["device_number_observation"] = json!(opened.address);
    report["receive_window"] = json!({});
    let result = runtime_receive::window(
        &mut endpoint,
        Instant::now() + IO_LIMIT,
        &mut report["receive_window"],
    );
    report["transport_owner_epoch_after"] = json!(owner.current_epoch()?);
    let pending = endpoint.pending();
    report["endpoint_pending_after"] = json!(pending);
    drop(endpoint);
    let release = if pending == 0 {
        let release = opened.release();
        report["interface_release"] =
            json!({"result":format!("{release:?}"),"physical_drain_proven":false});
        release
    } else {
        report["interface_release"] =
            json!({"result":"NOT_REQUESTED_UNDRAINED_ENDPOINT","physical_drain_proven":false});
        Err(io::Error::other(
            "endpoint remains quarantined; no drain claim",
        ))
    };
    result?;
    release?;
    report["status"] = json!("BOUNDED_DEVICE_PACKETS_OBSERVED_NOT_HOST_OR_RECOVERY");
    Ok(())
}
fn main() {
    let mut report = json!({"schema":1,"status":"REFUSED_OR_FAILED","scope":"VM_RUNTIME_HCC_PACKETS_NOT_HOST_OR_RECOVERY"});
    let args: Vec<_> = std::env::args().collect();
    let result = if args.len() == 2 && !args[1].starts_with('-') {
        run(&args[1], &mut report)
    } else {
        Err(io::Error::other("usage: ws73-directusb-packets EXPLICIT_GUEST_PORT").into())
    };
    if let Err(error) = &result {
        report["error"] = json!(error.to_string());
    }
    println!("{report}");
    if result.is_err() {
        std::process::exit(1);
    }
}
