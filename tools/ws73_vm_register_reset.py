#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded VM-only WS73 maintenance probes; never production recovery.

Explicit modes compare real register reads, SDK wakeup, BSLE route, one
interface rebind and one read-only EP0 HCC memory-credit request. The default SoC reset requires a successful register read;
no read-failure write fallback or synthesized controller acknowledgement.

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
import struct
import time


class Bulk(ctypes.Structure):
    _fields_=[('endpoint',ctypes.c_uint),('length',ctypes.c_uint),('timeout',ctypes.c_uint),('data',ctypes.c_void_p)]


class Control(ctypes.Structure):
    _fields_=[('kind',ctypes.c_uint8),('request',ctypes.c_uint8),('value',ctypes.c_uint16),
              ('index',ctypes.c_uint16),('length',ctypes.c_uint16),('timeout',ctypes.c_uint),('data',ctypes.c_void_p)]


class Urb(ctypes.Structure):
    _fields_=[('kind',ctypes.c_uint8),('endpoint',ctypes.c_uint8),('status',ctypes.c_int),
              ('flags',ctypes.c_uint),('buffer',ctypes.c_void_p),('length',ctypes.c_int),
              ('actual',ctypes.c_int),('frame',ctypes.c_int),('packets',ctypes.c_int),
              ('errors',ctypes.c_int),('signal',ctypes.c_uint),('context',ctypes.c_void_p)]


class AsyncFdClosed(RuntimeError):
    """The exclusive usbfs file was closed to join pending URBs."""


def route_packet(sequence, descriptor, queue):
    # ws73_wire_control / libws73 ws73_sle_qs_frame: USB_HCC_CONTROL_MSG,
    # queue selection then ASSEM_RESET. No SoC register write or fake ACK.
    if (type(sequence) is not int or not 0<=sequence<=0xffffffff
            or (descriptor,queue) not in ((1,10),(0,0))):
        raise ValueError('bounded BSLE route experiment only')
    return struct.pack('<IIII',3,0,sequence,descriptor)+bytes([queue])+bytes(19)


def read_usb_configuration(fd):
    """Two fixed standard reads; no GET_INTERFACE/GET_STATUS substitution."""
    rows=[]
    for name,request,value,size in [('configuration',8,0,1),('descriptor',6,0x200,53)]:
        data=ctypes.create_string_buffer(size)
        control=Control(0x80,request,value,0,size,2000,ctypes.addressof(data))
        row=dict(name=name,kind=0x80,request=request,value=value,length=size,before_wall_ns=time.time_ns())
        try:
            count=fcntl.ioctl(fd,0xc0185500,bytearray(bytes(control)))
            row.update(returned=count,data=data.raw[:max(0,min(count,size))].hex())
            if count!=size:row['error']='short USB configuration reply'
        except OSError as error:
            row.update(error=str(error),errno=error.errno)
        row['after_wall_ns']=time.time_ns();rows.append(row)
    return rows


def checked_single_runtime_interface(rows):
    # An unsupported GET_INTERFACE is not a zero reply. The real configuration
    # descriptor can independently prove the sole advertised interface0/alt0.
    if len(rows)!=2:raise ValueError('complete fixed configuration observations required')
    for row,name,size in zip(rows,['configuration','descriptor'],[1,53]):
        if row['name']!=name or type(row.get('returned')) is not int or row['returned']!=size or 'error' in row:
            raise ValueError('actual complete USB configuration replies required')
    raw=bytes.fromhex(rows[1]['data'])
    if (rows[0]['data']!='01' or len(raw)!=53 or raw[:6]!=bytes.fromhex('090235000101')
            or raw[9:17]!=bytes.fromhex('0904000005e00202')):
        raise ValueError('one actual runtime interface0/alt0 descriptor required')
    endpoints=[]
    for offset in range(18,53,7):
        endpoint=raw[offset:offset+7]
        if endpoint[:2]!=bytes([7,5]):raise ValueError('only five exact endpoint descriptors allowed')
        address=endpoint[2];kind=3 if address==0x83 else 2;size=8 if kind==3 else 512
        if endpoint[3]!=kind or int.from_bytes(endpoint[4:6],'little')!=size:
            raise ValueError('qualified WS73 endpoint type/size required')
        endpoints.append(address)
    if sorted(endpoints)!=[1,2,129,130,131]:raise ValueError('exact unique runtime endpoints required')
    return raw


