/* SPDX-License-Identifier: GPL-2.0-only */
/* Test-only exact permission witness from4b6 Kernel header;no default Kernel API. */
#ifndef SL_TEST_RETIRED_SSAP_PERMISSIONS_H
#define SL_TEST_RETIRED_SSAP_PERMISSIONS_H
#include <linux/types.h>
/* T/XS 20001-2025 V1.2.0 table 32: 32-bit operation indicator.
 * Permission semantics retained for userspace service code and regression.
 * Descriptor permissions must never be truncated into that staging API.
 */
#define SL_SSAP_OP_READ             (1U << 0)
#define SL_SSAP_OP_WRITE_NO_RSP     (1U << 1)
#define SL_SSAP_OP_WRITE_WITH_RSP   (1U << 2)
#define SL_SSAP_OP_NOTIFY           (1U << 3)
#define SL_SSAP_OP_INDICATE         (1U << 4)
#define SL_SSAP_OP_BROADCAST        (1U << 5)
#define SL_SSAP_OP_DESC_WRITABLE    (1U << 8)
#define SL_SSAP_OP_CLIENT_CFG_WR    (1U << 9)
#define SL_SSAP_OP_SERVER_CFG_WR    (1U << 10)
#define SL_SSAP_OP_VALID_MASK       (0x73fU)

static inline int sl_ssap_ops_valid(__u32 ops)
{
	return !(ops & ~SL_SSAP_OP_VALID_MASK);
}

static inline int sl_ssap_ops_allows(__u32 ops, __u32 required)
{
	return sl_ssap_ops_valid(ops) && sl_ssap_ops_valid(required) &&
	       (ops & required) == required;
}

static inline int sl_ssap_ops_fits_legacy(__u32 ops)
{
	return sl_ssap_ops_valid(ops) && !(ops & ~0xffU);
}
#endif
