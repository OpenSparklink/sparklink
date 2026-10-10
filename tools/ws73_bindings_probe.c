// SPDX-License-Identifier: GPL-2.0-only
/* Actual cdylib/native ioctl support gate, never physical/RF acceptance. */
#include <errno.h>
#include <inttypes.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "sparklink.h"

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "BINDING_C_FAIL:%d: %s\n", __LINE__, #x); exit(1); } } while (0)

static SlkAdapter *selected(unsigned index)
{
	SlkAdapter *h = slk_adapter_open("/dev/sparklink");
	CHECK(h && slk_adapter_select(h, index) == 0 && slk_adapter_fd(h) >= 0);
	return h;
}

static void observe(unsigned index, uint64_t generation, int ordinary)
{
	SlkAdapter *a = selected(index), *b = selected(index), *s = selected(index), *t = selected(index);
	SleControllerSnapshot info;
	SleManagementQuery owner;
	uint64_t lease = UINT64_C(0xabcdef);
	uint16_t mask = 0;
	CHECK(slk_device_mask(a, &mask) == 0 && (mask & (1U << index)));
	CHECK(slk_controller_snapshot(a, generation, &info) == 0);
	CHECK(info.generation == generation && info.dev_index == index && info.flags == 1 && info.profile == 1 && info.valid_fields == 1);
	CHECK(slk_controller_snapshot(a, generation + 100, &info) == -ENODEV);
	CHECK(slk_management_query(a, generation, &owner) == 0 && owner.state == 1 && owner.mode == 1 && owner.lease == 0 && owner.flags == 0);
	CHECK(slk_management_acquire(a, generation, 1, &lease) == (ordinary ? -EPERM : -EBUSY) && lease == UINT64_C(0xabcdef));
	SleControllerEventQuery e = {.version=1, .generation=generation}, f = e;
	int er = slk_controller_event(a, &e), fr = slk_controller_event(b, &f);
	CHECK(er == 1 && fr == 1 && e.after_seq == e.event.seq && e.event.generation == generation);
	CHECK(!memcmp(&e.event, &f.event, sizeof(e.event)));
	unsigned reads;
	for (reads=0; reads<64 && er==1; reads++) er=slk_controller_event(a, &e);
	CHECK(er == 0);
	SleControllerEventQuery quiet = e;
	CHECK(slk_controller_event(a, &e) == 0 && !memcmp(&e, &quiet, sizeof(e)));
	SleSnoopQuery p = {.version=1, .generation=generation}, q = p;
	int pr = slk_snoop(s, &p), qr = slk_snoop(t, &q);
	if (ordinary) {
		CHECK(pr == -EPERM && qr == -EPERM && p.after_seq == 0 && q.after_seq == 0);
		SleDiscoverySubmit submit = {.version=1, .profile=1, .operation=4, .generation=generation, .request_id=UINT64_C(0x4342494e44494e47)};
		CHECK(slk_discovery_submit(a, &submit) == -EPERM);
	} else {
		CHECK(pr == 1 && qr == 1 && !memcmp(&p.record, &q.record, sizeof(p.record)));
		CHECK(p.after_seq == p.record.seq && p.record.generation == generation);
		for (reads=0; reads<64 && pr==1; reads++) pr=slk_snoop(s, &p);
		CHECK(pr == 0);
		SleSnoopQuery quiet_snoop = p;
		CHECK(slk_snoop(s, &p) == 0 && !memcmp(&p, &quiet_snoop, sizeof(p)));
		CHECK(slk_snoop(a, &p) == -EBUSY); /* event/trace modes are separate */
	}
	slk_adapter_free(t); slk_adapter_free(s); slk_adapter_free(b); slk_adapter_free(a);
}

