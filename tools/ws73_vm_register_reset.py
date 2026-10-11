#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Single VM-only volatile SoC register reset; no read-failure write fallback.

Protocol facts: WS73 SDK plat_pm_board_ws73.c and libws73-usb
ws73_usb_control.c. Never run this on a host USB path or claim natural recovery.
"""
import argparse
import ctypes
import fcntl
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import time


class Bulk(ctypes.Structure):
    _fields_=[('endpoint',ctypes.c_uint),('length',ctypes.c_uint),('timeout',ctypes.c_uint),('data',ctypes.c_void_p)]


class Control(ctypes.Structure):
    _fields_=[('kind',ctypes.c_uint8),('request',ctypes.c_uint8),('value',ctypes.c_uint16),
              ('index',ctypes.c_uint16),('length',ctypes.c_uint16),('timeout',ctypes.c_uint),('data',ctypes.c_void_p)]


def setup_packet(write):
    # Register endpoint maps this AHB address through its 16-bit offset and
    # bit30 bus selector. bit0 selects write, bits1.. select four-byte width.
    return bytes(8)+bytes.fromhex('18f10000')+((1<<30)|8|int(write)).to_bytes(4,'little')


def checked_reset_value(raw):
    if not isinstance(raw,bytes) or len(raw)!=4:raise ValueError('exact successful register read required')
    value=int.from_bytes(raw,'little')
    if value&0x10:raise ValueError('reset bit already asserted; do not blindly rewrite')
    return value|(1<<4)


def wait_interface(count,timeout):
    path=Path('/sys/bus/usb/devices/1-1:1.0');deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            device=path.parent/'1-1'
            if ((device/'idVendor').read_text().strip()=='ffff' and (device/'idProduct').read_text().strip()=='3733'
                    and int((path/'bNumEndpoints').read_text(),16)==count):return path,device
        except (FileNotFoundError,ValueError):pass
        time.sleep(.02)
    raise TimeoutError('exact guest port 1-1 descriptor mode')


def run(args):
    if os.geteuid()!=0 or 'ws73.register_reset_lab=1' not in Path('/proc/cmdline').read_text().split():
        raise ValueError('explicit root VM-only maintenance boot required')
    if Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU' or not Path('/scratch-root-uuid').is_file():
        raise ValueError('dedicated QEMU scratch root required')
    if ctypes.sizeof(Bulk)!=24 or ctypes.sizeof(Control)!=24:raise ValueError('qualified 64-bit usbfs ABI required')
    output=args.output;output.mkdir(parents=True,exist_ok=False)
    record=dict(status='STARTING',physical_acceptance=False,automatic_fault_recovery_acceptance=False,
                natural_fault_root_cause_closed=False,managed_acceptance=False)
    def save():
        temporary=output/'run.tmp';temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(output/'run.json')
    fd=None
    try:
        interface,device=wait_interface(5,30)
        if (interface/'driver').exists():raise ValueError('maintenance requires no guest driver owner; never detach implicitly')
        addresses=sorted(int((p/'bEndpointAddress').read_text(),16) for p in interface.glob('ep_*'))
        if addresses!=[1,2,129,130,131]:raise ValueError('exact WS73 runtime endpoints required')
        node=Path('/dev/bus/usb')/f'{int((device/"busnum").read_text()):03}'/f'{int((device/"devnum").read_text()):03}'
        record.update(node=str(node),endpoints=addresses,started_wall_ns=time.time_ns());save()
        fd=os.open(node,os.O_RDWR|os.O_CLOEXEC)
        descriptor=ctypes.create_string_buffer(18)
        control=Control(0x80,6,0x100,0,18,2000,ctypes.addressof(descriptor))
        if fcntl.ioctl(fd,0xc0185500,bytearray(bytes(control)))!=18 or descriptor.raw[8:12]!=bytes.fromhex('ffff3337'):
            raise ValueError('opened fd device identity mismatch')
        if args.guest_usb_reset_before_read:
            if 'ws73.register_reset_usb=1' not in Path('/proc/cmdline').read_text().split():
                raise ValueError('explicit single guest USB reset boot permission required')
            record['guest_usb_reset_before_read_wall_ns']=time.time_ns();save()
            fcntl.ioctl(fd,0x5514)
            record['guest_usb_reset_returned_wall_ns']=time.time_ns();save()
        fcntl.ioctl(fd,0x8004550f,bytearray((0).to_bytes(4,'little')))
        def transfer(endpoint,data,length=None):
            buffer=ctypes.create_string_buffer(data if isinstance(data,bytes) else data)
            size=len(data) if isinstance(data,bytes) else data
            x=Bulk(endpoint,size,2000,ctypes.addressof(buffer))
            if fcntl.ioctl(fd,0xc0185502,bytearray(bytes(x)))!=size:raise ValueError('short register USB transfer')
            return buffer.raw[:size]
        transfer(2,setup_packet(False));raw=transfer(130,4);value=checked_reset_value(raw)
        record.update(register_before=raw.hex(),register_write=value.to_bytes(4,'little').hex());save()
        transfer(2,setup_packet(True))
        try:transfer(2,value.to_bytes(4,'little'))
        except OSError as error:
            # A reset may interrupt its own data completion. Record the error;
            # only exact subsequent boot-mode re-enumeration can qualify it.
            record['write_errno']=error.errno;save()
        os.close(fd);fd=None
        interface,device=wait_interface(2,15)
        record.update(boot_mode_observed_wall_ns=time.time_ns(),boot_device=int((device/'devnum').read_text()))
        save()
        subprocess.run(['/bin/sh','/native-ws73-module.sh'],check=True)
        sys.path.insert(0,'/usr/share/sparklink/python')
        from sparklink.native import NativeAdapter
        deadline=time.monotonic()+90
        while True:
            adapter=None
            try:
                adapter=NativeAdapter(0);snapshot=adapter.snapshot()
                if snapshot.flags==2 and snapshot.profile==1 and snapshot.valid_fields==1 and not snapshot.error:
                    record['setup_snapshot']=bytes(snapshot).hex();break
            except OSError as error:
                if error.errno not in (errno.ENODEV,errno.EAGAIN):raise
            finally:
                if adapter is not None:adapter.close()
            if time.monotonic()>deadline:raise TimeoutError('real rebootstrap Setup metadata')
            time.sleep(.02)
        record.update(status='VM_REGISTER_RESET_REBOOTSTRAP_SETUP_PASS',finished_wall_ns=time.time_ns());save()
    except BaseException as error:
        record.update(status='FAIL',error=str(error),error_type=type(error).__name__,errno=getattr(error,'errno',None));save();raise
    finally:
        if fd is not None:os.close(fd)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--guest-usb-reset-before-read',action='store_true');run(p.parse_args())
