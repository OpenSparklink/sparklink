#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "sparklink.h"
/* Actual exported SDK consumer for the private-bus fixture. No Host/codec/RF. */
static uint64_t now_ns(void) { struct timespec t; assert(!clock_gettime(CLOCK_MONOTONIC,&t)); return (uint64_t)t.tv_sec*1000000000+t.tv_nsec; }
int main(void) {
    setbuf(stdout,NULL);
    SlkClient *client=NULL; SlkLocalService *service=NULL; SlkWriteProvider *provider=NULL;
    SlkControllerId controller={.index=2,.generation=7};
    SlkServiceProperty property={.operations=6,.uuid_length=2,.uuid={2,0},.value_length=3,.value={7,8,9}};
    const uint8_t uuid[]={1,0}; uint64_t deadline=now_ns()+2000000000;
    assert(!slk_client_open_system(deadline,&client));
    assert(!slk_client_register_local_service(client,&controller,uuid,2,&property,1,0,deadline,&service));
    assert(!slk_local_service_bind_write_provider(service,17,deadline,&provider));
    slk_client_close(client);
    int fd=-1; assert(!slk_write_provider_fd(provider,&fd)); puts("READY");
    for (unsigned n=1;n<=4;n++) {
        SlkWriteProviderRequest *request=NULL; int rc;
        while ((rc=slk_write_provider_next(provider,&request))==-EAGAIN) { struct pollfd p={.fd=fd,.events=POLLIN}; assert(poll(&p,1,3000)>0); assert(!(p.revents&(POLLERR|POLLHUP|POLLNVAL))); }
        assert(rc==0); SlkWriteProviderRequestInfo info;
        assert(!slk_write_provider_request_info(request,&info));
        assert(info.request_id==n && info.property==17 && info.controller.index==2 && info.controller.generation==7);
        assert(info.connection_lifetime==13 && info.security_epoch==41 && !info.offset && !info.data_type);
        assert(info.value_length<=2042 && (info.operation==12 || info.operation==13));
        uint8_t bytes[2042]; size_t length=999;
        assert(!slk_write_provider_request_value(request,bytes,sizeof bytes,&length)); assert(length==info.value_length);
        printf("VALUE %u ",n); for(size_t i=0;i<length;i++) printf("%02x",bytes[i]); puts("");
        assert(slk_write_provider_request_reply(request,7,NULL,0)==-EINVAL);
        if (n==4) { struct timespec end={.tv_sec=info.deadline_ns/1000000000,.tv_nsec=info.deadline_ns%1000000000}; while(clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&end,NULL)==EINTR){} }
        /* Accepting the snapshot is this finite application's memory operation;
           it is not a claim of daemon/wire/remote delivery. */
        uint8_t stored[2042]; if(n<3)memcpy(stored,bytes,length);
        rc=slk_write_provider_request_reply(request,n==3?0xaf:0,info.verify&&n<3?stored:NULL,info.verify&&n<3?length:0);
        assert(rc==(n==4?-ETIMEDOUT:0)); printf("RESULT %u %d\n",n,rc);
        slk_write_provider_request_free(request);
        /* Keep the original bus alive until the harness actually receives the
           callback body. Local reply/expiry alone does not prove D-Bus drain. */
        char drained[32]; assert(fgets(drained,sizeof drained,stdin)); assert(!strcmp(drained,"CONTINUE\n"));
    }
    close(fd); slk_write_provider_free(provider); slk_local_service_free(service); puts("DONE"); return 0;
}
