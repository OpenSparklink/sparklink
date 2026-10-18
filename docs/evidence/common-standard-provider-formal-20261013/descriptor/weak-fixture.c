// SPDX-License-Identifier: GPL-2.0-only
/* Exercise the actual production validator, not a second implementation.
 * This pure host test proves no module/refcount/Runtime/callback barriers.
 */
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include "/home/sanchuanhehe/Documents/opensparklink/.dev/common-standard-provider-descriptor-proof/weak.h"

static void retain(void *c) { (void)c; }
static int open_backend(void *c, u16 id, u64 generation)
{ (void)c; (void)id; (void)generation; return 0; }
static int command(void *c, u16 op, const u8 *p, size_t n)
{ (void)c; (void)op; (void)p; (void)n; return 0; }
static int discovery(void *c, const struct sparklink_discovery_request *r,
                     struct sparklink_discovery_plan *p)
{ (void)c; (void)r; (void)p; return 0; }
static int step(void *c, unsigned int op, unsigned int s, unsigned int count,
                u16 opcode, const u8 *p, size_t n)
{ (void)c; (void)op; (void)s; (void)count; (void)opcode; (void)p; (void)n; return 0; }
static int connection(void *c, const struct sparklink_connection_request *r,
                      struct sparklink_connection_plan *p)
{ (void)c; (void)r; (void)p; return 0; }
static int validate_connection(void *c, unsigned int op, u16 opcode,
                               const u8 *p, size_t n)
{ (void)c; (void)op; (void)opcode; (void)p; (void)n; return 0; }
static int acb(void *c, struct sparklink_native_tx_ticket *t, u16 h,
               const u8 *p, size_t n)
{ (void)c; (void)t; (void)h; (void)p; (void)n; return 0; }

int main(void)
{
 struct sparklink_native_ops ops = { .get=retain, .put=retain, .open=open_backend,
  .close=retain, .validate_command=command, .send_command=command,
  .prepare_discovery=discovery, .validate_discovery_step=step,
  .prepare_connection=connection, .validate_connection=validate_connection,
  .send_acb=acb };
 struct sparklink_backend_descriptor valid = { .version=SPARKLINK_BACKEND_VERSION,
  .size=sizeof(valid), .bus=SPARKLINK_BACKEND_USB, .capabilities=SPARKLINK_BACKEND_CAPS,
  .info={ .profile=SPARKLINK_NATIVE_WS73_HCC, .acb_length=254, .acb_count=4 },
  .ops=&ops, .context=&ops }, d;
 unsigned int checks=0;
#define CHECK(expr, expected) do { int result=(expr); ++checks; \
 if (result!=(expected)) { fprintf(stderr,"check %u: got %d expected %d\n",checks,result,expected); return EXIT_FAILURE; } } while (0)
#define REJECT(field, value, error) do { d=valid; d.field=(value); CHECK(sparklink_backend_validate(&d),error); } while (0)
 CHECK(sparklink_backend_validate(&valid),0);
 CHECK(sparklink_backend_validate(NULL),-EINVAL);
 REJECT(version,0,-EOPNOTSUPP); REJECT(version,2,-EOPNOTSUPP);
 REJECT(size,sizeof(valid)-1,-EOPNOTSUPP); REJECT(size,sizeof(valid)+1,-EOPNOTSUPP);
 REJECT(bus,0,-EOPNOTSUPP); REJECT(bus,3,-EOPNOTSUPP);
 REJECT(info.profile,0,-EOPNOTSUPP); REJECT(info.profile,2,-EOPNOTSUPP);
 REJECT(capabilities,8,-EOPNOTSUPP); REJECT(ops,NULL,-EINVAL); REJECT(context,NULL,-EINVAL);
 REJECT(info.acb_length,0,-EPROTO); REJECT(info.acb_count,0,-EPROTO);
 REJECT(info.acb_length,2048,-EPROTO); REJECT(info.icb_length,1,-EPROTO);
 REJECT(info.icb_count,1,-EPROTO);
 for (unsigned int caps=0;caps<8;++caps) {
  d=valid; d.capabilities=caps;
  CHECK(sparklink_backend_validate(&d),caps==7 ? 0 : -EINVAL);
 }
#define MISSING(field) do { struct sparklink_native_ops copy=ops; copy.field=NULL; d=valid; d.ops=&copy; CHECK(sparklink_backend_validate(&d),-EINVAL); } while (0)
 MISSING(get); MISSING(put); MISSING(open); MISSING(close); MISSING(validate_command);
 MISSING(send_command); MISSING(prepare_discovery); MISSING(validate_discovery_step);
 MISSING(prepare_connection); MISSING(validate_connection); MISSING(send_acb);
 d=valid; d.bus=SPARKLINK_BACKEND_TEST; d.capabilities=0;
 ops.prepare_discovery=NULL; ops.validate_discovery_step=NULL;
 ops.prepare_connection=NULL; ops.validate_connection=NULL; ops.send_acb=NULL;
 CHECK(sparklink_backend_validate(&d),0);
 d.info.profile=SPARKLINK_NATIVE_STANDARD_DLI;CHECK(sparklink_backend_validate(&d),0);d.capabilities=SPARKLINK_BACKEND_ACB;CHECK(sparklink_backend_validate(&d),-EOPNOTSUPP);
 printf("BACKEND_DESCRIPTOR_PASS checks=%u scope=production-pure-validator\n",checks);
 return EXIT_SUCCESS;
}
