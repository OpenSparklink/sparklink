/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual structures and functions injected by runner. Locks/time/ref lifetimes
 * are explicit boundaries; arbitrary denial/failure, never an always-OK USB. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <errno.h>
#include "sle_channel_state.h"
#include "sle_channel_grant.h"
#include "sle_fragment_cursor.h"
#define SL_SESSION_CHANNELS 2
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef int spinlock_t;
struct sock { int unused; };
struct kref { int unused; };
struct delayed_work { int unused; };
struct sk_buff_head { int unused; };
struct sk_buff { unsigned long cb[6]; };
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
static void spin_lock(spinlock_t *p) { (void)p; }
static void spin_unlock(spinlock_t *p) { (void)p; }
static unsigned long jiffies;
static bool expired;
static int time_after_eq(unsigned long now,unsigned long deadline) { (void)now;(void)deadline;return expired; }
/* @@STRUCTS@@ */
/* @@FUNCTIONS@@ */
unsigned int nondet_uint(void);
unsigned long long nondet_u64(void);
int nondet_int(void);
bool nondet_bool(void);
struct sl_channel_grant nondet_grant(void);
static int calls, submit_result;
static int submit(void *p) { (void)p;calls++;return submit_result; }
int main(void)
{
    struct sl_connection_session s={0};
    struct sl_socket_binding binding={0};
    struct sk_buff packet={0}, other={0};
    unsigned int slot=nondet_bool();
    struct sl_basic_channel *c=&s.channels[slot];
    s.controller=nondet_uint()&65535;s.handle=nondet_uint()&65535;
    s.generation=nondet_u64();s.lifetime=nondet_u64();s.epoch=nondet_u64();
    s.progress.phase=(enum sl_channel_phase)(nondet_uint()%5);
    c->local_tcid=nondet_uint()&255;c->remote_tcid=nondet_uint()&255;c->pi=nondet_uint()&255;
    c->binding.bound=nondet_uint();c->binding.retired=nondet_uint();
    c->sk=nondet_bool()?&binding.sk:NULL;
    binding.grant=nondet_grant();s.tx_grant=nondet_grant();
    /* Explore valid and arbitrary mismatching grants, without assuming authority. */
    struct sl_grant_scope observed={.controller=s.controller,.handle=s.handle,.generation=s.generation,
        .lifetime=s.lifetime,.epoch=s.epoch,.local_tcid=c->local_tcid,.remote_tcid=c->remote_tcid,.pi=c->pi};
    if(nondet_bool()) {s.tx_grant.scope=observed;s.tx_grant.directions=1;s.tx_grant.security=0;}
    if(nondet_bool()) {binding.grant.scope=observed;binding.grant.directions=1;binding.grant.security=0;}
    s.tx_started=nondet_bool();bool before=s.tx_started;
    s.fragment_slot=nondet_bool()?slot:1-slot;
    s.tx_inflight=nondet_bool()?&packet:&other;
    expired=nondet_bool();submit_result=nondet_int();
    struct sl_submit_scope permission={.session=&s,.channel=c,.operation=&packet};
    int result=sl_session_submit(&permission,submit,NULL);
    assert(calls<=1);
    if(calls) {
        assert(sl_channel_active(s.progress));
        assert(s.tx_inflight==&packet&&s.fragment_slot==(int)slot);
        assert(sl_grant_permits(&s.tx_grant,observed,SL_GRANT_TX)&&!expired);
        assert(before||(sl_binding_live(c->binding)&&sl_permits(&s,c,SL_GRANT_TX)));
        assert(result==submit_result);
    }
    if(!calls||result) assert(s.tx_started==before);
    else assert(s.tx_started);
    if(!before&&!sl_binding_live(c->binding)) assert(!calls);
    if(expired||!sl_grant_permits(&s.tx_grant,observed,SL_GRANT_TX)) assert(!calls);
    /* A last-fd retirement does not erase an already begun obligation. The
     * Runtime lease/generation/connection gate is outside this C predicate. */
    if(before&&sl_channel_active(s.progress)&&s.tx_inflight==&packet&&s.fragment_slot==(int)slot&&
       !expired&&sl_grant_permits(&s.tx_grant,observed,SL_GRANT_TX)) assert(calls==1);
}
