/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual production binding transitions, not a verification-only substitute. */
#include <assert.h>
#include "../../../linux/net/sparklink/sle_channel_state.h"
extern unsigned int nondet_uint(void);
static int invariant(struct sl_binding_progress b)
{
    return b.bound <= 1 && b.retired <= 1 && b.busy <= 1 && (!b.retired || !b.bound);
}
int main(void)
{
    struct sl_binding_progress initial = {0};
    assert(invariant(initial));
    assert(sl_binding_attach(&initial));
    assert(sl_binding_start_tx(&initial));
    sl_binding_retire(&initial);
    assert(initial.busy == 1 && !sl_binding_live(initial));
    assert(!sl_binding_attach(&initial));
    sl_binding_finish_tx(&initial);
    assert(invariant(initial) && !initial.busy);
    struct sl_binding_progress b = {nondet_uint(), nondet_uint(), nondet_uint()};
    __CPROVER_assume(invariant(b));
    struct sl_binding_progress before = b;
    unsigned int event = nondet_uint();
    __CPROVER_assume(event < 4);
    switch(event) {
    case 0: sl_binding_attach(&b); break;
    case 1: sl_binding_retire(&b); break;
    case 2: sl_binding_start_tx(&b); break;
    default: sl_binding_finish_tx(&b); break;
    }
    assert(invariant(b));
    if(before.retired) assert(b.retired && !b.bound);
    unsigned int queued = nondet_uint(), limit = nondet_uint();
    if(sl_binding_space(b, queued, limit)) {
        assert(sl_binding_live(b));
        assert(queued < limit && b.busy < limit - queued);
        assert(queued + b.busy < limit);
    }
    return 0;
}
