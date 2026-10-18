#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify actual standard EP0 writer guards/setup with explicit copy/USB abstractions."""
from pathlib import Path
import argparse
import sys,json,hashlib,subprocess
def verdict(exit_code, timed_out, report, stderr, weak):
    results=[x for block in report for x in block.get('result',[])]
    messages=' '.join(str(block.get('messageText','')) for block in report)
    bad_messages=any(block.get('messageType') in ('WARNING','ERROR') for block in report)
    bad_text=any(word in (messages+' '+stderr).lower() for word in ('unsupported','warning','error'))
    return 'MODEL_CHECKED_SCOPED' if exit_code==0 and not timed_out and not weak and results and not bad_messages and not bad_text and any(block.get('cProverStatus')=='success' for block in report) and all(x.get('status')=='SUCCESS' for x in results) else 'NOT_PROVEN'


def run(args):
    kernel=args.kernel_source.resolve();sys.path.insert(0,str(kernel/'tools/testing/selftests/sparklink'));from run_connection_tx import function
    source=kernel/'drivers/sparklink/standard_usb.c';s=source.read_text();actual=function(s.replace('static int sle_usb_write_command_locked','int sle_usb_write_command_locked'),'sle_usb_write_command_locked');out=args.output.resolve();out.mkdir(exist_ok=False)
    fixture='''#include <stdbool.h>
    #include <stdint.h>
    #include <stddef.h>
    #include <stdlib.h>
    #include <errno.h>
    #include <assert.h>
    typedef uint8_t u8;typedef uint16_t u16;
    #define GFP_KERNEL 0
    u8 nondet_u8(void);u16 nondet_u16(void);int nondet_int(void);bool nondet_bool(void);
    struct usb_device{int unused;};
    struct sle_usb_dev{bool active;struct usb_device*udev;u8 command_request_type;u16 command_index;};
    static struct usb_device device;static struct sle_usb_dev context;
    static unsigned allocs,live,controls;static int expected_length,usb_result;static u16 expected_opcode;static int expected_timeout;
    static void*kmalloc(size_t n,int f){(void)f;assert(n>=4&&n<=65535);allocs++;void*p=malloc(n);if(p)live++;return p;}
    static void kfree(void*p){assert(p&&live==1);live--;free(p);}
    static void put_unaligned_le16(u16 n,u8*p){p[0]=(u8)n;p[1]=(u8)(n>>8);}
    static unsigned usb_sndctrlpipe(struct usb_device*d,int ep){assert(d==&device&&ep==0);return 0;}
    static void*bounded_copy(void*dest,const void*src,size_t n){assert(__CPROVER_r_ok(src,n));assert(__CPROVER_w_ok(dest,n));return dest;}
    #define memcpy bounded_copy
    static int usb_control_msg(struct usb_device*d,unsigned pipe,u8 request,u8 type,u16 value,u16 index,void*raw,u16 size,int timeout){
     assert(d==&device&&pipe==0&&request==0&&value==0&&type==context.command_request_type&&index==context.command_index&&timeout==expected_timeout);
     assert(expected_length>=0&&expected_length<=65531&&size==expected_length+4&&__CPROVER_r_ok(raw,size));
     u8*p=raw;assert(p[0]==(u8)expected_opcode&&p[1]==(u8)(expected_opcode>>8));assert(p[2]==(u8)expected_length&&p[3]==(u8)(expected_length>>8));controls++;usb_result=nondet_int();return usb_result;
    }
    '''+actual+'''
    static u8 payload[65531];
    int main(void){context.active=nondet_bool();context.udev=nondet_bool()?&device:NULL;context.command_request_type=nondet_u8();context.command_index=nondet_u16();expected_length=nondet_int();expected_opcode=nondet_u16();expected_timeout=nondet_int();const u8*p=nondet_bool()?payload:NULL;
     int ret=sle_usb_write_command_locked(&context,expected_opcode,p,expected_length,expected_timeout);
     assert(live==0&&controls<=1&&allocs<=1);
     if(!ret){assert(context.active&&context.udev&&controls==1&&expected_length>=0&&expected_length<=65531&&(expected_length==0||p)&&usb_result==4+expected_length);}
     if(!context.active||!context.udev){assert(ret==-ENODEV&&!controls&&!allocs);}
     else if(expected_length<0||(expected_length&&!p)){assert(ret==-EINVAL&&!controls&&!allocs);}
     else if(expected_length>65531){assert(ret==-EMSGSIZE&&!controls&&!allocs);}
     if(controls){assert(ret==(usb_result<0?usb_result:usb_result==expected_length+4?0:-EREMOTEIO));}
    }
    '''
    if args.weak_wlength:fixture=fixture.replace('if (plen > 65531)','if (plen > 65535)',1)
    f=out/'actual.c';f.write_text(fixture);cmd=['cbmc',str(f),'--bounds-check','--pointer-check','--signed-overflow-check','--unsigned-overflow-check','--memory-leak-check','--malloc-may-fail','--unwind','4','--unwinding-assertions','--json-ui']
    with (out/'solver.json').open('w') as output,(out/'stderr.log').open('w') as err:
     try:p=subprocess.run(cmd,stdout=output,stderr=err,timeout=args.budget_seconds);exit=p.returncode;timeout=False
     except subprocess.TimeoutExpired:exit=None;timeout=True
    try:d=json.loads((out/'solver.json').read_text())
    except json.JSONDecodeError:d=[]
    results=[x for b in d for x in b.get('result',[])];warnings=[b.get('messageText') for b in d if b.get('messageType') in ('WARNING','ERROR')];success=verdict(exit,timeout,d,(out/'stderr.log').read_text(),args.weak_wlength)=='MODEL_CHECKED_SCOPED'
    report={'status':'MODEL_CHECKED_SCOPED' if success else 'NOT_PROVEN','exit':exit,'timed_out':timeout,'properties':len(results),'warnings':warnings,'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=kernel,text=True).strip(),'source_sha256':hashlib.sha256(s.encode()).hexdigest(),'actual_function_sha256':hashlib.sha256(actual.encode()).hexdigest(),'generated_sha256':hashlib.sha256(fixture.encode()).hexdigest(),'tool':subprocess.check_output(['cbmc','--version'],text=True).strip(),'command':cmd,'bounds':'Full int32 parameter length/timeout/USB return, all u16 opcodes/indices/u8 target types; active/missing-device/null-params/allocation-failure states; valid parameter object65531 bytes; no loop-bound reduction of admitted length. Unwind4 for modeled dependencies.','assumptions':['Process-context caller pins context/device and holds I/O lock','memcpy abstracted to read/write-range assertions only: payload-byte provenance is NOT proved','little-endian primitive and USB APIs are controlled dependency models','No concurrency/URB/module/refcount/Host-credit/controller-Complete/Ready or hardware proof'],'implementation_regression':'actualC25 sanitizer cases incl65531/65532/65535, shorts/timeouts/alloc failures and C setup/header matching','physical_acceptance':False,'production_proof':not args.weak_wlength,'budget_seconds':args.budget_seconds}
    assert source.read_text()==s
    report['tool_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();report['weak_wlength']=args.weak_wlength
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ('status','properties','exit','timed_out')}));return 0 if success else 1

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--budget-seconds',type=int,default=60)
    parser.add_argument('--weak-wlength',action='store_true',help='deliberately ignore4-byte USB header; never a production proof')
    sys.exit(run(parser.parse_args()))