static void writer(unsigned index, uint64_t generation)
{
	SlkAdapter *a = selected(index), *b = selected(index);
	uint64_t lease = 0, other = 99;
	SleManagementQuery owner;
	CHECK(slk_management_acquire(a, generation, 1, &lease) == 0 && lease != 0);
	CHECK(slk_management_query(a, generation, &owner) == 0 && owner.flags == 1 && owner.lease == lease);
	CHECK(slk_management_query(b, generation, &owner) == 0 && owner.flags == 0 && owner.lease == 0);
	CHECK(slk_management_acquire(b, generation, 1, &other) == -EBUSY && other == 99);
	CHECK(slk_management_release(b, generation, lease, 1) == -EPERM);
	uint64_t request = UINT64_C(0x4342494e44494e47);
	SleDiscoveryResult r = {.request_id=99};
	CHECK(slk_discovery_result(a, generation, request, &r) == 0 && r.request_id == 99);
	SleDiscoverySubmit submit = {.version=1, .profile=1, .operation=4, .generation=generation, .request_id=request};
	CHECK(slk_discovery_submit(b, &submit) == -EPERM);
	struct timespec wall;
	CHECK(clock_gettime(CLOCK_REALTIME, &wall) == 0);
	uint64_t started = (uint64_t)wall.tv_sec * 1000000000 + wall.tv_nsec;
	CHECK(slk_discovery_submit(a, &submit) == 0);
	struct timespec pause = {.tv_nsec=10000000};
	unsigned tries;
	for (tries=0; tries<200; tries++) {
		CHECK(slk_discovery_result(a, generation, request, &r) == 1);
		if (r.state >= 3) break;
		nanosleep(&pause, NULL);
	}
	CHECK(tries < 200 && r.state == 3 && r.status == 0 && r.error == 0 && r.radio_scan == 1 && r.request_id == request && r.generation == generation);
	CHECK(clock_gettime(CLOCK_REALTIME, &wall) == 0);
	printf("WS73_NATIVE_BINDING_RESULT: {\"generation\":%"PRIu64",\"request_id\":%"PRIu64",\"operation\":4,\"opcode\":%u,\"state\":%u,\"status\":%u,\"error\":%d,\"started_wall_ns\":%"PRIu64",\"finished_wall_ns\":%"PRIu64"}\n",
	       generation, request, r.opcode, r.state, r.status, r.error, started, (uint64_t)wall.tv_sec*1000000000+wall.tv_nsec);
	CHECK(slk_management_release(a, generation, lease, 1) == 0);
	for (tries=0; tries<200; tries++) {
		CHECK(slk_management_query(b, generation, &owner) == 0);
		if (owner.state == 0) break;
		nanosleep(&pause, NULL);
	}
	CHECK(tries < 200 && owner.mode == 0 && owner.lease == 0);
	CHECK(slk_management_acquire(b, generation, 2, &other) == 0 && other != 0 && other != lease);
	CHECK(slk_management_release(b, generation, other, 2) == 0);
	slk_adapter_free(b); slk_adapter_free(a);
}

static uint64_t now_ms(void)
{
	struct timespec now;
	CHECK(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
	return (uint64_t)now.tv_sec*1000 + now.tv_nsec/1000000;
}

static void stale(unsigned index, uint64_t generation, int trace)
{
	SlkAdapter *old = selected(index);
	SleControllerSnapshot info;
	SleControllerEventQuery event = {.version=1, .generation=generation};
	SleSnoopQuery snoop = {.version=1, .generation=generation};
	CHECK((trace ? slk_snoop(old, &snoop) : slk_controller_event(old, &event)) >= 0);
	struct pollfd fd = {.fd=slk_adapter_fd(old), .events=POLLIN};
	struct timespec pause = {.tv_nsec=50000000};
	uint64_t deadline = now_ms()+120000;
	int result;
	while ((result=slk_controller_snapshot(old, generation, &info)) == 0) {
		CHECK(now_ms() < deadline); nanosleep(&pause, NULL);
	}
	CHECK(result == -ENODEV);
	CHECK(poll(&fd, 1, 0) == 1 && (fd.revents & (POLLERR|POLLHUP)) == (POLLERR|POLLHUP));
	CHECK((trace ? slk_snoop(old, &snoop) : slk_controller_event(old, &event)) == -ENODEV);
	SlkAdapter *fresh;
	for (;;) {
		CHECK(now_ms() < deadline);
		fresh=slk_adapter_open("/dev/sparklink"); CHECK(fresh);
		result=slk_adapter_select(fresh,index);
		if (!result) result=slk_controller_snapshot(fresh,0,&info);
		if (!result && info.flags==1 && info.generation!=generation) break;
		CHECK(result==0 || result==-ENODEV); slk_adapter_free(fresh); nanosleep(&pause,NULL);
	}
	CHECK(info.dev_index==index && info.generation>generation);
	uint64_t next=info.generation;
	CHECK(slk_controller_snapshot(old,generation,&info)==-ENODEV);
	CHECK(slk_controller_snapshot(fresh,generation,&info)==-ENODEV);
	printf("WS73_NATIVE_C_STALE: PASS mode=%s index=%u old=%"PRIu64" new=%"PRIu64" poll=ERR|HUP\n",trace ? "trace" : "event",index,generation,next);
	slk_adapter_free(fresh); slk_adapter_free(old);
}

int main(int argc, char **argv)
{
	CHECK(argc == 4);
	unsigned index = strtoul(argv[2], NULL, 10);
	uint64_t generation = strtoull(argv[3], NULL, 10);
	CHECK(index < 16 && generation != 0);
	if (!strcmp(argv[1], "observe")) observe(index, generation, getuid() != 0);
	else if (!strcmp(argv[1], "stale-event") || !strcmp(argv[1], "stale-trace")) {
		CHECK(getuid() == 0); stale(index,generation,!strcmp(argv[1],"stale-trace"));
	}
	else { CHECK(!strcmp(argv[1], "writer") && getuid() == 0); writer(index, generation); }
	printf("WS73_NATIVE_C_BINDINGS: PASS mode=%s uid=%u index=%u generation=%"PRIu64"\n", argv[1], getuid(), index, generation);
	return 0;
}
