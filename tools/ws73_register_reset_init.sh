#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Dedicated VM maintenance, never a production boot or Managed acceptance.
export PATH=/bin:/usr/bin PYTHONHOME=/usr LIBSPARKLINK_PATH=/usr/lib/libsparklink.so
fail() {
    echo "WS73_RESET_LAB_FAILURE: $*"
    if [ -n "${capture:-}" ]; then kill -INT "$capture" 2>/dev/null; wait "$capture"; fi
    [ -d /evidence/maintenance ] && dmesg > /evidence/maintenance/kernel.log
    sync
    poweroff -f
    while :; do sleep 60; done
}
trap 'fail interrupted' INT TERM HUP
grep -q ' /proc proc ' /proc/mounts || mount -t proc proc /proc || fail proc
grep -q ' /sys sysfs ' /proc/mounts || mount -t sysfs sysfs /sys || fail sysfs
grep -q ' /dev devtmpfs ' /proc/mounts || mount -t devtmpfs devtmpfs /dev || fail devtmpfs
. /native-evidence-modules.sh
mount -t 9p -o trans=virtio,version=9p2000.L evidence /evidence || fail evidence mount
mount -t debugfs debugfs /sys/kernel/debug
mkdir -p /evidence/maintenance
/bin/tcpdump -Z root -i usbmon0 -s 0 -U -w /evidence/maintenance/ws73.pcap > /evidence/maintenance/capture.log 2>&1 & capture=$!
sleep 1
kill -0 "$capture" || fail capture startup
echo WS73_RESET_LAB_CAPTURE_READY
reset_arg=''
if grep -q 'ws73.register_reset_usb=1' /proc/cmdline; then reset_arg='--guest-usb-reset-before-read'; fi
wake_arg=''
if grep -q 'ws73.register_wakeup_lab=1' /proc/cmdline; then wake_arg='--sdk-wakeup-before-read'; fi
async_arg=''
if grep -q 'ws73.register_async_read_lab=1' /proc/cmdline; then async_arg='--async-read-only'; fi
route_arg=''
if grep -q 'ws73.runtime_route_lab=1' /proc/cmdline; then route_arg='--runtime-route-before-module'; fi
interface_arg=''
if grep -q 'ws73.interface_rebind_lab=1' /proc/cmdline; then interface_arg='--guest-set-interface-before-route'; fi
clear_halt_arg=''
if grep -q 'ws73.clear_halt_lab=1' /proc/cmdline; then clear_halt_arg='--guest-clear-halt-before-route'; fi
if grep -q 'ws73.register_clear_halt_lab=1' /proc/cmdline; then clear_halt_arg="$clear_halt_arg --guest-clear-halt-before-register-read"; fi
credit_arg=''
if grep -q 'ws73.usb_credit_lab=1' /proc/cmdline; then credit_arg='--usb-credit-read-only'; fi
rom_arg=''
if grep -q 'ws73.rom_chip_expected=E' /proc/cmdline; then rom_arg='--rom-chip-expected E'; fi
if grep -q 'ws73.rom_chip_expected=U' /proc/cmdline; then rom_arg='--rom-chip-expected U'; fi
/bin/python3 /usr/share/sparklink/tools/ws73_vm_register_reset.py $rom_arg $credit_arg $reset_arg $wake_arg $async_arg $route_arg $interface_arg $clear_halt_arg --output /evidence/maintenance/reset > /evidence/maintenance/probe.log 2>&1
result=$?
dmesg > /evidence/maintenance/kernel.log
for interface in /sys/bus/usb/devices/*:*; do
    [ -f "$interface/boot_stage" ] || continue
    name=${interface##*/}
    for attribute in boot_stage boot_error warm_recovery recovery_budget failure_diagnostics native_runtime controller_information; do
        cat "$interface/$attribute" > "/evidence/maintenance/$name-$attribute.txt"
    done
done
kill -INT "$capture"
wait "$capture"
echo "WS73_RESET_LAB_RESULT: $result taint=$(cat /proc/sys/kernel/tainted)"
sync
poweroff -f
