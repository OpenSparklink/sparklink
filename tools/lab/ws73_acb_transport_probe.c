// SPDX-License-Identifier: GPL-2.0-only
/* Explicit VM-only external selftest module. Never built into production.
 * Real controller send/take only; no fabricated RX or completed-packet event.
 * This is a transport probe, not ordinary-user socket/business acceptance.
 */
#include <linux/delay.h>
#include <linux/errno.h>
#include <linux/init.h>
#include <linux/jiffies.h>
#include <linux/module.h>
#include <linux/random.h>
#include <linux/slab.h>
#include <linux/sparklink_native.h>
#include <linux/string.h>
#include <linux/unaligned.h>

static unsigned int ids[2], handles[2], rounds = 4;
static unsigned long long generations[2], lifetimes[2];
static unsigned int ni, nh, ng, nl;
module_param_array(ids, uint, &ni, 0400);
module_param_array(handles, uint, &nh, 0400);
module_param_array(generations, ullong, &ng, 0400);
module_param_array(lifetimes, ullong, &nl, 0400);
module_param(rounds, uint, 0400);

/* DTAP basic CUTC frame: TCID u8, flags u8, length LE16, experimental PI.
 * No dynamic TCID or capability negotiation is claimed by this raw probe.
 */
#define WS73_PROBE_FRAME_SIZE 62
static unsigned long probe_deadline;

static int send_frame(unsigned int side, const u8 *frame)
{
	unsigned long deadline = probe_deadline;
	int ret;

	do {
		ret = sparklink_native_acb_send(ids[side], generations[side],
			lifetimes[side], handles[side], frame, WS73_PROBE_FRAME_SIZE);
		if (ret != -EAGAIN)
			return ret;
		msleep(10);
	} while (time_before(jiffies, deadline));
	return -ETIMEDOUT;
}

static int receive_frame(unsigned int side, const u8 *expected)
{
	u8 *received;
	unsigned long deadline = probe_deadline;
	size_t length;
	int ret;

	received = kmalloc(2047, GFP_KERNEL);
	if (!received)
		return -ENOMEM;

	do {
		ret = sparklink_native_acb_take(ids[side], generations[side],
			lifetimes[side], handles[side], received, 2047, &length);
		if (!ret) {
			if (length == WS73_PROBE_FRAME_SIZE && !memcmp(received, expected, WS73_PROBE_FRAME_SIZE)) {
				ret = 0;
				goto out;
			}
			pr_info("WS73_ACB_PROBE_OTHER: side=%u length=%zu\n", side, length);
		} else if (ret != -EAGAIN) {
			goto out;
		}
		msleep(10);
	} while (time_before(jiffies, deadline));
	ret = -ETIMEDOUT;
out:
	kfree(received);
	return ret;
}

static int __init ws73_acb_transport_probe_init(void)
{
	u8 frame[WS73_PROBE_FRAME_SIZE], reply[WS73_PROBE_FRAME_SIZE];
	unsigned int round, source, peer;
	int ret;

	if (ni != 2 || nh != 2 || ng != 2 || nl != 2 || ids[0] == ids[1] ||
	    ids[0] > 65535 || ids[1] > 65535 || handles[0] > 0xfff ||
	    handles[1] > 0xfff || !generations[0] || !generations[1] ||
	    !lifetimes[0] || !lifetimes[1] || !rounds || rounds > 20)
		return -EINVAL;
	probe_deadline = jiffies + msecs_to_jiffies(45000);
	for (round = 0; round < rounds; round++) {
		source = round & 1;
		peer = source ^ 1;
		memset(frame, 0, sizeof(frame));
		frame[0] = 0x1f;
		put_unaligned_le16(WS73_PROBE_FRAME_SIZE - 4, frame + 2);
		frame[4] = 251;
		memcpy(frame + 5, "SLKACB1!", 8);
		get_random_bytes(frame + 13, 16);
		put_unaligned_le32(round, frame + 29);
		frame[33] = source;
		get_random_bytes(frame + 34, WS73_PROBE_FRAME_SIZE - 34);
		memcpy(reply, frame, WS73_PROBE_FRAME_SIZE);
		reply[33] |= 0x80;
		pr_info("WS73_ACB_PROBE_FRAME: round=%u source=%u bytes=%*phN\n",
			round, source, WS73_PROBE_FRAME_SIZE, frame);
		ret = send_frame(source, frame);
		if (ret)
			goto fail;
		ret = receive_frame(peer, frame);
		if (ret)
			goto fail;
		pr_info("WS73_ACB_PROBE_RECEIVED: round=%u side=%u\n", round, peer);
		ret = send_frame(peer, reply);
		if (ret)
			goto fail;
		ret = receive_frame(source, reply);
		if (ret)
			goto fail;
		pr_info("WS73_ACB_PROBE_ROUND: round=%u source=%u\n", round, source);
	}
	pr_info("WS73_ACB_PROBE_PASS: rounds=%u ordinary_socket=0 negotiation=0\n", rounds);
	return 0;
fail:
	pr_info("WS73_ACB_PROBE_FAIL: round=%u source=%u errno=%d\n", round, source, ret);
	return ret;
}

static void __exit ws73_acb_transport_probe_exit(void) { }
module_init(ws73_acb_transport_probe_init);
module_exit(ws73_acb_transport_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Explicit VM-only real WS73 ACB transport selftest");
MODULE_VERSION("1");
