#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
export PATH=/bin:/usr/bin
export DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/slkbus
# The policy probe selects this address explicitly; the bus is type=system.
export DBUS_SESSION_BUS_ADDRESS=$DBUS_SYSTEM_BUS_ADDRESS
export PYTHONHOME=/usr
# The scratch guest stages the Native SONAME in /usr/lib. The host-derived
# loader may search /usr/lib64 instead; select the sealed Native image
# explicitly for pre-daemon gates too, independently of the application SDK.
export LIBSLK_NATIVE_PATH=/usr/lib/libslk_native.so.0
benchmark_trace_requested() {
    for benchmark_word do
        case "$benchmark_word" in
            ws73.benchmark_mode=rate|ws73.benchmark_mode=window|ws73.benchmark_mode=duplex|ws73.parallel_benchmark=1) return 0 ;;
        esac
    done
    return 1
}
benchmark_trace=0
if benchmark_trace_requested $(cat /proc/cmdline); then benchmark_trace=1; fi
sender_case_argument() {
    selected_sender_case=''
    sender_case_enabled=''
    for sender_word do
        case "$sender_word" in
            ws73.ssap_sender_deadline=1)
                [ -z "$sender_case_enabled" ] || return 1
                sender_case_enabled=1 ;;
            ws73.ssap_sender_case=*)
                [ -z "$selected_sender_case" ] || return 1
                selected_sender_case=${sender_word#ws73.ssap_sender_case=}
                case "$selected_sender_case" in
                    deadline|owner-after-deadline) ;;
                    *) return 1 ;;
                esac ;;
        esac
    done
    [ -n "$selected_sender_case" ] || return 0
    [ "$sender_case_enabled" = 1 ] || return 1
    printf '%s' "$selected_sender_case"
}
fail() {
    echo "WS73_TARGET_FAILURE: $*"
    for role_pid in ${parallel_role_supervisors:-}; do
        kill -TERM "$role_pid" 2>/dev/null
        wait "$role_pid"
    done
    parallel_role_supervisors=''
    if [ -n "${application_role_supervisor:-}" ]; then
        kill -TERM "$application_role_supervisor" 2>/dev/null
        wait "$application_role_supervisor"
        application_role_supervisor=''
    fi
    if [ -n "${controller_directory_supervisor:-}" ]; then
        kill -TERM "$controller_directory_supervisor" 2>/dev/null
        wait "$controller_directory_supervisor"
        controller_directory_supervisor=''
    fi
    # A failed bootstrap is still evidence. Stop our owned processes and
    # flush usbmon before shutdown, even when the ordinary shell never opened.
    if [ -n "${daemon:-}" ]; then
        kill -TERM "$daemon" 2>/dev/null
        for n in $(seq 1 100); do kill -0 "$daemon" 2>/dev/null || break; sleep 0.1; done
    fi
    # Retain queue retirement during our bounded process cleanup attempt.
    # This remains ABORTED even if a process failed to stop; no drain or Free
    # is inferred from the wait or from successfully sealing the trace.
    if [ -f /evidence/session-service/run.json ]; then
        /bin/python3 /usr/share/sparklink/tools/ws73_session_service.py abort > /evidence/session-service-abort.log 2>&1 || true
    fi
    if [ -n "${capture:-}" ]; then
        kill -INT "$capture" 2>/dev/null
        wait "$capture"; capture_exit=$?
        echo "$capture_exit" > /evidence/capture-failure-exit.txt
    fi
    mkdir -p /evidence/device-failure
    for interface in /sys/bus/usb/devices/*:*; do
        [ -f "$interface/boot_stage" ] || continue
        name=${interface##*/}
        for attribute in boot_stage boot_error warm_recovery recovery_budget failure_diagnostics runtime_transport metadata_valid native_runtime controller_information chip_information sle_address_source; do
            [ -f "$interface/$attribute" ] && cat "$interface/$attribute" > "/evidence/device-failure/$name-$attribute.txt"
        done
    done
    [ -d /evidence/application ] && dmesg > /evidence/kernel.log
    if [ -d /evidence/application ] && [ -f /sys/kernel/tracing/tracing_on ]; then
        echo 0 > /sys/kernel/tracing/tracing_on
        cat /sys/kernel/tracing/trace > /evidence/xhci-trace.log
        for stats in /sys/kernel/tracing/per_cpu/cpu*/stats; do
            cat "$stats" >> /evidence/xhci-trace-stats.txt
        done
    fi
    dmesg
    sync
    poweroff -f
}
ensure_mount() {
    if [ -r /proc/mounts ]; then
        while read -r source target kind rest; do
            [ "$target" = "$1" ] || continue
            [ "$kind" = "$2" ] || fail "unexpected filesystem on $1: $kind"
            return
        done < /proc/mounts
    fi
    mount -t "$2" none "$1" || fail "$1"
}
ensure_mount /proc proc
ensure_mount /sys sysfs
ensure_mount /dev devtmpfs
if [ -f /scratch-root-uuid ]; then
    [ "$(uname -r)" = "$(cat /expected-release)" ] || fail 'VM release mismatch'
    grep -q '^/dev/nvme0n1 / btrfs ' /proc/mounts || fail 'private NVMe/Btrfs root missing'
    [ ! -d /sys/module/sparklink_ws73_usb ] || fail 'WS73 module loaded before capture'
    [ "$(cat /proc/sys/kernel/tainted)" = 0 ] || fail 'initial VM kernel taint'
    # mkfs --rootdir preserves host uid1000. Normalize only the VM code/config
    # tree before starting any ordinary app; never expose host system paths.
    chown 0:0 / /init /native-evidence-modules.sh /native-ws73-module.sh /expected-release /scratch-root-uuid || fail 'VM root ownership'
    for directory in /bin /usr /lib /lib64 /etc; do
        [ ! -d "$directory" ] || chown -R 0:0 "$directory" || fail 'VM code ownership'
    done
    . /native-evidence-modules.sh
    ensure_mount /sys/kernel/tracing tracefs
    [ -f /sys/kernel/tracing/events/xhci-hcd/enable ] || fail 'native xHCI trace events unavailable'
    echo 1024 > /sys/kernel/tracing/buffer_size_kb || fail 'native xHCI trace buffer'
    if [ "$benchmark_trace" = 1 ]; then
        echo mono > /sys/kernel/tracing/trace_clock || fail 'benchmark monotonic trace clock'
    fi
    xhci_mode=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_xhci=/){sub(/^ws73.benchmark_xhci=/,"",$i);print $i}}' /proc/cmdline)
    case "$xhci_mode" in
        ''|on) xhci_enabled=1 ;;
        off) [ "$benchmark_trace" = 1 ] || fail 'trace comparison needs benchmark'; xhci_enabled=0 ;;
        *) fail 'one explicit xHCI mode' ;;
    esac
    echo "$xhci_enabled" > /sys/kernel/tracing/events/xhci-hcd/enable || fail 'native xHCI tracing'
    echo "$xhci_enabled" > /sys/kernel/tracing/tracing_on || fail 'native trace gate'
    xhci_cookie=$(cat /proc/sys/kernel/random/uuid) || fail 'trace observation identity'
    echo "WS73_TARGET_NATIVE_VM_ROOT: $(uname -r) NVMe/Btrfs signed-module"
