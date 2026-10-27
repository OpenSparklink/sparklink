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
_Static_assert(sizeof(struct SlkSsapUpdate)==2064,"unpublished bounded SSAP update receipt ABI");
_Static_assert(offsetof(struct SlkSsapUpdate,pdu)==8,"SSAP update PDU ABI");
_Static_assert(offsetof(struct SlkSsapUpdate,acknowledgement)==2056,"SSAP update ACK ABI");
_Static_assert(sizeof(struct SlkSsapSubscriptionInfo)==120,"subscription info ABI");
_Static_assert(offsetof(struct SlkSsapSubscriptionInfo,handles)==56,"subscription handles ABI");
_Static_assert(sizeof(struct SlkSsapSubscriptionPacket)==2072,"subscription packet ABI");
_Static_assert(offsetof(struct SlkSsapSubscriptionPacket,pdu)==24,"subscription PDU ABI");
_Static_assert(sizeof(struct SlkSsapSubscriptionBatch)==33312,"subscription batch ABI");
_Static_assert(offsetof(struct SlkSsapSubscriptionBatch,packets)==160,"subscription packets ABI");
_Static_assert(sizeof(struct SlkServiceReceipt)==152,"Owned receipt ABI");
_Static_assert(offsetof(struct SlkServiceProperty,value)==32,"Owned value ABI");
_Static_assert(offsetof(struct SlkServiceReceipt,handles)==24,"Owned handles ABI");
_Static_assert(sizeof(struct SlkReadProviderRequestInfo)==80,"Provider context ABI");
_Static_assert(offsetof(struct SlkReadProviderRequestInfo,token)==16,"Provider token ABI");
_Static_assert(offsetof(struct SlkReadProviderRequestInfo,maximum_bytes)==64,"Provider budget ABI");
_Static_assert(offsetof(struct SlkReadProviderRequestInfo,reserved)==69,"Provider reserved ABI");
_Static_assert(sizeof(struct SlkAuthorizationRequestInfo)==2120,"approval context ABI");
_Static_assert(offsetof(struct SlkAuthorizationRequestInfo,value)==72,"approval value ABI");
_Static_assert(sizeof(struct SlkDiscoveryBatch)==40,"discovery batch ABI");
_Static_assert(sizeof(struct SlkDiscoveryReport)==312,"discovery report ABI");
_Static_assert(offsetof(struct SlkDiscoveryReport,data)==51,"discovery data offset");

static uint64_t now_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) exit(2);
    return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}
