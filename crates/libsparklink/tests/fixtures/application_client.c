/* Public C consumer; private bus fixture, not a SparkLink device/peer. */
#define _POSIX_C_SOURCE 200809L
#include <sparklink.h>
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static uint64_t deadline(void) {
    struct timespec now;
    assert(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
    return (uint64_t)now.tv_sec * 1000000000ULL + now.tv_nsec + 3000000000ULL;
}
static unsigned entries(const char *path) {
    DIR *directory=opendir(path);assert(directory);
    unsigned count=0;struct dirent *entry;
    while ((entry=readdir(directory))) if (strcmp(entry->d_name,".") && strcmp(entry->d_name,"..")) ++count;
    assert(closedir(directory)==0);return count;
}
int main(void) {
    const unsigned threads_before=entries("/proc/self/task"),fds_cold=entries("/proc/self/fd");
    /* Pinned Tokio1.51/full initializes one process-global signal socketpair.
       The original cold-zero assertion failed and actual C strace attributed
       its two fds to OsExtraData/OnceLock. Check that exact fixed cost, then
       strict per-caller convergence; no slack per iteration or new connection. */
    struct SlkClient *warm=NULL;
    assert(slk_client_open_system(deadline(),&warm)==0 && warm);
    slk_client_close(warm);
    const unsigned fds_before=entries("/proc/self/fd");
    assert(fds_before==fds_cold+2 && entries("/proc/self/task")==threads_before);
    for (unsigned i=0;i<16;++i) {
        struct SlkClient *next=NULL;
        assert(slk_client_open_system(deadline(),&next)==0 && next);
        slk_client_close(next);
        assert(entries("/proc/self/fd")==fds_before);
        assert(entries("/proc/self/task")==threads_before);
    }
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
    _Static_assert(sizeof(struct SlkControllerEvent)==32,"directory event ABI");
    _Static_assert(offsetof(struct SlkControllerEvent,kind)==24,"directory event offset");
    struct SlkControllerEvents *observer=NULL;
    assert(slk_client_controller_events(client,0,&observer)==-ETIMEDOUT && !observer);
    assert(slk_client_controller_events(client,deadline(),&observer)==0 && observer);
    struct SlkControllerEvent event,event_before;
    struct SlkControllerId observed_ids[2];
    uintptr_t observed_count=999;
    memset(&event,0xa5,sizeof event);memcpy(&event_before,&event,sizeof event);
    assert(slk_controller_events_next(observer,&event,NULL,0,&observed_count,0,deadline())==-ENOBUFS);
    assert(observed_count==2 && !memcmp(&event,&event_before,sizeof event));
    for (unsigned flags=1;;flags=0) {
        assert(slk_controller_events_next(observer,&event,observed_ids,2,&observed_count,flags,deadline())==0);
        assert(event.kind==1 && event.sequence==0 && observed_count==2 && !event.reserved);
        assert(observed_ids[0].index==2 && observed_ids[0].generation==7);
        if (!flags) break;
    }
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
    struct SlkConnection *link = NULL;
    assert(slk_client_connection(client, ids, path, sizeof path-1, 0, &link) == -ETIMEDOUT && !link);
    ids[0].generation = 8;
    assert(slk_client_connection(client, ids, path, sizeof path-1, deadline(), &link) == -ESTALE && !link);
    ids[0].generation = 7;
    assert(slk_client_connection(client, ids, path, sizeof path-1, deadline(), &link) == 0 && link);
    slk_client_close(client);
    slk_client_close(NULL);
    /* This observer survives parent close on the SAME caller/executor. */
    for (unsigned kind=2;kind<=3;++kind) {
        assert(slk_controller_events_next(observer,&event,observed_ids,2,&observed_count,0,deadline())==0);
        assert(event.kind==kind && event.sequence==kind-1 && observed_count==1);
        assert(observed_ids[0].index==2 && observed_ids[0].generation==7);
    }
    slk_controller_events_close(observer);slk_controller_events_close(NULL);
    puts("CURRENT_CONTROLLER_DIRECTORY_LANGUAGE_FIXTURE_PASS_NOT_RF");

    /* A derived view retains the same broker caller, not a new client/Engine. */
    uint8_t output[8], original[8], value[] = {0x56,0x12};
    static const uint8_t oversized[65536] = {0}; /* Valid entire FFI input region. */
    uintptr_t length = 99;
    memset(output,0xa5,sizeof output);memcpy(original,output,sizeof output);
    assert(slk_connection_ssap_read(link,0,0,output,sizeof output,&length,deadline()) == -EINVAL);
    assert(slk_connection_ssap_read(link,17,3,output,sizeof output,&length,deadline()) == -EINVAL);
    assert(slk_connection_ssap_read(link,17,2,output,sizeof output,&length,0) == -ETIMEDOUT);
    assert(length == 99 && !memcmp(output,original,sizeof output));
    assert(slk_connection_ssap_read(link,17,2,output,1,&length,deadline()) == -ENOBUFS && length == 2);
    assert(!memcmp(output,original,sizeof output));
    assert(slk_connection_ssap_read(link,17,2,output,sizeof output,&length,deadline()) == 0 && length == 2);
    assert(output[0]==0x34 && output[1]==0x78);
    assert(slk_connection_ssap_write(link,17,1,value,sizeof value,output,sizeof output,&length,deadline()) == 0 && length==1 && output[0]==0x90);
    assert(slk_connection_ssap_write(link,17,0,NULL,0,output,sizeof output,&length,deadline()) == 0 && length==1 && output[0]==0x91);
    memset(output,0xa5,sizeof output);length=99;
    assert(slk_connection_ssap_write(link,17,0,value,sizeof value,output,sizeof output,&length,deadline()) == -EINVAL);
    assert(slk_connection_ssap_write(link,17,0,oversized,sizeof oversized,output,sizeof output,&length,deadline()) == -EMSGSIZE);
    assert(slk_connection_ssap_read(link,18,0,output,sizeof output,&length,deadline()) == -EOVERFLOW);
    assert(length==99 && !memcmp(output,original,sizeof output));
    assert(slk_connection_ssap_read(link,20,0,output,sizeof output,&length,deadline()-2950000000ULL) == -ETIMEDOUT);
    assert(length==99 && !memcmp(output,original,sizeof output));
    assert(slk_connection_ssap_read(link,19,0,output,sizeof output,&length,deadline()) == -ESTALE);
    assert(slk_connection_ssap_read(link,17,2,output,sizeof output,&length,deadline()) == -ESTALE);
    assert(length==99 && !memcmp(output,original,sizeof output));
    slk_connection_close(link);
    slk_connection_close(NULL);
    assert(entries("/proc/self/task")==threads_before);
    assert(entries("/proc/self/fd")==fds_before);
    puts("CURRENT_APPLICATION_CONNECTION_SSAP_FIXTURE_PASS_NOT_RF");
    puts("CURRENT_APPLICATION_CLIENT_NEGATIVE_BUS_PASS");
    return 0;
}
