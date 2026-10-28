//! Language views over the existing Rust Owned registration, not manager
//! staging, a database, callback policy or another protocol Engine.
use crate::{
    ffi_client::{SlkClient, SlkControllerId, controller_input},
    ssap::local::{EntryRequirements, ServiceRegistration},
    sync_client::{Deadline, SyncClient},
};
use std::{ffi::c_int, sync::Arc};

/// Inline bounded input. Only uuid[0..uuid_length] and value[0..value_length]
/// are meaningful. Initialize the entire struct; reserved and tail must be zero.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SlkServiceProperty {
    pub operations: u32,
    pub access: u32,
    pub value_length: u16,
    pub uuid_length: u8,
    pub reserved: [u8; 5],
    pub uuid: [u8; 16],
    pub value: [u8; 2042],
    pub tail: [u8; 2],
}
/// A distinct method definition; access bits1/2/4 mean encryption,
/// authentication and explicit local approval. No property operation mask.
/// Initialize the entire object; reserved bytes must be zero.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SlkServiceMethod {
    pub access: u32,
    pub uuid_length: u8,
    pub reserved: [u8; 3],
    pub uuid: [u8; 16],
}
/// Immutable local receipt, not remote publication, Ready or authorization.
/// Handles are properties first, then methods; only their combined count is meaningful.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SlkServiceReceipt {
    pub controller: SlkControllerId,
    pub start: u16,
    pub end: u16,
    pub property_count: u16,
    pub method_count: u16,
    pub handles: [u16; 64],
}
/// Retains the original caller executor. Explicit unregister and local free
/// are separate; free does not silently withdraw or disconnect anything.
pub struct SlkLocalService {
    pub(crate) registration: Arc<tokio::sync::Mutex<ServiceRegistration>>,
    receipt: SlkServiceReceipt,
    pub(crate) executor: Arc<SyncClient>,
    pub(crate) providers: Arc<crate::ssap::provider::frontend::RegistrationScope>,
    pub(crate) approvals: Option<Arc<crate::ssap::authorization::inbox::Queue>>,
}
impl Drop for SlkLocalService {
    fn drop(&mut self) {
        self.providers.stop();
        if let Some(queue) = &self.approvals {
            queue.stop();
        }
    }
}
fn input_property(
    p: &SlkServiceProperty,
) -> Result<slk_contract::ssap::local::PropertyDefinition, i32> {
    if p.reserved != [0; 5] || p.tail != [0; 2] || !matches!(p.uuid_length, 2 | 16) {
        return Err(nix::libc::EINVAL);
    }
    if usize::from(p.value_length) > p.value.len() {
        return Err(nix::libc::EMSGSIZE);
    }
    let uuid = &p.uuid[..usize::from(p.uuid_length)];
    if !uuid.iter().any(|b| *b != 0) {
        return Err(nix::libc::EINVAL);
    }
    let ops =
        slk_protocol::SsapOperations::from_bits(p.operations).map_err(|_| nix::libc::EINVAL)?;
    let access = slk_protocol::ssap::access::SsapAccess::from_bits(p.access)
        .map_err(|_| nix::libc::EINVAL)?;
    if !slk_protocol::ssap::client_config::supported_owned(ops, true) {
        return Err(nix::libc::EOPNOTSUPP);
    }
    Ok((
        uuid.to_vec(),
        ops.bits(),
        access.bits(),
        p.value[..usize::from(p.value_length)].to_vec(),
    ))
}

