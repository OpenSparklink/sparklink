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
# Dracut moves these mounts into the root filesystem before switch-root.
# Reuse only the expected filesystem; do not mask an existing wrong mount.
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
    root_seen=no
    while read -r source target kind rest; do
        [ "$target" = / ] || continue
        [ "$source" = /dev/nvme0n1 ] && [ "$kind" = btrfs ] || fail 'scratch NVMe/Btrfs root'
        echo "NATIVE_ROOT_MOUNT: $source $kind"
        root_seen=yes
    done < /proc/mounts
    [ "$root_seen" = yes ] || fail 'scratch root mount missing'
fi
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