def clear_runtime_endpoints(fd,record,save,*,register_read=False):
    """Fixed route or read-only register endpoint comparison, not recovery.

    QEMU's original CLEAR_FEATURE emulation ignores libusb_clear_halt's return.
    A zero guest ioctl must therefore be corroborated by the private observer's
    actual host return; it never establishes Ready or production recovery.
    """
    if type(register_read) is not bool:raise ValueError('fixed endpoint comparison mode required')
    record['clear_halt_scope']='register-read EP02/EP82' if register_read else 'route EP01/EP81'
    record['usb_configuration_before_clear_halt']=read_usb_configuration(fd);save()
    before=checked_single_runtime_interface(record['usb_configuration_before_clear_halt'])
    record['clear_halt_transfers']=[]
    record['physical_clear_halt_confirmed']=False;save()
    for endpoint in ((2,130) if register_read else (1,129)):
        row=dict(endpoint=endpoint,before_wall_ns=time.time_ns())
        record['clear_halt_transfers'].append(row);save()
        try:
            # USBDEVFS_CLEAR_HALT (_IOR('U',21,unsigned int)), exclusively
            # claimed guest interface0. No reset, driver detach or SoC write.
            count=fcntl.ioctl(fd,0x80045515,bytearray(endpoint.to_bytes(4,'little')))
            row.update(returned=count,after_wall_ns=time.time_ns());save()
            if type(count) is not int or count!=0:
                raise ValueError('guest endpoint clear-halt ioctl failed')
        except OSError as error:
            row.update(error=str(error),errno=error.errno,after_wall_ns=time.time_ns());save();raise
    record['usb_configuration_after_clear_halt']=read_usb_configuration(fd);save()
    after=checked_single_runtime_interface(record['usb_configuration_after_clear_halt'])
    if before!=after:raise ValueError('runtime descriptor changed during endpoint clear-halt')


def read_credit_control(fd,record,save):
    """One SDK class-IN credit read. Raw memory count, never Ready/ACK."""
    row=dict(kind=0xa1,request=5,value=0,index=0,length=4,timeout_ms=2000,
             before_wall_ns=time.time_ns())
    record['credit_control']=row;save()
    data=ctypes.create_string_buffer(4)
    control=Control(0xa1,5,0,0,4,2000,ctypes.addressof(data))
    try:
        count=fcntl.ioctl(fd,0xc0185500,bytearray(bytes(control)))
        row.update(returned=count,data=data.raw[:count].hex() if type(count) is int and 0<=count<=4 else '')
        if type(count) is not int or count!=4:raise ValueError('exact four-byte SDK credit read required')
        row['raw_credit_u32']=int.from_bytes(data.raw[:4],'little')
    except BaseException as error:
        row.update(error=str(error),error_type=type(error).__name__,errno=getattr(error,'errno',None));raise
    finally:
        row['after_wall_ns']=time.time_ns();save()