/// Register one caller-owned service through the sole Rust LocalServices API.
/// uuid length2/16 with a nonzero byte; properties1..64, values0..2042. Only
/// READ/WRITE_NO_RSP/WRITE_WITH_RSP and owned NOTIFY/INDICATE+CLIENT_CFG_WR are supported.
/// Update capabilities require authorization=1; CPCD write also requires a
/// genuinely authenticated Native Session,not this registration receipt.
/// authorization=0 has no policy inbox and
/// refuses local authorization bits;1 requires explicit application decisions
/// via the bounded inbox. Unknown modes EOPNOTSUPP;never automatic approval.
/// A local receipt is not remote discovery/publication or peer delivery.
/// deadline_ns is original absolute CLOCK_MONOTONIC, future <=30s. No retry or
/// fallback.0/-errno; output unchanged on error. Timeout/lost receipt can leave
/// a registration until actual caller exit; neither timeout nor free proves
/// removal. Other derived objects can keep that caller alive after Client close.
/// # Safety
/// Client/controller/uuid/properties are live immutable initialized regions;
/// properties has count aligned elements. Output is exclusive aligned writable,
/// nonaliasing inputs. No concurrent Client close or use across fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_register_local_service(
    client: *const SlkClient,
    controller: *const SlkControllerId,
    uuid: *const u8,
    uuid_length: usize,
    properties: *const SlkServiceProperty,
    count: usize,
    authorization: u32,
    deadline_ns: u64,
    output: *mut *mut SlkLocalService,
) -> c_int {
    unsafe {
        slk_client_register_local_entries(
            client,
            controller,
            uuid,
            uuid_length,
            properties,
            count,
            std::ptr::null(),
            0,
            authorization,
            deadline_ns,
            output,
        )
    }
}

/// Register properties and/or distinct methods through the same owner and
/// absolute deadline. Combined count1..64; receipt orders properties then methods.
/// Authorization rules and uncertainty are identical to property registration.
/// Method access is0..7; approval requirements cannot be disabled.0/-errno.
/// # Safety
/// Same as slk_client_register_local_service. Each nonempty input array is live,
/// initialized and aligned for its count; NULL is allowed only for an empty array.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_register_local_entries(
    client: *const SlkClient,
    controller: *const SlkControllerId,
    uuid: *const u8,
    uuid_length: usize,
    properties: *const SlkServiceProperty,
    count: usize,
    methods: *const SlkServiceMethod,
    method_count: usize,
    authorization: u32,
    deadline_ns: u64,
    output: *mut *mut SlkLocalService,
) -> c_int {
    if client.is_null()
        || output.is_null()
        || uuid.is_null()
        || (properties.is_null() && count != 0)
        || (methods.is_null() && method_count != 0)
        || !matches!(uuid_length, 2 | 16)
        || !count
            .checked_add(method_count)
            .is_some_and(|n| (1..=64).contains(&n))
    {
        return -nix::libc::EINVAL;
    }
    let result = (|| {
        let id = unsafe { controller_input(controller) }?;
        let uuid = unsafe { std::slice::from_raw_parts(uuid, uuid_length) }.to_vec();
        if !uuid.iter().any(|b| *b != 0) {
            return Err(nix::libc::EINVAL);
        }
        let properties = if count == 0 {
            &[]
        } else {
            unsafe { std::slice::from_raw_parts(properties, count) }
        };
        let definitions = properties
            .iter()
            .map(input_property)
            .collect::<Result<Vec<_>, _>>()?;
        let methods = if method_count == 0 {
            &[]
        } else {
            unsafe { std::slice::from_raw_parts(methods, method_count) }
        };
        let methods = methods
            .iter()
            .map(|m| {
                if m.reserved != [0; 3] || !matches!(m.uuid_length, 2 | 16) {
                    return Err(nix::libc::EINVAL);
                }
                let uuid = &m.uuid[..usize::from(m.uuid_length)];
                if !uuid.iter().any(|b| *b != 0) {
                    return Err(nix::libc::EINVAL);
                }
                let access = slk_protocol::ssap::access::MethodAccess::from_bits(m.access)
                    .map_err(|_| nix::libc::EINVAL)?;
                Ok((uuid.to_vec(), access.bits()))
            })
            .collect::<Result<Vec<_>, i32>>()?;
        let deadline = Deadline::from_monotonic_ns(deadline_ns)?;
        let original = deadline.request()?;
        let executor = unsafe { &*client }.inner.clone();
        let mut requirements = definitions
            .iter()
            .map(|p| {
                Ok(EntryRequirements::Property(
                    slk_protocol::SsapOperations::from_bits(p.1).map_err(|_| nix::libc::EINVAL)?,
                    slk_protocol::ssap::access::SsapAccess::from_bits(p.2)
                        .map_err(|_| nix::libc::EINVAL)?,
                ))
            })
            .collect::<Result<Vec<_>, i32>>()?;
        requirements.extend(methods.iter().map(|(_, bits)| {
            EntryRequirements::Method(
                slk_protocol::ssap::access::MethodAccess::from_bits(*bits)
                    .expect("validated method access"),
            )
        }));
        let approvals = match authorization {
            0 if requirements.iter().any(|p| p.needs_local_authorization()) => {
                return Err(nix::libc::EOPNOTSUPP);
            }
            0 => None,
            1 => Some(executor.authorizers().reserve(id, &requirements)?),
            _ => return Err(nix::libc::EOPNOTSUPP),
        };
        let policy = approvals.clone();
        let registration = executor.call(deadline, move |caller| async move {
            let view = caller.controller(&id.path()).await?;
            let registration = view
                .local_services()
                .register_entries(
                    uuid,
                    definitions,
                    methods,
                    zbus::zvariant::OwnedObjectPath::try_from(if policy.is_some() {
                        crate::ssap::authorization::inbox::PATH
                    } else {
                        "/"
                    })
                    .expect("constant object path"),
                    original,
                )
                .await?;
            if let Some(queue) = &policy
                && let Err(error) = queue.bind(&registration.receipt().2)
            {
                // Do not invent a cleanup deadline or acknowledge rollback.
                // Local policy stays closed;the original caller's eventual
                // bus-owner exit handles uncertain remote registration.
                return Err(crate::ApplicationError::Io(
                    std::io::Error::from_raw_os_error(error),
                ));
            }
            Ok(registration)
        })?;
        let value = registration.receipt();
        let mut receipt = SlkServiceReceipt {
            controller: SlkControllerId {
                generation: id.generation,
                index: id.index,
                reserved: [0; 6],
            },
            start: value.0,
            end: value.1,
            property_count: count as u16,
            method_count: method_count as u16,
            handles: [0; 64],
        };
        receipt.handles[..value.2.len()].copy_from_slice(&value.2);
        Ok(SlkLocalService {
            providers: registration.provider_scope(),
            registration: Arc::new(tokio::sync::Mutex::new(registration)),
            receipt,
            executor,
            approvals,
        })
    })();
    match result {
        Ok(value) => {
            unsafe { output.write(Box::into_raw(Box::new(value))) };
            0
        }
        Err(error) => -error,
    }
}