fi
mount -t 9p -o trans=virtio,version=9p2000.L evidence /evidence || fail 'private evidence share'
chown 0:0 /evidence; chmod 0755 /evidence
mkdir /evidence/application; chown 1000:1002 /evidence/application; chmod 0700 /evidence/application
if grep -qw ws73.session_service=1 /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_session_service.py start > /evidence/session-service-start.log 2>&1 || fail 'Session service trace start'
fi
if [ -f /scratch-root-uuid ] && [ "$benchmark_trace" = 1 ]; then
    cat /sys/kernel/tracing/events/header_page > /evidence/benchmark-xhci-header-start.txt || fail 'trace header start'
    cat /sys/kernel/tracing/trace_clock > /evidence/benchmark-xhci-clock-start.txt || fail 'trace clock start'
    printf '{"enabled":"%s","tracing_on":"%s","tracer":"%s","buffer_kb":%s,"requested_buffer_kb":1024,"subbuffer_kb":%s,"cookie":"%s"}\n' "$(cat /sys/kernel/tracing/events/xhci-hcd/enable)" "$(cat /sys/kernel/tracing/tracing_on)" "$(cat /sys/kernel/tracing/current_tracer)" "$(cat /sys/kernel/tracing/buffer_size_kb)" "$(cat /sys/kernel/tracing/buffer_subbuf_size_kb)" "$xhci_cookie" > /evidence/benchmark-xhci-start.json || fail 'trace start readback'
    chmod 0444 /evidence/benchmark-xhci-start.json /evidence/benchmark-xhci-clock-start.txt /evidence/benchmark-xhci-header-start.txt || fail 'trace start evidence permissions'
    if [ "$xhci_enabled" = 1 ]; then echo "SLK_BENCH_BEGIN:$xhci_cookie" > /sys/kernel/tracing/trace_marker || fail 'trace begin marker'; fi
fi
for n in $(seq 1 100); do [ -c /dev/usbmon1 ] && [ -c /dev/sparklink ] && break; sleep 0.1; done
[ -c /dev/usbmon1 ] && [ -c /dev/sparklink ] || fail 'built-in usbmon/sparklink nodes'
chown 0:1000 /dev/sparklink; chmod 0660 /dev/sparklink
/bin/ssap-removed-uapi-probe > /evidence/ssap-removed-uapi-root.log 2>&1 || fail 'root retired SSAP ioctl rejection'
/bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c '/bin/ssap-removed-uapi-probe' > /evidence/application/ssap-removed-uapi-ordinary.log 2>&1 || fail 'ordinary retired SSAP ioctl rejection'
/bin/socket-type-probe > /evidence/socket-type-root.log 2>&1 || fail 'root basic datagram type contract'
/bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c '/bin/socket-type-probe' > /evidence/application/socket-type-ordinary.log 2>&1 || fail 'ordinary basic datagram type contract'
# All archive inodes are root-owned. Ordinary apps cannot alter daemon/fw/code.
/bin/tcpdump -i usbmon1 -s 0 -U -Z capture -w /evidence/ws73.pcap > /evidence/capture-stdout.txt 2> /evidence/capture-stats.txt & capture=$!
for n in $(seq 1 100); do
    [ -f /evidence/capture-stats.txt ] && grep -q 'listening on usbmon1' /evidence/capture-stats.txt && break
    kill -0 "$capture" || fail 'tcpdump startup'
    sleep 0.1
done
grep -q 'listening on usbmon1' /evidence/capture-stats.txt || fail 'capture readiness'
chmod 0600 /evidence/ws73.pcap /evidence/capture-stats.txt
cat "/proc/$capture/status" > /evidence/capture-process-status.txt || fail 'capture process credentials'
if [ -f /native-ws73-module.sh ]; then
    . /native-ws73-module.sh
    [ -d /sys/module/sparklink_ws73_usb ] || fail 'VM WS73 module missing'
    [ "$(cat /proc/sys/kernel/tainted)" = 0 ] || fail 'VM module signature/taint'
fi
/bin/dbus-daemon --config-file=/etc/dbus.conf --nofork > /evidence/dbus.log 2>&1 &
for n in $(seq 1 100); do [ -S /run/slkbus ] && break; sleep 0.1; done
[ -S /run/slkbus ] || fail 'system bus startup'
confirmed_off_arg=''
if grep -q 'ws73.managed_queue_confirmed_off=1' /proc/cmdline; then confirmed_off_arg='--confirmed-off'; fi
if grep -q 'ws73.managed_queue_ready_peer=1' /proc/cmdline; then confirmed_off_arg="$confirmed_off_arg --ready-peer"; fi
if grep -q 'ws73.managed_queue_connections=1' /proc/cmdline; then confirmed_off_arg="$confirmed_off_arg --connections"; fi
if grep -Eq 'ws73.managed_(queue|partial)_support=1' /proc/cmdline; then
    [ -f /scratch-root-uuid ] || fail 'synthetic queue scratch root'
    [ "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU ] || fail 'synthetic queue QEMU VM'
    echo 'WS73_TARGET_CAPTURE_READY'
    if grep -q 'ws73.managed_partial_support=1' /proc/cmdline; then
        grep -q 'ws73.managed_partial=1' /proc/cmdline || fail 'synthetic partial boot mode'
        ! grep -q 'ws73.managed_queue' /proc/cmdline || fail 'mixed synthetic support modes'
        support_mode=MANAGED_PARTIAL
        partial_case=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_case=/){sub(/^ws73.partial_case=/,"",$i);print $i}}' /proc/cmdline)
        partial_domain=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_domain=/){sub(/^ws73.partial_domain=/,"",$i);print $i}}' /proc/cmdline)
        partial_step=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_step=/){sub(/^ws73.partial_step=/,"",$i);print $i}}' /proc/cmdline)
        partial_step=${partial_step:-0}
        LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_management_partial.py --synthetic-support --initialization-step "$partial_step" --case "$partial_case" --domain "$partial_domain" --output /evidence/managed-partial > /evidence/managed-partial-supervisor.log 2>&1 || fail 'synthetic Managed partial support'
    else
        grep -q 'ws73.managed_queue=1' /proc/cmdline || fail 'synthetic queue boot mode'
        ! grep -q 'ws73.managed_partial' /proc/cmdline || fail 'mixed synthetic support modes'
        support_mode=MANAGED_QUEUE
        LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_management_queued.py --synthetic-support $confirmed_off_arg --output /evidence/managed-queue > /evidence/managed-queue-supervisor.log 2>&1 || fail 'synthetic Managed queue support'
    fi
    kill -INT "$capture"; wait "$capture" || fail 'synthetic queue capture sealing'
    capture=''
    dmesg > /evidence/kernel.log
    echo "WS73_TARGET_${support_mode}_SUPPORT_TAINT: $(cat /proc/sys/kernel/tainted)"
    echo "WS73_TARGET_${support_mode}_SUPPORT_FINISHED"
    sync
    poweroff -f
    while :; do sleep 60; done
