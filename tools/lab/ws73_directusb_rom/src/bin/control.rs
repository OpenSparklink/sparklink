// SPDX-License-Identifier: GPL-2.0-only
//! Fixed Runtime memory-backpressure read; never Native Ready or Host traffic.
use serde_json::{Value, json};
use std::io;
use std::time::Instant;
use ws73_directusb_rom::device::{ProbeKind, open_vm_interface};
use ws73_directusb_rom::memory_control::{IO_LIMIT, observe_memory_control};

fn run(port: &str, report: &mut Value) -> Result<(), Box<dyn std::error::Error>> {
    let opened = open_vm_interface(ProbeKind::MemoryBackpressure, port)?;
    report["guest_port"] = json!(port);
    report["bus"] = json!(opened.bus);
    report["device_number_observation"] = json!(opened.address);
    report["control"] = json!({"kind":161,"request":5,"value":0,"index":0,"length":4});
    let result = observe_memory_control(
        Instant::now() + IO_LIMIT,
        Instant::now,
        |request, deadline| opened.read_memory_control(request, deadline),
        &mut report["control"],
    );
    // wait() has returned the request result. Release is separate evidence,
    // never a firmware reset/drain or readiness barrier and never masks I/O error.
    let release = opened.release();
    report["interface_release"] =
        json!({"result":format!("{release:?}"),"physical_drain_proven":false});
    let word = result?;
    release?;
    report["raw_memory_backpressure_word_le"] = json!(word);
    report["status"] = json!("RUNTIME_EP0_BYTES_OBSERVED_NOT_HOST_OR_PROTOCOL_CREDIT");
    Ok(())
}
fn main() {
    let mut report = json!({"schema":1,"status":"REFUSED_OR_FAILED","scope":"VM_RUNTIME_EP0_READ_ONLY_NOT_HOST_OR_RECOVERY"});
    let args: Vec<_> = std::env::args().collect();
    let result = if args.len() == 2 {
        run(&args[1], &mut report)
    } else {
        Err(io::Error::other("usage: ws73-directusb-control EXPLICIT_GUEST_PORT").into())
    };
    if let Err(error) = &result {
        report["error"] = json!(error.to_string());
    }
    println!("{report}");
    if result.is_err() {
        std::process::exit(1)
    }
}
