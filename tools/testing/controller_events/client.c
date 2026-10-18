/* Real ordinary SDK directory consumer for the disposable VM gate only.
 * No Native operation, D-Bus dispatch, packet codec or generated event. */
#define _POSIX_C_SOURCE 200809L
#include <sparklink.h>
#include <dlfcn.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>
#include <time.h>

static uint64_t deadline(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC,&now)) return 0;
    return (uint64_t)now.tv_sec*1000000000ULL+(uint64_t)now.tv_nsec+30000000000ULL;
}
#define LOAD(name) __typeof__(&name) name##_call=(__typeof__(&name))dlsym(library,#name); if(!name##_call){fprintf(stderr,"missing actual SDK symbol: %s\n",#name);return 2;}
int main(int argc,char **argv) {
    _Static_assert(sizeof(SlkControllerEvent)==32,"actual event ABI");
    _Static_assert(offsetof(SlkControllerEvent,kind)==24,"actual event ABI offset");
    if(argc!=2){fputs("explicit prepared SDK library required\n",stderr);return 2;}
    void *library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
    if(!library){fprintf(stderr,"actual SDK load: %s\n",dlerror());return 2;}
    LOAD(slk_client_open_system); LOAD(slk_client_close);
    LOAD(slk_client_controller_events); LOAD(slk_controller_events_next); LOAD(slk_controller_events_close);
    SlkClient *client=NULL; SlkControllerEvents *stream=NULL;
    int result=slk_client_open_system_call(deadline(),&client);
    if(!result) result=slk_client_controller_events_call(client,deadline(),&stream);
    slk_client_close_call(client); /* The derived view must retain this caller. */
    if(result || !stream){fprintf(stderr,"actual directory open: %d\n",result);return 2;}
    setvbuf(stdout,NULL,_IOLBF,0);
    for(unsigned n=0;n<3;++n){
        SlkControllerEvent event={0}; SlkControllerId ids[256]; uintptr_t count=0;
        result=slk_controller_events_next_call(stream,&event,ids,256,&count,0,deadline());
        if(result || event.reserved || count>256 || (n==0?event.kind!=1:((event.kind!=2&&event.kind!=3)||count!=1))){fprintf(stderr,"actual directory next: %d kind=%u count=%"PRIuPTR"\n",result,event.kind,count);slk_controller_events_close_call(stream);return 2;}
        if(n==0){
            printf("ControllerDirectorySnapshot: cursor=%"PRIu64" controllers=",event.sequence);
            for(uintptr_t i=0;i<count;++i)printf("%s/org/sparklink/slk%u_g%"PRIu64,i?"|":"",ids[i].index,ids[i].generation);
            putchar('\n');
        }else printf("ControllerDirectoryEvent: sequence=%"PRIu64" action=%s path=/org/sparklink/slk%u_g%"PRIu64"\n",event.sequence,event.kind==2?"published":"withdrawn",ids[0].index,ids[0].generation);
    }
    slk_controller_events_close_call(stream);
    /* Keep the test library loaded through process exit; no unload qualification. */
    return 0;
}