fi
if grep -q 'ws73.setup_release=1' /proc/cmdline; then
    echo 'WS73_TARGET_CAPTURE_READY'
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_management_setup.py --output /evidence/setup-release > /evidence/setup-release-supervisor.log 2>&1 || fail 'untouched Setup lease release gate'
fi
if grep -q 'ws73.managed_queue=1' /proc/cmdline; then
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_management_queued.py $confirmed_off_arg --output /evidence/managed-queue > /evidence/managed-queue-supervisor.log 2>&1 || fail 'queued Managed cancellation gate'
fi
if grep -q 'ws73.managed_partial=1' /proc/cmdline; then
    selected_cleanup_arg=''
    if grep -q 'ws73.selected_domain_cleanup=1' /proc/cmdline; then selected_cleanup_arg='--selected-domain-cleanup'; fi
    if grep -q 'ws73.scan_parameter_cleanup=1' /proc/cmdline; then selected_cleanup_arg="$selected_cleanup_arg --scan-parameter-cleanup"; fi
    if grep -q 'ws73.managed_ready_peer=1' /proc/cmdline; then selected_cleanup_arg="$selected_cleanup_arg --ready-peer"; fi
    if grep -q 'ws73.ordinary_queue_eviction=1' /proc/cmdline; then selected_cleanup_arg="$selected_cleanup_arg --ordinary-queue-eviction"; fi
    if grep -q 'ws73.real_later_step=1' /proc/cmdline; then
        real_step=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_step=/){sub(/^ws73.partial_step=/,"",$i);print $i}}' /proc/cmdline)
        selected_cleanup_arg="$selected_cleanup_arg --real-later-step --initialization-step $real_step"
    fi
    partial_case=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_case=/){sub(/^ws73.partial_case=/,"",$i);print $i}}' /proc/cmdline)
    partial_domain=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_domain=/){sub(/^ws73.partial_domain=/,"",$i);print $i}}' /proc/cmdline)
    if grep -qw ws73.managed_recreate=1 /proc/cmdline; then
        resource_step=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_step=/){sub(/^ws73.partial_step=/,"",$i);print $i}}' /proc/cmdline)
        [ -n "$resource_step" ] || resource_step=0
        LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_resource_file_gate.py --case "$partial_case" --initialization-step "$resource_step" --output /evidence/managed-partial > /evidence/managed-partial-supervisor.log 2>&1 || fail 'resource File held-reply gate'
    else
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_management_partial.py $selected_cleanup_arg --case "$partial_case" --domain "$partial_domain" --output /evidence/managed-partial > /evidence/managed-partial-supervisor.log 2>&1 || fail 'partial Managed held-reply cleanup gate'
    fi
fi
# Keep untouched Setup/lease checks above address initialization. The same
# Native address setup serves ordinary applications and the pre-daemon Grant
# gate; the latter exits before daemon startup, so setup must precede it.
if grep -q 'ws73.runtime_addresses=' /proc/cmdline; then
    echo 'WS73_TARGET_CAPTURE_READY'
    (
        /bin/python3 /usr/share/sparklink/tools/ws73_runtime_address.py
        echo "$?" > /evidence/runtime-address-exit.txt
    ) 2>&1 | /bin/busybox tee /evidence/runtime-address-supervisor.log
    [ "$(cat /evidence/runtime-address-exit.txt)" = 0 ] || fail 'volatile runtime address gate'
fi
if grep -q 'ws73.connected_case=' /proc/cmdline; then
    connected_case=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.connected_case=/){sub(/^ws73.connected_case=/,"",$i);print $i}}' /proc/cmdline)
    connected_index=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.connected_index=/){sub(/^ws73.connected_index=/,"",$i);print $i}}' /proc/cmdline)
    connected_reply=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.connected_reply=/){sub(/^ws73.connected_reply=/,"",$i);print $i}}' /proc/cmdline)
    connected_reply_arg=''
    if grep -qw ws73.link_snapshot=1 /proc/cmdline; then connected_reply_arg='--link-snapshot'; fi
    if grep -qw ws73.channel_scm_rights=1 /proc/cmdline; then connected_reply_arg="$connected_reply_arg --channel-scm-rights"; fi
    if grep -qw ws73.channel_directions=1 /proc/cmdline; then connected_reply_arg="$connected_reply_arg --channel-directions"; fi
    if grep -qw ws73.channel_grant=1 /proc/cmdline; then connected_reply_arg="$connected_reply_arg --channel-grant"; fi
    if grep -qw ws73.peer_binding=1 /proc/cmdline; then connected_reply_arg="$connected_reply_arg --peer-binding"; fi
    if [ -n "$connected_reply" ]; then connected_reply_arg="--reply-hold $connected_reply"; fi
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_connected_file_gate.py $connected_reply_arg --case "$connected_case" --index "$connected_index" --output /evidence/connected-file > /evidence/connected-file-supervisor.log 2>&1 || fail 'established connection File gate'
fi
if grep -qw ws73.channel_grant=1 /proc/cmdline; then
    ! grep -qw ws73.recovery=1 /proc/cmdline || fail 'Grant gate excludes artificial recovery'
    if grep -qw ws73.session_service=1 /proc/cmdline; then
        /bin/python3 /usr/share/sparklink/tools/ws73_session_service.py finish > /evidence/session-service-finish.log 2>&1 || fail 'Session service trace finish'
    fi
    kill -INT "$capture"; wait "$capture" || fail 'Grant capture sealing'
    capture=''
    dmesg > /evidence/kernel.log
    [ "$(cat /proc/sys/kernel/tainted)" = 0 ] || fail 'Grant VM kernel taint'
    echo 'WS73_TARGET_NATIVE_VM_TAINT: 0'
    echo 'WS73_TARGET_CHANNEL_GRANT_FINISHED'
    echo 'WS73_TARGET_FINISHED'
    sync
    poweroff -f
    while :; do sleep 60; done
