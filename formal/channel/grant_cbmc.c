/* SPDX-License-Identifier: GPL-2.0-only */
/* Production fd grant pure constructor and identity/direction decision.
 * No Host epoch, kref/VFS, trust/security-state or hardware refinement claim. */
#include <assert.h>
#include "../../../linux/net/sparklink/sle_channel_grant.h"
extern unsigned int nondet_uint(void);
extern unsigned long long nondet_ull(void);
static struct sl_grant_scope arbitrary_scope(void)
{
 return (struct sl_grant_scope){.generation=nondet_ull(),.lifetime=nondet_ull(),.epoch=nondet_ull(),
  .controller=nondet_uint(),.handle=nondet_uint(),.local_tcid=nondet_uint(),.remote_tcid=nondet_uint(),.pi=nondet_uint()};
}
int main(void)
{
 struct sl_channel_grant initial={0};struct sl_grant_scope observed=arbitrary_scope();unsigned int operation=nondet_uint();
 assert(!sl_grant_permits(&initial,observed,operation));
 struct sl_grant_scope request=arbitrary_scope();unsigned int directions=nondet_uint(),security=nondet_uint();
 struct sl_channel_grant grant={.scope=arbitrary_scope(),.directions=nondet_uint(),.security=nondet_uint()};
 struct sl_channel_grant before=grant;
 int accepted=sl_grant_init(&grant,request,directions,security);
 assert(accepted == (sl_grant_scope_valid(request) && directions && !(directions & ~3U) && !security));
 if(!accepted){
  assert(grant.directions==before.directions && grant.security==before.security);
  assert(grant.scope.controller==before.scope.controller && grant.scope.generation==before.scope.generation);
  assert(grant.scope.lifetime==before.scope.lifetime && grant.scope.epoch==before.scope.epoch && grant.scope.handle==before.scope.handle);
  assert(grant.scope.local_tcid==before.scope.local_tcid && grant.scope.remote_tcid==before.scope.remote_tcid && grant.scope.pi==before.scope.pi);
 } else {
  assert(sl_grant_permits(&grant,request,SL_GRANT_TX) == !!(directions & SL_GRANT_TX));
  assert(sl_grant_permits(&grant,request,SL_GRANT_RX) == !!(directions & SL_GRANT_RX));
 }
 if(sl_grant_permits(&grant,observed,operation)){
  assert(operation==SL_GRANT_TX || operation==SL_GRANT_RX);
  assert(!grant.security && (grant.directions & operation) && !(grant.directions & ~3U));
  assert(grant.scope.controller==observed.controller && grant.scope.generation==observed.generation);
  assert(grant.scope.lifetime==observed.lifetime && grant.scope.epoch==observed.epoch && grant.scope.handle==observed.handle);
  assert(grant.scope.local_tcid==observed.local_tcid && grant.scope.remote_tcid==observed.remote_tcid && grant.scope.pi==observed.pi);
 }
 return 0;
}
