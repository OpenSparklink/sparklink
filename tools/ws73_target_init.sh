#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
export PATH=/bin:/usr/bin
export DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/slkbus
# The policy probe selects this address explicitly; the bus is type=system.
export DBUS_SESSION_BUS_ADDRESS=$DBUS_SYSTEM_BUS_ADDRESS
export PYTHONHOME=/usr
fail() {
    echo "WS73_TARGET_FAILURE: $*"
    if [ -f /evidence/session-service/run.json ]; then
        /bin/python3 /usr/share/sparklink/tools/ws73_session_service.py abort > /evidence/session-service-abort.log 2>&1 || true
    fi
    # A failed bootstrap is still evidence. Stop our owned processes and
    # flush usbmon before shutdown, even when the ordinary shell never opened.
    if [ -n "${daemon:-}" ]; then
        kill -TERM "$daemon" 2>/dev/null
        for n in $(seq 1 100); do kill -0 "$daemon" 2>/dev/null || break; sleep 0.1; done
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
        for attribute in boot_stage boot_error warm_recovery recovery_budget failure_diagnostics runtime_transport metadata_valid native_runtime controller_information; do
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
    xhci_mode=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.benchmark_xhci=/){sub(/^ws73.benchmark_xhci=/,"",$i);print $i}}' /proc/cmdline)
    case "$xhci_mode" in
        ''|on) xhci_enabled=1 ;;
        off) grep -q 'ws73.benchmark_mode=' /proc/cmdline || fail 'trace comparison needs benchmark'; xhci_enabled=0 ;;
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
if [ -f /scratch-root-uuid ] && grep -q 'ws73.benchmark_mode=' /proc/cmdline; then
    cat /sys/kernel/tracing/events/header_page > /evidence/benchmark-xhci-header-start.txt || fail 'trace header start'
    printf '{"enabled":"%s","tracing_on":"%s","tracer":"%s","buffer_kb":%s,"requested_buffer_kb":1024,"subbuffer_kb":%s,"cookie":"%s"}\n' "$(cat /sys/kernel/tracing/events/xhci-hcd/enable)" "$(cat /sys/kernel/tracing/tracing_on)" "$(cat /sys/kernel/tracing/current_tracer)" "$(cat /sys/kernel/tracing/buffer_size_kb)" "$(cat /sys/kernel/tracing/buffer_subbuf_size_kb)" "$xhci_cookie" > /evidence/benchmark-xhci-start.json || fail 'trace start readback'
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
storage=/tmp/bonds
if [ -f /scratch-root-uuid ]; then
    storage=/var/lib/sparklink
    mkdir -p "$storage"; chown 0:0 "$storage"; chmod 0700 "$storage"
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
/bin/slkd $config_args --storage "$storage" -n > /evidence/slkd.log 2>&1 & daemon=$!
if ! grep -q 'ws73.diagnostic=1' /proc/cmdline && ! grep -q 'ws73.active_deadline=1' /proc/cmdline && ! grep -q 'ws73.setup_release=1' /proc/cmdline; then
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
    /bin/slkd $config_args --storage "$storage" -n > /evidence/slkd-successor.log 2>&1 & daemon=$!
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
    /bin/slkd $config_args --storage "$storage" -n > /evidence/slkd-successor.log 2>&1 & daemon=$!
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py daemon-crash after "$daemon" || fail 'same-generation successor'
fi
cat "/proc/$daemon/status" > /evidence/slkd-process-status.txt || fail 'daemon process credentials'
if grep -q 'ws73.observer_policy=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py observer-policy initial || fail 'native observer initial role gate'
fi
if grep -q 'ws73.event_copy=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_event_copy_probe.py --probe /bin/event-copy-probe --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/event-copy" || fail 'live event copy fault gate'
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
        if grep -qw ws73.channel_socket=1 /proc/cmdline; then
            channel_rounds=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.channel_rounds=/){sub(/^ws73.channel_rounds=/,"",$i);print $i}}' /proc/cmdline)
            channel_bytes=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.channel_bytes=/){sub(/^ws73.channel_bytes=/,"",$i);print $i}}' /proc/cmdline)
            connection_arg="$connection_arg --channel-socket-verify --channel-socket-rounds ${channel_rounds:-4} --channel-socket-bytes ${channel_bytes:-61}"
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
            case "$benchmark_window" in 1|4) ;; *) fail 'explicit benchmark window' ;; esac
            connection_arg="$connection_arg --channel-benchmark $benchmark_mode --channel-benchmark-window $benchmark_window"
        fi
        for word in $(cat /proc/cmdline); do
            case "$word" in
                ws73.security_agent=approve|ws73.security_agent=reject|ws73.security_agent=timeout|ws73.security_agent=cancel|ws73.security_agent=agent-exit|ws73.security_agent=caller-exit|ws73.security_agent=cli-approve|ws73.security_agent=cli-reject)
                    connection_arg="$connection_arg --security-agent=${word#*=}" ;;
            esac
        done
        if grep -qw ws73.acb_probe=1 /proc/cmdline; then connection_arg="$connection_arg --acb-transport-probe"; fi
        if grep -qw ws73.link_resync=1 /proc/cmdline; then connection_arg="$connection_arg --daemon-link-resync"; fi
    fi
    initializer_arg=''
    if grep -q 'ws73.initializer_lifecycle=1' /proc/cmdline; then initializer_arg='--initializer-lifecycle'; fi
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_target_control.py --passthrough $daemon_remove_arg $initializer_arg $connection_arg --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/passthrough-control" || fail 'QMP passthrough control'
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
    if grep -q 'ws73.benchmark_mode=' /proc/cmdline; then
        if [ "$xhci_enabled" = 1 ]; then echo "SLK_BENCH_END:$xhci_cookie" > /sys/kernel/tracing/trace_marker || fail 'trace end marker'; fi
        cat /sys/kernel/tracing/events/header_page > /evidence/benchmark-xhci-header-end.txt || fail 'trace header end'
        printf '{"enabled":"%s","tracing_on":"%s","tracer":"%s","buffer_kb":%s,"requested_buffer_kb":1024,"subbuffer_kb":%s,"cookie":"%s"}\n' "$(cat /sys/kernel/tracing/events/xhci-hcd/enable)" "$(cat /sys/kernel/tracing/tracing_on)" "$(cat /sys/kernel/tracing/current_tracer)" "$(cat /sys/kernel/tracing/buffer_size_kb)" "$(cat /sys/kernel/tracing/buffer_subbuf_size_kb)" "$xhci_cookie" > /evidence/benchmark-xhci-end.json || fail 'trace end readback'
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
