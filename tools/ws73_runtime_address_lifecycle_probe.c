// SPDX-License-Identifier: GPL-2.0-only
/* Explicit isolated-VM syscall probe. No DLI encoding, transport, mock replies,
 * alternate Host, reset or permanent storage operation. Uses actual UAPI. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
#include "sparklink_ioctl.h"

static void failed(int line, const char *expression)
{
	fprintf(stderr, "runtime address probe line %d: %s errno=%d\n", line, expression, errno);
	exit(1);
}
#define CHECK(x) do { if (!(x)) failed(__LINE__, #x); } while (0)
static uint64_t clock_ns(clockid_t clock)
{
	struct timespec value;
	CHECK(!clock_gettime(clock, &value));
	return (uint64_t)value.tv_sec * 1000000000ULL + value.tv_nsec;
}
static void hex(const void *data, size_t length)
{
	const unsigned char *bytes = data;
	putchar('"');
	for (size_t i = 0; i < length; ++i) printf("%02x", bytes[i]);
	putchar('"');
}
static void command(const char *expected)
{
	/* One byte per poll prevents stdio read-ahead from hiding later commands. */
	char input[32]; size_t used = 0;
	uint64_t deadline = clock_ns(CLOCK_MONOTONIC) + 7000000000ULL;
	for (;;) {
		struct pollfd descriptor = { .fd = STDIN_FILENO, .events = POLLIN };
		CHECK(clock_ns(CLOCK_MONOTONIC) < deadline);
		int count = poll(&descriptor, 1, 50);
		if (count < 0 && errno == EINTR) continue;
		CHECK(count >= 0 && !(descriptor.revents & (POLLERR | POLLNVAL)));
		if (!count) continue;
		char byte;
		CHECK(read(STDIN_FILENO, &byte, 1) == 1);
		if (byte == '\n') break;
		CHECK(used + 1 < sizeof(input)); input[used++] = byte;
	}
	input[used] = 0; CHECK(!strcmp(input, expected));
}
static int selected(unsigned index)
{
	int fd = open("/dev/sparklink", O_RDWR | O_CLOEXEC);
	uint16_t value = index;
	CHECK(fd >= 0 && !ioctl(fd, SL_IOCTL_DEV_SELECT, &value)); return fd;
}
static void closed(int fd)
{
	CHECK(!close(fd)); errno = 0;
	CHECK(fcntl(fd, F_GETFD) == -1 && errno == EBADF);
}
static struct sle_controller_snapshot snapshot(int fd, uint64_t generation)
{
	struct sle_controller_snapshot value = { .version = 1, .generation = generation };
	CHECK(!ioctl(fd, SL_IOCTL_CONTROLLER_SNAPSHOT, &value));
	CHECK(value.version == 1 && value.generation == generation && value.profile == 1);
	return value;
}
static struct sle_management_query management(int fd, uint64_t generation)
{
	struct sle_management_query value = { .version = 1, .generation = generation };
	CHECK(!ioctl(fd, SL_IOCTL_MANAGEMENT_QUERY, &value)); return value;
}
static struct sle_diagnostic_result result(int fd, uint64_t generation, unsigned seq)
{
	struct sle_diagnostic_result value = { .version = 1, .generation = generation, .seq = seq };
	CHECK(!ioctl(fd, SL_IOCTL_DIAGNOSTIC_RESULT, &value));
	CHECK(value.version == 1 && value.generation == generation && value.seq == seq && value.opcode == 0x0405);
	return value;
}
static void result_record(const char *stage, const struct sle_diagnostic_result *value)
{
	printf("{\"stage\":\"%s\",\"wall_ns\":%llu,\"result\":", stage,
	       (unsigned long long)clock_ns(CLOCK_REALTIME));
	hex(value, sizeof(*value)); puts("}"); fflush(stdout);
}
static void observation(const char *stage, int observer, uint64_t generation)
{
	struct sle_controller_snapshot s = snapshot(observer, generation);
	struct sle_management_query q = management(observer, generation);
	printf("{\"stage\":\"%s\",\"wall_ns\":%llu,\"monotonic_ns\":%llu,\"snapshot\":", stage,
	       (unsigned long long)clock_ns(CLOCK_REALTIME), (unsigned long long)clock_ns(CLOCK_MONOTONIC));
	hex(&s, sizeof(s)); printf(",\"management\":"); hex(&q, sizeof(q)); puts("}"); fflush(stdout);
}
static unsigned number(const char *text, unsigned limit)
{
	char *end; errno = 0; unsigned long value = strtoul(text, &end, 10);
	CHECK(!errno && text[0] && strspn(text, "0123456789") == strlen(text) && !*end && value <= limit); return value;
}
static void vm_guard(void)
{
	char vendor[128], cmdline[16384];
	FILE *file = fopen("/sys/class/dmi/id/sys_vendor", "r");
	CHECK(file && fgets(vendor, sizeof(vendor), file)); CHECK(!fclose(file));
	file = fopen("/proc/cmdline", "r");
	CHECK(file && fgets(cmdline, sizeof(cmdline), file)); CHECK(!fclose(file));
	CHECK(!geteuid() && !strcmp(vendor, "QEMU\n") && strstr(cmdline, " ws73.runtime_address_lifecycle=1 "));
}
int main(int argc, char **argv)
{
	CHECK(argc == 6);
	unsigned index = number(argv[1], 1), timeout = number(argv[5], 5000);
	char *end; errno = 0; uint64_t generation = strtoull(argv[2], &end, 10);
	CHECK(!errno && argv[2][0] && strspn(argv[2], "0123456789") == strlen(argv[2]) && !*end && generation && timeout);
	const char *kind = argv[3];
	CHECK(!strcmp(kind, "release") || !strcmp(kind, "close") || !strcmp(kind, "dup") || !strcmp(kind, "deadline"));
	CHECK(strlen(argv[4]) == 12 && strspn(argv[4], "0123456789abcdefABCDEF") == 12);
	struct sle_runtime_address_submit input = { .version = 1, .generation = generation,
		.request_id = 1, .timeout_ms = timeout, .action = 1 };
	for (unsigned i = 0; i < 6; ++i) {
		char part[3] = { argv[4][2*i], argv[4][2*i+1], 0 };
		errno = 0; unsigned long value = strtoul(part, &end, 16);
		CHECK(!errno && end == part+2 && value <= 255); input.address[i] = value;
	}
	vm_guard();
	int writer = selected(index), observer = selected(index), duplicate = -1;
	struct sle_controller_snapshot before = snapshot(observer, generation);
	CHECK(before.flags == SLE_CONTROLLER_SETUP && before.valid_fields == 1 && !before.error);
	CHECK(memcmp(before.address, input.address, 6));
	struct sle_management_request lease = { .version = 1, .generation = generation, .mode = SLE_MANAGEMENT_DIAGNOSTIC };
	CHECK(!ioctl(writer, SL_IOCTL_MANAGEMENT_ACQUIRE, &lease) && lease.lease);
	if (!strcmp(kind, "dup")) { duplicate = dup(writer); CHECK(duplicate >= 0); }
	printf("{\"stage\":\"owner\",\"writer_fd\":%d,\"duplicate_fd\":%d,\"lease\":", writer, duplicate);
	hex(&lease, sizeof(lease)); puts("}"); fflush(stdout);
	observation("initialized", observer, generation); command("submit");
	uint64_t start = clock_ns(CLOCK_MONOTONIC), wall = clock_ns(CLOCK_REALTIME);
	struct sle_runtime_address_submit admitted = input;
	CHECK(!ioctl(writer, SL_IOCTL_RUNTIME_ADDRESS_SUBMIT, &admitted) && admitted.seq);
	struct sle_runtime_address_submit replay = input;
	CHECK(!ioctl(writer, SL_IOCTL_RUNTIME_ADDRESS_SUBMIT, &replay) && !memcmp(&replay, &admitted, sizeof(replay)));
	printf("{\"stage\":\"admitted\",\"start_monotonic_ns\":%llu,\"start_wall_ns\":%llu,\"end_wall_ns\":%llu,\"input\":",
	       (unsigned long long)start, (unsigned long long)wall, (unsigned long long)clock_ns(CLOCK_REALTIME));
	hex(&input, sizeof(input)); printf(",\"output\":"); hex(&admitted, sizeof(admitted));
	printf(",\"retry_output\":"); hex(&replay, sizeof(replay)); puts("}"); fflush(stdout);
	command("held");
	struct sle_diagnostic_result pending = result(writer, generation, admitted.seq);
	CHECK(pending.state == 1 && !pending.error && !pending.status && !pending.data_len);
	result_record("pending-result", &pending);
	struct sle_controller_snapshot unverified = snapshot(observer, generation);
	CHECK(unverified.valid_fields == 0 && unverified.flags == SLE_CONTROLLER_SETUP && !unverified.error);
	CHECK(!memcmp(before.address, unverified.address, 6));
	observation("held", observer, generation); command("withdraw");
	if (!strcmp(kind, "release")) CHECK(!ioctl(writer, SL_IOCTL_MANAGEMENT_RELEASE, &lease));
	else if (!strcmp(kind, "close")) { closed(writer); writer = -1; }
	else if (!strcmp(kind, "dup")) {
		closed(writer); writer = -1;
		struct sle_management_query same = management(duplicate, generation);
		CHECK(same.state == SLE_MANAGEMENT_HELD && same.mode == SLE_MANAGEMENT_DIAGNOSTIC && same.lease == lease.lease && same.flags == 1);
		pending = result(duplicate, generation, admitted.seq); CHECK(pending.state == 1 && !pending.error);
		result_record("dup-first-close-result", &pending);
		observation("dup-first-close", observer, generation);
		closed(duplicate); duplicate = -1;
	} else {
		for (;;) {
			pending = result(writer, generation, admitted.seq);
			if (pending.state != 1) break;
			CHECK(clock_ns(CLOCK_MONOTONIC) - start < (uint64_t)(timeout+1500)*1000000ULL);
			struct timespec pause = { .tv_nsec = 1000000 }; CHECK(!nanosleep(&pause, NULL));
		}
		CHECK(pending.state == 3 && pending.error == -ETIMEDOUT && !pending.status && !pending.data_len);
		result_record("expired-result", &pending);
	}
	struct sle_controller_snapshot fault = snapshot(observer, generation);
	CHECK(fault.flags == SLE_CONTROLLER_FAULT && fault.valid_fields == 0 && fault.error == (!strcmp(kind, "deadline") ? -ETIMEDOUT : -EIO));
	CHECK(!memcmp(before.address, fault.address, 6));
	if (strcmp(kind, "deadline")) {
		struct sle_management_query q = management(observer, generation);
		CHECK(q.state == SLE_MANAGEMENT_FAULTED && !q.lease && !q.mode && !q.flags && q.error == -EIO);
	}
	observation("withdrawn", observer, generation); command("released");
	struct sle_controller_snapshot after = snapshot(observer, generation);
	CHECK(!memcmp(&after, &fault, sizeof(after)));
	if (!strcmp(kind, "deadline")) {
		struct sle_diagnostic_result late = result(writer, generation, admitted.seq);
		CHECK(!memcmp(&late, &pending, sizeof(late)));
		result_record("late-result", &late);
	}
	observation("after-late-reply", observer, generation);
	if (writer >= 0) closed(writer);
	closed(observer); return 0;
}
