/* SPDX-License-Identifier: GPL-2.0-only */
/* One-shot external application SDK consumer, not a Host or benchmark loop. */
#define _POSIX_C_SOURCE 200809L
#include <sparklink.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#include <stddef.h>
_Static_assert(sizeof(struct SlkServiceProperty)==2076,"Owned property ABI");
_Static_assert(sizeof(struct SlkServiceReceipt)==152,"Owned receipt ABI");
_Static_assert(offsetof(struct SlkServiceProperty,value)==32,"Owned value ABI");
_Static_assert(offsetof(struct SlkServiceReceipt,handles)==24,"Owned handles ABI");
_Static_assert(sizeof(struct SlkDiscoveryBatch)==40,"discovery batch ABI");
_Static_assert(sizeof(struct SlkDiscoveryReport)==312,"discovery report ABI");
_Static_assert(offsetof(struct SlkDiscoveryReport,data)==51,"discovery data offset");

static uint64_t now_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) exit(2);
    return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}
static int wait_fd(int fd, short events, uint64_t end) {
    for (;;) {
        uint64_t now=now_ns();
        if (now>=end) { errno=ETIMEDOUT;return -1; }
        struct pollfd p={.fd=fd,.events=events};
        int n=poll(&p,1,(int)((end-now+999999)/1000000));
        if (n<0 && errno==EINTR) continue;
        if (n<=0) { if (!n) errno=ETIMEDOUT;return -1; }
        if (p.revents&(POLLERR|POLLHUP|POLLNVAL)) { errno=ECONNRESET;return -1; }
        if (p.revents&events) return 0;
    }
}
static uint64_t number(const char *s) {
    char *end=NULL;errno=0;
    if (!*s || *s=='-') exit(2);
    uint64_t value=strtoull(s,&end,10);
    if (errno || !end || *end) exit(2);
    return value;
}
static int nybble(char c) {
    if (c>='0' && c<='9') return c-'0';
    if (c>='a' && c<='f') return c-'a'+10;
    return -1;
}
static size_t bytes(const char *hex, uint8_t *out) {
    size_t n=strlen(hex);
    if (!n || n%2 || n>4084) exit(2);
    for (size_t i=0;i<n/2;i++) {
        int a=nybble(hex[2*i]),b=nybble(hex[2*i+1]);
        if (a<0 || b<0) exit(2);
        out[i]=(uint8_t)((a<<4)|b);
    }
    return n/2;
}
static void hex_print(const uint8_t *p,size_t n) {
    for (size_t i=0;i<n;i++) printf("%02x",p[i]);
}
/* Single existing SSAP RPC, not a wire codec or a second receive loop. */
static int ssap_mode(int argc,char **argv) {
    if ((argc!=8 && argc!=9) || !*argv[4] || strlen(argv[4])>256) return 2;
    int writing=!strcmp(argv[5],"ssap-write");
    if ((!writing && strcmp(argv[5],"ssap-read")) || argc!=(writing?9:8)) return 2;
    uint64_t index=number(argv[2]),generation=number(argv[3]),handle=number(argv[6]);
    if (index>UINT16_MAX || !generation || !handle || handle>UINT16_MAX) return 2;
    int error_mode=!strcmp(argv[1],"ssap-error");
    uint64_t expected_errno=error_mode?number(argv[7]):0;
    if (error_mode && (!expected_errno || expected_errno>4095)) return 2;
    uint8_t expected[2042],value[2042],received[2042];
    size_t expected_n=error_mode?0:bytes(argv[7],expected),value_n=writing?bytes(argv[8],value):0;
    const uint64_t deadline=now_ns()+5000000000ULL;
    struct SlkControllerId id={.generation=generation,.index=(uint16_t)index};
    struct SlkClient *client=NULL;struct SlkConnection *link=NULL;int status=1;
    int error=slk_client_open_system(deadline,&client);
    if (error) { errno=-error;goto done; }
    error=slk_client_connection(client,&id,(const uint8_t *)argv[4],strlen(argv[4]),deadline,&link);
    if (error) { errno=-error;goto done; }
    slk_client_close(client);client=NULL;
    if (error_mode) {
        printf("{\"stage\":\"ssap_call\",\"api\":\"c\",\"deadline_ns\":%"PRIu64",\"call_ns\":%"PRIu64",\"client_closed\":true}\n",deadline,now_ns());fflush(stdout);
    } else {
        printf("{\"stage\":\"ssap_start_barrier\",\"api\":\"c\",\"client_closed\":true}\n");fflush(stdout);
        char start[6];
        if (wait_fd(STDIN_FILENO,POLLIN,deadline) || read(STDIN_FILENO,start,sizeof start)!=(ssize_t)sizeof start || memcmp(start,"start\n",sizeof start)) { errno=EPROTO;goto done; }
    }
    uintptr_t length=0;
    if (writing) error=slk_connection_ssap_write(link,(uint16_t)handle,0,value,value_n,received,sizeof received,&length,deadline);
    else error=slk_connection_ssap_read(link,(uint16_t)handle,0,received,sizeof received,&length,deadline);
    if (error_mode) {
        printf("{\"stage\":\"ssap_error\",\"api\":\"c\",\"errno\":%d,\"operation_success\":%s,\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",-error,error==0?"true":"false",deadline,now_ns());fflush(stdout);
        if (error!=-(int)expected_errno) { errno=EPROTO;goto done; }
        status=0;goto done;
    }
    if (error) { errno=-error;goto done; }
    if (length!=expected_n || memcmp(received,expected,expected_n)) { errno=EPROTO;goto done; }
    printf("SsapPeerValue: operation=%s path=%s handle=%"PRIu64" value=",argv[5],argv[4],handle);hex_print(received,length);printf("\n");fflush(stdout);
    status=0;
done:
    if (status) perror("application-client-c-ssap");
    slk_connection_close(link);slk_client_close(client);return status;
}
/* Bounded external discovery consumer of the same SDK; no scanner/decoder. */
static int discovery_mode(int argc,char **argv) {
    if (argc!=7) return 2;
    uint64_t index=number(argv[2]),generation=number(argv[3]),wanted=number(argv[5]);
    uint8_t prefix[2042],address[2042];size_t length=bytes(argv[4],prefix);
    if (index>UINT16_MAX || !generation || !wanted || wanted>1024 || length>64 || bytes(argv[6],address)!=6) return 2;
    const uint64_t deadline=now_ns()+20000000000ULL;
    struct SlkClient *client=NULL;struct SlkDiscovery *view=NULL;int status=1,error;
    struct SlkControllerId id={.generation=generation,.index=(uint16_t)index},actual={0};uint64_t session=0;
    error=slk_client_open_system(deadline,&client);if (error) {errno=-error;goto done;}
    error=slk_client_discover(client,&id,prefix,length,-128,20000,deadline,&view);if (error) {errno=-error;goto done;}
    error=slk_discovery_identity(view,&actual,&session);if (error) {errno=-error;goto done;}
    if (actual.index!=id.index || actual.generation!=id.generation || !session) {errno=EPROTO;goto done;}
    slk_client_close(client);client=NULL;
    printf("Selected /org/sparklink/slk%u_g%"PRIu64"\n",id.index,generation);
    printf("DiscoverySession: id=%"PRIu64" path=/org/sparklink/slk%u_g%"PRIu64" state=active source=broker\n",session,id.index,generation);fflush(stdout);
    uint64_t received=0;
    while (received<wanted) {
        struct SlkDiscoveryBatch batch={0};struct SlkDiscoveryReport reports[32];uintptr_t count=0;
        error=slk_discovery_read(view,&batch,reports,32,&count,1,deadline);if (error) {errno=-error;goto done;}
        if (batch.session!=session || batch.generation!=generation || count>32) {errno=EPROTO;goto done;}
        for (uintptr_t n=0;n<count && received<wanted;n++) {
            const struct SlkDiscoveryReport *r=&reports[n];if (memcmp(r->address,address,6)) continue;
            if (r->rssi_known!=1 || r->data_length>255) {errno=EPROTO;goto done;}
            printf("DiscoveryReport: session=%"PRIu64" generation=%"PRIu64" sequence=%"PRIu64" address_type=%u address=",session,generation,r->sequence,r->address_type);
            hex_print(r->address,6);printf(" rssi=%d data=",r->rssi);hex_print(r->data,r->data_length);printf("\n");fflush(stdout);received++;
        }
    }
    uint32_t stopped=99;error=slk_discovery_release(view,deadline,&stopped);if (error) {errno=-error;goto done;}
    if (stopped>1) {errno=EPROTO;goto done;}
    printf("DiscoveryReleased: session=%"PRIu64" last_physical_stop_confirmed=%s\n",session,stopped?"true":"false");fflush(stdout);status=0;
done:
    if (status) perror("application-client-c-discovery");
    slk_discovery_free(view);slk_client_close(client);return status;
}


