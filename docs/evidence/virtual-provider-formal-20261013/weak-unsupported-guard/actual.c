
#include <errno.h>
#include <assert.h>
#include <stdint.h>
#include "virtual_codec.h"
extern unsigned short nondet_u16(void);
extern size_t nondet_size(void);
extern unsigned char nondet_u8(void);
int main(void) {
 struct sparklink_native_info info;
 unsigned char *bytes=(unsigned char*)&info;
 for(size_t i=0;i<sizeof(info);i++) bytes[i]=nondet_u8();
 u16 opcode=nondet_u16(); size_t length=nondet_size(); u8 param=nondet_u8(),out[18],old[18];
 for(size_t i=0;i<18;i++) out[i]=old[i]=nondet_u8();
 int ret=sparklink_virtual_reply(&info,opcode,&param,length,out);
 if(ret<0) { for(size_t i=0;i<18;i++) assert(out[i]==old[i]); }
 else {
  assert(ret>=8 && ret<=18);assert(out[0]==2 && out[1]==0);
  assert(out[2]==ret-4 && out[3]==0 && out[4]==(u8)opcode && out[5]==(u8)(opcode>>8));
  assert(out[6]==1 && out[7]==0);
  if(opcode==0x0401) {assert(ret==10);assert(out[8]==255 && out[9]==0);}
  else if(opcode==0x0402) {assert(ret==14);for(size_t i=8;i<14;i++) assert(out[i]==0);}
  else if(opcode==0x0403) {assert(ret==18);for(size_t i=0;i<10;i++) assert(out[8+i]==info.features[i]);}
  else if(opcode==0x0404) {assert(ret==13);for(size_t i=0;i<5;i++) assert(out[8+i]==info.version[i]);}
  else {assert(opcode==0x0406 && length==1);assert(ret==14);for(size_t i=0;i<6;i++) assert(out[8+i]==info.address[i]);}
 }
}
