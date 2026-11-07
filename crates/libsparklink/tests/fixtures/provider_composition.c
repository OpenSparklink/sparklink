/* Real C ABI and SDK on a private metadata bus, not a wire/RF Engine. */
#define _POSIX_C_SOURCE 200809L
#include <sparklink.h>
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
static uint64_t deadline(void) {
    struct timespec t;assert(clock_gettime(CLOCK_MONOTONIC,&t)==0);
    return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec+3000000000ULL;
}
static void ready(int fd) {struct pollfd p={.fd=fd,.events=POLLIN};assert(poll(&p,1,3000)==1 && (p.revents&POLLIN));}
int main(int argc,char **argv) {
    assert(argc==2);int read_first=strcmp(argv[1],"read")==0;
    struct SlkClient *client=NULL;struct SlkLocalService *service=NULL;
    struct SlkReadProvider *reader=NULL,*bad_read=NULL;struct SlkWriteProvider *writer=NULL,*bad_write=NULL;
    struct SlkControllerId controller={.index=2,.generation=7};uint8_t uuid[]={1,0};
    struct SlkServiceProperty property={.operations=5,.value_length=3,.uuid_length=2,.uuid={2,0},.value={7,8,9}};
    assert(slk_client_open_system(deadline(),&client)==0);
    assert(slk_client_register_local_entries(client,&controller,uuid,2,&property,1,NULL,0,NULL,0,0,deadline(),&service)==0);
    if(read_first) assert(slk_local_service_bind_read_provider(service,17,deadline(),&reader)==0);
    assert(slk_local_service_bind_write_provider(service,17,deadline(),&writer)==0);
    if(!read_first) assert(slk_local_service_bind_read_provider(service,17,deadline(),&reader)==0);
    assert(slk_local_service_bind_read_provider(service,17,deadline(),&bad_read)==-EALREADY && !bad_read);
    assert(slk_local_service_bind_write_provider(service,17,deadline(),&bad_write)==-EALREADY && !bad_write);
    int read_fd=-1,write_fd=-1;assert(slk_read_provider_fd(reader,&read_fd)==0);assert(slk_write_provider_fd(writer,&write_fd)==0);
    slk_client_close(client);client=NULL;
    uint8_t value[32]={0x51,0xa3};uintptr_t size=2;
    puts("COMPOSITION_READY");fflush(stdout);
    for(unsigned round=0;round<4;round++) {
        int result;
        if(round%2==0) {
            struct SlkReadProviderRequest *request=NULL;
            while((result=slk_read_provider_next(reader,&request))==-EAGAIN) ready(read_fd);
            assert(result==0);struct SlkReadProviderRequestInfo info={0};assert(slk_read_provider_request_info(request,&info)==0);
            assert(info.property==17 && info.request_id==round+1 && info.controller.generation==7);
            assert(slk_read_provider_request_reply(request,0,value,size)==0);slk_read_provider_request_free(request);
        }else{
            struct SlkWriteProviderRequest *request=NULL;
            while((result=slk_write_provider_next(writer,&request))==-EAGAIN) ready(write_fd);
            assert(result==0);struct SlkWriteProviderRequestInfo info={0};assert(slk_write_provider_request_info(request,&info)==0);
            assert(info.property==17 && info.request_id==round+1 && info.operation==13 && info.verify);
            assert(slk_write_provider_request_value(request,value,sizeof value,&size)==0);
            assert(slk_write_provider_request_reply(request,0,value,size)==0);slk_write_provider_request_free(request);
        }
        if(round==2) {
            char barrier[32];assert(fgets(barrier,sizeof barrier,stdin) && strcmp(barrier,"CLOSE_READ\n")==0);
            slk_read_provider_free(reader);reader=NULL;puts("READ_CLOSED");fflush(stdout);
        }
    }
    char barrier[32];assert(fgets(barrier,sizeof barrier,stdin) && strcmp(barrier,"UNREGISTER\n")==0);
    assert(slk_local_service_unregister(service,deadline())==0);
    struct SlkWriteProviderRequest *request=NULL;assert(slk_write_provider_next(writer,&request)==-ESHUTDOWN && !request);
    close(read_fd);close(write_fd);slk_write_provider_free(writer);slk_local_service_free(service);
    puts("COMPOSITION_COMPLETE");return 0;
}