def async_register_read(fd,diagnostics=None,save=lambda:None):
    # SUBMITURB retains the userspace URB pointer. libc ioctl uses the stable
    # ctypes object directly, unlike fcntl's small-buffer temporary copy.
    if ctypes.sizeof(Urb)!=56:raise ValueError('qualified 64-bit usbfs URB ABI required')
    libc=ctypes.CDLL(None,use_errno=True)
    libc.ioctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_void_p];libc.ioctl.restype=ctypes.c_int
    out=ctypes.create_string_buffer(setup_packet(False));incoming=ctypes.create_string_buffer(4)
    urbs=[Urb(kind=3,endpoint=2,buffer=ctypes.addressof(out),length=16),
          Urb(kind=3,endpoint=130,buffer=ctypes.addressof(incoming),length=4)]
    pending={};completed=[]
    if diagnostics is None:diagnostics={}
    diagnostics.update(submitted=[],completed=[],cancel_requested=[],cancel_reaped=[],fd_closed_to_join=False)
    save()
    def call(request,arg):
        ret=libc.ioctl(fd,request,arg)
        if ret<0:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
        return ret
    try:
        for urb in urbs:
            call(0x8038550a,ctypes.byref(urb));pending[ctypes.addressof(urb)]=urb
            diagnostics['submitted'].append(dict(endpoint=urb.endpoint,length=urb.length,wall_ns=time.time_ns()));save()
        deadline=time.monotonic()+2.5
        while pending:
            pointer=ctypes.c_void_p()
            try:call(0x4008550d,ctypes.byref(pointer))
            except OSError as error:
                if error.errno!=errno.EAGAIN:raise
                if time.monotonic()>deadline:raise TimeoutError('bounded asynchronous setup/read completion')
                time.sleep(.002);continue
            if pointer.value not in pending:raise ValueError('unknown completed URB pointer')
            urb=pending.pop(pointer.value)
            row=dict(endpoint=urb.endpoint,status=urb.status,actual=urb.actual,wall_ns=time.time_ns())
            completed.append(row);diagnostics['completed'].append(row);save()
            if urb.status or urb.actual!=urb.length:raise ValueError('failed/short asynchronous register transfer')
        return incoming.raw,completed
    except BaseException as error:
        diagnostics['original_error']=dict(type=type(error).__name__,message=str(error),errno=getattr(error,'errno',None));save();raise
    finally:
        # Keep every object/buffer alive until cancellation is joined by reap
        # or closing this exclusively owned usbfs fd in the caller.
        for pointer,urb in pending.items():
            ret=libc.ioctl(fd,0x550b,ctypes.c_void_p(pointer))
            diagnostics['cancel_requested'].append(dict(endpoint=urb.endpoint,returned=ret,errno=ctypes.get_errno() if ret<0 else None,wall_ns=time.time_ns()));save()
        deadline=time.monotonic()+2
        while pending and time.monotonic()<deadline:
            pointer=ctypes.c_void_p();ret=libc.ioctl(fd,0x4008550d,ctypes.byref(pointer))
            if ret==0:
                urb=pending.pop(pointer.value,None)
                if urb is None:
                    diagnostics['cancel_unknown_pointer']=True;save();break
                diagnostics['cancel_reaped'].append(dict(endpoint=urb.endpoint,status=urb.status,actual=urb.actual,wall_ns=time.time_ns()));save()
            elif ctypes.get_errno()==errno.EAGAIN:time.sleep(.002)
            else:
                diagnostics['cancel_reap_errno']=ctypes.get_errno();save();break
        if pending:
            os.close(fd)
            diagnostics['fd_closed_to_join']=True;save()
            raise AsyncFdClosed('async URB cancellation did not reap; owned fd closed to join')

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
    credit=getattr(args,'usb_credit_read_only',False)
    if type(credit) is not bool:raise ValueError('typed explicit credit probe mode required')
    credit_tokens=[v for v in Path('/proc/cmdline').read_text().split() if v.startswith('ws73.usb_credit_lab=')]
    if credit_tokens!=(['ws73.usb_credit_lab=1'] if credit else []):raise ValueError('exact matching credit read-only boot required')
    if credit and any(getattr(args,k,False) for k in ['runtime_route_before_module','guest_set_interface_before_route','guest_clear_halt_before_route','guest_clear_halt_before_register_read','guest_usb_reset_before_read','sdk_wakeup_before_read','async_read_only']):
        raise ValueError('credit read-only excludes reset, route, wakeup, clear-halt and register modes')
    route=bool(getattr(args,'runtime_route_before_module',False))
    rebind=bool(getattr(args,'guest_set_interface_before_route',False))
    clear_halt=bool(getattr(args,'guest_clear_halt_before_route',False))
    register_clear_halt=bool(getattr(args,'guest_clear_halt_before_register_read',False))
    if rebind and (not route or 'ws73.interface_rebind_lab=1' not in Path('/proc/cmdline').read_text().split()):
        raise ValueError('explicit route and single interface-rebind boot required')
    if clear_halt and (not route or rebind or 'ws73.clear_halt_lab=1' not in Path('/proc/cmdline').read_text().split()):
        raise ValueError('explicit route and exclusive endpoint clear-halt boot required')
    if register_clear_halt and (not args.async_read_only or route or rebind or clear_halt
            or args.guest_usb_reset_before_read or args.sdk_wakeup_before_read
            or 'ws73.register_clear_halt_lab=1' not in Path('/proc/cmdline').read_text().split()):
        raise ValueError('explicit exclusive read-only register endpoint clear-halt boot required')
    if route and (args.guest_usb_reset_before_read or args.sdk_wakeup_before_read or args.async_read_only):
        raise ValueError('route comparison excludes other reset/read/wakeup modes')
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
        if args.sdk_wakeup_before_read:
            if 'ws73.register_wakeup_lab=1' not in Path('/proc/cmdline').read_text().split():
                raise ValueError('explicit SDK USB wakeup maintenance boot required')
            wake=ctypes.create_string_buffer(bytes(4))
            request=Control(0x21,2,0,0,4,2000,ctypes.addressof(wake))
            record['sdk_wakeup_before_wall_ns']=time.time_ns();save()
            count=fcntl.ioctl(fd,0xc0185500,bytearray(bytes(request)))
            record.update(sdk_wakeup_returned=count,sdk_wakeup_after_wall_ns=time.time_ns());save()
            if count!=4:raise ValueError('complete SDK DISALLOW_TO_SLEEP control required')
        fcntl.ioctl(fd,0x8004550f,bytearray((0).to_bytes(4,'little')))
        if credit:
            record.update(usb_credit_read_only=True,register_write_not_requested=True,
                          module_load_requested=False,ready_acknowledgement_observed=False,
                          usb_configuration_before_credit=read_usb_configuration(fd));save()
            before=checked_single_runtime_interface(record['usb_configuration_before_credit'])
            read_credit_control(fd,record,save)
            record['usb_configuration_after_credit']=read_usb_configuration(fd);save()
            after=checked_single_runtime_interface(record['usb_configuration_after_credit'])
            if before!=after:raise ValueError('runtime descriptor changed during credit read')
            record.update(status='VM_USB_CREDIT_READ_GUEST_REQUIRES_HOST_CORROBORATION',finished_wall_ns=time.time_ns());save()
            return
        if clear_halt:
            clear_runtime_endpoints(fd,record,save)
        if register_clear_halt:
            clear_runtime_endpoints(fd,record,save,register_read=True)
        if rebind:
            record['usb_configuration_before_interface']=read_usb_configuration(fd);save()
            before_descriptor=checked_single_runtime_interface(record['usb_configuration_before_interface'])
            record['set_interface_before_wall_ns']=time.time_ns();save()
            # USBDEVFS_SETINTERFACE, interface0/alt0, within this exclusively
            # owned guest USB file. Never a bus/hub/SoC reset or driver detach.
            count=fcntl.ioctl(fd,0x80085504,bytearray(8))
            record.update(set_interface_returned=count,set_interface_after_wall_ns=time.time_ns());save()
            if count!=0:raise ValueError('single interface rebind failed')
            record['usb_configuration_after_interface']=read_usb_configuration(fd);save()
            after_descriptor=checked_single_runtime_interface(record['usb_configuration_after_interface'])
            if before_descriptor!=after_descriptor:raise ValueError('runtime descriptor changed during rebind')
        def transfer(endpoint,data,length=None):
            buffer=ctypes.create_string_buffer(data if isinstance(data,bytes) else data)
            size=len(data) if isinstance(data,bytes) else data
            x=Bulk(endpoint,size,2000,ctypes.addressof(buffer))
            if fcntl.ioctl(fd,0xc0185502,bytearray(bytes(x)))!=size:raise ValueError('short maintenance USB transfer')
            return buffer.raw[:size]
        if args.async_read_only:
            if 'ws73.register_async_read_lab=1' not in Path('/proc/cmdline').read_text().split():
                raise ValueError('explicit SDK asynchronous read-only boot required')
            record['async_read_before_wall_ns']=time.time_ns();save()
            record.update(register_read_diagnostics={},register_write_not_requested=True,register_read_experiment=True);save()
            try:raw,completions=async_register_read(fd,record['register_read_diagnostics'],save)
            except AsyncFdClosed:
                fd=None
                raise
            record.update(register_before=raw.hex(),async_completions=completions,
                register_write_not_requested=True,status='VM_CLEAR_HALT_ASYNC_READ_GUEST_REQUIRES_HOST_CORROBORATION' if register_clear_halt else 'VM_ASYNC_REGISTER_READ_SUPPORT_PASS',finished_wall_ns=time.time_ns());save()
            return
        if route:
            if 'ws73.runtime_route_lab=1' not in Path('/proc/cmdline').read_text().split():
                raise ValueError('explicit VM runtime route boot required')
            record.update(runtime_route_experiment=True,register_write_not_requested=True,route_transfers=[]);save()
            for seq,descriptor,queue in [(0,1,10),(1,0,0)]:
                packet=route_packet(seq,descriptor,queue)
                row=dict(endpoint=1,data=packet.hex(),before_wall_ns=time.time_ns())
                record['route_transfers'].append(row);save()
                transfer(1,packet)
                row['completed_wall_ns']=time.time_ns();save()
            os.close(fd);fd=None
        else:
            transfer(2,setup_packet(False));raw=transfer(130,4);value=checked_reset_value(raw)
            record['register_before']=raw.hex()
            if not args.sdk_wakeup_before_read:record['register_write']=value.to_bytes(4,'little').hex()
            save()
        if not route and not args.sdk_wakeup_before_read:
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
        elif not route:
            record.update(register_write_not_requested=True,wakeup_only_experiment=True);save()
            os.close(fd);fd=None
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
        status='VM_CLEAR_HALT_GUEST_SETUP_REQUIRES_HOST_CORROBORATION' if clear_halt else 'VM_INTERFACE_REBIND_SETUP_PASS' if rebind else 'VM_RUNTIME_ROUTE_SETUP_PASS' if route else 'VM_SDK_WAKEUP_RUNTIME_SETUP_PASS' if args.sdk_wakeup_before_read else 'VM_REGISTER_RESET_REBOOTSTRAP_SETUP_PASS'
        record.update(status=status,finished_wall_ns=time.time_ns());save()
    except BaseException as error:
        record.update(status='FAIL',error=str(error),error_type=type(error).__name__,errno=getattr(error,'errno',None));save();raise
    finally:
        if fd is not None:
            try:os.close(fd)
            except OSError as error:
                if error.errno!=errno.EBADF:raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--guest-usb-reset-before-read',action='store_true');p.add_argument('--sdk-wakeup-before-read',action='store_true');p.add_argument('--async-read-only',action='store_true');p.add_argument('--usb-credit-read-only',action='store_true');p.add_argument('--runtime-route-before-module',action='store_true');p.add_argument('--guest-set-interface-before-route',action='store_true');p.add_argument('--guest-clear-halt-before-route',action='store_true');p.add_argument('--guest-clear-halt-before-register-read',action='store_true');run(p.parse_args())
