// SPDX-License-Identifier: GPL-2.0-only
//! One finite HCC receive window; not a continuously running Host or RX actor.
use crate::bulk::receive_hcc;
use crate::device::OwnedBulkEndpoint;
use crate::wire::{self, DevicePacket};
use nusb::transfer::{Completion, In};
use serde_json::{Value, json};
use std::{io, time::Instant};

pub const AGGREGATE_LIMIT: usize = 8;
pub const BYTE_LIMIT: usize = AGGREGATE_LIMIT * wire::MAX_RX_BYTES;
fn metadata(packet: DevicePacket<'_>) -> Value {
    match packet {
        DevicePacket::Event {
            code,
            parameters,
            original,
        } => json!({"kind":"Event", "code":code,
            "parameter_octets":parameters.len(),"wire_octets":original.len()}),
        DevicePacket::Acb {
            handle,
            boundary,
            priority,
            payload,
            original,
        } => json!({"kind":"Acb",
            "connection_handle":handle,"PB":boundary as u32,"priority":priority,
            "payload_octets":payload.len(),"wire_octets":original.len()}),
        DevicePacket::Bsle(bytes) => json!({"kind":"Bsle","wire_octets":bytes.len()}),
        DevicePacket::Platform(bytes) => json!({"kind":"Platform","wire_octets":bytes.len()}),
    }
}
fn window_io(
    deadline: Instant,
    row: &mut Value,
    mut receive: impl FnMut(Instant, &mut Value) -> io::Result<Completion>,
    mut now: impl FnMut() -> Instant,
) -> io::Result<()> {
    if !row.is_object() || row.get("stage").is_some() || row.get("aggregates").is_some() {
        return Err(io::Error::other("one fresh receive-window record required"));
    }
    let mut aggregates = Vec::with_capacity(AGGREGATE_LIMIT);
    let (mut bytes, mut packets) = (0usize, 0usize);
    let result = (|| {
        for _ in 0..AGGREGATE_LIMIT {
            if now() >= deadline {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "original receive window deadline",
                ));
            }
            let mut attempt = json!({"endpoint":129,"requested":wire::MAX_RX_BYTES});
            let completion = match receive(deadline, &mut attempt) {
                Ok(completion) => completion,
                Err(error) => {
                    aggregates.push(attempt);
                    return Err(error);
                }
            };
            let validation = (|| {
                if completion.status.is_err()
                    || completion.actual_len != completion.buffer.len()
                    || completion.actual_len > wire::MAX_RX_BYTES
                {
                    return Err(io::Error::other("receive completion accounting mismatch"));
                }
                let decoded = wire::decode_receive(&completion.buffer, wire::MAX_ACB_BYTES as u16)?;
                let descriptions: Vec<_> = decoded.into_iter().map(metadata).collect();
                bytes = bytes
                    .checked_add(completion.actual_len)
                    .filter(|n| *n <= BYTE_LIMIT)
                    .ok_or_else(|| io::Error::other("window byte budget exceeded"))?;
                packets = packets
                    .checked_add(descriptions.len())
                    .filter(|n| *n <= AGGREGATE_LIMIT * wire::MAX_RX_SLOTS)
                    .ok_or_else(|| io::Error::other("window packet budget exceeded"))?;
                attempt["packets"] = json!(descriptions);
                if now() >= deadline {
                    return Err(io::Error::new(
                        io::ErrorKind::TimedOut,
                        "original deadline after packet validation",
                    ));
                }
                Ok(())
            })();
            if let Err(ref error) = validation {
                attempt["packet_validation_error"] = json!(error.to_string());
            }
            aggregates.push(attempt);
            validation?;
        }
        if packets == 0 {
            return Err(io::Error::other("bounded window had no supported packets"));
        }
        Ok(())
    })();
    row["acb_decode_ceiling"] = json!(wire::MAX_ACB_BYTES);
    row["negotiated_controller_limit_verified"] = json!(false);
    row["aggregate_limit"] = json!(AGGREGATE_LIMIT);
    row["byte_limit"] = json!(BYTE_LIMIT);
    row["observed_octets"] = json!(bytes);
    row["validated_transport_packets"] = json!(packets);
    row["aggregates"] = json!(aggregates);
    row["stage"] = json!(if result.is_ok() {
        "BOUNDED_TRANSPORT_WINDOW_COMPLETE_NOT_HOST"
    } else {
        "WINDOW_FAILED_PARTIAL_OBSERVATIONS_RETAINED"
    });
    result
}
pub fn window(
    endpoint: &mut OwnedBulkEndpoint<'_, In>,
    deadline: Instant,
    row: &mut Value,
) -> io::Result<()> {
    window_io(
        deadline,
        row,
        |original, attempt| receive_hcc(endpoint, original, attempt),
        Instant::now,
    )
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    use nusb::transfer::Buffer;
    use std::time::Duration;
    fn completion(valid: bool) -> Completion {
        let mut bytes = vec![0; 156];
        bytes[0] = 2;
        bytes[4..8].copy_from_slice(&156u32.to_le_bytes());
        bytes[12..14].copy_from_slice(&64u16.to_le_bytes());
        bytes[92..101].copy_from_slice(&[0xa1, 8, 5, 0, 0xa2, 1, 0, 0, 0]);
        if !valid {
            bytes[99] = 1;
        }
        let mut buffer = Buffer::new(512);
        buffer.extend_from_slice(&bytes);
        Completion {
            buffer,
            actual_len: 156,
            status: Ok(()),
        }
    }
    #[test]
    fn actual_c_receive_window_is_finite_and_retains_original_deadline() {
        let t = Instant::now();
        let deadline = t + Duration::from_secs(2);
        let mut row = json!({});
        let mut calls = 0;
        let mut ticks = 0;
        window_io(
            deadline,
            &mut row,
            |original, attempt| {
                assert_eq!(original, deadline);
                calls += 1;
                attempt["fixture"] = json!("completion only,no USB");
                Ok(completion(true))
            },
            || {
                ticks += 1;
                t + Duration::from_millis(ticks * 10)
            },
        )
        .unwrap();
        assert_eq!(calls, 8);
        assert_eq!(row["validated_transport_packets"], 8);
        assert_eq!(row["observed_octets"], 1248);
        assert_eq!(row["stage"], "BOUNDED_TRANSPORT_WINDOW_COMPLETE_NOT_HOST");
        assert!(window_io(deadline, &mut row, |_, _| panic!("no repeat"), || t).is_err());
    }
    #[test]
    fn malformed_later_packet_and_original_io_error_stop_without_success() {
        let t = Instant::now();
        let deadline = t + Duration::from_secs(2);
        for malformed in [false, true] {
            let mut row = json!({});
            let mut calls = 0;
            let result = window_io(
                deadline,
                &mut row,
                |_, attempt| {
                    calls += 1;
                    if calls == 2 && !malformed {
                        attempt["stage"] = json!("DEADLINE_COMPLETION_RETAINED_NOT_SUCCESS");
                        return Err(io::Error::new(
                            io::ErrorKind::TimedOut,
                            "original IO deadline",
                        ));
                    }
                    Ok(completion(calls != 2))
                },
                || t,
            );
            assert!(result.is_err());
            assert_eq!(calls, 2);
            assert_eq!(row["aggregates"].as_array().unwrap().len(), 2);
            assert_eq!(row["validated_transport_packets"], 1);
            assert_eq!(row["stage"], "WINDOW_FAILED_PARTIAL_OBSERVATIONS_RETAINED");
            if !malformed {
                assert_eq!(result.unwrap_err().to_string(), "original IO deadline");
            }
        }
    }
    #[test]
    fn expired_window_never_invokes_dependency_and_empty_window_is_not_success() {
        let t = Instant::now();
        let mut row = json!({});
        assert!(window_io(t, &mut row, |_, _| panic!("expired"), || t).is_err());
        assert!(row["aggregates"].as_array().unwrap().is_empty());
        let mut calls = 0;
        let mut row = json!({});
        assert!(
            window_io(
                t + Duration::from_secs(2),
                &mut row,
                |_, _| {
                    calls += 1;
                    let mut buffer = Buffer::new(512);
                    buffer.extend_fill(12, 0);
                    Ok(Completion {
                        buffer,
                        actual_len: 12,
                        status: Ok(()),
                    })
                },
                || t
            )
            .is_err()
        );
        assert_eq!(calls, 8);
        assert_eq!(row["validated_transport_packets"], 0);
    }
    #[test]
    fn completion_accounting_and_validation_time_cannot_make_window_successful() {
        let t = Instant::now();
        let deadline = t + Duration::from_secs(2);
        for bad in 0..3 {
            let mut calls = 0;
            let mut times = 0;
            let mut row = json!({});
            let result = window_io(
                deadline,
                &mut row,
                |_, _| {
                    calls += 1;
                    let mut completion = completion(true);
                    if bad == 0 {
                        completion.actual_len = 500;
                    }
                    if bad == 1 {
                        completion.status = Err(nusb::transfer::TransferError::Disconnected);
                    }
                    Ok(completion)
                },
                || {
                    times += 1;
                    if bad == 2 && times > 1 { deadline } else { t }
                },
            );
            assert!(result.is_err());
            assert_eq!(calls, 1);
            assert_eq!(row["aggregates"].as_array().unwrap().len(), 1);
            assert_eq!(row["stage"], "WINDOW_FAILED_PARTIAL_OBSERVATIONS_RETAINED");
        }
    }
}