fi
if grep -q 'ws73.diagnostic=1' /proc/cmdline; then
    # The runner attaches the first USB owner after capture readiness. Signal
    # before the diagnostic barrier, which needs that owner before slkd starts.
    echo 'WS73_TARGET_CAPTURE_READY'
    /bin/python3 /usr/share/sparklink/tools/ws73_diagnostic_probe.py --probe /bin/diagnostic-result-probe --slkconfig /bin/slkconfig --output /evidence/diagnostic > /evidence/diagnostic-supervisor.log 2>&1 & diagnostic=$!
    for n in $(seq 1 1200); do
        [ -f /evidence/diagnostic/before-daemon.json ] && break
        kill -0 "$diagnostic" || fail 'diagnostic pre-daemon gate'
        sleep 0.1
    done
    [ -f /evidence/diagnostic/before-daemon.json ] || fail 'diagnostic pre-daemon deadline'
fi
if grep -q 'ws73.active_deadline=1' /proc/cmdline; then
    echo 'WS73_TARGET_CAPTURE_READY'
    close_arg=''
    if grep -q 'ws73.active_close=1' /proc/cmdline; then close_arg='--last-file-close'; fi
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_active_deadline.py $close_arg --output /evidence/active-deadline > /evidence/active-deadline-supervisor.log 2>&1 || fail 'active deadline retirement gate'
fi
config_args=''
if [ -f /expected-discovery-config-sha256 ]; then
    chown 0:0 /expected-discovery-config-sha256 /etc/sparklink/main.conf || fail 'frozen config ownership'
    if [ -f /expected-discovery-policies.json ]; then
        chown 0:0 /expected-discovery-policies.json || fail 'policy expectation ownership'
        chmod 0444 /expected-discovery-policies.json || fail 'policy expectation mode'
    fi
    expected=$(cat /expected-discovery-config-sha256)
    actual=$(/bin/busybox sha256sum /etc/sparklink/main.conf | awk '{print $1}')
    [ "$actual" = "$expected" ] || fail 'frozen discovery config hash'
    /bin/busybox cp /etc/sparklink/main.conf /evidence/slkd-config.conf || fail 'config evidence copy'
    /bin/slkd --check-config --config /etc/sparklink/main.conf > /evidence/discovery-config-validation.txt 2>&1 || fail 'guest config validation'
    config_args='--config /etc/sparklink/main.conf'
fi
native_return_fixture_enabled() {
    grep -qw ws73.native_return=1 /proc/cmdline ||
    grep -qw ws73.native_controller_return=initiator /proc/cmdline ||
    grep -qw ws73.native_controller_return=acceptor /proc/cmdline
}
if native_return_fixture_enabled; then
    [ -f /expected-native-return-sha256 ] || fail 'explicit Native fixture preparation required'
    chown 0:0 /usr/lib/sparklink /usr/lib/sparklink/native-return-fixture.so /expected-native-return-sha256 || fail 'Native fixture root ownership'
    chmod 0755 /usr/lib/sparklink || fail 'Native fixture directory mode'
    chmod 0555 /usr/lib/sparklink/native-return-fixture.so || fail 'Native fixture library mode'
    chmod 0444 /expected-native-return-sha256 || fail 'Native fixture expectation mode'
    actual=$(/bin/busybox sha256sum /usr/lib/sparklink/native-return-fixture.so | awk '{print $1}')
    [ "$actual" = "$(cat /expected-native-return-sha256)" ] || fail 'Native return library identity'
    /bin/python3 /usr/share/sparklink/tools/ws73_native_return.py setup || fail 'native VM-only fixture setup'
    LD_PRELOAD=/usr/lib/sparklink/native-return-fixture.so /bin/slkd $config_args -n > /evidence/slkd.log 2>&1 & daemon=$!
else
    /bin/slkd $config_args -n > /evidence/slkd.log 2>&1 & daemon=$!
fi
if ! grep -q 'ws73.runtime_addresses=' /proc/cmdline && ! grep -q 'ws73.diagnostic=1' /proc/cmdline && ! grep -q 'ws73.active_deadline=1' /proc/cmdline && ! grep -q 'ws73.setup_release=1' /proc/cmdline; then
    echo 'WS73_TARGET_CAPTURE_READY'
fi
if grep -qw ws73.early_bootstrap_fault=1 /proc/cmdline; then
    # Foreground tee drains each marker once and preserves Python's own exit;
    # no asynchronous tail startup/final-flush race can lose a QMP handshake.
    (
        /bin/python3 /usr/share/sparklink/tools/ws73_early_fault.py coordinate --slkd-pid "$daemon" < /dev/console
        echo "$?" > /evidence/early-bootstrap-exit.txt
    ) 2>&1 | /bin/busybox tee /evidence/early-bootstrap-supervisor.log
    early_exit=$(cat /evidence/early-bootstrap-exit.txt)
    [ "$early_exit" = 0 ] || fail 'actual early bootstrap fault/peer business'
    cat "/proc/$daemon/status" > /evidence/slkd-process-status.txt || fail 'early fault daemon credentials'
    kill -TERM "$daemon"; wait "$daemon"
    kill -INT "$capture"; wait "$capture" || fail 'capture final flush'
    chown 0:1000 /evidence/ws73.pcap /evidence/capture-stats.txt; chmod 0640 /evidence/ws73.pcap /evidence/capture-stats.txt
    dmesg > /evidence/kernel.log
    echo 0 > /sys/kernel/tracing/tracing_on
    cat /sys/kernel/tracing/trace > /evidence/xhci-trace.log
    [ "$(cat /proc/sys/kernel/tainted)" = 0 ] || fail 'final VM kernel taint'
    echo 'WS73_TARGET_NATIVE_VM_TAINT: 0'
    echo 'WS73_TARGET_FINISHED'
    sync; poweroff -f
    while :; do sleep 60; done
fi
last_slot=1
if grep -q 'ws73.parallel=1' /proc/cmdline; then last_slot=3; fi
for slot in $(seq 0 $last_slot); do
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py ready "$slot" || fail "independent Ready slot=$slot"
    echo "WS73_TARGET_READY: slot=$slot"