/* Actual Owned SDK publisher. No wire codec, database or callback simulation. */
static int owned_mode(int argc,char **argv) {
    if (argc!=7) return 2;
    uint64_t index=number(argv[2]),generation=number(argv[3]);
    uint8_t service[2042],property_uuid[2042],initial[2042];
    size_t service_n=bytes(argv[4],service),property_n=bytes(argv[5],property_uuid),initial_n=bytes(argv[6],initial);
    if (index>UINT16_MAX || !generation || (service_n!=2 && service_n!=16) || (property_n!=2 && property_n!=16)) return 2;
    struct SlkServiceProperty property={.operations=5,.uuid_length=(uint8_t)property_n,.value_length=(uint16_t)initial_n};
    memcpy(property.uuid,property_uuid,property_n);memcpy(property.value,initial,initial_n);
    struct SlkControllerId id={.generation=generation,.index=(uint16_t)index};
    struct SlkClient *client=NULL;struct SlkLocalService *view=NULL;struct SlkServiceReceipt receipt={0};
    int status=1,error;const uint64_t original=now_ns()+5000000000ULL;
    error=slk_client_open_system(original,&client);if (error) {errno=-error;goto done;}
    error=slk_client_register_local_service(client,&id,service,service_n,&property,1,original,&view);if (error) {errno=-error;goto done;}
    error=slk_local_service_receipt(view,&receipt);if (error) {errno=-error;goto done;}
    if (receipt.controller.index!=id.index || receipt.controller.generation!=generation || receipt.property_count!=1 || !receipt.start || receipt.handles[0]<=receipt.start || receipt.handles[0]>receipt.end) {errno=EPROTO;goto done;}
    slk_client_close(client);client=NULL;
    printf("SdkOwnedAPI: api=c client_closed=true\nSsapOwnedService: start=%u end=%u property=%u; local registration only\n",receipt.start,receipt.end,receipt.handles[0]);fflush(stdout);
    const uint64_t end=now_ns()+30000000000ULL;
    for (;;) {
        char line[32];if (wait_fd(STDIN_FILENO,POLLIN,end) || !fgets(line,sizeof line,stdin)) {errno=EPROTO;goto done;}
        if (!strcmp(line,"value\n")) {
            uint8_t value[2042];uintptr_t length=0;
            error=slk_local_service_read(view,receipt.handles[0],value,sizeof value,&length,now_ns()+5000000000ULL);if (error) {errno=-error;goto done;}
            if (length>sizeof value) {errno=EPROTO;goto done;}
            printf("SsapOwnedValue: handle=%u value=",receipt.handles[0]);hex_print(value,length);printf("\n");fflush(stdout);
        } else if (!strcmp(line,"quit\n")) {
            error=slk_local_service_unregister(view,now_ns()+5000000000ULL);if (error) {errno=-error;goto done;}
            printf("SdkOwnedRemoved: api=c start=%u\n",receipt.start);fflush(stdout);status=0;break;
        } else {errno=EINVAL;goto done;}
    }
done:
    if (status) perror("application-client-c-owned");
    slk_local_service_free(view);slk_client_close(client);return status;
}

