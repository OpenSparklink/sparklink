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
    [ -d /evidence/application ] && dmesg > /evidence/kernel.log
    dmesg
    sync
    poweroff -f
}
mount -t proc none /proc || fail proc
mount -t sysfs none /sys || fail sysfs
mount -t devtmpfs none /dev || mdev -s
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
/bin/dbus-daemon --config-file=/etc/dbus.conf --nofork > /evidence/dbus.log 2>&1 &
for n in $(seq 1 100); do [ -S /run/slkbus ] && break; sleep 0.1; done
[ -S /run/slkbus ] || fail 'system bus startup'
/bin/slkd --storage /tmp/bonds -n > /evidence/slkd.log 2>&1 & daemon=$!
echo 'WS73_TARGET_CAPTURE_READY'
/bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py ready 0 || fail 'first independent Ready'
echo 'WS73_TARGET_READY: slot=0'
/bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py ready 1 || fail 'second independent Ready'
echo 'WS73_TARGET_READY: slot=1'
if grep -q 'ws73.support=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c '/bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py support-input' || fail 'ordinary serial input'
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py support || fail 'synthetic environment integration'
elif grep -q 'ws73.passthrough=1' /proc/cmdline; then
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh -c "/bin/python3 /usr/share/sparklink/tools/ws73_target_control.py --passthrough --slctl /bin/slctl --slkd-pid $daemon --output /evidence/application/passthrough-control" || fail 'QMP passthrough control'
else
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py instructions || fail 'physical mapping'
    # The only interactive shell is uid1000; raw capture and slkd remain root.
    /bin/busybox setsid -c /bin/su ws73 -s /bin/sh || fail 'ordinary application shell'
    echo 'WS73_TARGET_SHELL_CLOSED'
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
if grep -q 'ws73.support=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py verify-support || fail 'sealed actual capture'
fi
if grep -q 'ws73.passthrough=1' /proc/cmdline; then
    /bin/python3 /usr/share/sparklink/tools/ws73_target_guest.py verify-passthrough || fail 'sealed QMP passthrough capture'
fi
echo 'WS73_TARGET_FINISHED'
sync
poweroff -f
