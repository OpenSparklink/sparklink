// SPDX-License-Identifier: GPL-2.0-only
/* VM-only test interposer. Always execute the real bind and return its exact
 * result/errno. Only delay a successful selected SMTC bind's return to Rust.
 * No protocol bytes, fd, grant, completion or device state are manufactured.
 * The caller is the production Rust creator: its complete Address stays alive
 * throughout this call. This is not a bad-user-pointer/host-driver fuzz entry.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>

struct native_address {
	uint16_t family, controller, version, flags;
	uint64_t generation, lifetime, lease;
	uint16_t handle;
	uint8_t local, remote, pi, reserved[3];
	uint32_t directions, security;
};
struct selection {
	char magic[8];
	uint32_t phase, controller;
	uint64_t generation;
	uint32_t kind, reserved;
};
struct observation {
	char magic[8];
	uint32_t phase, pid, tid;
	int32_t fd;
	uint32_t controller, handle;
	uint64_t generation, lifetime, start_mono, start_wall, end_mono, end_wall;
	uint32_t outcome, kind;
};
_Static_assert(sizeof(struct native_address) == 48, "actual Native v2 address");
_Static_assert(sizeof(struct selection) == 32, "fixed selector");
_Static_assert(sizeof(struct observation) == 88, "fixed observation");
_Static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "reviewed x86 VM only");

static uint64_t now_ns(clockid_t clock)
{
	struct timespec value;
	if (clock_gettime(clock, &value))
		return 0;
	return (uint64_t)value.tv_sec * 1000000000ULL + value.tv_nsec;
}

static int regular_root(int fd, off_t size)
{
	struct stat value;
	return !fstat(fd, &value) && S_ISREG(value.st_mode) && !value.st_uid &&
	       (value.st_mode & 0777) == 0600 && value.st_size == size;
}

static int selected(const struct native_address *a, const struct selection *s)
{
	return !memcmp(s->magic, "SLKSEL1", 8) && s->phase < 4 &&
	       s->kind == s->phase / 2 && !s->reserved &&
	       s->controller < 16 && s->generation && a->family == 46 &&
	       a->version == 2 && !a->flags && a->controller == s->controller &&
	       a->generation == s->generation && a->lifetime && a->lease &&
	       ((s->kind == 0 && a->local == 10 && a->remote == 10 && !a->pi) ||
		(s->kind == 1 && a->local == 31 && a->remote == 31 && a->pi == 241)) &&
	       !a->reserved[0] && !a->reserved[1] && !a->reserved[2] &&
	       a->directions == 3 && !a->security;
}

static int vm_directory(void)
{
	char command[4096] = {0};
	struct utsname kernel;
	struct stat directory;
	if (geteuid() || uname(&kernel) ||
	    !strstr(kernel.release, "-opensparklink-native-lab+"))
		return -1;
	int input = open("/proc/cmdline", O_RDONLY | O_CLOEXEC);
	if (input < 0)
		return -1;
	ssize_t length = read(input, command + 1, sizeof(command) - 3);
	close(input);
	if (length < 0)
		return -1;
	command[0] = ' ';
	command[length + 1] = ' ';
	for (ssize_t i = 1; i <= length; i++)
		if (command[i] == '\n' || command[i] == '\t')
			command[i] = ' ';
	if (!strstr(command, " ws73.native_return=1 "))
		return -1;
	int fd = open("/run/ws73-native-return", O_RDONLY | O_DIRECTORY |
		      O_NOFOLLOW | O_CLOEXEC);
	if (fd >= 0 && (!fstat(fd, &directory) && !directory.st_uid &&
			(directory.st_mode & 0777) == 0700))
		return fd;
	if (fd >= 0)
		close(fd);
	return -1;
}

static int write_observation(int root, const char *name, const struct observation *o)
{
	int fd = openat(root, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW |
			O_CLOEXEC, 0600);
	if (fd < 0)
		return 0;
	int complete = write(fd, o, sizeof(*o)) == (ssize_t)sizeof(*o);
	close(fd);
	return complete;
}

static void hold_return(int fd, const struct native_address *a)
{
	int root = vm_directory();
	if (root < 0)
		return;
	int input = openat(root, "selection", O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
	struct selection s;
	int valid = input >= 0 && regular_root(input, sizeof(s)) &&
		    read(input, &s, sizeof(s)) == (ssize_t)sizeof(s) && selected(a, &s);
	if (input >= 0)
		close(input);
	if (!valid) {
		close(root);
		return;
	}
	char held[32], release[32], returned[32];
	snprintf(held, sizeof(held), "%u-held", s.phase);
	snprintf(release, sizeof(release), "%u-release", s.phase);
	snprintf(returned, sizeof(returned), "%u-returned", s.phase);
	struct observation o = {
		.magic = "SLKRET1", .phase = s.phase, .pid = getpid(),
		.tid = syscall(SYS_gettid), .fd = fd, .controller = a->controller,
		.handle = a->handle, .generation = a->generation, .lifetime = a->lifetime,
		.kind = s.kind,
		.start_mono = now_ns(CLOCK_MONOTONIC), .start_wall = now_ns(CLOCK_REALTIME),
	};
	if (!o.start_mono || !o.start_wall || !write_observation(root, held, &o)) {
		close(root);
		return;
	}
	o.outcome = 2; /* bounded expiry is a test failure, never recovery */
	while (now_ns(CLOCK_MONOTONIC) - o.start_mono < 2000000000ULL) {
		int done = openat(root, release, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
		if (done >= 0) {
			valid = regular_root(done, 0);
			close(done);
			if (valid) {
				o.outcome = 1;
				break;
			}
		}
		struct timespec pause = {.tv_nsec = 1000000};
		nanosleep(&pause, NULL);
	}
	o.end_mono = now_ns(CLOCK_MONOTONIC);
	o.end_wall = now_ns(CLOCK_REALTIME);
	write_observation(root, returned, &o);
	close(root);
}

__attribute__((visibility("default")))
int bind(int fd, const struct sockaddr *address, socklen_t length)
{
	int result = syscall(SYS_bind, fd, address, length);
	int original_errno = errno;
	if (!result && length == sizeof(struct native_address)) {
		struct native_address complete;
		memcpy(&complete, address, sizeof(complete));
		if (complete.family == 46)
			hold_return(fd, &complete);
	}
	errno = original_errno;
	return result;
}
