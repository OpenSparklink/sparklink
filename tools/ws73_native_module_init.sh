#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Empty-USB KVM boot/module smoke only. No native host or WS73 RF acceptance.
export PATH=/bin
fail() {
    echo "NATIVE_MODULE_FAILURE: $*"
    dmesg
    sync
    poweroff -f
    exit 1
}
mount -t proc none /proc || fail proc
mount -t sysfs none /sys || fail sysfs
mount -t devtmpfs none /dev || fail devtmpfs
release=$(cat /expected-release) || fail 'expected release'
[ "$(uname -r)" = "$release" ] || fail 'booted release mismatch'
echo "NATIVE_MODULE_RELEASE: $release"
[ -c /dev/sparklink ] || fail 'built-in SparkLink control node'
[ ! -d /sys/module/sparklink_ws73_usb ] || fail 'WS73 unexpectedly built-in or already loaded'
echo "NATIVE_MODULE_TAINT_BEFORE: $(cat /proc/sys/kernel/tainted)"
# The caller supplies no USB device to this guest. Reject an unexpected WS73
# before any module can bind and upload firmware to it.
for device in /sys/bus/usb/devices/*; do
    [ -f "$device/idVendor" ] || continue
    if [ "$(cat "$device/idVendor")" = ffff ] && [ "$(cat "$device/idProduct")" = 3733 ]; then
        fail 'WS73 present in empty-USB smoke'
    fi
done
for round in 1 2; do
    insmod /sparklink_ws73_usb.ko || fail "module load $round"
    [ -d /sys/module/sparklink_ws73_usb ] || fail "module missing $round"
    [ -d /sys/bus/usb/drivers/sparklink_ws73_usb ] || fail "USB driver missing $round"
    echo "NATIVE_MODULE_LOAD: $round"
    rmmod sparklink_ws73_usb || fail "module unload $round"
    [ ! -d /sys/module/sparklink_ws73_usb ] || fail "module retained $round"
    [ ! -d /sys/bus/usb/drivers/sparklink_ws73_usb ] || fail "USB driver retained $round"
    echo "NATIVE_MODULE_UNLOAD: $round"
done
echo "NATIVE_MODULE_TAINT_AFTER: $(cat /proc/sys/kernel/tainted)"
echo NATIVE_MODULE_KERNEL_LOG_BEGIN
dmesg
echo NATIVE_MODULE_KERNEL_LOG_END
echo 'NATIVE_MODULE_SMOKE: PASS (EMPTY_USB_KVM_ONLY)'
sync
poweroff -f
