// SPDX-License-Identifier: GPL-2.0-only
//! A fixed device-layer read; the returned word is not any protocol credit.
use nusb::transfer::{ControlIn, ControlType, Recipient};
use serde_json::{Value, json};
use std::io;
use std::time::{Duration, Instant};

pub const IO_LIMIT: Duration = Duration::from_secs(2);

/// Production admission/receipt function. Tests substitute only the clock and
/// one I/O completion; the real caller constructs the nusb future inside `perform`.
pub fn observe_memory_control(
    deadline: Instant,
    mut now: impl FnMut() -> Instant,
    perform: impl FnOnce(ControlIn, Duration) -> io::Result<Vec<u8>>,
    row: &mut Value,
) -> io::Result<u32> {
    if !row.is_object() || row.get("stage").is_some() {
        return Err(io::Error::other(
            "single fresh control record required; no retry",
        ));
    }
    let start = now();
    if start >= deadline {
        row["stage"] = json!("NOT_SUBMITTED_ORIGINAL_DEADLINE");
        return Err(io::Error::other("not submitted: original deadline"));
    }
    row["stage"] = json!("SUBMIT_CALLED_OUTCOME_PENDING");
    let result = perform(
        ControlIn {
            control_type: ControlType::Class,
            recipient: Recipient::Interface,
            request: 5,
            value: 0,
            index: 0,
            length: 4,
        },
        deadline.saturating_duration_since(start),
    );
    row["elapsed_ns"] = json!(
        now()
            .saturating_duration_since(start)
            .as_nanos()
            .min(u64::MAX as u128) as u64
    );
    let data = match result {
        Ok(data) => data,
        Err(error) => {
            row["stage"] = json!("TRANSPORT_ERROR_NOT_SUCCESS");
            row["error"] = json!(error.to_string());
            return Err(error);
        }
    };
    row["reply"] = json!(&data);
    if now() >= deadline {
        row["stage"] = json!("LATE_COMPLETION_REJECTED");
        return Err(io::Error::other("completion after original deadline"));
    }
    if data.len() != 4 {
        row["stage"] = json!("SHORT_OR_OVERSIZED_REPLY_REJECTED");
        return Err(io::Error::other("exact four-byte memory response required"));
    }
    let word = u32::from_le_bytes(data.as_slice().try_into().expect("exact length checked"));
    row["stage"] = json!("USB_BYTES_NOT_HOST_OR_PROTOCOL_CREDIT");
    Ok(word)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn expired_admission_never_constructs_or_submits_the_transfer() {
        let t = Instant::now();
        let mut row = json!({});
        assert!(
            observe_memory_control(t, || t, |_, _| panic!("must not submit"), &mut row).is_err()
        );
        assert_eq!(row["stage"], "NOT_SUBMITTED_ORIGINAL_DEADLINE");
    }
    #[test]
    fn actual_request_and_exact_word_do_not_manufacture_protocol_credit() {
        let t = Instant::now();
        let mut row = json!({});
        let word = observe_memory_control(
            t + IO_LIMIT,
            || t,
            |r, budget| {
                assert_eq!(r.control_type, ControlType::Class);
                assert_eq!(r.recipient, Recipient::Interface);
                assert_eq!((r.request, r.value, r.index, r.length), (5, 0, 0, 4));
                assert_eq!(budget, IO_LIMIT);
                Ok(vec![0x12, 0x34, 0x56, 0x78])
            },
            &mut row,
        )
        .unwrap();
        assert_eq!(word, 0x78563412);
        assert_eq!(row["stage"], "USB_BYTES_NOT_HOST_OR_PROTOCOL_CREDIT");
    }
    #[test]
    fn zero_is_only_a_raw_word_and_one_record_cannot_submit_twice() {
        let t = Instant::now();
        let mut row = json!({});
        assert_eq!(
            observe_memory_control(t + IO_LIMIT, || t, |_, _| Ok(vec![0; 4]), &mut row).unwrap(),
            0
        );
        let saved = row.clone();
        assert!(
            observe_memory_control(
                t + IO_LIMIT,
                || t,
                |_, _| panic!("must not resubmit"),
                &mut row
            )
            .is_err()
        );
        assert_eq!(row, saved);
        for mut malformed in [json!(null), json!([]), json!("not a record")] {
            assert!(
                observe_memory_control(
                    t + IO_LIMIT,
                    || t,
                    |_, _| panic!("must not submit"),
                    &mut malformed
                )
                .is_err()
            );
        }
    }

    #[test]
    fn failed_short_oversized_and_late_results_never_publish_success() {
        let t = Instant::now();
        for length in [0, 1, 3, 5, 512] {
            let mut row = json!({});
            assert!(
                observe_memory_control(t + IO_LIMIT, || t, |_, _| Ok(vec![0; length]), &mut row)
                    .is_err()
            );
            assert_eq!(row["stage"], "SHORT_OR_OVERSIZED_REPLY_REJECTED");
        }
        let mut row = json!({});
        let error = observe_memory_control(
            t + IO_LIMIT,
            || t,
            |_, _| {
                Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "original completion failure",
                ))
            },
            &mut row,
        )
        .unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::TimedOut);
        assert_eq!(row["stage"], "TRANSPORT_ERROR_NOT_SUCCESS");
        let mut row = json!({});
        let mut clocks = [t, t + IO_LIMIT, t + IO_LIMIT].into_iter();
        assert!(
            observe_memory_control(
                t + IO_LIMIT,
                || clocks.next().unwrap(),
                |_, _| Ok(vec![0; 4]),
                &mut row
            )
            .is_err()
        );
        assert_eq!(row["reply"], json!([0, 0, 0, 0]));
        assert_eq!(row["stage"], "LATE_COMPLETION_REJECTED");
    }
}
