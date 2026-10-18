/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual bounded production channel key map, no queue/concurrency/RF proof. */
#include <assert.h>
#include "../../../linux/net/sparklink/sle_channel_table.h"
extern unsigned int nondet_uint(void);
int main(void)
{
    unsigned int local = nondet_uint(), remote = nondet_uint(), pi = nondet_uint();
    int slot = sl_channel_key_slot(local, remote, pi);
    assert(slot == -1 || (slot >= 0 && slot < SL_SESSION_CHANNELS));
    if (slot == (int)SL_CHANNEL_USER_SLOT)
        assert(local == 31 && remote == 31 && pi == 241);
    if (slot == (int)SL_CHANNEL_SMTC_SLOT)
        assert(local == 10 && remote == 10 && pi == 0);
    if (slot >= 0) assert(sl_channel_rx_slot(local, pi) == slot);
    assert(sl_channel_key_slot(31, 31, 241) == SL_CHANNEL_USER_SLOT);
    assert(sl_channel_key_slot(10, 10, 0) == SL_CHANNEL_SMTC_SLOT);
    assert(SL_CHANNEL_USER_SLOT != SL_CHANNEL_SMTC_SLOT);
    assert(sl_channel_rx_slot(2, 0) == -1); /* CMTC is never fd data. */
    return 0;
}
