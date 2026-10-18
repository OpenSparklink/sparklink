/// SparkLink ioctl magic number: 'S' (0x53)
pub const SL_MAGIC: u8 = b'S';

nix::ioctl_readwrite!(
    sl_connection_security,
    SL_MAGIC,
    0xd6,
    slk_protocol::SleConnectionSecurity
);

// ----- Core registration and explicit File affinity -----

// Removed unpublished no-op registration commands 0x01/0x02.
nix::ioctl_read!(sl_dev_info, SL_MAGIC, 0x04, slk_protocol::SciDevInfo);

nix::ioctl_read!(sl_dev_list, SL_MAGIC, 0x06, u16);
nix::ioctl_write_ptr!(sl_dev_select, SL_MAGIC, 0x07, i16);

nix::ioctl_readwrite!(
    sl_registration_snapshot,
    SL_MAGIC,
    0x9f,
    slk_protocol::SleRegistrationSnapshot
);

// ----- DLI Controller (0x80 - 0x86) -----

nix::ioctl_none!(sl_dli_reset, SL_MAGIC, 0x83);

nix::ioctl_readwrite!(
    sl_controller_event_get,
    SL_MAGIC,
    0x87,
    slk_protocol::SleControllerEventQuery
);

// ----- Measurement (0xC0 - 0xC3) -----

// Versioned per-registration typed discovery. Submit has no output copy.
nix::ioctl_write_ptr!(
    sl_discovery_submit,
    SL_MAGIC,
    0x88,
    slk_protocol::SleDiscoverySubmit
);
nix::ioctl_readwrite!(
    sl_discovery_result,
    SL_MAGIC,
    0x89,
    slk_protocol::SleDiscoveryResult
);

nix::ioctl_readwrite!(
    sl_controller_snapshot,
    SL_MAGIC,
    0x8a,
    slk_protocol::SleControllerSnapshot
);

nix::ioctl_readwrite!(
    sl_management_acquire,
    SL_MAGIC,
    0x8b,
    slk_protocol::SleManagementRequest
);
nix::ioctl_write_ptr!(
    sl_management_release,
    SL_MAGIC,
    0x8c,
    slk_protocol::SleManagementRequest
);
nix::ioctl_readwrite!(
    sl_management_query,
    SL_MAGIC,
    0x8d,
    slk_protocol::SleManagementQuery
);
nix::ioctl_readwrite!(sl_snoop_get, SL_MAGIC, 0x8e, slk_protocol::SleSnoopQuery);

nix::ioctl_readwrite!(
    sl_discovery_timing,
    SL_MAGIC,
    0x8f,
    slk_protocol::SleDiscoveryTiming
);

nix::ioctl_readwrite!(
    sl_diagnostic_result,
    SL_MAGIC,
    0xd0,
    slk_protocol::SleDiagnosticResult
);

nix::ioctl_readwrite!(
    sl_diagnostic_submit,
    SL_MAGIC,
    0xd1,
    slk_protocol::SleDiagnosticSubmit
);

// Unpublished typed Native connection; raw DLI mutation stays unsupported.
nix::ioctl_write_ptr!(
    sl_connection_submit,
    SL_MAGIC,
    0x9c,
    slk_protocol::SleConnectionSubmit
);
nix::ioctl_readwrite!(
    sl_connection_result,
    SL_MAGIC,
    0x9d,
    slk_protocol::SleConnectionResult
);
nix::ioctl_readwrite!(
    sl_link_snapshot,
    SL_MAGIC,
    0x9e,
    slk_protocol::SleLinkSnapshot
);

// Native Session negotiation; original Managed File, deadlines and command credit.
nix::ioctl_write_ptr!(
    sl_security_negotiation_submit,
    SL_MAGIC,
    0xd2,
    slk_protocol::SleSecurityNegotiationSubmit
);
nix::ioctl_readwrite!(
    sl_security_negotiation_result,
    SL_MAGIC,
    0xd3,
    slk_protocol::SleSecurityNegotiationResult
);

// Local author withdrawal, original Managed File and CAP_NET_ADMIN required.
nix::ioctl_write_ptr!(
    sl_security_negotiation_cancel,
    SL_MAGIC,
    0xd4,
    slk_protocol::SleSecurityNegotiationCancel
);

// Original Managed File, admin and original numeric prompt required.
nix::ioctl_write_ptr!(
    sl_security_numeric_confirm,
    SL_MAGIC,
    0xd5,
    slk_protocol::SleSecurityNumericConfirm
);
