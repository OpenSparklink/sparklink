// SPDX-License-Identifier: GPL-2.0-only
//! One bounded experimental USB transfer, shared by ROM and Runtime consumers.
//! No controller identity, protocol credit, retry, or firmware-drain authority.
use crate::device::OwnedBulkEndpoint;
use nusb::transfer::{Buffer, Completion, Direction, EndpointDirection};
use serde_json::{Value, json};
use std::io;
use std::time::{Duration, Instant};

pub const IO_LIMIT: Duration = Duration::from_secs(2);
pub const DRAIN_LIMIT: Duration = Duration::from_secs(1);
pub const MAX_TRANSFER_BYTES: usize = 512;

// Only the OS endpoint boundary and clock are substituted in unit tests. The
// same exchange below performs all actual admission, cancellation and verdicts.
trait BulkIo {
    fn direction(&self) -> Direction;
    fn max_packet_size(&self) -> usize;
    fn pending(&self) -> usize;
    fn submit(&mut self, buffer: Buffer, deadline: Instant) -> io::Result<()>;
    fn wait(&mut self, duration: Duration) -> Option<Completion>;
    fn cancel(&mut self);
}
impl<D: EndpointDirection> BulkIo for OwnedBulkEndpoint<'_, D> {
    fn direction(&self) -> Direction {
        D::DIR
    }
    fn max_packet_size(&self) -> usize {
        self.max_packet_size()
    }
    fn pending(&self) -> usize {
        self.pending()
    }
    fn submit(&mut self, buffer: Buffer, deadline: Instant) -> io::Result<()> {
        self.submit(buffer, deadline)
    }
    fn wait(&mut self, duration: Duration) -> Option<Completion> {
        self.wait(duration)
    }
    fn cancel(&mut self) {
        self.cancel();
    }
}

fn error(message: &str) -> io::Error {
    io::Error::other(message)
}

fn record_completion(
    endpoint: &impl BulkIo,
    completion: &Completion,
    row: &mut Value,
    maximum: usize,
) {
    row["completion"] = json!({"actual":completion.actual_len,
        "status":format!("{:?}",completion.status),"buffer_length":completion.buffer.len()});
    row["pending_after"] = json!(endpoint.pending());
    if endpoint.direction() == Direction::In {
        if completion.buffer.len() <= maximum {
            row["received_data"] = json!(&completion.buffer[..]);
        } else {
            row["data_omitted_invalid_buffer_length"] = json!(true);
        }
    }
}

fn exchange_io(
    maximum: usize,
    endpoint: &mut impl BulkIo,
    buffer: Buffer,
    deadline: Instant,
    mut now: impl FnMut() -> Instant,
    row: &mut Value,
) -> io::Result<Completion> {
    if !row.is_object() || row.get("stage").is_some() {
        return Err(error("single fresh bulk record required; no retry"));
    }
    let incoming = endpoint.direction() == Direction::In;
    let requested = if incoming {
        buffer.requested_len()
    } else {
        buffer.len()
    };
    let mps = endpoint.max_packet_size();
    if requested == 0
        || requested > maximum
        || mps == 0
        || (incoming && requested % mps != 0)
        || endpoint.pending() != 0
        || now() >= deadline
    {
        row["stage"] = json!("NOT_SUBMITTED_BUSY_BUDGET_OR_DEADLINE");
        return Err(error(
            "not submitted: busy, geometry, budget or original deadline",
        ));
    }
    row["stage"] = json!("SUBMIT_CALLED_OUTCOME_PENDING");
    // nusb submit is the actual low-level call, not a future queued for later.
    // Recheck after receipt preparation; no caller work is queued behind it.
    let Some(_) = deadline
        .checked_duration_since(now())
        .filter(|v| !v.is_zero())
    else {
        row["stage"] = json!("NOT_SUBMITTED_ORIGINAL_DEADLINE");
        return Err(error("not submitted: original deadline"));
    };
    if let Err(error) = endpoint.submit(buffer, deadline) {
        row["stage"] = json!("NOT_SUBMITTED_OWNER_GATE");
        row["error"] = json!(error.to_string());
        return Err(error);
    }
    if endpoint.pending() != 1 {
        row["pending_after"] = json!(endpoint.pending());
        row["stage"] = json!("QUARANTINED_SUBMIT_ACCOUNTING");
        return Err(error(
            "submitted outcome uncertain: expected one pending transfer",
        ));
    }
    if let Some(completion) = endpoint.wait(deadline.saturating_duration_since(now())) {
        record_completion(endpoint, &completion, row, maximum);
        if endpoint.pending() != 0
            || completion.actual_len > requested
            || (incoming && completion.actual_len != completion.buffer.len())
        {
            row["stage"] = json!("QUARANTINED_COMPLETION_ACCOUNTING");
            return Err(error("completion accounting mismatch"));
        }
        if now() >= deadline {
            row["stage"] = json!("LATE_COMPLETION_REJECTED");
            return Err(error("completion after original deadline"));
        }
        if let Err(status) = completion.status {
            row["stage"] = json!("USB_ERROR_COMPLETION_RETAINED_NOT_SUCCESS");
            return Err(status.into());
        }
        row["stage"] = json!("USB_COMPLETION_NOT_PROTOCOL_DELIVERY");
        return Ok(completion);
    }
    // None does not cancel or return the buffer. Only take a completion while
    // the real endpoint still accounts for this operation; do not panic on an
    // inconsistent dependency by calling wait_next_complete with zero pending.
    if endpoint.pending() != 1 {
        row["pending_after"] = json!(endpoint.pending());
        row["stage"] = json!("QUARANTINED_WAIT_ACCOUNTING");
        return Err(error("deadline with unaccounted pending transfer"));
    }
    let drain_deadline = now() + DRAIN_LIMIT;
    row["cancel_requested"] = json!(true);
    endpoint.cancel();
    if let Some(completion) = endpoint.wait(drain_deadline.saturating_duration_since(now())) {
        record_completion(endpoint, &completion, row, maximum);
        if endpoint.pending() != 0
            || completion.actual_len > requested
            || (incoming && completion.actual_len != completion.buffer.len())
            || now() >= drain_deadline
        {
            row["stage"] = json!("QUARANTINED_COMPLETION_ACCOUNTING");
        } else {
            row["stage"] = json!("DEADLINE_COMPLETION_RETAINED_NOT_SUCCESS");
        }
    } else {
        row["pending_after"] = json!(endpoint.pending());
        row["stage"] = json!("QUARANTINED_UNDRAINED");
    }
    Err(error("original deadline; no retry or follow-up transfer"))
}

