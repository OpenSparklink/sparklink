/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _SPARKLINK_VIRTUAL_CODEC_H
#define _SPARKLINK_VIRTUAL_CODEC_H

#include <linux/sparklink_native.h>

/* Emulation exists only in the explicitly selected virtual test driver.
 * Same standard DLI framing/Host ingress as the standard provider. There is
 * no method echo, mutation success, or RF/data claim. Stateless validation
 * is used at admission and again before the actual bounded enqueue.
 */
static inline int sparklink_virtual_validate(u16 opcode, const u8 *params,
					    size_t length)
{
	if (length && !params)
		return -EINVAL;
	switch (opcode) {
	case 0x0401: case 0x0402: case 0x0403: case 0x0404:
		return length ? -EINVAL : 0;
	case 0x0406:
		if (length != 1)
			return -EINVAL;
		return params[0] == 0 || (params[0] >= 2 && params[0] <= 6) ? 0 : -EINVAL;
	default:
		return 0; /* deliberately removed unsupported-opcode guard */
	}
}

/* Caller supplies a live 18-byte output. Success returns its exact length;
 * rejection leaves output unchanged. Metadata is immutable per controller.
 */
static inline int sparklink_virtual_reply(const struct sparklink_native_info *info,
					 u16 opcode, const u8 *params,
					 size_t length, u8 out[18])
{
	u8 reply[18] = { 2, 0, 4, 0, (u8)opcode, (u8)(opcode >> 8), 1, 0 };
	size_t result = 0, i;
	int ret = sparklink_virtual_validate(opcode, params, length);

	if (ret)
		return ret;
	switch (opcode) {
	case 0x0401:
		reply[8] = 0xff; /* Emulated command parameter budget, LE16. */
		result = 2;
		break;
	case 0x0402:
		/* No emulated data transport: both buffer pairs are zero. */
		result = 6;
		break;
	case 0x0403:
		result = sizeof(info->features);
		for (i = 0; i < result; i++)
			reply[8 + i] = info->features[i];
		break;
	case 0x0404:
		result = sizeof(info->version);
		for (i = 0; i < result; i++)
			reply[8 + i] = info->version[i];
		break;
	case 0x0406:
		result = sizeof(info->address);
		for (i = 0; i < result; i++)
			reply[8 + i] = info->address[i];
		break;
	}
	reply[2] = 4 + result;
	for (i = 0; i < 8 + result; i++)
		out[i] = reply[i];
	return 8 + result;
}

#endif
