#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
export PATH=/bin:/usr/bin
export DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/slkbus
# The policy probe selects this address explicitly; the bus is type=system.
export DBUS_SESSION_BUS_ADDRESS=$DBUS_SYSTEM_BUS_ADDRESS
export PYTHONHOME=/usr
fail() {
    echo "WS73_TARGET_FAILURE: $*"
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
    echo 1 > /sys/kernel/tracing/events/xhci-hcd/enable || fail 'native xHCI tracing'
    echo "WS73_TARGET_NATIVE_VM_ROOT: $(uname -r) NVMe/Btrfs signed-module"
fi
mount -t 9p -o trans=virtio,version=9p2000.L evidence /evidence || fail 'private evidence share'
chown 0:0 /evidence; chmod 0755 /evidence
mkdir /evidence/application; chown 1000:1002 /evidence/application; chmod 0700 /evidence/application
for n in $(seq 1 100); do [ -c /dev/usbmon1 ] && [ -c /dev/sparklink ] && break; sleep 0.1; done
[ -c /dev/usbmon1 ] && [ -c /dev/sparklink ] || fail 'built-in usbmon/sparklink nodes'
chown 0:1000 /dev/sparklink; chmod 0660 /dev/sparklink
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
    partial_case=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_case=/){sub(/^ws73.partial_case=/,"",$i);print $i}}' /proc/cmdline)
    partial_domain=$(awk '{for(i=1;i<=NF;i++)if($i~/^ws73.partial_domain=/){sub(/^ws73.partial_domain=/,"",$i);print $i}}' /proc/cmdline)
    LIBSPARKLINK_PATH=/usr/lib/libsparklink.so /bin/python3 /usr/share/sparklink/tools/ws73_management_partial.py --case "$partial_case" --domain "$partial_domain" --output /evidence/managed-partial > /evidence/managed-partial-supervisor.log 2>&1 || fail 'partial Managed held-reply cleanup gate'
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
/bin/slkd --storage "$storage" -n > /evidence/slkd.log 2>&1 & daemon=$!
if ! grep -q 'ws73.diagnostic=1' /proc/cmdline && ! grep -q 'ws73.active_deadline=1' /proc/cmdline && ! grep -q 'ws73.setup_release=1' /proc/cmdline; then
    echo 'WS73_TARGET_CAPTURE_READY'
fi
/bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py ready 0 || fail 'first independent Ready'
echo 'WS73_TARGET_READY: slot=0'
/bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py ready 1 || fail 'second independent Ready'
echo 'WS73_TARGET_READY: slot=1'
cat "/proc/$daemon/status" > /evidence/slkd-process-status.txt || fail 'daemon process credentials'
if grep -q 'ws73.event_copy=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_event_copy_probe.py --probe /bin/event-copy-probe --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/event-copy" || fail 'live event copy fault gate'
fi
if grep -q 'ws73.support=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c '/bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py support-input' || fail 'ordinary serial input'
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py support || fail 'synthetic environment integration'
elif grep -q 'ws73.recovery=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_target_recovery.py --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/recovery-control" || fail 'artificial transport recovery control'
elif grep -q 'ws73.passthrough=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_target_control.py --passthrough --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/passthrough-control" || fail 'QMP passthrough control'
else
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py instructions || fail 'physical mapping'
    # The only interactive shell is uid1000; raw capture and slkd remain root.
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh || fail 'ordinary application shell'
    echo 'WS73_TARGET_SHELL_CLOSED'
fi
if grep -q 'ws73.diagnostic=1' /proc/cmdline; then
    /bin/busybox touch /run/diagnostic-retired
    wait "$diagnostic" || fail 'diagnostic retired-fd gate'
fi
kill -TERM "$daemon"
for n in $(seq 1 100); do kill -0 "$daemon" 2>/dev/null || break; sleep 0.1; done
kill -0 "$daemon" 2>/dev/null && fail 'daemon cleanup timeout'
if grep -q 'ws73.support=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py bindings-writer || fail 'actual C/Python ownership writer'
fi
kill -INT "$capture"
wait "$capture" || fail 'capture shutdown'
chown 0:1000 /evidence/ws73.pcap /evidence/capture-stats.txt; chmod 0640 /evidence/ws73.pcap /evidence/capture-stats.txt
dmesg > /evidence/kernel.log
if [ -f /scratch-root-uuid ]; then
    echo 0 > /sys/kernel/tracing/tracing_on
    cat /sys/kernel/tracing/trace > /evidence/xhci-trace.log || fail 'native xHCI trace seal'
    for stats in /sys/kernel/tracing/per_cpu/cpu*/stats; do
        cat "$stats" >> /evidence/xhci-trace-stats.txt || fail 'native xHCI trace statistics'
    done
    [ "$(cat /proc/sys/kernel/tainted)" = 0 ] || fail 'final VM kernel taint'
    echo 'WS73_TARGET_NATIVE_VM_TAINT: 0'
fi
if grep -q 'ws73.support=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py verify-support || fail 'sealed actual capture'
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