/// Copy the immutable local receipt, even after unregister. This never checks
/// current owner/Ready or mints permission; it performs no RPC.
/// # Safety
/// view is live immutable; output is exclusive aligned and nonaliasing.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_receipt(
    view: *const SlkLocalService,
    output: *mut SlkServiceReceipt,
) -> c_int {
    if view.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    unsafe { output.write((*view).receipt) };
    0
}

/// Observe this owner's current local value using the existing Rust receipt.
/// capacity0..2042. ENOBUFS sets required length and leaves buffer untouched;
/// no truncation. A later read may observe a new value, not a cached size query.
/// Other errors leave outputs unchanged. Original deadline includes local queue,
/// receipt mutex and RPC. This is not remote delivery or authorization.
/// # Safety
/// view live; length exclusive aligned; buffer nonaliasing writable capacity
/// bytes,null only for0. No concurrent free; do not use after fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_read(
    view: *const SlkLocalService,
    handle: u16,
    buffer: *mut u8,
    capacity: usize,
    length: *mut usize,
    deadline_ns: u64,
) -> c_int {
    if view.is_null() || length.is_null() || capacity > 2042 || (capacity != 0 && buffer.is_null())
    {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let result = (|| {
        let deadline = Deadline::from_monotonic_ns(deadline_ns)?;
        let original = deadline.request()?;
        let registration = view.registration.clone();
        view.executor.call(deadline, move |_| async move {
            registration.lock().await.read_local(handle, original).await
        })
    })();
    match result {
        Ok(value) if value.len() > 2042 => -nix::libc::EOVERFLOW,
        Ok(value) => {
            unsafe { length.write(value.len()) };
            if value.len() > capacity {
                return -nix::libc::ENOBUFS;
            }
            if !value.is_empty() {
                unsafe { std::ptr::copy_nonoverlapping(value.as_ptr(), buffer, value.len()) };
            }
            0
        }
        Err(error) => -error,
    }
}

/// Replace this owner's local property value,0..2042 bytes,without truncation.
/// Success acknowledges local commit only,not publication/notification/delivery.
/// Timeout/lost reply may follow commit;never automatically retry. Peer operation
/// and security permissions are unchanged. Foreign/inactive handles are refused.
/// # Safety
/// view live;value immutable initialized length bytes,null only for0;no concurrent
/// free,no use across fork. Inputs remain live throughout the call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_replace(
    view: *const SlkLocalService,
    handle: u16,
    value: *const u8,
    length: usize,
    deadline_ns: u64,
) -> c_int {
    if view.is_null() || handle == 0 || length > 2042 || (length != 0 && value.is_null()) {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let result = (|| {
        let deadline = Deadline::from_monotonic_ns(deadline_ns)?;
        let original = deadline.request()?;
        let value = if length == 0 {
            Vec::new()
        } else {
            unsafe { std::slice::from_raw_parts(value, length) }.to_vec()
        };
        let registration = view.registration.clone();
        view.executor.call(deadline, move |_| async move {
            registration
                .lock()
                .await
                .replace_local(handle, value, original)
                .await
        })
    })();
    result.map_or_else(|e| -e, |()| 0)
}

/// Set this original owner's public read-only type1 description (1..244 UTF-8
/// bytes). Success is local commit only, not peer discovery or delivery. Property
/// value/permissions stay unchanged; timeout may follow commit, without retries.
/// Invalid length, invalid UTF-8/NUL, inactive or foreign handle returns EINVAL.
/// # Safety
/// view remains live without concurrent free or use across fork. description
/// is an initialized immutable length-byte region, not null, live for the call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_set_description(
    view: *const SlkLocalService,
    handle: u16,
    description: *const u8,
    length: usize,
    deadline_ns: u64,
) -> c_int {
    if view.is_null()
        || handle == 0
        || description.is_null()
        || !(1..=slk_contract::ssap::local::MAX_DESCRIPTION_BYTES).contains(&length)
    {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let result = (|| {
        let deadline = Deadline::from_monotonic_ns(deadline_ns)?;
        let original = deadline.request()?;
        let description =
            std::str::from_utf8(unsafe { std::slice::from_raw_parts(description, length) })
                .map_err(|_| nix::libc::EINVAL)?
                .to_owned();
        let registration = view.registration.clone();
        view.executor.call(deadline, move |_| async move {
            registration
                .lock()
                .await
                .set_description(handle, description, original)
                .await
        })
    })();
    result.map_or_else(|e| -e, |()| 0)
}

/// Explicitly unregister this original owner's registration. No controller stop,
/// peer disconnect, new-owner fallback or blanket removal. Timely success is the
/// original broker's local removal acknowledgement,not remote peer completion.
/// Timeout does not prove removal; the same Rust receipt keeps uncertain state.
/// # Safety
/// view live throughout; no concurrent free or use across fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_unregister(
    view: *const SlkLocalService,
    deadline_ns: u64,
) -> c_int {
    if view.is_null() {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let result = (|| {
        let deadline = Deadline::from_monotonic_ns(deadline_ns)?;
        let original = deadline.request()?;
        if let Some(queue) = &view.approvals {
            queue.stop();
        }
        view.providers.stop();
        let registration = view.registration.clone();
        view.executor.call(deadline, move |_| async move {
            registration.lock().await.unregister(original).await
        })
    })();
    match result {
        Ok(()) => 0,
        Err(error) => -error,
    }
}

/// Release this local view only,NULL allowed. Explicit unregister is separate.
/// Other references may keep the same caller/service alive. Final executor
/// release joins bounded local work; actual caller exit invokes broker cleanup.
/// # Safety
/// view NULL or one live owned pointer freed exactly once; no concurrent calls
/// or later use. Never use inherited Client/service objects after fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_free(view: *mut SlkLocalService) {
    if !view.is_null() {
        drop(unsafe { Box::from_raw(view) });
    }
}