pub fn exchange<D: EndpointDirection>(
    endpoint: &mut OwnedBulkEndpoint<'_, D>,
    buffer: Buffer,
    deadline: Instant,
    row: &mut Value,
) -> io::Result<Completion> {
    exchange_io(
        MAX_TRANSFER_BYTES,
        endpoint,
        buffer,
        deadline,
        Instant::now,
        row,
    )
}

// HCC uses the existing lifecycle with its own finite codec budget. This never
// changes the 512-byte ROM/register probe budget, or exposes arbitrary budgets.
pub(crate) fn receive_hcc(
    endpoint: &mut OwnedBulkEndpoint<'_, nusb::transfer::In>,
    deadline: Instant,
    row: &mut Value,
) -> io::Result<Completion> {
    exchange_io(
        crate::wire::MAX_RX_BYTES,
        endpoint,
        Buffer::new(crate::wire::MAX_RX_BYTES),
        deadline,
        Instant::now,
        row,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use nusb::transfer::TransferError;
    use std::collections::VecDeque;

    // Endpoint/clock fixture only: no USB, driver, allocator-failure, lock,
    // cancellation callback or scheduling/concurrency qualification.
    enum Answer {
        Pending,
        Done(Result<(), TransferError>, usize),
    }
    struct Fixture {
        answers: VecDeque<Answer>,
        buffer: Option<Buffer>,
        incoming: bool,
        pending: usize,
        submits: usize,
        cancels: usize,
        leave_pending: bool,
        waits: Vec<Duration>,
    }
    impl Fixture {
        fn new(answers: Vec<Answer>) -> Self {
            Self {
                answers: answers.into(),
                buffer: None,
                incoming: true,
                pending: 0,
                submits: 0,
                cancels: 0,
                leave_pending: false,
                waits: vec![],
            }
        }
    }
    impl BulkIo for Fixture {
        fn direction(&self) -> Direction {
            if self.incoming {
                Direction::In
            } else {
                Direction::Out
            }
        }
        fn max_packet_size(&self) -> usize {
            512
        }
        fn pending(&self) -> usize {
            self.pending
        }
        fn submit(&mut self, buffer: Buffer, _: Instant) -> io::Result<()> {
            assert!(self.buffer.is_none());
            self.buffer = Some(buffer);
            self.pending += 1;
            self.submits += 1;
            Ok(())
        }
        fn wait(&mut self, duration: Duration) -> Option<Completion> {
            self.waits.push(duration);
            match self.answers.pop_front().expect("explicit endpoint answer") {
                Answer::Pending => None,
                Answer::Done(status, actual_len) => {
                    let mut buffer = self.buffer.take().expect("submitted buffer is returned");
                    if self.incoming {
                        buffer.extend_fill(actual_len.min(buffer.capacity()), 0x45);
                    }
                    if !self.leave_pending {
                        self.pending -= 1;
                    }
                    Some(Completion {
                        buffer,
                        actual_len,
                        status,
                    })
                }
            }
        }
        fn cancel(&mut self) {
            assert_eq!(self.pending, 1);
            self.cancels += 1;
        }
    }
    #[test]
    fn rejects_before_io_and_does_not_reuse_a_finished_record() {
        let t = Instant::now();
        for (pending, size, deadline) in [
            (0, 512, t),
            (1, 512, t + IO_LIMIT),
            (0, 513, t + IO_LIMIT),
            (0, 1024, t + IO_LIMIT),
            (0, 4, t + IO_LIMIT),
            (0, 0, t + IO_LIMIT),
        ] {
            let mut ep = Fixture::new(vec![Answer::Done(Ok(()), 4)]);
            ep.pending = pending;
            let mut row = json!({});
            assert!(
                exchange_io(
                    MAX_TRANSFER_BYTES,
                    &mut ep,
                    Buffer::new(size),
                    deadline,
                    || t,
                    &mut row
                )
                .is_err()
            );
            assert_eq!((ep.submits, ep.cancels), (0, 0));
            let saved = row.clone();
            assert!(
                exchange_io(
                    MAX_TRANSFER_BYTES,
                    &mut ep,
                    Buffer::new(512),
                    t + IO_LIMIT,
                    || t,
                    &mut row
                )
                .is_err()
            );
            assert_eq!(row, saved);
        }
        let mut clock = vec![t, t + IO_LIMIT].into_iter();
        let mut ep = Fixture::new(vec![]);
        let mut row = json!({});
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::new(512),
                t + IO_LIMIT,
                || clock.next().unwrap(),
                &mut row
            )
            .is_err()
        );
        assert_eq!(ep.submits, 0);
        assert_eq!(row["stage"], "NOT_SUBMITTED_ORIGINAL_DEADLINE");
    }
    #[test]
    fn timely_completion_returns_the_owned_buffer_and_never_protocol_credit() {
        let t = Instant::now();
        let mut ep = Fixture::new(vec![Answer::Done(Ok(()), 4)]);
        let mut row = json!({});
        let c = exchange_io(
            MAX_TRANSFER_BYTES,
            &mut ep,
            Buffer::new(512),
            t + IO_LIMIT,
            || t,
            &mut row,
        )
        .unwrap();
        assert_eq!(c.buffer.len(), 4);
        assert_eq!(c.actual_len, 4);
        assert_eq!((ep.submits, ep.cancels, ep.pending), (1, 0, 0));
        assert_eq!(row["stage"], "USB_COMPLETION_NOT_PROTOCOL_DELIVERY");
        assert!(ep.buffer.is_none());
    }
    #[test]
    fn failed_partial_out_is_retained_without_turning_buffer_length_into_delivery() {
        let t = Instant::now();
        let mut ep = Fixture::new(vec![Answer::Done(Err(TransferError::Disconnected), 2)]);
        ep.incoming = false;
        let mut row = json!({});
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::from(vec![1; 18]),
                t + IO_LIMIT,
                || t,
                &mut row
            )
            .is_err()
        );
        assert_eq!(row["completion"]["actual"], 2);
        assert_eq!(row["completion"]["buffer_length"], 18);
        assert!(row.get("received_data").is_none());
        assert_eq!(row["stage"], "USB_ERROR_COMPLETION_RETAINED_NOT_SUCCESS");
    }
    #[test]
    fn timeout_cancel_completion_remains_failure_even_if_completion_succeeded() {
        for status in [
            Ok(()),
            Err(TransferError::Cancelled),
            Err(TransferError::Fault),
        ] {
            let t = Instant::now();
            let mut ep = Fixture::new(vec![Answer::Pending, Answer::Done(status, 3)]);
            let mut row = json!({});
            assert!(
                exchange_io(
                    MAX_TRANSFER_BYTES,
                    &mut ep,
                    Buffer::new(512),
                    t + IO_LIMIT,
                    || t,
                    &mut row
                )
                .is_err()
            );
            assert_eq!((ep.submits, ep.cancels, ep.pending), (1, 1, 0));
            assert_eq!(row["completion"]["actual"], 3);
            assert_eq!(row["stage"], "DEADLINE_COMPLETION_RETAINED_NOT_SUCCESS");
            assert!(ep.buffer.is_none());
        }
    }
    #[test]
    fn undrained_or_inconsistent_endpoint_is_quarantined_without_a_retry() {
        let t = Instant::now();
        let mut ep = Fixture::new(vec![Answer::Pending, Answer::Pending]);
        let mut row = json!({});
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::new(512),
                t + IO_LIMIT,
                || t,
                &mut row
            )
            .is_err()
        );
        assert_eq!((ep.submits, ep.cancels, ep.pending), (1, 1, 1));
        assert!(ep.buffer.is_some());
        assert_eq!(row["stage"], "QUARANTINED_UNDRAINED");
        let saved = row.clone();
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::new(512),
                t + IO_LIMIT,
                || t,
                &mut row
            )
            .is_err()
        );
        assert_eq!(row, saved);
        assert_eq!(ep.submits, 1);
        let mut ep = Fixture::new(vec![Answer::Done(Ok(()), 4)]);
        ep.leave_pending = true;
        let mut row = json!({});
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::new(512),
                t + IO_LIMIT,
                || t,
                &mut row
            )
            .is_err()
        );
        assert_eq!(row["stage"], "QUARANTINED_COMPLETION_ACCOUNTING");
    }
    #[test]
    fn late_and_oversized_completions_cannot_become_success() {
        let t = Instant::now();
        let mut ep = Fixture::new(vec![Answer::Done(Ok(()), 4)]);
        let mut row = json!({});
        let mut clock = vec![t, t, t, t + IO_LIMIT].into_iter();
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::new(512),
                t + IO_LIMIT,
                || clock.next().unwrap(),
                &mut row
            )
            .is_err()
        );
        assert_eq!(row["stage"], "LATE_COMPLETION_REJECTED");
        let mut ep = Fixture::new(vec![Answer::Done(Ok(()), 513)]);
        let mut row = json!({});
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::new(512),
                t + IO_LIMIT,
                || t,
                &mut row
            )
            .is_err()
        );
        assert_eq!(row["stage"], "QUARANTINED_COMPLETION_ACCOUNTING");
    }

    #[test]
    fn cleanup_has_its_own_original_bound_and_malformed_receipts_never_submit() {
        let t = Instant::now();
        let mut ep = Fixture::new(vec![
            Answer::Pending,
            Answer::Done(Err(TransferError::Cancelled), 0),
        ]);
        let mut row = json!({});
        let mut clock = vec![
            t,
            t,
            t,
            t + IO_LIMIT,
            t + IO_LIMIT,
            t + IO_LIMIT + DRAIN_LIMIT,
        ]
        .into_iter();
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::new(512),
                t + IO_LIMIT,
                || clock.next().unwrap(),
                &mut row
            )
            .is_err()
        );
        assert_eq!((ep.submits, ep.cancels, ep.pending), (1, 1, 0));
        assert_eq!(row["stage"], "QUARANTINED_COMPLETION_ACCOUNTING");
        for mut row in [json!(null), json!([]), json!("not a receipt")] {
            let mut ep = Fixture::new(vec![]);
            assert!(
                exchange_io(
                    MAX_TRANSFER_BYTES,
                    &mut ep,
                    Buffer::new(512),
                    t + IO_LIMIT,
                    || t,
                    &mut row
                )
                .is_err()
            );
            assert_eq!(ep.submits, 0);
        }
    }

    #[test]
    fn wait_budgets_consume_submit_and_cancel_time_without_resetting_deadlines() {
        let t = Instant::now();
        let mut ep = Fixture::new(vec![
            Answer::Pending,
            Answer::Done(Err(TransferError::Cancelled), 0),
        ]);
        let mut row = json!({});
        let mut clock = vec![
            t,
            t + Duration::from_millis(100),
            t + Duration::from_millis(500),
            t + IO_LIMIT,
            t + IO_LIMIT + Duration::from_millis(250),
            t + IO_LIMIT + Duration::from_millis(500),
        ]
        .into_iter();
        assert!(
            exchange_io(
                MAX_TRANSFER_BYTES,
                &mut ep,
                Buffer::new(512),
                t + IO_LIMIT,
                || clock.next().unwrap(),
                &mut row
            )
            .is_err()
        );
        assert_eq!(
            ep.waits,
            [Duration::from_millis(1500), Duration::from_millis(750)]
        );
        assert_eq!(row["stage"], "DEADLINE_COMPLETION_RETAINED_NOT_SUCCESS");
        assert_eq!((ep.submits, ep.cancels, ep.pending), (1, 1, 0));
    }
}
