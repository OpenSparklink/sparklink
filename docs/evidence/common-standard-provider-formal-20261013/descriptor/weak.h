/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LINUX_SPARKLINK_BACKEND_H
#define _LINUX_SPARKLINK_BACKEND_H

#include <linux/errno.h>
#include <linux/sparklink_native.h>

#define SPARKLINK_BACKEND_VERSION 1U
#define SPARKLINK_BACKEND_USB 1U
#define SPARKLINK_BACKEND_TEST 2U
#define SPARKLINK_BACKEND_DISCOVERY 1U
#define SPARKLINK_BACKEND_CONNECTION 2U
#define SPARKLINK_BACKEND_ACB 4U
#define SPARKLINK_BACKEND_CAPS 7U

/* Internal, unpublished driver/core contract. All pointers are live for the
 * call; descriptor, metadata and ops are copied before retaining context.
 * TEST identifies an explicit test provider, never a hardware capability.
 * Other buses/dialects require an implemented ingress and admission contract
 * before adding an identifier here. Registration creates Setup, not Ready.
 * get/put and open/close/submit retain the native lifetime rules; the provider
 * must stop and join RX/completions before close returns. Core owns generation,
 * admission and credits. Bus provenance grants no command permission.
 */
struct sparklink_backend_descriptor {
	u32 version, size, bus, capabilities;
	struct sparklink_native_info info;
	const struct sparklink_native_ops *ops;
	void *context;
};

/* Pure production validation, shared with selftests. No allocation, callback,
 * module reference or Runtime publication occurs before this succeeds.
 */
static inline int sparklink_backend_validate(const struct sparklink_backend_descriptor *d)
{
	const struct sparklink_native_ops *o;

	if (!d)
		return -EINVAL;
	if (d->version != SPARKLINK_BACKEND_VERSION || d->size != sizeof(*d))
		return -EOPNOTSUPP;
	if (d->bus != SPARKLINK_BACKEND_USB && d->bus != SPARKLINK_BACKEND_TEST)
		return -EOPNOTSUPP;
	if ((d->info.profile != SPARKLINK_NATIVE_WS73_HCC &&
	     d->info.profile != SPARKLINK_NATIVE_STANDARD_DLI) ||
	    (d->capabilities & ~SPARKLINK_BACKEND_CAPS))
		return -EOPNOTSUPP;
	/* Standard typed policy/ACB ingress still needs its own qualification. */
	if (0)
		return -EOPNOTSUPP;
	o = d->ops;
	if (!o || !d->context || !o->get || !o->put || !o->open || !o->close ||
	    !o->validate_command || !o->send_command ||
	    !!o->prepare_discovery != !!o->validate_discovery_step ||
	    !!o->prepare_connection != !!o->validate_connection)
		return -EINVAL;
	if (!!(d->capabilities & SPARKLINK_BACKEND_DISCOVERY) != !!o->prepare_discovery ||
	    !!(d->capabilities & SPARKLINK_BACKEND_CONNECTION) != !!o->prepare_connection ||
	    !!(d->capabilities & SPARKLINK_BACKEND_ACB) != !!o->send_acb)
		return -EINVAL;
	if ((d->info.acb_length == 0) != (d->info.acb_count == 0) ||
	    (d->info.icb_length == 0) != (d->info.icb_count == 0) ||
	    d->info.acb_length > 2047 || d->info.icb_length > 2047 ||
	    ((d->capabilities & SPARKLINK_BACKEND_ACB) && !d->info.acb_count))
		return -EPROTO;
	return 0;
}

int sparklink_backend_register(const struct sparklink_backend_descriptor *descriptor,
			      struct sparklink_native_identity *identity);

/* Pending diagnostics have no Ready/credit assertion. bus is the public bus
 * value (USB=4, TEST=6), profile identifies the phase namespace, phase is raw
 * provider diagnostic data, error is zero or a negative errno. */
struct sparklink_backend_pending { u32 bus, profile, phase; int error; };
int sparklink_backend_reserve(u32 bus, u32 profile, struct sparklink_native_identity *identity);
int sparklink_backend_register_reserved(const struct sparklink_backend_descriptor *descriptor,
                                       const struct sparklink_native_identity *reserved,
                                       struct sparklink_native_identity *identity);
int sparklink_backend_pending_update(u16 id, u64 generation, u32 phase, int error);
int sparklink_backend_pending_query(u16 id, u64 generation, struct sparklink_backend_pending *status);
/* Cancel only an uninstalled reservation; a successful install is removed via
 * sparklink_native_unregister. Failed install may retire identity if open was
 * reached: caller must re-query validity before keeping a diagnostic record. */
void sparklink_backend_cancel(u16 id, u64 generation);

#endif
