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
module_name=sparklink_ws73_usb
if [ -f /expected-module-name ]; then module_name=$(cat /expected-module-name) || fail "module name"; fi
case "$module_name" in sparklink_ws73_usb|sparklink_standard_usb) ;; *) fail "unsupported module name" ;; esac
release=$(cat /expected-release) || fail 'expected release'
[ "$(uname -r)" = "$release" ] || fail 'booted release mismatch'
echo "NATIVE_MODULE_RELEASE: $release"
[ -c /dev/sparklink ] || fail 'built-in SparkLink control node'
[ ! -d /sys/module/$module_name ] || fail 'WS73 unexpectedly built-in or already loaded'
echo "NATIVE_MODULE_TAINT_BEFORE: $(cat /proc/sys/kernel/tainted)"
# The caller supplies no USB device to this guest. Reject an unexpected WS73
# before any module can bind and upload firmware to it.
for device in /sys/bus/usb/devices/*; do
    [ -f "$device/idVendor" ] || continue
    if [ "$(cat "$device/idVendor")" = ffff ] && [ "$(cat "$device/idProduct")" = 3733 ]; then
        fail 'WS73 present in empty-USB smoke'
    fi
done
if [ -x /bin/sparklink-no-ghost-probe ]; then
    /bin/sparklink-no-ghost-probe || fail 'empty registry/unsupported selector before module'
fi
for round in 1 2; do
    insmod /sparklink_ws73_usb.ko || fail "module load $round"
    [ -d /sys/module/$module_name ] || fail "module missing $round"
    [ -d /sys/bus/usb/drivers/$module_name ] || fail "USB driver missing $round"
    echo "NATIVE_MODULE_LOAD: $round"
    if [ -x /bin/sparklink-no-ghost-probe ]; then
        /bin/sparklink-no-ghost-probe || fail "empty registry/unsupported selector round=$round"
    fi
    rmmod "$module_name" || fail "module unload $round"
    [ ! -d /sys/module/$module_name ] || fail "module retained $round"
    [ ! -d /sys/bus/usb/drivers/$module_name ] || fail "USB driver retained $round"
    echo "NATIVE_MODULE_UNLOAD: $round"
done
echo "NATIVE_MODULE_TAINT_AFTER: $(cat /proc/sys/kernel/tainted)"
if [ -x /bin/slktest ]; then
    /bin/su ws73 -s /bin/sh -c 'echo "SLKTEST_VM_UID: $(id -u)"; /bin/slktest channel --help > /tmp/slktest-help && grep -q duplex /tmp/slktest-help' || fail 'actual slktest entry'
    if /bin/su ws73 -s /bin/sh -c '/bin/slktest --adapter /org/sparklink/slk0_g7 channel rate /link --interval-us 1 --report /tmp/slktest-invalid.json' > /tmp/slktest-invalid.log 2>&1; then fail 'slktest invalid interval accepted'; fi
    grep -q 'absolute interval' /tmp/slktest-invalid.log || fail 'slktest parameter error before bus'
    echo SLKTEST_VM_ENTRY_PASS
    echo SLKTEST_VM_TESTS_BEGIN
    /bin/su ws73 -s /bin/sh -c '/bin/slktest-tests --test-threads=1' || fail 'actual slktest local application regression'
    echo SLKTEST_VM_TESTS_END
fi
echo NATIVE_MODULE_KERNEL_LOG_BEGIN
dmesg
echo NATIVE_MODULE_KERNEL_LOG_END
echo 'NATIVE_MODULE_SMOKE: PASS (EMPTY_USB_KVM_ONLY)'
sync
poweroff -f