done
if grep -qw ws73.channel_daemon_crash=1 /proc/cmdline; then
    cat "/proc/$daemon/status" > /evidence/slkd-process-status.txt || fail 'original daemon credentials'
    death_index=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.channel_daemon_index=/){sub(/^ws73.channel_daemon_index=/,"",$i);print $i}}' /proc/cmdline)
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_channel_daemon_crash.py --slkd-pid "$daemon" --index "$death_index" > /evidence/channel-daemon-supervisor.log 2>&1 & death_supervisor=$!
    ticks=0
    while [ ! -f /evidence/channel-daemon-crash/armed.json ]; do
        kill -0 "$death_supervisor" || fail 'daemon fd supervisor exited before armed'
        ticks=$((ticks+1)); [ "$ticks" -lt 900 ] || fail 'daemon fd armed deadline'
        sleep 0.1
    done
    before_death=$(/bin/python3 -c 'import time;print(time.time_ns())')
    old_daemon=$daemon
    kill -KILL "$daemon" || fail 'actual daemon fd SIGKILL'
    wait "$daemon"; death_status=$?
    [ "$death_status" = 137 ] || fail 'actual daemon fd reap'
    daemon=''
    /bin/python3 -c 'import json,sys,time,os;p="/evidence/channel-daemon-crash/death.json";open(p+".tmp","w").write(json.dumps(dict(pid=int(sys.argv[1]),status=int(sys.argv[2]),before_wall_ns=int(sys.argv[3]),reaped_wall_ns=time.time_ns())));os.replace(p+".tmp",p)' "$old_daemon" "$death_status" "$before_death" || fail 'actual death receipt'
    ticks=0
    while [ ! -f /evidence/channel-daemon-crash/free.json ]; do
        kill -0 "$death_supervisor" || fail 'daemon fd supervisor exited before Free'
        ticks=$((ticks+1)); [ "$ticks" -lt 150 ] || fail 'daemon fd cleanup deadline'
        sleep 0.1
    done
    /bin/slkd $config_args -n > /evidence/slkd-successor.log 2>&1 & daemon=$!
    for slot in 0 1; do
        /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py ready "$slot" || fail 'daemon fd successor Ready'
    done
    /bin/python3 -c 'import json,sys,time,os;p="/evidence/channel-daemon-crash/successor.json";open(p+".tmp","w").write(json.dumps(dict(pid=int(sys.argv[1]),wall_ns=time.time_ns())));os.replace(p+".tmp",p)' "$daemon" || fail 'actual successor receipt'
    wait "$death_supervisor" || fail 'daemon fd supervisor'
    kill -TERM "$daemon"; wait "$daemon"; daemon=''
    kill -INT "$capture"; wait "$capture" || fail 'daemon fd capture seal'
    capture=''
    dmesg > /evidence/kernel.log
    [ "$(cat /proc/sys/kernel/tainted)" = 0 ] || fail 'daemon fd VM taint'
    echo 'WS73_TARGET_NATIVE_VM_TAINT: 0'
    cat /evidence/channel-daemon-supervisor.log
    echo 'WS73_TARGET_DAEMON_CHANNEL_FINISHED'
    echo 'WS73_TARGET_FINISHED'
    sync
    poweroff -f
    while :; do sleep 60; done
fi
if grep -q 'ws73.daemon_crash=1' /proc/cmdline; then
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py daemon-crash before "$daemon" || fail 'active crash preparation'
    old_daemon=$daemon
    kill -KILL "$daemon" || fail 'guest daemon SIGKILL'
    wait "$daemon"; killed_exit=$?
    echo "WS73_TARGET_DAEMON_CRASH_EXIT: pid=$daemon status=$killed_exit"
    [ "$killed_exit" = 137 ] || fail 'guest SIGKILL wait status'
    daemon=''
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py daemon-crash free "$old_daemon" "$killed_exit" || fail 'last-File real cleanup'
    /bin/slkd $config_args -n > /evidence/slkd-successor.log 2>&1 & daemon=$!
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py daemon-crash after "$daemon" || fail 'same-generation successor'
fi
cat "/proc/$daemon/status" > /evidence/slkd-process-status.txt || fail 'daemon process credentials'
if grep -qw ws73.ssap_service_policy=1 /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py service-policy "$daemon" || fail 'actual service-only policy gate'
fi
if grep -q 'ws73.observer_policy=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py observer-policy initial || fail 'native observer initial role gate'
fi
if grep -q 'ws73.event_copy=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_event_copy_probe.py --probe /bin/event-copy-probe --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/event-copy" || fail 'live event copy fault gate'
fi
if grep -qw ws73.application_discovery=1 /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_application_discovery.py "$daemon" > /evidence/discovery-role-supervisor.log 2>&1 & application_role_supervisor=$!
fi
if grep -qw ws73.ssap_subscription=1 /proc/cmdline; then
    if grep -qw ws73.parallel_subscription=1 /proc/cmdline; then
        parallel_role_supervisors=''
        for pair in 0 1; do
            /bin/python3 /usr/share/sparklink/tools/ws73_application_role.py "$daemon" subscription --parallel-pair "$pair" > "/evidence/subscription-role-supervisor-pair-$pair.log" 2>&1 &
            parallel_role_supervisors="$parallel_role_supervisors $!"
        done
    else
        /bin/python3 /usr/share/sparklink/tools/ws73_application_role.py "$daemon" subscription > /evidence/subscription-role-supervisor.log 2>&1 & application_role_supervisor=$!
    fi
fi
if grep -qw ws73.socket_benchmark_apps=1 /proc/cmdline; then
    if grep -qw ws73.parallel_benchmark=1 /proc/cmdline; then
        grep -qw ws73.parallel_business=1 /proc/cmdline || fail 'paired benchmark requires explicit four business mode'
        parallel_role_supervisors=''
        for pair in 0 1; do
            /bin/python3 /usr/share/sparklink/tools/ws73_application_role.py "$daemon" benchmark --parallel-pair "$pair" > "/evidence/benchmark-role-supervisor-pair-$pair.log" 2>&1 &
            parallel_role_supervisors="$parallel_role_supervisors $!"
        done
    else
        /bin/python3 /usr/share/sparklink/tools/ws73_application_role.py "$daemon" benchmark > /evidence/benchmark-role-supervisor.log 2>&1 & application_role_supervisor=$!
    fi
