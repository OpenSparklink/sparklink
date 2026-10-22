//! Thin Managed caller; Runtime owns state, credit and physical obligations.
use crate::state::SharedState;
use slk_protocol::{SleLinkInfo, SleLinkQueryResult, SleLinkQuerySubmit};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use std::time::{Duration, Instant};
fn failed(value: impl ToString) -> zbus::fdo::Error {
    zbus::fdo::Error::Failed(value.to_string())
}

/// A cancelled RPC signals its bounded blocking task. The task keeps the
/// actual fd/resource permit until exit; author cancellation is not USB drain.
struct RpcLifetime(Arc<AtomicBool>);
impl Drop for RpcLifetime {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}
struct Author {
    fd: Arc<slk_native::Adapter>,
    request: SleLinkQuerySubmit,
}
impl Drop for Author {
    fn drop(&mut self) {
        let mut request = SleLinkQuerySubmit {
            seq: 0,
            action: 2,
            ..self.request
        };
        if let Err(error) = self.fd.link_query_submit(&mut request) {
            tracing::debug!(%error,request_id=request.request_id,"link observation author withdrawal;not physical cleanup");
        }
    }
}
fn matches(value: &SleLinkQueryResult, request: &SleLinkQuerySubmit) -> bool {
    value.deadline_monotonic_ns == request.deadline_monotonic_ns
        && value.generation == request.generation
        && value.lease_epoch == request.lease_epoch
        && value.request_id == request.request_id
        && value.lifetime == request.lifetime
        && value.handle == request.handle
        && value.role == request.role
        && value.address_type == request.address_type
        && value.address == request.address
        && value.kind == request.kind
}

pub(crate) async fn read(
    state: &SharedState,
    generation: u64,
    reference: SleLinkInfo,
    kind: u8,
    original: Instant,
    deadline_monotonic_ns: u64,
) -> zbus::fdo::Result<slk_contract::link_query::Observation> {
    if !matches!(kind, 1 | 2) {
        return Err(zbus::fdo::Error::InvalidArgs(
            "kind1RSSI/2PHY required".into(),
        ));
    }
    let (fd, lease, slots) = {
        let s = state.lock().await;
        if !s.present || s.controller.generation != generation {
            return Err(failed("retired controller"));
        }
        (
            s.native_control
                .clone()
                .ok_or_else(|| failed("native control unavailable"))?,
            s.native_lease
                .clone()
                .ok_or_else(|| failed("management unavailable"))?,
            s.link_query_slots.clone(),
        )
    };
    let permit = slots
        .try_acquire_owned()
        .map_err(|_| failed("controller observation budget busy"))?;
    let mut authority = lease
        .try_lock_owned()
        .map_err(|_| failed("management handoff busy"))?;
    if !authority.accepting {
        return Err(failed("management withdrawn"));
    }
    let epoch = authority
        .token
        .ok_or_else(|| failed("management unavailable"))?;
    authority.connection_id = authority
        .connection_id
        .checked_add(1)
        .ok_or_else(|| failed("control request IDs exhausted"))?;
    let id = authority.connection_id;
    let remaining = original
        .saturating_duration_since(Instant::now())
        .as_nanos()
        .div_ceil(1_000_000);
    if remaining == 0 {
        return Err(failed("link observation original deadline"));
    }
    let request = SleLinkQuerySubmit {
        version: 1,
        action: 1,
        deadline_monotonic_ns,
        generation,
        lease_epoch: epoch,
        request_id: id,
        lifetime: reference.lifetime,
        handle: reference.handle,
        role: reference.role,
        address_type: reference.address_type,
        address: reference.address,
        kind,
        timeout_ms: remaining.min(5000) as u32,
        ..Default::default()
    };
    let cancelled = Arc::new(AtomicBool::new(false));
    let _rpc = RpcLifetime(cancelled.clone());
    let task = tokio::task::spawn_blocking(move || -> slk_native::Result<SleLinkQueryResult> {
        let _permit = permit;
        if cancelled.load(Ordering::Acquire) || Instant::now() >= original {
            return Err(slk_native::Error::Timeout);
        }
        let mut author = Author { fd, request };
        // Admission only: do not hold the lease guard across the reply wait.
        // Runtime revalidates the epoch at the actual atomic USB submission.
        let admitted = author.fd.link_query_submit(&mut author.request);
        drop(authority);
        admitted?;
        loop {
            if cancelled.load(Ordering::Acquire) || Instant::now() >= original {
                return Err(slk_native::Error::Timeout);
            }
            let result = author
                .fd
                .link_query_result(generation, author.request.seq, id)?
                .ok_or(slk_native::Error::InvalidParam(
                    "link observation result missing",
                ))?;
            if !matches(&result, &request) {
                return Err(slk_native::Error::InvalidParam(
                    "link observation scope changed",
                ));
            }
            if result.state != 1 {
                return Ok(result);
            }
            // Bounded control-result polling, not data-path scheduling.
            std::thread::sleep(Duration::from_millis(1));
        }
    });
    let value = tokio::time::timeout_at(tokio::time::Instant::from_std(original), task)
        .await
        .map_err(|_| failed("link observation original deadline"))?
        .map_err(failed)?
        .map_err(|e| match e {
            slk_native::Error::Ioctl(nix::errno::Errno::ENOTTY | nix::errno::Errno::EOPNOTSUPP) => {
                zbus::fdo::Error::NotSupported("typed link observation unavailable".into())
            }
            _ => failed(e),
        })?;
    Ok(slk_contract::link_query::Observation {
        generation: value.generation,
        lifetime: value.lifetime,
        handle: value.handle,
        role: value.role,
        address_type: value.address_type,
        address: crate::dbus_iface::format_addr(&reference.address),
        request_id: value.request_id,
        deadline_monotonic_ns: value.deadline_monotonic_ns,
        kind: value.kind,
        state: value.state,
        error: value.error,
        status: value.status,
        flags: value.flags,
        data: value.data[..usize::from(value.data_len)].to_vec(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn result_scope_never_uses_handle_as_lifetime_or_authority() {
        let r = SleLinkQuerySubmit {
            generation: 1,
            lease_epoch: 2,
            request_id: 3,
            lifetime: 4,
            handle: 5,
            kind: 1,
            address: [1; 6],
            ..Default::default()
        };
        let v = SleLinkQueryResult {
            generation: 1,
            lease_epoch: 2,
            request_id: 3,
            lifetime: 4,
            handle: 5,
            kind: 1,
            address: [1; 6],
            ..Default::default()
        };
        assert!(matches(&v, &r));
        for bad in [
            SleLinkQueryResult { generation: 2, ..v },
            SleLinkQueryResult {
                lease_epoch: 3,
                ..v
            },
            SleLinkQueryResult { request_id: 4, ..v },
            SleLinkQueryResult { lifetime: 5, ..v },
            SleLinkQueryResult { role: 1, ..v },
            SleLinkQueryResult {
                address: [2; 6],
                ..v
            },
            SleLinkQueryResult { kind: 2, ..v },
        ] {
            assert!(!matches(&bad, &r));
        }
    }
    #[test]
    fn rpc_drop_notifies_worker_without_claiming_physical_cleanup() {
        let flag = Arc::new(AtomicBool::new(false));
        {
            let _scope = RpcLifetime(flag.clone());
            assert!(!flag.load(Ordering::Acquire));
        }
        assert!(flag.load(Ordering::Acquire));
    }
}