int main(int argc,char **argv) {
    if (argc>1 && !strcmp(argv[1],"owned")) return owned_mode(argc,argv);
    if (argc>1 && !strcmp(argv[1],"discovery")) return discovery_mode(argc,argv);
    if (argc>1 && (!strcmp(argv[1],"ssap") || !strcmp(argv[1],"ssap-error"))) return ssap_mode(argc,argv);
    if (argc!=7 || strlen(argv[3])>256) return 2;
    uint64_t index=number(argv[1]),generation=number(argv[2]),role=number(argv[4]);
    if (index>UINT16_MAX || !generation || role>1) return 2;
    uint8_t request[2042],reply[2042],received[2042];
    size_t request_n=bytes(argv[5],request),reply_n=bytes(argv[6],reply);
    if (request_n!=reply_n || !memcmp(request,reply,request_n)) return 2;
    struct SlkControllerId selected={.generation=generation,.index=(uint16_t)index},ids[256];
    struct SlkClient *client=NULL;
    int fd=-1,duplicate=-1,status=1;uintptr_t count=0;
    const uint64_t deadline=now_ns()+5000000000ULL;
    int error=slk_client_open_system(deadline,&client);
    if (error) { errno=-error;goto done; }
    error=slk_client_controllers(client,ids,256,&count,deadline);
    if (error) { errno=-error;goto done; }
    int found=0;
    for (uintptr_t i=0;i<count;i++) if (ids[i].index==selected.index && ids[i].generation==generation) found++;
    if (found!=1) { errno=ESTALE;goto done; }
    error=slk_client_open_channel(client,&selected,(const uint8_t *)argv[3],strlen(argv[3]),3,0,deadline,&fd);
    if (error) { errno=-error;goto done; }
    duplicate=fcntl(fd,F_DUPFD_CLOEXEC,3);
    if (duplicate<0) goto done;
    if (close(fd)) { fd=-1;goto done; } fd=-1;
    slk_client_close(client);client=NULL;
    struct linger linger={.l_onoff=1,.l_linger=2};
    if (setsockopt(duplicate,SOL_SOCKET,SO_LINGER,&linger,sizeof linger)) goto done;
    struct SleChannelInfo info;
    for (;;) {
        error=slk_channel_info(duplicate,&info);
        if (!error) break;
        if (error!=-EAGAIN) { errno=-error;goto done; }
        if (wait_fd(duplicate,POLLOUT,deadline)) goto done;
    }
    if (info.controller!=index || info.generation!=generation || info.directions!=3 || info.local_tcid!=31 || info.remote_tcid!=31 || info.pi!=241 || info.mode || info.mtu<request_n) { errno=EPROTO;goto done; }
    printf("{\"stage\":\"ready\",\"api\":\"c\",\"index\":%u,\"generation\":%"PRIu64",\"lifetime\":%"PRIu64",\"handle\":%u,\"dup_alive\":true,\"client_closed\":true}\n",info.controller,info.generation,info.lifetime,info.handle);
    fflush(stdout);
    char start[6];
    if (wait_fd(STDIN_FILENO,POLLIN,deadline) || read(STDIN_FILENO,start,sizeof start)!=(ssize_t)sizeof start || memcmp(start,"start\n",sizeof start)) { errno=EPROTO;goto done; }
    const uint8_t *outgoing=role?reply:request,*expected=role?request:reply;
    if (!role) {
        if (wait_fd(duplicate,POLLOUT,deadline)) goto done;
        if (send(duplicate,outgoing,request_n,MSG_DONTWAIT|MSG_NOSIGNAL)!=(ssize_t)request_n) goto done;
    }
    if (wait_fd(duplicate,POLLIN,deadline)) goto done;
    struct SleMessageSecurity receipt={0};int flags=0;
    intptr_t got=slk_channel_recv_security(duplicate,received,sizeof received,MSG_DONTWAIT|MSG_TRUNC,&receipt,&flags);
    if (got<0) { errno=(int)-got;goto done; }
    if (got!=(intptr_t)request_n || memcmp(received,expected,request_n) || flags&(MSG_TRUNC|MSG_CTRUNC)
        || receipt.controller!=info.controller || receipt.generation!=info.generation || receipt.lifetime!=info.lifetime
        || receipt.handle!=info.handle || receipt.local_tcid!=31 || receipt.remote_tcid!=31 || receipt.pi!=241) { errno=EPROTO;goto done; }
    if (role) {
        if (wait_fd(duplicate,POLLOUT,deadline)) goto done;
        if (send(duplicate,outgoing,request_n,MSG_DONTWAIT|MSG_NOSIGNAL)!=(ssize_t)request_n) goto done;
    }
    if (close(duplicate)) { duplicate=-1;goto done; } duplicate=-1;
    error=slk_client_open_system(deadline,&client);
    if (error) { errno=-error;goto done; }
    int untouched=123456;
    error=slk_client_open_channel(client,&selected,(const uint8_t *)argv[3],strlen(argv[3]),3,0,deadline,&untouched);
    if (error!=-EOPNOTSUPP || untouched!=123456) { if (!error) close(untouched);errno=EPROTO;goto done; }
    printf("{\"stage\":\"complete\",\"api\":\"c\",\"sent\":\"");hex_print(outgoing,request_n);
    printf("\",\"received\":\"");hex_print(received,request_n);
    printf("\",\"last_close_rebind\":\"NotSupported\"}\n");fflush(stdout);status=0;
done:
    if (status) perror("application-client-c");
    if (fd>=0) close(fd);
    if (duplicate>=0) close(duplicate);
    slk_client_close(client);
    return status;
}