fi
if grep -qw ws73.application_clients=1 /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_application_role.py "$daemon" > /evidence/application-role-supervisor.log 2>&1 & application_role_supervisor=$!
fi
if grep -q 'ws73.support=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c '/bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py support-input' || fail 'ordinary serial input'
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py support || fail 'synthetic environment integration'
elif grep -q 'ws73.recovery=1' /proc/cmdline; then
    daemon_hold_arg=''
    daemon_hold_case=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.daemon_hold=/){sub(/^ws73.daemon_hold=/,"",$i);print $i}}' /proc/cmdline)
    if [ -n "$daemon_hold_case" ]; then daemon_hold_arg="--daemon-hold-case $daemon_hold_case"; fi
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_target_recovery.py $daemon_hold_arg --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/recovery-control" || fail 'artificial transport recovery control'
elif grep -q 'ws73.parallel_business=1' /proc/cmdline; then
    disconnect_arg=''
    if grep -q 'ws73.parallel_disconnect=1' /proc/cmdline; then disconnect_arg='--disconnect-isolation'; fi
    if grep -q 'ws73.parallel_burst=1' /proc/cmdline; then disconnect_arg='--burst'; fi
    if grep -q 'ws73.parallel_owned=1' /proc/cmdline; then disconnect_arg='--owned-ssap'; fi
    if grep -q 'ws73.parallel_delivery=1' /proc/cmdline; then disconnect_arg='--update-delivery'; fi
    if grep -qw ws73.parallel_subscription=1 /proc/cmdline; then disconnect_arg='--shared-subscription'; fi
    if grep -qw ws73.parallel_benchmark=1 /proc/cmdline; then disconnect_arg='--dynamic-benchmark'; fi
    shared_case=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.subscription_shared_case=/){sub(/^ws73.subscription_shared_case=/,"",$i);print $i}}' /proc/cmdline)
    if [ -n "$shared_case" ]; then
        [ "$disconnect_arg" = '--shared-subscription' ] || fail 'shared case requires shared parallel mode'
        case "$shared_case" in expiry|owner-exit|pressure) ;; *) fail 'supported explicit parallel shared case' ;; esac
        disconnect_arg="$disconnect_arg --ssap-subscription-shared-case $shared_case"
    fi
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_parallel_data.py run $disconnect_arg --ports 1-1 1-2 1-3 1-4 --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/parallel-business --policy-expectation /expected-discovery-policies.json" || fail 'four-device parallel business'
elif grep -q 'ws73.parallel=1' /proc/cmdline; then
    parallel_offset=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.parallel_offset=/){sub(/^ws73.parallel_offset=/,"",$i);print $i}}' /proc/cmdline)
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_parallel.py run --ports 1-1 1-2 1-3 1-4 --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/parallel-control --policy-expectation /expected-discovery-policies.json --second-pair-start-offset-ms ${parallel_offset:-0}" || fail 'four-device parallel control'
elif grep -q 'ws73.passthrough=1' /proc/cmdline; then
    daemon_remove_arg=''
    if grep -q 'ws73.daemon_remove=1' /proc/cmdline; then daemon_remove_arg='--daemon-cancel-remove'; fi
    connection_arg=''
    if grep -qw ws73.acb_probe=1 /proc/cmdline; then
        LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_acb_transport_probe.py > /evidence/acb-transport-supervisor.log 2>&1 & acb_supervisor=$!
    fi
    if grep -qw ws73.link_resync=1 /proc/cmdline; then
        LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_link_resync.py --slkd-pid "$daemon" > /evidence/link-resync-supervisor.log 2>&1 & resync_supervisor=$!
    fi
    if grep -q 'ws73.connection_verify=1' /proc/cmdline; then
        posture=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.connection_advertising=/){sub(/^ws73.connection_advertising=/,"",$i);print $i}}' /proc/cmdline)
        case "$posture" in fixed-t|negotiable-t) ;; *) fail 'explicit connection posture' ;; esac
        connection_arg="--connection-verify --connection-advertising $posture"
        if grep -qw ws73.link_payload_preference=reported-acb-maximum /proc/cmdline; then connection_arg="$connection_arg --link-payload-preference reported-acb-maximum"; fi
        if grep -qw ws73.link_measurements=1 /proc/cmdline; then connection_arg="$connection_arg --link-measurements"; fi
        if grep -qw ws73.application_clients=1 /proc/cmdline; then connection_arg="$connection_arg --application-client-verify"; fi
        if grep -qw ws73.application_discovery=1 /proc/cmdline; then connection_arg="$connection_arg --application-discovery-verify"; fi
        if grep -qw ws73.application_discovery_case=owner-loss /proc/cmdline; then connection_arg="$connection_arg --application-discovery-case owner-loss"; fi
        if grep -qw ws73.application_discovery_case=ttl /proc/cmdline; then connection_arg="$connection_arg --application-discovery-case ttl"; fi
        if grep -qw ws73.application_discovery_case=sdk-release /proc/cmdline; then connection_arg="$connection_arg --application-discovery-case sdk-release"; fi
        if grep -qw ws73.channel_socket=1 /proc/cmdline; then
            channel_rounds=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.channel_rounds=/){sub(/^ws73.channel_rounds=/,"",$i);print $i}}' /proc/cmdline)
            channel_bytes=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.channel_bytes=/){sub(/^ws73.channel_bytes=/,"",$i);print $i}}' /proc/cmdline)
            connection_arg="$connection_arg --channel-socket-verify --channel-socket-rounds ${channel_rounds:-4} --channel-socket-bytes ${channel_bytes:-61}"
            down_failure_observe=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.down_failure_observe=/){sub(/^ws73.down_failure_observe=/,"",$i);print $i}}' /proc/cmdline)
            case "$down_failure_observe" in
                '') ;;
                6|12) connection_arg="$connection_arg --connection-down-failure-observe-seconds $down_failure_observe" ;;
                *) fail 'invalid passive Down failure capture bound' ;;
            esac
            if grep -qw ws73.ssap_initialization=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-initialization-verify"; fi
            if grep -qw ws73.native_return=1 /proc/cmdline; then connection_arg="$connection_arg --native-return-verify"; fi
            for role in initiator acceptor; do
                if grep -qw "ws73.native_controller_return=$role" /proc/cmdline; then connection_arg="$connection_arg --native-controller-return $role"; fi
            done
            if grep -qw ws73.ssap_initialization_stage=exchange /proc/cmdline; then connection_arg="$connection_arg --ssap-initialization-stage exchange"; fi
            if grep -qw ws73.ssap_owner_lifecycle=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-owner-lifecycle-verify"; fi
            if grep -qw ws73.ssap_owner_sdk=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-owner-publisher sdk"; fi
            if grep -qw ws73.ssap_requester_lifecycle=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-requester-lifecycle-verify"; fi
            if grep -qw ws73.ssap_owned_update=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-owned-update-verify"; fi
            if grep -qw ws73.ssap_subscription=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-subscription-verify"; fi
            if grep -qw ws73.ssap_subscription_shared=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-subscription-shared-verify"; fi
            for token in $(cat /proc/cmdline); do
                case "$token" in
                    ws73.subscription_shared_case=expiry) connection_arg="$connection_arg --ssap-subscription-shared-case expiry" ;;
                    ws73.subscription_shared_case=owner-exit) connection_arg="$connection_arg --ssap-subscription-shared-case owner-exit" ;;
                    ws73.subscription_shared_case=pressure) connection_arg="$connection_arg --ssap-subscription-shared-case pressure" ;;
                    ws73.subscription_shared_case=*) echo 'invalid shared lifetime boot selector'; poweroff -f ;;
                esac
            done
            if grep -qw ws73.ssap_subscription_renewal=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-subscription-renewal-verify"; fi
            if grep -qw ws73.ssap_subscription_pressure=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-subscription-pressure-verify"; fi
            if grep -qw ws73.ssap_subscription_owner_loss=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-subscription-owner-loss-verify"; fi
            if grep -qw ws73.ssap_subscription_inflight_release=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-subscription-inflight-release-verify"; fi
            if grep -qw ws73.subscription_inflight_case=expiry /proc/cmdline; then connection_arg="$connection_arg --ssap-subscription-inflight-case expiry"; fi
            if grep -qw ws73.ssap_update_delivery=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-update-delivery-verify"; fi
            if grep -qw ws73.ssap_receive_lifecycle=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-update-lifecycle-verify"; fi
            if grep -qw ws73.ssap_sender_deadline=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-sender-deadline-verify"; fi
            sender_case=$(sender_case_argument $(cat /proc/cmdline)) || fail sender-lifecycle-case
            if [ -n "$sender_case" ]; then connection_arg="$connection_arg --ssap-sender-lifecycle-case $sender_case"; fi
            if grep -qw ws73.ssap_value_lengths=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-value-lengths-verify"; fi
            if grep -qw ws73.ssap_owned=1 /proc/cmdline; then connection_arg="$connection_arg --ssap-owned-verify"; fi
            if grep -qw ws73.channel_fairness=1 /proc/cmdline; then connection_arg="$connection_arg --channel-fairness-verify"; fi
            if grep -qw ws73.dynamic_channels=1 /proc/cmdline; then connection_arg="$connection_arg --dynamic-channel-verify"; fi
            dynamic_long=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.dynamic_long=/){sub(/^ws73.dynamic_long=/,"",$i);print $i}}' /proc/cmdline)
            if [ -n "$dynamic_long" ]; then
                case "$dynamic_long" in 249|250|253|254|255|1024|2042) ;; *) fail 'explicit dynamic long size' ;; esac
                connection_arg="$connection_arg --dynamic-channel-long-bytes $dynamic_long"
            fi
            if grep -qw ws73.dynamic_burst=1 /proc/cmdline; then connection_arg="$connection_arg --dynamic-channel-burst"; fi
            if grep -qw ws73.channel_burst=1 /proc/cmdline; then connection_arg="$connection_arg --channel-socket-burst"; fi
            if grep -qw ws73.channel_prefix_close=1 /proc/cmdline; then connection_arg="$connection_arg --channel-socket-close-prefix"; fi
            if grep -qw ws73.channel_boundaries=1 /proc/cmdline; then connection_arg="$connection_arg --channel-socket-boundaries"; fi
        fi
        benchmark_mode=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_mode=/){sub(/^ws73.benchmark_mode=/,"",$i);print $i}}' /proc/cmdline)
        if [ -n "$benchmark_mode" ]; then
            case "$benchmark_mode" in rate|window|duplex) ;; *) fail 'explicit benchmark mode' ;; esac
            benchmark_window=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_window=/){sub(/^ws73.benchmark_window=/,"",$i);print $i}}' /proc/cmdline)
            case "$benchmark_window" in ''|*[!0-9]*) fail 'explicit numeric benchmark window' ;; esac
            connection_arg="$connection_arg --channel-benchmark $benchmark_mode --channel-benchmark-window $benchmark_window"
            for field in count bytes interval_us; do
                value=$(awk -v key="ws73.benchmark_$field=" '{for(i=1;i<=NF;i++)if(index($i,key)==1){print substr($i,length(key)+1)}}' /proc/cmdline)
                case "$value" in ''|*[!0-9]*) fail 'explicit numeric benchmark workload' ;; esac
                case "$field" in interval_us) option=interval-us ;; *) option=$field ;; esac
                connection_arg="$connection_arg --channel-benchmark-$option $value"
            done
            benchmark_dynamic=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_dynamic=/){sub(/^ws73.benchmark_dynamic=/,"",$i);print $i}}' /proc/cmdline)
            benchmark_parallel=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_parallel=/){sub(/^ws73.benchmark_parallel=/,"",$i);print $i}}' /proc/cmdline)
            benchmark_active=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_active=/){sub(/^ws73.benchmark_active=/,"",$i);print $i}}' /proc/cmdline)
            benchmark_close=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_close=/){sub(/^ws73.benchmark_close=/,"",$i);print $i}}' /proc/cmdline)
            if [ -n "$benchmark_dynamic$benchmark_parallel$benchmark_active$benchmark_close" ]; then
                case "$benchmark_dynamic:$benchmark_parallel" in
                    1:) benchmark_selector=--channel-benchmark-dynamic ;;
                    :1) benchmark_selector=--channel-benchmark-parallel ;;
                    *) fail 'one explicit dynamic benchmark contract' ;;
                esac
                case "$benchmark_active" in 0|1) ;; *) fail 'explicit dynamic benchmark role' ;; esac
                connection_arg="$connection_arg $benchmark_selector --channel-benchmark-active-endpoint $benchmark_active"
                if [ -n "$benchmark_close" ]; then
                    [ "$benchmark_parallel:$benchmark_close" = 1:short ] || fail 'explicit parallel short-close profile'
                    connection_arg="$connection_arg --channel-benchmark-close-short"
                fi
            fi
            benchmark_ssap=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_ssap=/){sub(/^ws73.benchmark_ssap=/,"",$i);print $i}}' /proc/cmdline)
            case "$benchmark_ssap" in
                '') ;;
                owned) connection_arg="$connection_arg --channel-benchmark-ssap-owned" ;;
                owned-duplex) connection_arg="$connection_arg --channel-benchmark-ssap-owned --channel-benchmark-ssap-duplex" ;;
                owned-credit) connection_arg="$connection_arg --channel-benchmark-ssap-owned --channel-benchmark-credit-observe" ;;
                owned-duplex-credit) connection_arg="$connection_arg --channel-benchmark-ssap-owned --channel-benchmark-ssap-duplex --channel-benchmark-credit-observe" ;;
                *) fail 'one explicit concurrent SSAP profile' ;;
            esac
            hcc_observe=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.hcc_memory_observation=/){sub(/^ws73.hcc_memory_observation=/,"",$i);print $i}}' /proc/cmdline)
            case "$hcc_observe" in
                '') ;;
                1)
                    case "$benchmark_ssap" in owned-credit|owned-duplex-credit) ;; *) fail 'HCC diagnostic requires explicit credit observation' ;; esac
                    connection_arg="$connection_arg --channel-benchmark-hcc-memory-observe" ;;
                *) fail 'one explicit HCC diagnostic profile' ;;
            esac
            link_probe=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.load_link_probe=/){sub(/^ws73.load_link_probe=/,"",$i);print $i}}' /proc/cmdline)
            case "$link_probe" in
                '') ;;
                once-rssi-6s)
                    case "$benchmark_ssap" in owned-credit|owned-duplex-credit) ;; *) fail 'finite link probe requires explicit credit observation' ;; esac
                    grep -qw ws73.link_measurements=1 /proc/cmdline || fail 'finite link probe requires initial measurements'
                    connection_arg="$connection_arg --channel-benchmark-link-probe" ;;
                *) fail 'one explicit finite load link probe' ;;
            esac
        fi
        for word in $(cat /proc/cmdline); do
            case "$word" in
                ws73.security_agent=*)
                    case "${word#*=}" in
                        approve|reject|timeout|cancel|agent-exit|caller-exit|cli-approve|cli-reject|install-cancel|numeric-approve|numeric-reject|numeric-late) ;;
                        *) fail 'unsupported Agent witness mode' ;;
                    esac
                    connection_arg="$connection_arg --security-agent=${word#*=}" ;;
            esac
        done
        if grep -qw ws73.acb_probe=1 /proc/cmdline; then connection_arg="$connection_arg --acb-transport-probe"; fi
        if grep -qw ws73.link_resync=1 /proc/cmdline; then connection_arg="$connection_arg --daemon-link-resync"; fi
    fi
    initializer_arg=''
    if grep -q 'ws73.initializer_lifecycle=1' /proc/cmdline; then initializer_arg='--initializer-lifecycle'; fi
    if grep -qw ws73.ssap_initialization=1 /proc/cmdline; then
        /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py ssap-init-fds "$daemon" > /evidence/ssap-initialization-fds.log 2>&1 & initialization_fds=$!
    fi
    if native_return_fixture_enabled; then
        /bin/python3 /usr/share/sparklink/tools/ws73_native_return.py supervise /evidence "$daemon" > /evidence/native-return-supervisor.log 2>&1 & native_return_supervisor=$!
    fi
    if grep -qw ws73.controller_directory_events=1 /proc/cmdline; then
        /bin/python3 /usr/share/sparklink/tools/ws73_controller_directory.py --daemon-pid "$daemon" > /evidence/controller-directory-supervisor.log 2>&1 & controller_directory_supervisor=$!
        for n in $(seq 1 100); do
            [ ! -f /evidence/controller-directory/ready ] || break
            kill -0 "$controller_directory_supervisor" 2>/dev/null || fail 'directory observer exited before snapshot'
            sleep 0.1
        done
        [ -f /evidence/controller-directory/ready ] || fail 'directory observer snapshot deadline'
    fi
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_target_control.py --passthrough $daemon_remove_arg $initializer_arg $connection_arg --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/passthrough-control" || fail 'QMP passthrough control'
    if grep -qw ws73.controller_directory_events=1 /proc/cmdline; then
        wait "$controller_directory_supervisor" || fail 'actual controller directory observer'
        controller_directory_supervisor=''
        echo WS73_TARGET_CONTROLLER_DIRECTORY_PASS
    fi
    if grep -qw ws73.ssap_initialization=1 /proc/cmdline; then wait "$initialization_fds" || fail 'partial initialization fd observer'; fi
    if native_return_fixture_enabled; then wait "$native_return_supervisor" || fail 'actual Native return supervisor'; fi
    if grep -qw ws73.link_resync=1 /proc/cmdline; then wait "$resync_supervisor" || fail 'real subscriber overflow supervisor'; fi
    if grep -qw ws73.acb_probe=1 /proc/cmdline; then wait "$acb_supervisor" || fail 'real ACB transport supervisor'; fi