static uint64_t wall_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_REALTIME, &t)) exit(2);
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
static size_t bytes_bounded(const char *hex, uint8_t *out, size_t capacity) {
    size_t n=strlen(hex);
    if (!n || n%2 || n/2>capacity) exit(2);
    for (size_t i=0;i<n/2;i++) {
        int a=nybble(hex[2*i]),b=nybble(hex[2*i+1]);
        if (a<0 || b<0) exit(2);
        out[i]=(uint8_t)((a<<4)|b);
    }
    return n/2;
}
static size_t bytes(const char *hex, uint8_t *out) {
    return bytes_bounded(hex,out,2042);
}
static void hex_print(const uint8_t *p,size_t n) {
    for (size_t i=0;i<n;i++) printf("%02x",p[i]);
}
/* Single existing SSAP RPC, not a wire codec or a second receive loop. */
static int ssap_mode(int argc,char **argv) {
    if ((argc!=8 && argc!=9) || !*argv[4] || strlen(argv[4])>256) return 2;
    int writing=!strcmp(argv[5],"ssap-write");
    int method=!strcmp(argv[5],"ssap-call-method");
    int description=!strcmp(argv[5],"ssap-read-description");
    if ((!writing && !method && !description && strcmp(argv[5],"ssap-read")) || argc!=((writing||method)?9:8)) return 2;
    uint64_t index=number(argv[2]),generation=number(argv[3]),handle=number(argv[6]);
    if (index>UINT16_MAX || !generation || !handle || handle>UINT16_MAX) return 2;
    int error_mode=!strcmp(argv[1],"ssap-error");
    uint64_t expected_errno=error_mode?number(argv[7]):0;
    if (error_mode && (!expected_errno || expected_errno>4095)) return 2;
    uint8_t expected[2045],value[2043],received[2045];
    size_t capacity=method?2045:2042;
    size_t expected_n=(error_mode || (!writing && !description && !*argv[7]))?0:bytes_bounded(argv[7],expected,capacity);
    size_t value_n=method?(*argv[8]?bytes_bounded(argv[8],value,2043):0):(writing?bytes(argv[8],value):0);
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
    if (method) error=slk_connection_ssap_call_method(link,(uint16_t)handle,0,value,value_n,received,capacity,&length,deadline);
    else if (writing) error=slk_connection_ssap_write(link,(uint16_t)handle,0,value,value_n,received,capacity,&length,deadline);
    else if (description) error=slk_connection_ssap_read_description(link,(uint16_t)handle,0,received,capacity,&length,deadline);
    else error=slk_connection_ssap_read(link,(uint16_t)handle,0,received,capacity,&length,deadline);
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
/* Independent command mode: no response parser or fabricated peer value. */
static int ssap_command_mode(int argc,char **argv) {
    if ((argc!=7 && argc!=8) || !*argv[4] || strlen(argv[4])>256) return 2;
    int reject=!strcmp(argv[1],"ssap-command-reject");
    uint64_t index=number(argv[2]),generation=number(argv[3]),handle=number(argv[5]);
    uint64_t minimum=argc==8?number(argv[7]):0;
    if (index>UINT16_MAX || !generation || !handle || handle>UINT16_MAX || minimum>2 || (reject && minimum)) return 2;
    uint8_t value[2043];size_t value_n=*argv[6]?bytes_bounded(argv[6],value,reject?sizeof value:2042):0;
    if (reject && value_n!=2043) return 2;
    const uint64_t deadline=now_ns()+5000000000ULL;
    struct SlkControllerId id={.generation=generation,.index=(uint16_t)index};
    struct SlkClient *client=NULL;struct SlkConnection *link=NULL;int status=1;
    int error=slk_client_open_system(deadline,&client);
    if (error) {errno=-error;goto done;}
    error=slk_client_connection(client,&id,(const uint8_t *)argv[4],strlen(argv[4]),deadline,&link);
    if (error) {errno=-error;goto done;}
    slk_client_close(client);client=NULL;
    if (reject) {
        printf("{\"stage\":\"ssap_command_start_barrier\",\"api\":\"c\",\"deadline_ns\":%"PRIu64",\"client_closed\":true,\"mode\":\"ssap-command-reject\",\"schema_version\":1}\n",deadline);
    } else {
        printf("{\"stage\":\"ssap_command_start_barrier\",\"api\":\"c\",\"deadline_ns\":%"PRIu64",\"client_closed\":true}\n",deadline);
    }
    fflush(stdout);
    char start[6];
    if (wait_fd(STDIN_FILENO,POLLIN,deadline) || read(STDIN_FILENO,start,sizeof start)!=(ssize_t)sizeof start || memcmp(start,"start\n",sizeof start)) {errno=EPROTO;goto done;}
    uint64_t called=now_ns();
    if (reject && called>=deadline) {errno=ETIMEDOUT;goto done;}
    error=slk_connection_ssap_write_command(link,(uint16_t)handle,(uint32_t)minimum,value,value_n,deadline);
    uint64_t returned=now_ns();
    if (reject) {
        /* This is the actual SDK error, not an input-parser rejection. The
         * paired capture gate separately checks absence of a wire command. */
        if (error!=-EINVAL || called>=returned || returned>=deadline) {
            fprintf(stderr,"command rejection expected timely EINVAL; actual SDK status=%d\n",error);
            errno=returned>=deadline?ETIMEDOUT:error<0?-error:EPROTO;goto done;
        }
        printf("SSAP_COMMAND_REJECTED: {\"schema_version\":1,\"mode\":\"ssap-command-reject\",\"api\":\"c\",\"method\":\"WriteSsapCommand\",\"index\":%"PRIu64",\"generation\":%"PRIu64",\"path\":\"%s\",\"handle\":%"PRIu64",\"value\":\"",index,generation,argv[4],handle);hex_print(value,value_n);
        printf("\",\"application_bytes\":2043,\"minimum\":0,\"sdk_entered\":true,\"errno\":%d,\"operation_success\":false,\"peer_delivery_confirmed\":false,\"deadline_ns\":%"PRIu64",\"call_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",-error,deadline,called,returned);fflush(stdout);
        status=0;goto done;
    }
    if (error) {errno=-error;goto done;}
    printf("SSAP_COMMAND_ADMITTED: {\"api\":\"c\",\"handle\":%"PRIu64",\"value\":\"",handle);hex_print(value,value_n);
    printf("\",\"minimum\":%"PRIu64",\"admission_only\":true,\"peer_delivery_confirmed\":false,\"deadline_ns\":%"PRIu64",\"call_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",minimum,deadline,called,returned);fflush(stdout);
    status=0;
done:
    if (status) perror("application-client-c-ssap-command");
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


/* Explicit test-application policy, never a default policy in the SDK/daemon. */
struct OwnedPending {
    struct SlkAuthorizationRequest *request;
    struct SlkAuthorizationRequestInfo info;
};
static void owned_info_json(const struct SlkAuthorizationRequestInfo *p) {
    printf("{\"api\":\"c\",\"index\":%u,\"generation\":%"PRIu64",\"token\":%"PRIu64",\"request_id\":%"PRIu64",\"lifetime\":%"PRIu64",\"handle\":%u,\"epoch\":%"PRIu64",\"level\":%u,\"deadline_ns\":%"PRIu64",\"property\":%u,\"data_type\":%u,\"write\":%s,\"value\":\"",
        p->controller.index,p->controller.generation,p->token,p->request_id,p->connection_lifetime,
        p->connection_handle,p->security_epoch,p->security_level,p->deadline_ns,p->property,p->data_type,p->write?"true":"false");
    hex_print(p->value,p->value_length);
    printf("\",\"local_tcid\":%u,\"remote_tcid\":%u,\"pi\":%u",p->local_tcid,p->remote_tcid,p->pi);
}
static void owned_clear(struct OwnedPending *p) {
    slk_authorization_request_free(p->request);p->request=NULL;
}
/* Explicit benchmark observation only. No server TTL,commit or delivery claim. */
static void owned_lifecycle(const char *stage,const struct SlkServiceReceipt *r,
    uint64_t created,uint64_t end,int error,uint64_t token,uint64_t request,
    uint64_t call_started,uint64_t call_returned) {
    printf("SdkOwnedLifecycle: {\"version\":1,\"api\":\"c\",\"stage\":\"%s\",\"pid\":%ld,\"index\":%u,\"generation\":%"PRIu64",\"start\":%u,\"property\":%u,\"created_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"sampled_ns\":%"PRIu64",\"wall_ns\":%"PRIu64",\"error\":%d,\"token\":%"PRIu64",\"request_id\":%"PRIu64",\"call_started_ns\":%"PRIu64",\"call_returned_ns\":%"PRIu64"}\n",
        stage,(long)getpid(),r->controller.index,r->controller.generation,r->start,r->handles[0],
        created,end,now_ns(),wall_ns(),error,token,request,call_started,call_returned);fflush(stdout);
}
static int owned_receive(struct SlkLocalService *view,const struct SlkServiceReceipt *receipt,
                         struct OwnedPending *p,int ask,int allow,uint64_t created,uint64_t end) {
    if (p->request) return 0;
    int error=slk_local_service_next_authorization(view,&p->request);
    if (error==-EAGAIN) return 0;
    if (error) return error;
    error=slk_authorization_request_info(p->request,&p->info);
    const struct SlkAuthorizationRequestInfo *info=&p->info;
    if (!error && (info->controller.index!=receipt->controller.index
        || info->controller.generation!=receipt->controller.generation
        || info->property!=receipt->handles[0] || !info->token || !info->request_id
        || !info->connection_lifetime || !info->security_epoch || !info->deadline_ns
        || info->security_level>2 || (info->data_type!=0 && info->data_type!=2) || info->write>1 || info->value_length>2042
        || (info->data_type==2 && (info->security_level!=2 || !info->write || info->value_length!=2 || info->value[1] || (info->value[0]&~3)))
        || (!info->write && info->value_length)
        || info->local_tcid!=10 || info->remote_tcid!=10 || info->pi)) error=-EPROTO;
    if (error) {owned_clear(p);return error;}
    if (ask) {
        printf("SdkAuthorizationRequest: ");owned_info_json(info);printf("}\n");
        printf("SsapAuthorizationPrompt: token=%"PRIu64" request=%"PRIu64" index=%u generation=%"PRIu64" lifetime=%"PRIu64" handle=%u epoch=%"PRIu64" security=%u property=%u data_type=%u write=%s bytes=%u deadline_ns=%"PRIu64"; answer 'yes %"PRIu64"' or 'no %"PRIu64"'\n",
            info->token,info->request_id,info->controller.index,info->controller.generation,
            info->connection_lifetime,info->connection_handle,info->security_epoch,info->security_level,
            info->property,info->data_type,info->write?"true":"false",info->value_length,info->deadline_ns,info->token,info->token);
        fflush(stdout);return 0;
    }
    /* Call-start observations,not the internal decision linearization point. */
    uint64_t decision=now_ns(),wall=wall_ns();
    error=slk_authorization_request_reply(p->request,(uint32_t)allow);
    if (created) {
        uint64_t returned=now_ns();
        owned_lifecycle("approval_return",receipt,created,end,error,info->token,info->request_id,decision,returned);
    }
    owned_clear(p);
    if (!error) {
        printf("SdkAuthorizationDecision: ");owned_info_json(info);
        printf(",\"allow\":%s,\"decision_ns\":%"PRIu64",\"decision_wall_ns\":%"PRIu64"}\n",allow?"true":"false",decision,wall);fflush(stdout);
    }
    return error;
}
static int owned_answer(struct OwnedPending *p,uint64_t token,int allow) {
    const int called=p->request && p->info.token==token;
    const uint64_t current=p->request?p->info.token:0;
    const int result=called?slk_authorization_request_reply(p->request,(uint32_t)allow):-ESTALE;
    if (called) owned_clear(p);
    printf("SdkAuthorizationReply: {\"api\":\"c\",\"token\":%"PRIu64",\"current_token\":%"PRIu64",\"allow\":%s,\"api_called\":%s,\"result\":%d,\"returned_ns\":%"PRIu64"}\n",
        token,current,allow?"true":"false",called?"true":"false",result,now_ns());fflush(stdout);
    return result==0 || result==-ESTALE || result==-ETIMEDOUT || result==-ESHUTDOWN ? 0 : result;
}

/* External SDK observations only. No callback endpoint, wire codec or Engine. */
struct OwnedProviderPending {
    struct SlkReadProviderRequest *request;
    struct SlkReadProviderRequestInfo info;
    struct SlkWriteProviderRequest *write_request;
    struct SlkWriteProviderRequestInfo write_info;
    uint8_t proposed[2042],applied[2042];
    size_t applied_length;
    int has_applied;
};
static void owned_provider_clear(struct OwnedProviderPending *p) {
    slk_read_provider_request_free(p->request);p->request=NULL;
    slk_write_provider_request_free(p->write_request);p->write_request=NULL;
}
static int owned_provider_close(struct OwnedProviderPending *p,
                                struct SlkReadProvider **provider,struct SlkWriteProvider **writer,int *fd) {
    /* Stop new callback admission before releasing the delivered request. */
    slk_read_provider_free(*provider);*provider=NULL;
    slk_write_provider_free(*writer);*writer=NULL;
    owned_provider_clear(p);
    int result=0;
    if (*fd>=0 && close(*fd)) result=-errno;
    *fd=-1;return result;
}
static int owned_provider_receive(struct SlkReadProvider *provider,
                                  const struct SlkServiceReceipt *receipt,
                                  struct OwnedProviderPending *p) {
    if (p->request) return 0;
    int error=slk_read_provider_next(provider,&p->request);
    if (error==-EAGAIN) return 0;
    if (error) return error;
    error=slk_read_provider_request_info(p->request,&p->info);
    const struct SlkReadProviderRequestInfo *info=&p->info;
    if (!error && (info->controller.index!=receipt->controller.index
        || info->controller.generation!=receipt->controller.generation
        || info->property!=receipt->handles[0] || !info->token || !info->request_id
        || !info->connection_lifetime || !info->security_epoch || !info->deadline_ns
        || info->connection_handle>0x0fff || info->security_level>2
        || info->maximum_bytes>2042 || info->local_tcid!=10
        || info->remote_tcid!=10 || info->pi)) error=-EPROTO;
    for (size_t i=0;i<sizeof info->reserved;i++) if (info->reserved[i]) error=-EPROTO;
    for (size_t i=0;i<sizeof info->controller.reserved;i++) if (info->controller.reserved[i]) error=-EPROTO;
    if (error) {owned_provider_clear(p);return error;}
    const uint64_t observed=now_ns(),observed_wall=wall_ns();
    printf("SdkReadProviderRequest: {\"api\":\"c\",\"index\":%u,\"generation\":%"PRIu64",\"token\":%"PRIu64",\"request_id\":%"PRIu64",\"lifetime\":%"PRIu64",\"handle\":%u,\"epoch\":%"PRIu64",\"level\":%u,\"deadline_ns\":%"PRIu64",\"property\":%u,\"maximum_bytes\":%u,\"local_tcid\":%u,\"remote_tcid\":%u,\"pi\":%u,\"observed_ns\":%"PRIu64",\"observed_wall_ns\":%"PRIu64"}\n",
        info->controller.index,info->controller.generation,info->token,info->request_id,
        info->connection_lifetime,info->connection_handle,info->security_epoch,
        info->security_level,info->deadline_ns,info->property,info->maximum_bytes,
        info->local_tcid,info->remote_tcid,info->pi,observed,observed_wall);
    fflush(stdout);return 0;
}
static int owned_write_provider_receive(struct SlkWriteProvider *provider,
                                        const struct SlkServiceReceipt *receipt,
                                        struct OwnedProviderPending *p) {
    if (p->write_request) return 0;
    int error=slk_write_provider_next(provider,&p->write_request);
    if (error==-EAGAIN) return 0;
    if (error) return error;
    error=slk_write_provider_request_info(p->write_request,&p->write_info);
    const struct SlkWriteProviderRequestInfo *i=&p->write_info;
    if (!error && (i->controller.index!=receipt->controller.index
        || i->controller.generation!=receipt->controller.generation
        || i->property!=receipt->handles[0] || !i->token || !i->request_id
        || !i->connection_lifetime || !i->security_epoch || !i->deadline_ns
        || i->connection_handle>0x0fff || i->security_level>2 || i->value_length>2042
        || i->local_tcid!=10 || i->remote_tcid!=10 || i->pi || i->offset || i->data_type
        || (i->operation!=12 && i->operation!=13) || i->verify>1
        || (i->operation==12 && i->verify))) error=-EPROTO;
    for (size_t n=0;n<sizeof i->reserved;n++) if (i->reserved[n]) error=-EPROTO;
    for (size_t n=0;n<sizeof i->controller.reserved;n++) if (i->controller.reserved[n]) error=-EPROTO;
    size_t length=0;
    if (!error) error=slk_write_provider_request_value(p->write_request,p->proposed,sizeof p->proposed,&length);
    if (!error && length!=i->value_length) error=-EPROTO;
    if (error) {owned_provider_clear(p);return error;}
    printf("SdkWriteProviderRequest: {\"api\":\"c\",\"index\":%u,\"generation\":%"PRIu64",\"token\":%"PRIu64",\"request_id\":%"PRIu64",\"lifetime\":%"PRIu64",\"handle\":%u,\"epoch\":%"PRIu64",\"level\":%u,\"deadline_ns\":%"PRIu64",\"property\":%u,\"local_tcid\":%u,\"remote_tcid\":%u,\"pi\":%u,\"operation\":%u,\"data_type\":%u,\"offset\":%u,\"value_length\":%u,\"verify\":%s,\"value\":\"",
        i->controller.index,i->controller.generation,i->token,i->request_id,i->connection_lifetime,
        i->connection_handle,i->security_epoch,i->security_level,i->deadline_ns,i->property,
        i->local_tcid,i->remote_tcid,i->pi,i->operation,i->data_type,i->offset,i->value_length,i->verify?"true":"false");
    hex_print(p->proposed,length);
    printf("\",\"observed_ns\":%"PRIu64",\"observed_wall_ns\":%"PRIu64"}\n",now_ns(),wall_ns());
    fflush(stdout);return 0;
}
/* This bounded UI parser only selects an opaque SDK request. No request_id or
 * deadline is accepted from stdin, and no malformed input becomes a reply. */
static int owned_provider_input(char *line,uint64_t *token,uint16_t *status,
                                uint8_t *value,size_t *length) {
    const int application_error=!strncmp(line,"provider-error ",15);
    char *text=line+(application_error?15:8);
    size_t total=strlen(text);
    if (!total || text[total-1]!='\n') return -EINVAL;
    text[total-1]='\0';
    char *separator=strchr(text,' ');
    if (!separator || text[0]!='p' || separator==text+1) return -EINVAL;
    *separator='\0';
    for (const char *p=text+1;*p;p++) if (*p<'0' || *p>'9') return -EINVAL;
    char *endptr=NULL;errno=0;
    *token=strtoull(text+1,&endptr,10);
    if (errno || !endptr || *endptr || !*token) return -EINVAL;
    char *argument=separator+1;
    *status=0;*length=0;
    if (application_error) {
        if (strlen(argument)!=2) return -EINVAL;
        int a=nybble(argument[0]>='A' && argument[0]<='F'?argument[0]+('a'-'A'):argument[0]);
        int b=nybble(argument[1]>='A' && argument[1]<='F'?argument[1]+('a'-'A'):argument[1]);
        if (a<0 || b<0 || ((a<<4)|b)<0xaf) return -EINVAL;
        *status=(uint16_t)((a<<4)|b);return 0;
    }
    if (!strcmp(argument,"-")) return 0;
    size_t digits=strlen(argument);
    if (!digits || digits%2 || digits/2>2042) return -EINVAL;
    for (size_t i=0;i<digits;i++) {
        if (argument[i]>='A' && argument[i]<='F') argument[i]+='a'-'A';
        if (nybble(argument[i])<0) return -EINVAL;
    }
    /* Reuse the existing hex decoder after validating its exit-on-error input. */
    *length=bytes(argument,value);return 0;
}
static int owned_provider_answer(struct OwnedProviderPending *p,
                                 uint64_t token,uint16_t status,
                                 const uint8_t *value,size_t length,uint64_t end,int writing) {
    int called=writing?(p->write_request && p->write_info.token==token):(p->request && p->info.token==token);
    const uint64_t current=writing?(p->write_request?p->write_info.token:0):(p->request?p->info.token:0);
    const uint64_t deadline=writing?(p->write_request?p->write_info.deadline_ns:0):(p->request?p->info.deadline_ns:0);
    const uint64_t started=now_ns();
    if (started>=end) return -ETIMEDOUT;
    const int matched=called && (!writing || status!=0 || (length==p->write_info.value_length && !memcmp(value,p->proposed,length)));
    const size_t response_length=writing && !p->write_info.verify?0:length;
    int result=-ESTALE;
    if (called && !matched) {result=-EINVAL;called=0;}
    if (called) result=writing?slk_write_provider_request_reply(p->write_request,status,value,response_length):slk_read_provider_request_reply(p->request,status,value,length);
    if (writing && called && !result && !status) {memcpy(p->applied,value,length);p->applied_length=length;p->has_applied=1;}
    const uint64_t returned=now_ns();
    printf("%sReply: {\"api\":\"c\",\"token\":%"PRIu64",\"current_token\":%"PRIu64",\"status\":%u,\"value\":\"",
        writing?"SdkWriteProvider":"SdkReadProvider",token,current,status);hex_print(value,response_length);
    printf("\",\"api_called\":%s,\"result\":%d,\"deadline_ns\":%"PRIu64",\"started_ns\":%"PRIu64",\"returned_ns\":%"PRIu64",\"local_acceptance_only\":true",
        called?"true":"false",result,deadline,started,returned);
    if (writing) {
        printf(",\"matched_value\":%s,\"accepted_value\":",matched?"true":"false");
        if (called && !result && !status) {printf("\"");hex_print(value,length);printf("\"");}else printf("null");
    }
    printf("}\n");fflush(stdout);
    if (called && (result==0 || result==-ESTALE || result==-ETIMEDOUT || result==-ESHUTDOWN)) owned_provider_clear(p);
    /* Validation failures do not consume the same opaque request. Wrong UI
     * tokens never called the API and cannot clear someone else's request. */
    return result==0 || result==-ESTALE || result==-ETIMEDOUT || result==-ESHUTDOWN
        || result==-EINVAL || result==-EMSGSIZE ? 0 : result;
}

/* Actual Owned SDK publisher. No wire codec, database or callback simulation. */
static int owned_mode(int argc,char **argv) {
    int updates=!strcmp(argv[1],"owned-updates"),writing=!strcmp(argv[1],"owned-writeonly");
    if ((updates && argc!=9) || (!updates && argc!=7 && argc!=8)) return 2;
    int requests=updates || argc==8,allow=requests && !strcmp(argv[7],"allow"),ask=requests && !strcmp(argv[7],"ask");
    if (requests && !allow && !ask && strcmp(argv[7],"deny")) return 2;
    uint64_t index=number(argv[2]),generation=number(argv[3]);
    uint8_t service[2042],property_uuid[2042],initial[2042];
    size_t service_n=bytes(argv[4],service),property_n=bytes(argv[5],property_uuid),initial_n=bytes(argv[6],initial);
    if (index>UINT16_MAX || !generation || (service_n!=2 && service_n!=16) || (property_n!=2 && property_n!=16)) return 2;
    struct SlkServiceProperty property={.operations=updates?541:writing?6:!strcmp(argv[1],"owned-readonly")?1:5,.access=requests && !updates?36:0,.uuid_length=(uint8_t)property_n,.value_length=(uint16_t)initial_n};
    memcpy(property.uuid,property_uuid,property_n);memcpy(property.value,initial,initial_n);
    struct SlkControllerId id={.generation=generation,.index=(uint16_t)index};
    struct SlkClient *client=NULL;struct SlkLocalService *view=NULL;struct SlkServiceReceipt receipt={0};
    struct SlkConnection *link=NULL;
    int status=1,error,approval_fd=-1,observing=0;uint64_t created=0,end=0;
    struct SlkReadProvider *provider=NULL;struct SlkWriteProvider *writer=NULL;struct OwnedProviderPending provider_pending={0};
    int provider_fd=-1,provider_attempted=0,owner_loss_hold=0,owner_loss_observations=0;
    struct OwnedPending pending={0};const uint64_t original=now_ns()+5000000000ULL;
    error=slk_client_open_system(original,&client);if (error) {errno=-error;goto done;}
    error=slk_client_register_local_service(client,&id,service,service_n,&property,1,requests?SLK_SERVICE_AUTHORIZATION_REQUESTS:SLK_SERVICE_AUTHORIZATION_NONE,original,&view);if (error) {errno=-error;goto done;}
    error=slk_local_service_receipt(view,&receipt);if (error) {errno=-error;goto done;}
    if (receipt.controller.index!=id.index || receipt.controller.generation!=generation || receipt.property_count!=1 || !receipt.start || receipt.handles[0]<=receipt.start || receipt.handles[0]>receipt.end) {errno=EPROTO;goto done;}
    if (requests) {error=slk_local_service_authorization_fd(view,&approval_fd);if (error) {errno=-error;goto done;}}
    if (updates) {
        error=slk_client_connection(client,&id,(const uint8_t *)argv[8],strlen(argv[8]),original,&link);
        if (error) {errno=-error;goto done;}
    }
    slk_client_close(client);client=NULL;
    printf("SdkOwnedAPI: api=c client_closed=true\nSsapOwnedService: start=%u end=%u property=%u; local registration only\n",receipt.start,receipt.end,receipt.handles[0]);fflush(stdout);
    created=now_ns();end=created+30000000000ULL;char line[2*2042+64];size_t used=0;
    for (;;) {
        /* Try next before sleeping;the duplicated eventfd is poll-only. */
        if (requests && view && !owner_loss_hold) {error=owned_receive(view,&receipt,&pending,ask,allow,observing?created:0,end);if (error) {errno=-error;goto done;}}
        uint64_t now=now_ns();if (now>=end) {errno=ETIMEDOUT;goto done;}
        if ((provider || writer) && view && !owner_loss_hold) {error=writing?owned_write_provider_receive(writer,&receipt,&provider_pending):owned_provider_receive(provider,&receipt,&provider_pending);if (error) {errno=-error;goto done;}}
        now=now_ns();if (now>=end) {errno=ETIMEDOUT;goto done;}
        struct pollfd fds[3]={{.fd=STDIN_FILENO,.events=POLLIN},{.fd=view && !owner_loss_hold?approval_fd:-1,.events=POLLIN},
            {.fd=view && !owner_loss_hold && (provider || writer) && !provider_pending.request && !provider_pending.write_request?provider_fd:-1,.events=POLLIN}};
        int count=poll(fds,3,(int)((end-now+999999)/1000000));
        if (count<0 && errno==EINTR) continue;
        if (count<=0) {if (!count) errno=ETIMEDOUT;goto done;}
        if (requests && fds[1].revents&(POLLERR|POLLHUP|POLLNVAL)) {errno=EIO;goto done;}
        if (fds[2].revents&(POLLERR|POLLHUP|POLLNVAL)) {errno=EIO;goto done;}
        if (!(fds[0].revents&POLLIN)) {
            if (fds[0].revents&(POLLERR|POLLHUP|POLLNVAL)) {errno=EPIPE;goto done;}
            continue;
        }
        ssize_t n=read(STDIN_FILENO,line+used,1);
        if (n<0 && errno==EINTR) continue;
        if (n!=1) {errno=EPIPE;goto done;}
        if (line[used++]!='\n') {if (used==sizeof line-1) {errno=E2BIG;goto done;}continue;}
        line[used]='\0';used=0;
        if (!strcmp(line,"provider\n")) {
            if ((!writing && strcmp(argv[1],"owned-readonly")) || updates || !view || provider_attempted) {errno=EINVAL;goto done;}
            const uint64_t started=now_ns();
            if (started>=end) {errno=ETIMEDOUT;goto done;}
            uint64_t deadline=started+5000000000ULL;if (deadline>end) deadline=end;
            provider_attempted=1;
            error=writing?slk_local_service_bind_write_provider(view,receipt.handles[0],deadline,&writer):slk_local_service_bind_read_provider(view,receipt.handles[0],deadline,&provider);
            const uint64_t returned=now_ns();
            const int notification_called=error==0;
            const int notification_error=notification_called?(writing?slk_write_provider_fd(writer,&provider_fd):slk_read_provider_fd(provider,&provider_fd)):0;
            printf("%sBound: {\"api\":\"c\",\"index\":%u,\"generation\":%"PRIu64",\"property\":%u,\"started_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64",\"result\":%d,\"notification_result\":",
                writing?"SdkWriteProvider":"SdkReadProvider",receipt.controller.index,receipt.controller.generation,receipt.handles[0],started,deadline,returned,error);
            if (notification_called) printf("%d",notification_error);else printf("null");
            printf(",\"notification_ready\":%s,\"local_binding_only\":true}\n",notification_called && !notification_error?"true":"false");fflush(stdout);
            if (error || notification_error) {errno=error?-error:-notification_error;goto done;}
        } else if (!strncmp(line,"provide ",8) || !strncmp(line,"provider-error ",15)) {
            if (!view || (!provider && !writer) || !provider_attempted) {errno=ESHUTDOWN;goto done;}
            uint64_t token=0;uint16_t reply_status=0;uint8_t value[2042];size_t length=0;
            error=owned_provider_input(line,&token,&reply_status,value,&length);
            if (error) {errno=-error;goto done;}
            error=owned_provider_answer(&provider_pending,token,reply_status,value,length,end,writing);
            if (error) {errno=-error;goto done;}
        } else if (!strcmp(line,"hold-owner-loss\n")) {
            if (!writing || !view || !writer || !provider_pending.write_request || pending.request || owner_loss_hold) {errno=EINVAL;goto done;}
            owner_loss_hold=1;
            /* Test UI observation only: retain the actual SDK request and fd. */
            printf("SdkWriteProviderOwnerLossArmed: {\"api\":\"c\",\"token\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"armed_ns\":%"PRIu64"}\n",
                provider_pending.write_info.token,provider_pending.write_info.deadline_ns,now_ns());fflush(stdout);
        } else if (!strcmp(line,"observe-owner-loss\n")) {
            if (!owner_loss_hold || !view || !writer || !provider_pending.write_request) {errno=EINVAL;goto done;}
            const struct SlkWriteProviderRequestInfo original_info=provider_pending.write_info;
            const uint64_t started=now_ns();
            const uint64_t observation_deadline=owner_loss_observations?end:(original_info.deadline_ns<end?original_info.deadline_ns:end);
            if (wait_fd(provider_fd,POLLIN,observation_deadline)) goto done;
            struct pollfd notice={.fd=provider_fd,.events=POLLIN};
            if (poll(&notice,1,0)!=1 || !(notice.revents&POLLIN) || notice.revents&(POLLERR|POLLHUP|POLLNVAL)) {errno=EIO;goto done;}
            struct SlkWriteProviderRequest *next=NULL;struct SlkAuthorizationRequest *approval=NULL;
            const int next_result=slk_write_provider_next(writer,&next);
            const int authorization_result=slk_local_service_next_authorization(view,&approval);
            slk_write_provider_request_free(next);slk_authorization_request_free(approval);
            const int rejected=slk_write_provider_request_reply(provider_pending.write_request,0,
                provider_pending.proposed,original_info.verify?original_info.value_length:0);
            struct SlkWriteProviderRequestInfo after={0};uint8_t value[2042];uintptr_t length=0;
            const int same=!slk_write_provider_request_info(provider_pending.write_request,&after) && !memcmp(&after,&original_info,sizeof after);
            const int value_preserved=!slk_write_provider_request_value(provider_pending.write_request,value,sizeof value,&length)
                && length==original_info.value_length && !memcmp(value,provider_pending.proposed,length);
            const int alive=fcntl(provider_fd,F_GETFD)>=0;const uint64_t returned=now_ns();owner_loss_observations++;
            printf("SdkWriteProviderOwnerLoss: {\"api\":\"c\",\"ordinal\":%d,\"token\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"observation_deadline_ns\":%"PRIu64",\"started_ns\":%"PRIu64",\"returned_ns\":%"PRIu64",\"notification_events\":%d,\"next_result\":%d,\"authorization_result\":%d,\"reply_result\":%d,\"info_preserved\":%s,\"value_preserved\":%s,\"notification_fd_alive\":%s,\"local_observation_only\":true}\n",
                owner_loss_observations,original_info.token,original_info.deadline_ns,observation_deadline,started,returned,notice.revents,
                next_result,authorization_result,rejected,same?"true":"false",value_preserved?"true":"false",alive?"true":"false");fflush(stdout);
            if (next_result!=-ESTALE || authorization_result!=-ESTALE || rejected!=-ESTALE || !same || !value_preserved || !alive || returned>=observation_deadline) {errno=EPROTO;goto done;}
        } else if (!strcmp(line,"provider-unregister\n")) {
            if (!view || (writing?(!writer || !provider_pending.write_request):
                    (strcmp(argv[1],"owned-readonly") || !provider || !provider_pending.request))) {errno=EINVAL;goto done;}
            /* Keep the original opaque request, immutable proposed bytes and
             * notification fd while the SDK closes admission and withdraws. */
            const struct SlkReadProviderRequestInfo snapshot=provider_pending.info;
            const struct SlkWriteProviderRequestInfo write_snapshot=provider_pending.write_info;
            const uint64_t token=writing?write_snapshot.token:snapshot.token;
            const uint16_t property=writing?write_snapshot.property:snapshot.property;
            const uint64_t original_deadline=writing?write_snapshot.deadline_ns:snapshot.deadline_ns;
            const uint64_t started=now_ns();
            uint64_t deadline=original_deadline;if (deadline>end) deadline=end;
            if (started>=deadline) {errno=ETIMEDOUT;goto done;}
            const int removed=slk_local_service_unregister(view,deadline);
            const uint64_t returned=now_ns();
            int same=0,value_preserved=1;
            if (writing) {
                struct SlkWriteProviderRequestInfo after={0};
                const int info_result=slk_write_provider_request_info(provider_pending.write_request,&after);
                same=!info_result && !memcmp(&after,&write_snapshot,sizeof after);
                uint8_t bytes_after[2042];uintptr_t length_after=0;
                const int value_result=slk_write_provider_request_value(provider_pending.write_request,
                    bytes_after,sizeof bytes_after,&length_after);
                value_preserved=!value_result && length_after==write_snapshot.value_length
                    && !memcmp(bytes_after,provider_pending.proposed,length_after);
            } else {
                struct SlkReadProviderRequestInfo after={0};
                const int info_result=slk_read_provider_request_info(provider_pending.request,&after);
                same=!info_result && !memcmp(&after,&snapshot,sizeof after);
            }
            const int notification_alive=fcntl(provider_fd,F_GETFD)>=0;
            const uint64_t reply_started=now_ns();
            /* Use valid original WRITE bytes so validation cannot mask the
             * withdrawal result. This attempt must not mutate app memory. */
            const int rejected=writing?slk_write_provider_request_reply(provider_pending.write_request,0,
                provider_pending.proposed,write_snapshot.verify?write_snapshot.value_length:0):
                slk_read_provider_request_reply(provider_pending.request,0,NULL,0);
            const uint64_t reply_returned=now_ns();
            printf("%sUnregistered: {\"api\":\"c\",\"token\":%"PRIu64",\"property\":%u,\"original_deadline_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"started_ns\":%"PRIu64",\"returned_ns\":%"PRIu64",\"result\":%d,\"info_preserved\":%s,\"notification_fd_alive\":%s,\"reply_started_ns\":%"PRIu64",\"reply_returned_ns\":%"PRIu64",\"reply_result\":%d,\"local_observation_only\":true",
                writing?"SdkWriteProvider":"SdkReadProvider",token,property,original_deadline,deadline,started,returned,removed,
                same?"true":"false",notification_alive?"true":"false",reply_started,reply_returned,rejected);
            if (writing) printf(",\"value_preserved\":%s",value_preserved?"true":"false");
            printf("}\n");fflush(stdout);
            /* Preserve uncertain failures; never print a successful removal for
             * a failed RPC. The supervisor checks the separate peer outcome. */
            if (removed) {errno=-removed;goto done;}
            if (!same || !value_preserved || !notification_alive || rejected!=-ESHUTDOWN || reply_returned>=deadline) {errno=EPROTO;goto done;}
            slk_local_service_free(view);view=NULL;
            error=owned_provider_close(&provider_pending,&provider,&writer,&provider_fd);if (error) {errno=-error;goto done;}
        } else if (!strcmp(line,"lifecycle\n")) {
            if (updates || !allow || !view || observing) {errno=EINVAL;goto done;}
            if (now_ns()>=end) {errno=ETIMEDOUT;goto done;}
            observing=1;owned_lifecycle("observed",&receipt,created,end,0,0,0,0,0);
        } else if (writing && !strcmp(line,"value\n")) {
            printf("SdkWriteProviderValue: {\"api\":\"c\",\"property\":%u,\"value\":",receipt.handles[0]);
            if (provider_pending.has_applied) {printf("\"");hex_print(provider_pending.applied,provider_pending.applied_length);printf("\"");}else printf("null");
            printf(",\"application_memory_only\":true}\n");fflush(stdout);
        } else if (!strcmp(line,"value\n")) {
            if (!view) {errno=ESHUTDOWN;goto done;}
            uint8_t value[2042];uintptr_t length=0;
            error=slk_local_service_read(view,receipt.handles[0],value,sizeof value,&length,now_ns()+5000000000ULL);if (error) {errno=-error;goto done;}
            if (length>sizeof value) {errno=EPROTO;goto done;}
            printf("SsapOwnedValue: handle=%u value=",receipt.handles[0]);hex_print(value,length);printf("\n");fflush(stdout);
        } else if (!strncmp(line,"replace ",8)) {
            if (!view) {errno=ESHUTDOWN;goto done;}
            line[strlen(line)-1]='\0';uint8_t value[2042];size_t length=line[8]?bytes(line+8,value):0;
            uint64_t started=now_ns(),deadline=started+5000000000ULL;
            error=slk_local_service_replace(view,receipt.handles[0],value,length,deadline);
            if (error) {errno=-error;goto done;}
            printf("SdkOwnedReplaced: {\"api\":\"c\",\"handle\":%u,\"value\":\"",receipt.handles[0]);hex_print(value,length);
            printf("\",\"started_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",started,deadline,now_ns());fflush(stdout);
        } else if (updates && !strcmp(line,"configuration\n")) {
            uint8_t modes=0;uint64_t started=now_ns(),deadline=started+5000000000ULL;
            error=slk_connection_ssap_owned_configuration(link,receipt.handles[0],&modes,deadline);
            if (error || modes>3) {errno=error?-error:EPROTO;goto done;}
            printf("SdkOwnedConfiguration: {\"api\":\"c\",\"handle\":%u,\"modes\":%u,\"started_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",receipt.handles[0],modes,started,deadline,now_ns());fflush(stdout);
        } else if (updates && (!strcmp(line,"notify\n") || !strcmp(line,"indicate\n") || !strcmp(line,"indicate-deadline\n") || !strcmp(line,"indicate-observe\n"))) {
            int short_deadline=!strcmp(line,"indicate-deadline\n"),observe=short_deadline || !strcmp(line,"indicate-observe\n"),indication=strcmp(line,"notify\n")!=0;struct SlkSsapUpdate result={0};
            uint64_t started=now_ns(),deadline=started+(short_deadline?1000000000ULL:5000000000ULL);
            error=slk_connection_ssap_send_owned(link,receipt.handles[0],(uint32_t)indication,&result,deadline);
            if (observe) {
                /* Observed API result only. The supervisor must reject a wrong
                 * errno or an unexpected success; neither is a PASS here. */
                printf("%s: {\"api\":\"c\",\"handle\":%u,\"result\":%d,\"started_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",short_deadline?"SdkOwnedUpdateDeadline":"SdkOwnedUpdateObserved",receipt.handles[0],error,started,deadline,now_ns());fflush(stdout);
                continue;
            }
            if (error || result.stage!=(indication?2U:1U) || result.pdu_length>2048 || result.acknowledgement_length>3) {errno=error?-error:EPROTO;goto done;}
            printf("SdkOwnedUpdate: {\"api\":\"c\",\"handle\":%u,\"stage\":%u,\"pdu\":\"",receipt.handles[0],result.stage);hex_print(result.pdu,result.pdu_length);
            printf("\",\"ack\":\"");hex_print(result.acknowledgement,result.acknowledgement_length);
            printf("\",\"started_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",started,deadline,now_ns());fflush(stdout);
        } else if (ask && (!strncmp(line,"yes ",4) || !strncmp(line,"no ",3))) {
            int answer=!strncmp(line,"yes ",4);line[strlen(line)-1]='\0';
            const char *token=line+(answer?4:3);
            for (const char *p=token;*p;p++) if (*p<'0' || *p>'9') {errno=EINVAL;goto done;}
            error=owned_answer(&pending,number(token),answer);
            if (error) {errno=-error;goto done;}
        } else if (ask && !strcmp(line,"close\n")) {
            if (!view || !pending.request) {errno=EINVAL;goto done;}
            struct SlkAuthorizationRequestInfo after={0};uint64_t token=pending.info.token;
            slk_local_service_free(view);view=NULL;
            int info_result=slk_authorization_request_info(pending.request,&after);
            int same=!info_result && !memcmp(&after,&pending.info,sizeof after);
            int rejected=slk_authorization_request_reply(pending.request,1);
            int notification_alive=fcntl(approval_fd,F_GETFD)>=0;
            printf("SdkServiceClosed: {\"api\":\"c\",\"token\":%"PRIu64",\"info_preserved\":%s,\"notification_fd_alive\":%s,\"reply_result\":%d,\"closed_ns\":%"PRIu64"}\n",
                token,same?"true":"false",notification_alive?"true":"false",rejected,now_ns());fflush(stdout);
            owned_clear(&pending);
            if (!same || !notification_alive || rejected!=-ESTALE) {errno=EPROTO;goto done;}
        } else if (!strcmp(line,"quit\n")) {
            if (owner_loss_hold) {
                if (!owner_loss_observations) {errno=EPROTO;goto done;}
                printf("SdkOwnedRetiredExit: api=c start=%u; local release only\n",receipt.start);fflush(stdout);status=0;break;
            }
            if (!view) {printf("SdkOwnedClosedExit: api=c start=%u\n",receipt.start);fflush(stdout);status=0;break;}
            error=owned_provider_close(&provider_pending,&provider,&writer,&provider_fd);if (error) {errno=-error;goto done;}
            uint64_t cleanup_deadline=now_ns()+5000000000ULL;
            if (provider_attempted && cleanup_deadline>end) cleanup_deadline=end;
            error=slk_local_service_unregister(view,cleanup_deadline);if (error) {errno=-error;goto done;}
            printf("SdkOwnedRemoved: api=c start=%u\n",receipt.start);fflush(stdout);status=0;break;
        } else {errno=EINVAL;goto done;}
    }
done:
    if (observing) owned_lifecycle("cleanup_begin",&receipt,created,end,status?-errno:0,0,0,0,0);
    if (status) perror("application-client-c-owned");
    int provider_cleanup=owned_provider_close(&provider_pending,&provider,&writer,&provider_fd);
    if (provider_cleanup && !status) {errno=-provider_cleanup;perror("application-client-c-owned-provider-close");status=1;}
    owned_clear(&pending);
    if (approval_fd>=0) close(approval_fd);
    slk_local_service_free(view);slk_connection_close(link);slk_client_close(client);
    if (observing) owned_lifecycle("cleanup_end",&receipt,created,end,0,0,0,0,0);
    return status;
}

/* Ordinary application actually verifies the complete random update,then writes
 * a distinct business reply through the same existing SSAP/physical Session. */
static int checked_update_write(struct SlkConnection *link,uint16_t handle,unsigned mode,
    const uint8_t *pdu,size_t pdu_n,const uint8_t *expected,size_t n,const uint8_t *reply,size_t r) {
    uint8_t raw[2048],echo[2042];uintptr_t count=0;
    raw[0]=mode==2?16:15;raw[1]=3;raw[2]=(uint8_t)handle;raw[3]=(uint8_t)(handle>>8);
    raw[4]=(uint8_t)n;raw[5]=(uint8_t)(n>>8);memcpy(raw+6,expected,n);
    if (pdu_n!=n+6 || memcmp(pdu,raw,n+6)) {errno=EBADMSG;return -1;}
    int error=slk_connection_ssap_write(link,handle,2,reply,r,echo,sizeof echo,&count,now_ns()+5000000000ULL);
    if (error || count!=r || memcmp(echo,reply,r)) {errno=error?-error:EBADMSG;return -1;}
    return 0;
}
static int update_peer_mode(int argc,char **argv) {
    if (argc!=9) return 2;
    const int retired=!strcmp(argv[1],"update-retired");
    const int negative=!strcmp(argv[1],"update-error") || retired;
    uint64_t index=number(argv[2]),generation=number(argv[3]),handle=number(argv[5]),mode=number(argv[6]);
    uint8_t expected[2042],reply[2042];
    size_t n=negative?0:bytes(argv[7],expected),r=negative?0:bytes(argv[8],reply);
    const uint64_t budget_ms=negative?number(argv[8]):5000;
    const int expected_error=retired?EIO:ETIMEDOUT;
    if (negative && (number(argv[7])!=(uint64_t)expected_error || budget_ms<50 || budget_ms>5000 || (retired && (mode!=2 || budget_ms!=5000)))) return 2;
    if (index>UINT16_MAX || !generation || !handle || handle>UINT16_MAX || (mode!=1 && mode!=2) || n>2042 || r>2042 || (!negative && n==r && !memcmp(expected,reply,n))) return 2;
    struct SlkControllerId id={.generation=generation,.index=(uint16_t)index};struct SlkClient *client=NULL;struct SlkConnection *link=NULL;
    int status=1,error;const uint64_t started=now_ns(),original=started+budget_ms*1000000ULL;
    error=slk_client_open_system(original,&client);if (error) {errno=-error;goto done;}
    error=slk_client_connection(client,&id,(const uint8_t *)argv[4],strlen(argv[4]),original,&link);if (error) {errno=-error;goto done;}
    slk_client_close(client);client=NULL;
    printf("{\"stage\":\"ssap_update_wait\",\"api\":\"c\",\"handle\":%"PRIu64",\"mode\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"client_closed\":true",handle,mode,original);
    printf(",\"started_ns\":%"PRIu64",\"budget_ms\":%"PRIu64,started,budget_ms);
    printf("}\n");fflush(stdout);
    struct SlkSsapUpdate result={0};error=slk_connection_ssap_receive(link,(uint16_t)handle,(uint32_t)mode,&result,original);
    if (negative) {
        if (error!=-expected_error) {errno=error?-error:EBADMSG;goto done;}
        printf("{\"stage\":\"ssap_update_error\",\"api\":\"c\",\"handle\":%"PRIu64",\"mode\":%"PRIu64",\"errno\":%d,\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",handle,mode,-error,original,now_ns());fflush(stdout);status=0;goto done;
    }
    if (error) {errno=-error;goto done;}
    if (result.stage!=3 || result.acknowledgement_length) {errno=EBADMSG;goto done;}
    if (checked_update_write(link,(uint16_t)handle,(unsigned)mode,result.pdu,result.pdu_length,expected,n,reply,r)) goto done;
    printf("{\"stage\":\"ssap_update_checked_reply\",\"api\":\"c\",\"handle\":%"PRIu64",\"mode\":%"PRIu64",\"pdu\":\"",handle,mode);hex_print(result.pdu,result.pdu_length);
    printf("\",\"value\":\"");hex_print(expected,n);printf("\",\"reply\":\"");hex_print(reply,r);printf("\"}\n");fflush(stdout);status=0;
done:
    if (status) perror("application-client-c-update-peer");
    slk_connection_close(link);slk_client_close(client);return status;
}

/* The same real SDK/Connection,not a second receiver or wire Engine. The
 * interactive finite commands are also used by isolated ABI contract tests. */
static int subscription_mode(int argc,char **argv) {
    if (argc!=8) return 2;
    uint64_t index=number(argv[2]),generation=number(argv[3]),handle=number(argv[5]),modes=number(argv[6]),lease=number(argv[7]);
    if (index>UINT16_MAX || !generation || !handle || handle>UINT16_MAX || modes<1 || modes>3 || lease<250 || lease>60000) return 2;
    struct SlkControllerId id={.generation=generation,.index=(uint16_t)index};
    struct SlkClient *client=NULL;struct SlkConnection *link=NULL;struct SlkSsapSubscription *sub=NULL;
    int status=1,error,released=0;uint16_t target=(uint16_t)handle;
    struct SlkSsapSubscriptionInfo info={0};struct SlkSsapSubscriptionBatch batch={0},cache={0};unsigned cached=0,next=0;
    error=slk_client_open_system(now_ns()+5000000000ULL,&client);if (error){errno=-error;goto done;}
    error=slk_client_connection(client,&id,(const uint8_t *)argv[4],strlen(argv[4]),now_ns()+5000000000ULL,&link);
    if (error){errno=-error;goto done;}
    slk_client_close(client);client=NULL;
    uint64_t started=now_ns(),creation_deadline=started+5000000000ULL;
    error=slk_connection_ssap_subscribe(link,&target,1,(uint32_t)modes,(uint32_t)lease,creation_deadline,&sub);
    if (error){errno=-error;goto done;}
    error=slk_ssap_subscription_info(sub,&info);if (error){errno=-error;goto done;}
    printf("{\"stage\":\"ssap_subscription_active\",\"api\":\"c\",\"token\":%"PRIu64",\"epoch\":%"PRIu64",\"expires_ns\":%"PRIu64",\"started_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64",\"client_closed\":true}\n",info.token,info.security_epoch,info.expires_ns,started,creation_deadline,now_ns());fflush(stdout);
    char line[16384];
    while (fgets(line,sizeof line,stdin)) {
        if (!strchr(line,'\n')) {errno=EMSGSIZE;goto done;}
        char *command=strtok(line," \n"),*arg=strtok(NULL," \n"),*other=strtok(NULL," \n");
        if (!command) {errno=EINVAL;goto done;}
        if (!strcmp(command,"quit") && !arg) {if(next!=cached){errno=EBUSY;goto done;}break;}
        if (!strcmp(command,"parent-close") && !arg) {
            slk_connection_close(link);link=NULL;
            printf("{\"stage\":\"ssap_subscription_parent_closed\",\"api\":\"c\"}\n");fflush(stdout);continue;
        }
        if (!strcmp(command,"renew") && arg && !other) {
            uint64_t duration=number(arg);if (duration<250 || duration>60000) {errno=EINVAL;goto done;}
            uint64_t renewal_started=now_ns(),renewal_deadline=renewal_started+5000000000ULL;
            error=slk_ssap_subscription_renew(sub,(uint32_t)duration,&info,renewal_deadline);
            if (error){errno=-error;goto done;}
            printf("{\"stage\":\"ssap_subscription_renewed\",\"api\":\"c\",\"token\":%"PRIu64",\"epoch\":%"PRIu64",\"expires_ns\":%"PRIu64",\"started_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64",\"returned_ns\":%"PRIu64"}\n",info.token,info.security_epoch,info.expires_ns,renewal_started,renewal_deadline,now_ns());fflush(stdout);continue;
        }
        if ((!strcmp(command,"release") || !strcmp(command,"release-observe")) && !arg) {
            if(next!=cached){errno=EBUSY;goto done;}
            uint64_t close_started=now_ns(),close_deadline=close_started+5000000000ULL;
            if (!strcmp(command,"release-observe")) {
                printf("{\"stage\":\"ssap_subscription_release_started\",\"api\":\"c\",\"started_ns\":%"PRIu64",\"deadline_ns\":%"PRIu64"}\n",close_started,close_deadline);fflush(stdout);
            }
            error=slk_ssap_subscription_release(sub,&batch,close_deadline);
            if (error){errno=-error;goto done;}released=1;
            printf("{\"stage\":\"ssap_subscription_released\",\"api\":\"c\",\"flags\":%u,\"discarded\":%"PRIu64"}\n",batch.flags,batch.discarded_on_close);fflush(stdout);continue;
        }
        int from_cache=!strcmp(command,"check-cached"),check=from_cache || !strcmp(command,"check"),drain=!strcmp(command,"drain");
        if ((!check && !drain && strcmp(command,"read") && strcmp(command,"poll")) || (check?(!arg || !other || strtok(NULL," \n")):(arg!=NULL))) {errno=EINVAL;goto done;}
        uint8_t expected[2042],reply[2042];size_t n=0,r=0;
        if (check) {
            n=bytes(arg,expected);r=bytes(other,reply);
            if (!link || (n==r && !memcmp(expected,reply,n))) {errno=EINVAL;goto done;}
        }
        if (from_cache) {
            if(next>=cached){errno=ENODATA;goto done;}
        } else {
            if(next!=cached){errno=EBUSY;goto done;}
            error=slk_ssap_subscription_read(sub,strcmp(command,"poll")!=0,&batch,now_ns()+5000000000ULL);
            if (error){errno=-error;goto done;}
            if (drain) {
                if(!batch.count || batch.count>16){errno=EBADMSG;goto done;}
                cache=batch;cached=batch.count;next=0;
            }
        }
        if (check) {
            if (!from_cache && batch.count!=1) {errno=EBADMSG;goto done;}
            const struct SlkSsapSubscriptionPacket *packet=from_cache?&cache.packets[next]:&batch.packets[0];
            if (checked_update_write(link,(uint16_t)handle,packet->indication?2:1,
                packet->pdu,packet->pdu_length,expected,n,reply,r)) goto done;
            printf("{\"stage\":\"ssap_subscription_checked_reply\",\"api\":\"c\",\"sequence\":%"PRIu64",\"value\":\"",packet->sequence);
            hex_print(expected,n);printf("\",\"reply\":\"");hex_print(reply,r);printf("\"}\n");
            if(from_cache){next++;fflush(stdout);continue;}
        }
        if (batch.info.state==3 && (batch.flags & 1)==1) released=1;
        printf("{\"stage\":\"ssap_subscription_batch\",\"api\":\"c\",\"last\":%"PRIu64",\"dropped\":%"PRIu64",\"refused\":%"PRIu64",\"state\":%u,\"flags\":%u,\"reason\":%u,\"discarded\":%"PRIu64",\"packets\":[",batch.last_sequence,batch.dropped_notifications,batch.refused_indications,batch.info.state,batch.flags,batch.reason,batch.discarded_on_close);
        for (unsigned i=0;i<batch.count;i++) {
            if (i) {printf(",");}
            printf("{\"sequence\":%"PRIu64",\"epoch\":%"PRIu64",\"level\":%u,\"indication\":%s,\"pdu\":\"",batch.packets[i].sequence,batch.packets[i].security_epoch,batch.packets[i].security_level,batch.packets[i].indication?"true":"false");
            hex_print(batch.packets[i].pdu,batch.packets[i].pdu_length);printf("\"}");
        }
        printf("]}\n");fflush(stdout);
    }
    if (ferror(stdin)) goto done;
    if(next!=cached){errno=EBUSY;goto done;}
    if (!released) {
        error=slk_ssap_subscription_release(sub,&batch,now_ns()+5000000000ULL);
        if (error){errno=-error;goto done;}
        printf("{\"stage\":\"ssap_subscription_released\",\"api\":\"c\",\"flags\":%u,\"discarded\":%"PRIu64"}\n",batch.flags,batch.discarded_on_close);fflush(stdout);
    }
    status=0;
done:
    if (status) perror("application-client-c-subscription");
    slk_ssap_subscription_free(sub);slk_connection_close(link);slk_client_close(client);return status;
}

int main(int argc,char **argv) {
    if (argc>1 && !strcmp(argv[1],"subscription")) return subscription_mode(argc,argv);
    if (argc>1 && (!strcmp(argv[1],"owned") || !strcmp(argv[1],"owned-readonly") || !strcmp(argv[1],"owned-writeonly") || !strcmp(argv[1],"owned-updates"))) return owned_mode(argc,argv);
    if (argc>1 && (!strcmp(argv[1],"update-peer") || !strcmp(argv[1],"update-error") || !strcmp(argv[1],"update-retired"))) return update_peer_mode(argc,argv);
    if (argc>1 && !strcmp(argv[1],"discovery")) return discovery_mode(argc,argv);
    if (argc>1 && (!strcmp(argv[1],"ssap") || !strcmp(argv[1],"ssap-error"))) return ssap_mode(argc,argv);
    if (argc>1 && (!strcmp(argv[1],"ssap-command") || !strcmp(argv[1],"ssap-command-reject"))) return ssap_command_mode(argc,argv);
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
