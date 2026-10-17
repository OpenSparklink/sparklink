/* Public C consumer; private bus fixture, not a SparkLink device/peer. */
#define _POSIX_C_SOURCE 200809L
#include <sparklink.h>
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

static uint64_t deadline(void) {
    struct timespec now;
    assert(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
    return (uint64_t)now.tv_sec * 1000000000ULL + now.tv_nsec + 3000000000ULL;
}
int main(void) {
    _Static_assert(sizeof(struct SlkControllerId) == 16, "controller C ABI");
    _Static_assert(offsetof(struct SlkControllerId, index) == 8, "controller C offsets");
    struct SlkClient *client = NULL;
    assert(slk_client_open_system(0, &client) == -ETIMEDOUT && client == NULL);
    assert(slk_client_open_system(deadline(), NULL) == -EINVAL);
    assert(slk_client_open_system(deadline(), &client) == 0 && client);
    uintptr_t count = 999;
    struct SlkControllerId ids[2], before[2];
    memset(ids, 0xa5, sizeof ids); memcpy(before, ids, sizeof ids);
    assert(slk_client_controllers(client, NULL, 0, &count, deadline()) == 0 && count == 2);
    assert(slk_client_controllers(client, ids, 1, &count, deadline()) == -ENOBUFS && count == 2);
    assert(memcmp(ids, before, sizeof ids) == 0);
    assert(slk_client_controllers(client, ids, 2, &count, deadline()) == 0 && count == 2);
    assert(ids[0].index == 2 && ids[0].generation == 7 && ids[1].index == 3 && ids[1].generation == 9);
    for (unsigned i=0;i<6;i++) assert(ids[0].reserved[i] == 0);
    const uint8_t path[] = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b";
    int fd = 123456;
    assert(slk_client_open_channel(client, ids, path, sizeof path-1, 0, 0, deadline(), &fd) == -EINVAL && fd == 123456);
    assert(slk_client_open_channel(client, ids, path, sizeof path-1, 3, 0, 0, &fd) == -ETIMEDOUT && fd == 123456);
    ids[0].reserved[0] = 1;
    assert(slk_client_open_channel(client, ids, path, sizeof path-1, 3, 0, deadline(), &fd) == -EINVAL && fd == 123456);
    ids[0].reserved[0] = 0;
    ids[0].generation = 8;
    assert(slk_client_open_channel(client, ids, path, sizeof path-1, 3, 0, deadline(), &fd) == -ESTALE && fd == 123456);
    ids[0].generation = 7;
    assert(slk_client_open_channel(client, ids, path, sizeof path-1, 3, 0, deadline(), &fd) == -EACCES && fd == 123456);
    assert(slk_client_open_channel(client, ids, path, sizeof path-1, 3, 2, deadline(), &fd) == -EAFNOSUPPORT && fd == 123456);
    slk_client_close(client);
    slk_client_close(NULL);
    puts("CURRENT_APPLICATION_CLIENT_NEGATIVE_BUS_PASS");
    return 0;
}