else
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py instructions || fail 'physical mapping'
    # The only interactive shell is uid1000; raw capture and slkd remain root.
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh || fail 'ordinary application shell'
    echo 'WS73_TARGET_SHELL_CLOSED'
fi
if grep -q 'ws73.observer_policy=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py observer-policy business || fail 'native observer business role gate'
fi
if grep -q 'ws73.diagnostic=1' /proc/cmdline; then
    /bin/busybox touch /run/diagnostic-retired
    wait "$diagnostic" || fail 'diagnostic retired-fd gate'
fi
for role_pid in ${parallel_role_supervisors:-}; do
    wait "$role_pid" || fail 'actual per-pair application roles'
done
parallel_role_supervisors=''
if [ -n "${application_role_supervisor:-}" ]; then
    wait "$application_role_supervisor" || fail 'actual SDK application-only roles'
    application_role_supervisor=''
fi
kill -TERM "$daemon"
for n in $(seq 1 100); do kill -0 "$daemon" 2>/dev/null || break; sleep 0.1; done
kill -0 "$daemon" 2>/dev/null && fail 'daemon cleanup timeout'
if grep -qw ws73.session_service=1 /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_session_service.py finish > /evidence/session-service-finish.log 2>&1 || fail 'Session service trace finish'
fi
if grep -q 'ws73.support=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py bindings-writer || fail 'actual C/Python ownership writer'
fi
kill -INT "$capture"
wait "$capture" || fail 'capture shutdown'
chown 0:1000 /evidence/ws73.pcap /evidence/capture-stats.txt; chmod 0640 /evidence/ws73.pcap /evidence/capture-stats.txt
dmesg > /evidence/kernel.log
if [ -f /scratch-root-uuid ]; then
    if [ "$benchmark_trace" = 1 ]; then
        if [ "$xhci_enabled" = 1 ]; then echo "SLK_BENCH_END:$xhci_cookie" > /sys/kernel/tracing/trace_marker || fail 'trace end marker'; fi
        cat /sys/kernel/tracing/events/header_page > /evidence/benchmark-xhci-header-end.txt || fail 'trace header end'
        cat /sys/kernel/tracing/trace_clock > /evidence/benchmark-xhci-clock-end.txt || fail 'trace clock end'
        printf '{"enabled":"%s","tracing_on":"%s","tracer":"%s","buffer_kb":%s,"requested_buffer_kb":1024,"subbuffer_kb":%s,"cookie":"%s"}\n' "$(cat /sys/kernel/tracing/events/xhci-hcd/enable)" "$(cat /sys/kernel/tracing/tracing_on)" "$(cat /sys/kernel/tracing/current_tracer)" "$(cat /sys/kernel/tracing/buffer_size_kb)" "$(cat /sys/kernel/tracing/buffer_subbuf_size_kb)" "$xhci_cookie" > /evidence/benchmark-xhci-end.json || fail 'trace end readback'
        chmod 0444 /evidence/benchmark-xhci-end.json /evidence/benchmark-xhci-clock-end.txt /evidence/benchmark-xhci-header-end.txt || fail 'trace end evidence permissions'
    fi
    echo 0 > /sys/kernel/tracing/tracing_on
    cat /sys/kernel/tracing/trace > /evidence/xhci-trace.log || fail 'native xHCI trace seal'
    for stats in /sys/kernel/tracing/per_cpu/cpu*/stats; do
        cat "$stats" >> /evidence/xhci-trace-stats.txt || fail 'native xHCI trace statistics'
    done
    expected_taint=0
    if grep -qw ws73.acb_probe=1 /proc/cmdline; then expected_taint=4096; fi
    [ "$(cat /proc/sys/kernel/tainted)" = "$expected_taint" ] || fail 'final VM kernel taint'
    echo "WS73_TARGET_NATIVE_VM_TAINT: $expected_taint"
fi
if grep -q 'ws73.support=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py verify-support || fail 'sealed actual capture'
fi
if grep -q 'ws73.parallel=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py verify-parallel || fail 'sealed four-device parallel capture'
fi
if grep -q 'ws73.passthrough=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py verify-passthrough || fail 'sealed QMP passthrough capture'
fi
if grep -q 'ws73.recovery=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py verify-recovery || fail 'sealed recovery capture'
fi
echo 'WS73_TARGET_FINISHED'
sync
poweroff -f
