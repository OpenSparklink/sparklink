/* SPDX-License-Identifier: GPL-2.0-only
 * Production validator proof only. Pointers are valid kernel provider-owned
 * objects for the duration of registration; no callback is executed here.
 * No reference, module, concurrency, Runtime or hardware proof follows.
 */
#define main descriptor_example_main
#include "/home/sanchuanhehe/Documents/opensparklink/.dev/common-standard-provider-descriptor-proof/weak-fixture.c"
#undef main
extern unsigned int nondet_uint(void);
extern unsigned short nondet_ushort(void);
extern unsigned char nondet_uchar(void);
extern _Bool nondet_bool(void);
void proof(void)
{
 struct sparklink_native_ops ops = { .get=retain, .put=retain, .open=open_backend,
  .close=retain, .validate_command=command, .send_command=command,
  .prepare_discovery=discovery, .validate_discovery_step=step,
  .prepare_connection=connection, .validate_connection=validate_connection,
  .send_acb=acb };
 struct sparklink_backend_descriptor d = { .version=nondet_uint(),
  .size=nondet_uint(), .bus=nondet_uint(), .capabilities=nondet_uint(),
  .info={ .profile=nondet_uint(), .acb_length=nondet_ushort(),
   .icb_length=nondet_ushort(), .acb_count=nondet_uchar(), .icb_count=nondet_uchar() },
  .ops=&ops, .context=&ops };
 if(nondet_bool())ops.prepare_discovery=NULL;
 if(nondet_bool())ops.validate_discovery_step=NULL;
 if(nondet_bool())ops.prepare_connection=NULL;
 if(nondet_bool())ops.validate_connection=NULL;
 if(nondet_bool())ops.send_acb=NULL;
 if(nondet_bool())ops.get=NULL;
 if(nondet_bool())ops.put=NULL;
 if(nondet_bool())ops.open=NULL;
 if(nondet_bool())ops.close=NULL;
 if(nondet_bool())ops.validate_command=NULL;
 if(nondet_bool())ops.send_command=NULL;
 if(nondet_bool())d.ops=NULL;
 if(nondet_bool())d.context=NULL;
 int result=sparklink_backend_validate(&d);
 if(!result) {
  __CPROVER_assert(d.version==1 && d.size==sizeof(d),"accepted version and exact size");
  __CPROVER_assert(d.bus==1 || d.bus==2,"accepted implemented provenance only");
  __CPROVER_assert(d.info.profile<=1 && !(d.capabilities & ~7U),"accepted dialect and capability bits");
  __CPROVER_assert(d.info.profile!=0 || d.capabilities==0,"standard query profile has no unqualified typed or data capability");
  __CPROVER_assert(d.ops && d.context && ops.get && ops.put && ops.open && ops.close && ops.validate_command && ops.send_command,"accepted required callbacks");
  __CPROVER_assert(!!ops.prepare_discovery==!!ops.validate_discovery_step && !!ops.prepare_connection==!!ops.validate_connection,"paired typed callbacks");
  __CPROVER_assert(!!(d.capabilities&1)==!!ops.prepare_discovery && !!(d.capabilities&2)==!!ops.prepare_connection && !!(d.capabilities&4)==!!ops.send_acb,"capability matches operations");
  __CPROVER_assert(d.info.acb_length<=2047 && d.info.icb_length<=2047 && (!d.info.acb_length)==(!d.info.acb_count) && (!d.info.icb_length)==(!d.info.icb_count),"finite consistent buffers");
  __CPROVER_assert(!(d.capabilities&4) || d.info.acb_count,"ACB requires queried data buffers");
 }
 __CPROVER_assert(result==0 || result==-EINVAL || result==-EOPNOTSUPP || result==-EPROTO,"explicit rejection only");
}
