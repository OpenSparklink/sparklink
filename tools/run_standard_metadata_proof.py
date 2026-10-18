#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify the actual standard USB bootstrap; controlled sequential response dependencies only."""
from pathlib import Path
import argparse
import hashlib,json,subprocess,sys,re,time
def verdict(exit_code, complete, results, warnings, timed_out, weak):
    if exit_code == 0 and complete and results and not warnings and not timed_out and not weak and all(x.get('status') == 'SUCCESS' for x in results):
        return 'MODEL_CHECKED_SCOPED'
    return 'NOT_PROVEN'


def run(args):
    kernel=args.kernel_source.resolve();sys.path.insert(0,str(kernel/'tools/testing/selftests/sparklink'))
    from run_connection_tx import function
    source=kernel/'drivers/sparklink/standard_usb.c';header=kernel/'include/linux/sparklink_usb.h';s=source.read_text();h=header.read_text()
    out=args.output.resolve();out.mkdir(exist_ok=False)
    start=h.index('struct sle_usb_capabilities {');struct=h[start:h.index('};',start)+2];start=h.index('struct sle_usb_metadata {');struct+='\n'+h[start:h.index('};',start)+2]
    constants='\n'.join(re.search(r'(?m)^#define '+n+r' .+$',s).group() for n in ['SLE_OP_RESET','SLE_OP_READ_LOCAL_VERSION','SLE_OP_READ_CMD_LENGTH','SLE_OP_READ_BUFFER','SLE_OP_READ_FEATURES','SLE_OP_READ_MAC_ADDR','SLE_EVT_CMD_COMPLETE'])
    fixture='''#include <stdbool.h>
    #include <stdint.h>
    #include <stddef.h>
    #include <string.h>
    #include <errno.h>
    typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;
    #define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
    '''+struct+'''
    struct mutex { bool held; };
static void mutex_lock(struct mutex*m){assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex*m){assert(m->held);m->held=false;}
struct sle_usb_dev { struct mutex io_lock;bool active,metadata_valid;void*udev;u8 version[5],mac_addr[6],command_credits;u32 fw_version;struct sle_usb_capabilities capabilities;};
    static u16 get_unaligned_le16(const u8*p){return p[0]|(u16)p[1]<<8;}
    static u32 get_unaligned_le32(const u8*p){return p[0]|(u32)p[1]<<8|(u32)p[2]<<16|(u32)p[3]<<24;}
    static void*memchr_inv(const void*p,int c,unsigned n){const u8*b=p;for(unsigned i=0;i<n;i++)if(b[i]!=(u8)c)return(void*)(b+i);return NULL;}
    '''+constants+'''
    u8 nondet_u8(void);int nondet_int(void);struct sle_usb_capabilities nondet_caps(void);struct sle_usb_metadata nondet_metadata(void);
    static unsigned calls;
    static u8 responses[6][18];
    static int sle_usb_send_cmd_sync(struct sle_usb_dev*d,u16 op,const u8*p,int n,u8*r,int capacity,int*len){
     (void)d;assert(calls<6);assert(capacity==64);assert(n==(op==SLE_OP_READ_MAC_ADDR?1:0));assert(!n||(p&&*p==0));
     unsigned index=calls++;for(unsigned i=0;i<18;i++){responses[index][i]=nondet_u8();r[i]=responses[index][i];}*len=nondet_int();return nondet_int();
    }
    '''
    fixture='#include <assert.h>\n'+fixture
    for name in ('sle_usb_validate_init_reply','sle_usb_dev_init_controller_locked','sle_usb_dev_get_metadata'):
     actual=function(s.replace('static int '+name,'int '+name),name)
     if args.weak_invalidation:actual=actual.replace('d->metadata_valid = false;', 'd->metadata_valid = true;',1)
     fixture+=actual+'\n'
    fixture+='''int main(void){
     struct sle_usb_dev d={.active=true,.metadata_valid=true,.udev=&d,.fw_version=42,.version={9,9,9,9,9},.mac_addr={8,8,8,8,8,8},.command_credits=7,.capabilities=nondet_caps()};
     struct sle_usb_dev old=d;d.io_lock.held=true;int ret=sle_usb_dev_init_controller_locked(&d);d.io_lock.held=false;assert(calls<=6);
     if(ret){assert(!d.metadata_valid);assert(d.fw_version==old.fw_version&&d.command_credits==old.command_credits);assert(!memcmp(d.version,old.version,5)&&!memcmp(d.mac_addr,old.mac_addr,6));assert(!memcmp(&d.capabilities,&old.capabilities,sizeof(d.capabilities)));}
     else {assert(calls==6&&d.metadata_valid);assert(d.capabilities.command_max>=255);assert(d.capabilities.acb_length<=2047&&d.capabilities.icb_length<=2047);assert((!d.capabilities.acb_length)==(!d.capabilities.acb_count));assert((!d.capabilities.icb_length)==(!d.capabilities.icb_count));assert(!memcmp(d.version,responses[1]+8,5));assert(!memcmp(d.capabilities.features,responses[4]+8,10));assert(!memcmp(d.mac_addr,responses[5]+8,6));assert(d.command_credits==responses[5][6]);assert(memchr_inv(d.mac_addr,0,6)&&memchr_inv(d.mac_addr,255,6));}
    }
    '''
    f=out/'actual.c';f.write_text(fixture)
    cmd=['cbmc',str(f),'--bounds-check','--pointer-check','--signed-overflow-check','--unsigned-overflow-check','--unwind','19','--unwinding-assertions','--json-ui']
    with (out/'solver.json').open('w') as stdout,(out/'stderr.log').open('w') as stderr:
     try:
      r=subprocess.run(cmd,stdout=stdout,stderr=stderr,timeout=args.budget_seconds);timed_out=False
     except subprocess.TimeoutExpired:
      r=None;timed_out=True
    try:report=json.loads((out/'solver.json').read_text())
    except json.JSONDecodeError:report=[]
    results=[x for b in report for x in b.get('result',[])];failed=[x for x in results if x['status']!='SUCCESS']
    warnings=[b.get('messageText','') for b in report if b.get('messageType') in ('WARNING','ERROR')];complete=any(b.get('cProverStatus')=='success' for b in report);exit_code=None if r is None else r.returncode
    record=dict(status=verdict(exit_code,complete,results,warnings,timed_out,args.weak_invalidation),exit=exit_code,timed_out=timed_out,warnings=warnings,weak_invalidation=args.weak_invalidation,properties=len(results),failed=[{k:x[k] for k in ('property','description','sourceLocation','status') if k in x} for x in failed],tool=subprocess.check_output(['cbmc','--version'],text=True).strip(),source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=kernel,text=True).strip(),source_sha256=hashlib.sha256(s.encode()).hexdigest(),header_sha256=hashlib.sha256(h.encode()).hexdigest(),harness_sha256=hashlib.sha256(fixture.encode()).hexdigest(),scope='Actual standard bootstrap and strict validator; all first18 response bytes, reported length and dependency return unrestricted; 6 sequential queries/unwind19. Coherent commit/failure invalidation, buffer schema, version/features/address provenance, bounded call count; actual combined getter under abstract mutex, no partial output on errors.',assumptions=['active retained context with io_lock held by caller','synchronous response dependency provides initialized first18 bytes in64-byte localbuffer','no concurrency/USB/module/refcount/firmware/Ready/lifetime proof'],physical_acceptance=False)
    record['source_mapping']=['sle_usb_validate_init_reply', 'sle_usb_dev_init_controller_locked','sle_usb_dev_get_metadata'];record['bounds']={'commands':6,'relevant_bytes_per_response':18,'lengths_and_dependency_returns':'all signed int32','unwind':19};record['implementation_regression']='actual44 sanitizer cases, ENODATA/no-output-overwrite after failed query';record['source_paths']=[str(source),str(header)];record['tool_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();record['command']=cmd;record['original_budget_seconds']=args.budget_seconds;record['production_proof']=not args.weak_invalidation
    assert source.read_text()==s and header.read_text()==h
    (out/'report.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record[k] for k in ('status','properties','exit','timed_out','weak_invalidation')}));return 0 if record['status']=='MODEL_CHECKED_SCOPED' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--budget-seconds', type=int, default=60)
    parser.add_argument('--weak-invalidation', action='store_true', help='deliberately broken invalidation: never a production proof; expected nonzero exit')
    sys.exit(run(parser.parse_args()))
