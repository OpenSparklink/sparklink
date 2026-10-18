/* SPDX-License-Identifier: GPL-2.0-only */
/* Harness includes the production transitions; no alternate implementation. */
#include <assert.h>
#include "../../../linux/net/sparklink/sle_channel_state.h"
extern unsigned int nondet_uint(void);
extern int nondet_int(void);

static int invariant(struct sl_channel_progress s)
{
	if (s.phase < SL_CH_UNBOUND || s.phase > SL_CH_CLOSED ||
	    s.request_submitted > 1 || s.peer_capability > 1 || s.response_submitted > 1)
		return 0;
	if (s.peer_capability && !s.request_submitted)
		return 0;
	if (sl_channel_active(s)) {
		if (!s.maximum || s.maximum > 2042 || !s.mtu || s.mtu > s.maximum)
			return 0;
		if ((s.phase == SL_CH_OPEN) !=
		    (s.request_submitted && s.peer_capability && s.response_submitted))
			return 0;
	}
	return 1;
}
static void step(struct sl_channel_progress *s, unsigned int event,
	unsigned int mtu, int expired)
{
	switch (event) {
	case 0: sl_channel_request_submitted(s, expired); break;
	case 1: sl_channel_peer_capability(s, mtu, expired); break;
	case 2: sl_channel_response_submitted(s, expired); break;
	case 3: sl_channel_close(s); break;
	case 4: sl_channel_fail(s); break;
	case 5: sl_channel_start(s, mtu); break;
	default: sl_channel_tick(s, expired); break;
	}
}
int main(void)
{
	struct sl_channel_progress initial = {0};
	struct sl_channel_progress before, after;
	unsigned int event = nondet_uint(), mtu = nondet_uint();
	int expired = nondet_int();

	sl_channel_start(&initial, nondet_uint());
	assert(invariant(initial)); /* constructor: all unsigned maximum inputs */
	before.phase = nondet_uint();
	before.maximum = nondet_uint(); before.mtu = nondet_uint();
	before.request_submitted = nondet_uint();
	before.peer_capability = nondet_uint(); before.response_submitted = nondet_uint();
	__CPROVER_assume(invariant(before)); /* induction domain, not hardware perfection */
	after = before;
	step(&after, event, mtu, expired);
	assert(invariant(after));
	if (before.phase == SL_CH_CLOSED)
		assert(after.phase == SL_CH_CLOSED);
	if (before.phase == SL_CH_FAILED)
		assert(after.phase == SL_CH_FAILED || after.phase == SL_CH_CLOSED);
	if (before.phase == SL_CH_NEGOTIATING && expired &&
	    (event <= 2 || event > 5))
		assert(after.phase == SL_CH_FAILED);
	return 0;
}
