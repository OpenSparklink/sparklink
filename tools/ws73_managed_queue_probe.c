// SPDX-License-Identifier: GPL-2.0-only
/* VM-only real queued Managed cancellation. One vCPU + bounded FIFO critical
 * section controls selection; actual Queued/opcode=0 and USB capture prove it.
 * This is privileged scheduling support, not normal concurrency acceptance. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
#include <sched.h>
#include "sparklink_ioctl.h"

static int confirmed_off;
static void fail(int line,const char *expr) {int e=errno;struct sched_param normal={0};sched_setscheduler(0,SCHED_OTHER,&normal);fprintf(stderr,"line %d: %s errno=%d\n",line,expr,e);exit(1);}
#define CHECK(x) do { if (!(x)) fail(__LINE__,#x); } while (0)
static uint64_t wall_ns(void) {struct timespec t;CHECK(!clock_gettime(CLOCK_REALTIME,&t));return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
static void pause_ms(unsigned ms) {struct timespec t={ms/1000,(long)(ms%1000)*1000000};while(nanosleep(&t,&t))CHECK(errno==EINTR);}
static int selected(unsigned index) {int fd=open("/dev/sparklink",O_RDWR|O_CLOEXEC);short n=(short)index;CHECK(fd>=0);CHECK(!ioctl(fd,SL_IOCTL_DEV_SELECT,&n));return fd;}
static void hex(const void *data,size_t len) {const unsigned char *p=data;putchar('"');for(size_t i=0;i<len;i++)printf("%02x",p[i]);putchar('"');}
static struct sle_controller_snapshot snapshot(int fd,uint64_t generation) {
 struct sle_controller_snapshot s={.version=1,.generation=generation};CHECK(!ioctl(fd,SL_IOCTL_CONTROLLER_SNAPSHOT,&s));
 CHECK(s.generation==generation&&s.profile==1&&s.flags==(confirmed_off?SLE_CONTROLLER_READY:SLE_CONTROLLER_SETUP)&&s.valid_fields==1&&!s.error);return s;
}
static struct sle_discovery_result radio(int fd,uint64_t generation) {
 struct sle_discovery_result s={.version=1,.generation=generation};CHECK(!ioctl(fd,SL_IOCTL_DISCOVERY_RESULT,&s));
 CHECK(s.generation==generation&&s.radio_adv==(unsigned)confirmed_off&&s.radio_scan==(unsigned)confirmed_off&&!s.error);return s;
}
static struct sle_management_query query(int fd,uint64_t generation,unsigned state) {
 struct sle_management_query q={.version=1,.generation=generation};CHECK(!ioctl(fd,SL_IOCTL_MANAGEMENT_QUERY,&q));
 CHECK(q.state==state&&q.mode==(state==SLE_MANAGEMENT_HELD?SLE_MANAGEMENT_MANAGED:0)&&!q.lease&&!q.flags&&!q.error&&!q.status&&!q.opcode);return q;
}
static void closed(int fd) {CHECK(!close(fd));errno=0;CHECK(fcntl(fd,F_GETFD)==-1&&errno==EBADF);}
static struct sle_discovery_result operation(int fd,uint64_t gen,uint64_t id,unsigned state) {
 struct sle_discovery_result r={.version=1,.generation=gen,.request_id=id};
 CHECK(!ioctl(fd,SL_IOCTL_DISCOVERY_RESULT,&r));
 CHECK(r.state==state&&!r.opcode&&!r.step&&!r.status&&!r.power_valid&&!r.flags&&r.radio_adv==(unsigned)confirmed_off&&r.radio_scan==(unsigned)confirmed_off);
 CHECK(r.error==(state==SLE_DISCOVERY_CANCELLED?-ECANCELED:0));return r;
}
static struct sle_discovery_result completed(int fd,uint64_t gen,uint64_t id,unsigned op,unsigned count,unsigned opcode) {
 uint64_t deadline=wall_ns()+500000000ULL;
 for(;;){struct sle_discovery_result r={.version=1,.generation=gen,.request_id=id};CHECK(!ioctl(fd,SL_IOCTL_DISCOVERY_RESULT,&r));
  if(r.state==SLE_DISCOVERY_SUCCEEDED){CHECK(!r.error&&!r.status&&r.operation==op&&r.count==count&&r.step==count-1&&r.opcode==opcode);return r;}
  CHECK(r.state==SLE_DISCOVERY_QUEUED||r.state==SLE_DISCOVERY_PENDING);CHECK(wall_ns()<deadline);pause_ms(1);
 }
}
static void bootstrap(int fd,unsigned index,uint64_t gen) {
 struct sle_controller_snapshot initial=snapshot(fd,gen);
 struct sle_management_request lease={.version=1,.generation=gen,.mode=SLE_MANAGEMENT_MANAGED};CHECK(!ioctl(fd,SL_IOCTL_MANAGEMENT_ACQUIRE,&lease)&&lease.lease);
 struct sle_discovery_submit adv={.version=1,.profile=1,.generation=gen,.request_id=1000,.operation=SLE_DISCOVERY_ADV_CONFIGURE_OFF,
  .advertising={.gt_role=2,.interval_min=1200,.interval_max=1200,.channel_map=7,.tx_power=127,.supervision_timeout=200}};
 memcpy(adv.advertising.own_address,initial.address,6);
 struct sle_discovery_submit scan={.version=1,.profile=1,.generation=gen,.request_id=1001,.operation=SLE_DISCOVERY_SCAN_INITIALIZE_OFF,.scanning={.frame_types=1,.interval=1600,.window=800}};
 uint64_t start=wall_ns();CHECK(!ioctl(fd,SL_IOCTL_DISCOVERY_SUBMIT,&adv));struct sle_discovery_result ar=completed(fd,gen,1000,5,2,0xc05);
 CHECK(ar.radio_adv==1&&ar.radio_scan==0&&ar.power_valid==1);
 CHECK(!ioctl(fd,SL_IOCTL_DISCOVERY_SUBMIT,&scan));struct sle_discovery_result sr=completed(fd,gen,1001,6,3,0x1002);CHECK(sr.radio_adv==1&&sr.radio_scan==1&&!sr.power_valid);
 CHECK(!ioctl(fd,SL_IOCTL_MANAGEMENT_RELEASE,&lease));pause_ms(20);query(fd,gen,SLE_MANAGEMENT_FREE);
 confirmed_off=1;struct sle_controller_snapshot ready=snapshot(fd,gen);struct sle_discovery_result rr=radio(fd,gen);confirmed_off=0;
 printf("{\"bootstrap\":true,\"index\":%u,\"start_wall_ns\":%llu,\"end_wall_ns\":%llu,\"advertising_input\":",index,(unsigned long long)start,(unsigned long long)wall_ns());hex(&adv,sizeof(adv));printf(",\"scanning_input\":");hex(&scan,sizeof(scan));printf(",\"advertising_result\":");hex(&ar,sizeof(ar));printf(",\"scanning_result\":");hex(&sr,sizeof(sr));printf(",\"ready_snapshot\":");hex(&ready,sizeof(ready));printf(",\"radio\":");hex(&rr,sizeof(rr));puts("}");fflush(stdout);
}
int main(int argc,char **argv) {
 CHECK(argc==3||(argc==4&&!strcmp(argv[3],"--confirmed-off")));CHECK(sysconf(_SC_NPROCESSORS_ONLN)==1);CHECK(sched_getscheduler(0)==SCHED_OTHER);uint64_t generations[2];unsigned long long parsed;char tail;
 CHECK(sscanf(argv[1],"%llu%c",&parsed,&tail)==1);generations[0]=parsed;
 CHECK(sscanf(argv[2],"%llu%c",&parsed,&tail)==1);generations[1]=parsed;
 CHECK(generations[0]&&generations[1]&&generations[0]!=generations[1]);
 int observe[2]={selected(0),selected(1)};
 if(argc==4){for(unsigned i=0;i<2;i++)bootstrap(observe[i],i,generations[i]);confirmed_off=1;}
 for(unsigned target=0;target<2;target++)for(unsigned kind=0;kind<3;kind++) {
  unsigned peer=1-target;uint64_t start=wall_ns();
  struct sle_controller_snapshot before=snapshot(observe[target],generations[target]),pb=snapshot(observe[peer],generations[peer]);
  struct sle_discovery_result rb=radio(observe[target],generations[target]);query(observe[target],generations[target],SLE_MANAGEMENT_FREE);
  int writer=selected(target),duplicate=-1,wrong_errno=0;
  struct sle_management_request lease={.version=1,.generation=generations[target],.mode=SLE_MANAGEMENT_MANAGED};
  CHECK(!ioctl(writer,SL_IOCTL_MANAGEMENT_ACQUIRE,&lease)&&lease.lease);
  struct sle_discovery_submit commands[2]={
   {.version=1,.profile=1,.generation=generations[target],.request_id=kind*2+1,.operation=SLE_DISCOVERY_ADV_CONFIGURE_OFF,
    .advertising={.gt_role=2,.interval_min=1200,.interval_max=1200,.channel_map=7,.tx_power=127,.supervision_timeout=200}},
   {.version=1,.profile=1,.generation=generations[target],.request_id=kind*2+2,.operation=SLE_DISCOVERY_SCAN_STOP}};
  struct sle_discovery_submit rejected[2]={
   {.version=1,.profile=1,.generation=generations[target],.request_id=100+kind,.operation=SLE_DISCOVERY_SCAN_INITIALIZE_OFF,
    .scanning={.frame_types=1,.interval=1600,.window=800}},
   {.version=1,.profile=1,.generation=generations[target],.request_id=200+kind,.operation=SLE_DISCOVERY_SCAN_INITIALIZE_OFF,
    .scanning={.frame_types=1,.interval=1600,.window=800}}};
  int rejected_errno[2]={0},missing_errno[2]={0};
  if(confirmed_off){commands[1]=rejected[0];commands[1].request_id=kind*2+2;}
  memcpy(commands[0].advertising.own_address,before.address,6);
  if(kind==2){duplicate=dup(writer);CHECK(duplicate>=0);}
  struct sched_param rt={.sched_priority=1},normal={0};
  uint64_t critical_start=wall_ns();CHECK(!sched_setscheduler(0,SCHED_FIFO,&rt));
  if(confirmed_off){
   // Scan INITIALIZE contains START: admit while prior advertising Off is
   // confirmed and no advertising request is pending, then queue advertising.
   CHECK(!ioctl(writer,SL_IOCTL_DISCOVERY_SUBMIT,&commands[1]));
   CHECK(!ioctl(writer,SL_IOCTL_DISCOVERY_SUBMIT,&commands[0]));
  } else {
  errno=0;CHECK(ioctl(writer,SL_IOCTL_DISCOVERY_SUBMIT,&rejected[0])==-1&&errno==EBUSY);rejected_errno[0]=errno;
  struct sle_discovery_result absent={.version=1,.generation=generations[target],.request_id=rejected[0].request_id};
  errno=0;CHECK(ioctl(observe[target],SL_IOCTL_DISCOVERY_RESULT,&absent)==-1&&errno==ENOENT);missing_errno[0]=errno;
  CHECK(!ioctl(writer,SL_IOCTL_DISCOVERY_SUBMIT,&commands[0]));
  errno=0;CHECK(ioctl(writer,SL_IOCTL_DISCOVERY_SUBMIT,&rejected[1])==-1&&errno==EBUSY);rejected_errno[1]=errno;
  absent=(struct sle_discovery_result){.version=1,.generation=generations[target],.request_id=rejected[1].request_id};
  errno=0;CHECK(ioctl(observe[target],SL_IOCTL_DISCOVERY_RESULT,&absent)==-1&&errno==ENOENT);missing_errno[1]=errno;
  CHECK(!ioctl(writer,SL_IOCTL_DISCOVERY_SUBMIT,&commands[1]));
  }
  struct sle_discovery_result queued[2]={operation(observe[target],generations[target],commands[0].request_id,SLE_DISCOVERY_QUEUED),operation(observe[target],generations[target],commands[1].request_id,SLE_DISCOVERY_QUEUED)};
  struct sle_management_query held=query(observe[target],generations[target],SLE_MANAGEMENT_HELD),first={0};

  if(!kind) {
   struct sle_management_request wrong=lease;wrong.lease++;
   errno=0;CHECK(ioctl(writer,SL_IOCTL_MANAGEMENT_RELEASE,&wrong)==-1&&errno==EPERM);wrong_errno=errno;
   query(observe[target],generations[target],SLE_MANAGEMENT_HELD);
   CHECK(!ioctl(writer,SL_IOCTL_MANAGEMENT_RELEASE,&lease));
  } else if(kind==1) closed(writer);
  else {
   closed(writer);
   first=query(observe[target],generations[target],SLE_MANAGEMENT_HELD);
   CHECK(operation(observe[target],generations[target],commands[0].request_id,SLE_DISCOVERY_QUEUED).state==SLE_DISCOVERY_QUEUED);
   query(observe[target],generations[target],SLE_MANAGEMENT_HELD);closed(duplicate);
  }
  struct sle_discovery_result cancelled[2]={operation(observe[target],generations[target],commands[0].request_id,SLE_DISCOVERY_CANCELLED),operation(observe[target],generations[target],commands[1].request_id,SLE_DISCOVERY_CANCELLED)};
  CHECK(!sched_setscheduler(0,SCHED_OTHER,&normal));uint64_t critical_end=wall_ns();CHECK(critical_end-critical_start<50000000ULL);
  CHECK(sched_getscheduler(0)==SCHED_OTHER);pause_ms(350);
  struct sle_management_query free=query(observe[target],generations[target],SLE_MANAGEMENT_FREE);
  struct sle_controller_snapshot after=snapshot(observe[target],generations[target]),pa=snapshot(observe[peer],generations[peer]);
  struct sle_discovery_result ra=radio(observe[target],generations[target]);
  query(observe[peer],generations[peer],SLE_MANAGEMENT_FREE);
  CHECK(!memcmp(&before,&after,sizeof(before))&&!memcmp(&pb,&pa,sizeof(pb))&&!memcmp(&rb,&ra,sizeof(rb)));
  uint64_t end=wall_ns();
  printf("{\"case\":\"%s\",\"index\":%u,\"generation\":%llu,\"peer_index\":%u,\"peer_generation\":%llu,\"start_wall_ns\":%llu,\"end_wall_ns\":%llu,\"writer_fd\":%d,\"duplicate_fd\":%d,\"wrong_token_errno\":%d,\"snapshot_before\":",kind==0?"explicit-release":kind==1?"last-fd-close":"dup-last-fd-close",target,(unsigned long long)generations[target],peer,(unsigned long long)generations[peer],(unsigned long long)start,(unsigned long long)end,writer,duplicate,wrong_errno);
  hex(&before,sizeof(before));printf(",\"snapshot_after\":");hex(&after,sizeof(after));printf(",\"peer_before\":");hex(&pb,sizeof(pb));printf(",\"peer_after\":");hex(&pa,sizeof(pa));
  printf(",\"radio_before\":");hex(&rb,sizeof(rb));printf(",\"radio_after\":");hex(&ra,sizeof(ra));printf(",\"held\":");hex(&held,sizeof(held));printf(",\"after_first_close\":");hex(&first,sizeof(first));printf(",\"free\":");hex(&free,sizeof(free));printf(",\"queued\":[");hex(&queued[0],sizeof(queued[0]));printf(",");hex(&queued[1],sizeof(queued[1]));printf("],\"cancelled\":[");hex(&cancelled[0],sizeof(cancelled[0]));printf(",");hex(&cancelled[1],sizeof(cancelled[1]));printf("],\"scan_initialize_rejections\":[");
  for(unsigned i=0;!confirmed_off&&i<2;i++){if(i)printf(",");printf("{\"input\":");hex(&rejected[i],sizeof(rejected[i]));printf(",\"submit_errno\":%d,\"result_errno\":%d}",rejected_errno[i],missing_errno[i]);}
  printf("],\"critical_start_ns\":%llu,\"critical_end_ns\":%llu,\"scheduler_restored\":true}\n",(unsigned long long)critical_start,(unsigned long long)critical_end);fflush(stdout);
  if(!kind)closed(writer);
 }
 closed(observe[0]);closed(observe[1]);return 0;
}
