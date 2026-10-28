/* Actual public C SDK; metadata/private D-Bus fixture only, not wire/RF. */
#define _POSIX_C_SOURCE 200809L
#include <sparklink.h>
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
_Static_assert(sizeof(struct SlkServiceMethod)==24,"method input ABI");
_Static_assert(sizeof(struct SlkServiceReceipt)==152,"receipt ABI");
_Static_assert(offsetof(struct SlkServiceReceipt,method_count)==22,"method count ABI");
_Static_assert(sizeof(struct SlkAuthorizationRequestInfo)==2120,"authorization ABI");
_Static_assert(sizeof(((struct SlkAuthorizationRequestInfo *)0)->value)==2043,"method argument budget");
_Static_assert(sizeof(struct SlkMethodProviderRequestInfo)==80,"method info ABI");
static uint64_t deadline(void) {
    struct timespec t; assert(clock_gettime(CLOCK_MONOTONIC,&t)==0);
    return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec+3000000000ULL;
}
static void wait_ready(int fd) {
    struct pollfd p={.fd=fd,.events=POLLIN};assert(poll(&p,1,3000)==1 && (p.revents&POLLIN));
}
int main(void) {
    struct SlkClient *client=NULL;struct SlkLocalService *service=NULL;
    struct SlkControllerId controller={.generation=7,.index=2};uint8_t uuid[2]={4,0};
    struct SlkServiceMethod method={.access=4,.uuid_length=2,.uuid={3,0}};
    assert(slk_client_open_system(deadline(),&client)==0);
    /* Invalid definitions never create a registration or consume the output. */
    for (unsigned bad=0;bad<4;bad++) {
        struct SlkServiceMethod invalid=method;
        if (bad==0) invalid.access=8;
        if (bad==1) invalid.reserved[0]=1;
        if (bad==2) invalid.uuid_length=3;
        if (bad==3) memset(invalid.uuid,0,sizeof invalid.uuid);
        assert(slk_client_register_local_entries(client,&controller,uuid,2,NULL,0,&invalid,1,1,deadline(),&service)==-EINVAL && !service);
    }
    assert(slk_client_register_local_entries(client,&controller,uuid,2,NULL,0,&method,1,0,deadline(),&service)==-EOPNOTSUPP && !service);
    assert(slk_client_register_local_entries(client,&controller,uuid,2,NULL,0,&method,1,1,deadline(),&service)==0);
    struct SlkServiceReceipt receipt={0};assert(slk_local_service_receipt(service,&receipt)==0);
    assert(receipt.property_count==0 && receipt.method_count==1 && receipt.handles[0]==17);
    struct SlkMethodProvider *provider=NULL;assert(slk_local_service_bind_method_provider(service,17,deadline(),&provider)==0);
    struct SlkReadProvider *reader=NULL;assert(slk_local_service_bind_read_provider(service,17,deadline(),&reader)==-EOPNOTSUPP && !reader);
    int policy_fd=-1,provider_fd=-1;assert(slk_local_service_authorization_fd(service,&policy_fd)==0);
    assert(slk_method_provider_fd(provider,&provider_fd)==0);
    puts("METHOD_READY");fflush(stdout);
    struct SlkAuthorizationRequest *approval=NULL;int r;
    while ((r=slk_local_service_next_authorization(service,&approval))==-EAGAIN) wait_ready(policy_fd);
    assert(r==0);struct SlkAuthorizationRequestInfo a={0};assert(slk_authorization_request_info(approval,&a)==0);
    assert(a.data_type==3 && a.property==17 && a.write==1 && a.value_length==2043);
    for (unsigned i=0;i<a.value_length;i++) assert(a.value[i]==0x31);
    assert(slk_authorization_request_reply(approval,1)==0);
    assert(slk_authorization_request_reply(approval,1)==-ESTALE);slk_authorization_request_free(approval);
    puts("AUTH_OK");fflush(stdout);
    for (unsigned round=0;round<4;round++) {
        struct SlkMethodProviderRequest *request=NULL;
        while ((r=slk_method_provider_next(provider,&request))==-EAGAIN) wait_ready(provider_fd);
        assert(r==0);struct SlkMethodProviderRequestInfo info={0};assert(slk_method_provider_request_info(request,&info)==0);
        assert(info.method==17 && info.controller.index==2 && info.controller.generation==7);
        assert(info.connection_lifetime==13 && info.connection_handle==1 && info.security_epoch==41);
        assert(info.operation==(round==1?18:19) && info.argument_length==2043);
        uint8_t arguments[2043];memset(arguments,0x55,sizeof arguments);uintptr_t length=0;
        assert(slk_method_provider_request_arguments(request,arguments,1,&length)==-ENOSPC && length==2043 && arguments[0]==0x55);
        assert(slk_method_provider_request_arguments(request,arguments,sizeof arguments,&length)==0);
        for (unsigned i=0;i<length;i++) assert(arguments[i]==0x31);
        uint8_t result[2046];memset(result,0xa6,sizeof result);
        if (round==2) {
            struct timespec now, pause={.tv_nsec=1000000};
            do {
                assert(clock_gettime(CLOCK_MONOTONIC,&now)==0);
                if ((uint64_t)now.tv_sec*1000000000ULL+now.tv_nsec>=info.deadline_ns) break;
                assert(nanosleep(&pause,NULL)==0);
            } while (1);
            assert(slk_method_provider_request_reply(request,0,NULL,0)==-ETIMEDOUT);
            puts("METHOD_EXPIRED");
        } else if (round==3) {
            assert(slk_local_service_unregister(service,deadline())==0);
            assert(slk_method_provider_request_reply(request,0,NULL,0)==-ESHUTDOWN);
            puts("METHOD_REVOKED");
        } else {
            assert(slk_method_provider_request_reply(request,0,result,(uintptr_t)info.maximum_result_bytes+1)==-EMSGSIZE);
            assert(slk_method_provider_request_reply(request,1,NULL,0)==-EINVAL);
            assert(slk_method_provider_request_reply(request,0,result,info.maximum_result_bytes)==0);
            assert(slk_method_provider_request_reply(request,0,NULL,0)==-ESTALE);
            puts("METHOD_REPLIED");
        }
        slk_method_provider_request_free(request);fflush(stdout);
    }
    close(policy_fd);close(provider_fd);slk_method_provider_free(provider);
    slk_local_service_free(service);slk_client_close(client);
    puts("METHOD_COMPLETE");return 0;
}
